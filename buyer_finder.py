"""
Buyer Finder: an AI agent that helps exporters find overseas buyers.

Step 1  research_buyers()  -> searches the web and returns a list of
                              potential importers / distributors.
Step 1b verify_websites()  -> opens every website and flags dead or
                              made-up links.
Step 2  draft_emails()     -> writes a personalised first email to the
                              best-fit companies, in English or the
                              buyer's own language.

Every step also reports its usage, so the app can show what a run cost.
"""

import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import anthropic

# Which AI to use. Change PROVIDER to switch, no code changes needed.
#   "claude"   -> Claude Haiku 5.5 with Claude's built-in web search
#   "deepseek" -> DeepSeek Flash (V4.1-Flash-1017), with DeepSeek's own Search API
#                 (set BUYER_FINDER_SEARCH=serpapi to use SerpAPI instead)
PROVIDER = os.getenv("BUYER_FINDER_PROVIDER", "deepseek").lower()

SETTINGS = {
    "claude": {
        "model": "claude-haiku-5-5",
        "base_url": None,
        "key_env": "ANTHROPIC_API_KEY",
        # USD; Haiku 5.5 prompts up to 100K tokens; web search is $10 per 1,000 searches
        "currency": "$", "input_per_m": 0.10, "output_per_m": 0.50, "per_search": 0.01,
    },
    "deepseek": {
        "model": "deepseek-flash",
        # DeepSeek accepts the same request format as Claude at this address
        "base_url": "https://api.deepseek.com/anthropic",
        "key_env": "DEEPSEEK_API_KEY",
        # USD, deepseek-flash peak-hour price (off-peak is half); DeepSeek Search is $0.75 per 1,000 searches
        "currency": "$", "input_per_m": 0.30, "output_per_m": 1.20, "per_search": 0.00075,
    },
}


def settings():
    if PROVIDER not in SETTINGS:
        raise ValueError(f"Unknown provider '{PROVIDER}'. Use 'claude' or 'deepseek'.")
    return SETTINGS[PROVIDER]


def model_name():
    return os.getenv("BUYER_FINDER_MODEL") or settings()["model"]


_client = None


def get_client():
    """Create the AI client on first use, for whichever provider is switched on."""
    global _client
    if _client is None:
        cfg = settings()
        key = os.getenv(cfg["key_env"])
        if not key:
            raise ValueError(
                f"API key missing: set {cfg['key_env']}. / 缺少 API 密钥：请设置 {cfg['key_env']}。")
        _client = anthropic.Anthropic(api_key=key, base_url=cfg["base_url"]) if cfg["base_url"] else anthropic.Anthropic(api_key=key)
    return _client


def ask(messages, max_tokens, **kwargs):
    """One model call. DeepSeek's thinking mode is switched off so the whole budget goes to the answer."""
    if PROVIDER == "deepseek":
        kwargs.setdefault("thinking", {"type": "disabled"})
    return get_client().messages.create(model=model_name(), max_tokens=max_tokens, messages=messages, **kwargs)


@dataclass
class Usage:
    """Adds up tokens and searches across all calls in one run."""
    input_tokens: int = 0
    output_tokens: int = 0
    searches: int = 0

    def add(self, response):
        u = getattr(response, "usage", None)
        if u is None:
            return
        self.input_tokens += getattr(u, "input_tokens", 0) or 0
        self.output_tokens += getattr(u, "output_tokens", 0) or 0
        tools = getattr(u, "server_tool_use", None)
        self.searches += (getattr(tools, "web_search_requests", 0) or 0) if tools else 0

    @property
    def cost(self) -> float:
        cfg = settings()
        return (self.input_tokens * cfg["input_per_m"] / 1e6
                + self.output_tokens * cfg["output_per_m"] / 1e6
                + self.searches * cfg["per_search"])

    @property
    def currency(self) -> str:
        return settings()["currency"]


RESEARCH_PROMPT = """You are a B2B researcher helping a Chinese exporter find buyers abroad.

Seller: {seller}
Product: {product}
Target country: {country}

Use web search to find {n} real companies in {country} that are likely to buy this
product in bulk: importers, distributors, wholesalers or retail chains.
Prefer companies that already sell similar products. Only include companies you
found evidence for in your searches. Do not invent companies, websites or people.
Do not include personal phone numbers or personal email addresses.

For each company, give:
- name
- website (official site, or "" if not found)
- city
- type (importer / distributor / wholesaler / retailer / other)
- what_they_sell (one sentence)
- why_fit (one sentence, specific to this seller)
- fit_score (a whole number from 1 to 5, 5 = best fit)
- next_step (one short, practical tip for how to approach this company)
- source (the URL where you found it)

Only include companies that BUY or DISTRIBUTE this kind of product. Leave out
manufacturers and suppliers that would compete with the seller, B2B marketplaces
(e.g. Alibaba, Made-in-China), directories and yellow pages, job sites and social media pages.

Return ONLY a JSON array inside <json></json> tags, sorted by fit_score, highest first."""

# For DeepSeek: we search first (SerpAPI), then ask the model to pick buyers from the results.
PICK_PROMPT = RESEARCH_PROMPT.replace(
    "Use web search to find {n} real companies",
    "Below are web search results. From them, pick up to {n} real companies",
).replace(
    "Only include companies you\nfound evidence for in your searches.",
    "Only use companies that appear in these results, and set source to the result's URL.",
) + """

Search results:
{results}"""


EMAIL_PROMPT = """Write a short first email (under 120 words) from this seller to this company.

Seller: {seller}
Product: {product}
Company: {company}

Rules:
- Write the email in {language}.
- Mention one specific thing about the company (from what_they_sell or why_fit).
- One clear ask: a short call or a product catalogue.
- Plain and friendly. No exaggeration, no claims about the seller that are not given above.
- Start with a subject line: "Subject: ..."
"""


def _text_from(response) -> str:
    """Join all text blocks in a Claude response (search results are skipped)."""
    return "".join(block.text for block in response.content if block.type == "text")


def _extract_json(text: str):
    """Pull the JSON array out of <json>...</json> tags."""
    match = re.search(r"<json>(.*?)</json>", text, re.DOTALL)
    raw = match.group(1) if match else text
    start, end = raw.find("["), raw.rfind("]")
    if start == -1 or end == -1:
        raise ValueError("The agent did not return a list of companies. Please try again.")
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError as e:
        raise ValueError("The agent's answer was cut off or badly formatted. Please try again.") from e
    if not isinstance(data, list):
        raise ValueError("The agent did not return a list of companies. Please try again.")
    return [c for c in data if isinstance(c, dict)]


def _score(company) -> float:
    """fit_score as a number from 0 to 5, even if the model wrote "4", "4/5", "4 out of 5" or "high"."""
    value = company.get("fit_score", 0)
    if isinstance(value, (int, float)):
        return float(max(0, min(5, value)))
    text = str(value or "").strip().lower()
    match = re.search(r"\d+(\.\d+)?", text)
    if match:
        return float(max(0, min(5, float(match.group()))))
    words = {"very high": 5, "high": 4, "medium": 3, "moderate": 3, "low": 2}
    for word, score in words.items():
        if word in text:
            return float(score)
    return 0.0


# Sites that are never a buyer: marketplaces, directories, social media, job boards.
# Learned from open-source export tools that filter these out before scoring.
NOT_A_BUYER_DOMAINS = (
    "alibaba.com", "aliexpress.", "made-in-china.com", "globalsources.com", "dhgate.com",
    "indiamart.com", "tradeindia.com", "ec21.com", "kompass.com", "europages.",
    "yellowpages", "paginasamarillas", "yelp.", "linkedin.com", "facebook.com",
    "instagram.com", "twitter.com", "x.com", "youtube.com", "tiktok.com",
    "indeed.", "glassdoor.", "wikipedia.org", "amazon.",
)

TIERS = {5: "Very high / 极高", 4: "High / 高", 3: "Medium / 中"}


def _is_not_a_buyer(company) -> bool:
    site = (company.get("website") or "").lower()
    kind = (company.get("type") or "").lower()
    return any(d in site for d in NOT_A_BUYER_DOMAINS) or kind in ("manufacturer", "supplier")


def _linkedin_search(company) -> str:
    """A search link (not scraping): opens LinkedIn people search for buyers at this company."""
    name = urllib.parse.quote(f"{company.get('name', '')} purchasing manager")
    return f"https://www.linkedin.com/search/results/people/?keywords={name}"


def _clean(companies: list) -> list:
    """Remove duplicates (same website or same name) and sort by fit score."""
    seen, result = set(), []
    for c in companies:
        key = (c.get("website") or "").lower().replace("https://", "").replace("http://", "").replace("www.", "").strip("/")
        key = key or (c.get("name") or "").lower().strip()
        if key and key in seen:
            continue
        seen.add(key)
        if _is_not_a_buyer(c):
            continue
        c["fit_score"] = _score(c)
        c["intent"] = TIERS.get(round(c["fit_score"]), "Low / 低")
        c["linkedin_search"] = _linkedin_search(c)
        result.append(c)
    return sorted(result, key=_score, reverse=True)


def research_buyers(seller: str, product: str, country: str, n: int = 10,
                    max_searches: int = 5, usage: Usage | None = None):
    """Step 1: find potential buyers (list of dicts), using whichever provider is switched on."""
    usage = usage or Usage()
    if PROVIDER == "claude":
        return _research_with_claude(seller, product, country, n, max_searches, usage)
    return _research_with_search_api(seller, product, country, n, usage)


def _research_with_claude(seller, product, country, n, max_searches, usage):
    """Claude searches the web itself (built-in web search tool)."""
    messages = [{
        "role": "user",
        "content": RESEARCH_PROMPT.format(seller=seller, product=product, country=country, n=n),
    }]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]

    # Long searches can pause mid-way ("pause_turn"); send the partial answer back to continue.
    for _ in range(3):
        response = ask(messages, 8000, tools=tools)
        usage.add(response)
        if getattr(response, "stop_reason", None) != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": response.content}]

    return _clean(_extract_json(_text_from(response)))


def serp_search(query: str, timeout: int = 20) -> list:
    """One Google search through SerpAPI. Returns [{title, link, snippet}]."""
    key = os.getenv("SERPAPI_API_KEY")
    if not key:
        raise ValueError("Search key missing: set SERPAPI_API_KEY. / 缺少搜索密钥：请设置 SERPAPI_API_KEY。")
    params = urllib.parse.urlencode({"engine": "google", "q": query, "num": 10, "api_key": key})
    with urllib.request.urlopen(f"https://serpapi.com/search.json?{params}", timeout=timeout) as r:
        data = json.loads(r.read().decode("utf-8"))
    if data.get("error"):
        raise ValueError(f"Search error: {data['error']}")
    return [{"title": x.get("title", ""), "link": x.get("link", ""), "snippet": x.get("snippet", "")}
            for x in data.get("organic_results", [])]


def deepseek_search(query: str, timeout: int = 30) -> list:
    """One web search through DeepSeek's Search API (same key as the model). Returns [{title, link, snippet}]."""
    key = os.getenv("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("API key missing: set DEEPSEEK_API_KEY. / 缺少 API 密钥：请设置 DEEPSEEK_API_KEY。")
    body = json.dumps({"query": query[:128], "count": 15, "need_content": False}).encode("utf-8")
    request = urllib.request.Request(
        "https://api.deepseek.com/v1/tools/search", data=body, method="POST",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:200]
        if e.code == 402 or "balance" in detail.lower():
            raise ValueError("Not enough balance. Top up your DeepSeek account. / DeepSeek 余额不足，请充值。") from e
        if e.code == 401:
            raise ValueError("DeepSeek API key wrong. / DeepSeek 密钥错误。") from e
        raise ValueError(f"Search error {e.code}: {detail}") from e
    results = []
    for x in data.get("results", []):
        snippet = x.get("summary") or x.get("snippet") or x.get("short_summary") or (x.get("content") or "")[:300]
        results.append({"title": x.get("title", ""), "link": x.get("url") or x.get("link", ""), "snippet": snippet})
    return results


def web_search(query: str) -> list:
    """Pick the search service: DeepSeek's own by default, SerpAPI if asked for."""
    if os.getenv("BUYER_FINDER_SEARCH", "deepseek").lower() == "serpapi":
        return serp_search(query)
    return deepseek_search(query)


def search_queries(product: str, country: str) -> list:
    """Three angles that buyers of a product usually show up under."""
    return [f"{product} distributor {country}",
            f"{product} importer {country}",
            f"{product} wholesaler {country}"]


def _research_with_search_api(seller, product, country, n, usage):
    """Search the web first (DeepSeek Search or SerpAPI), then let the model pick real buyers from the results."""
    results, seen = [], set()
    for q in search_queries(product, country):
        usage.searches += 1
        for r in web_search(q):
            if r["link"] and r["link"] not in seen:
                seen.add(r["link"])
                results.append(r)
    if not results:
        return []

    listing = "\n".join(f"[{i}] {r['title']}\n    URL: {r['link']}\n    {r['snippet']}"
                        for i, r in enumerate(results[:40], 1))
    messages = [{"role": "user", "content": PICK_PROMPT.format(
        seller=seller, product=product, country=country, n=n, results=listing)}]
    companies = None
    for attempt in range(2):
        response = ask(messages, 8000)
        usage.add(response)
        text = _text_from(response)
        try:
            companies = _extract_json(text)
            break
        except ValueError:
            # Shows up in the app logs (Manage app) so a bad answer can be checked
            print(f"[buyer-finder] attempt {attempt + 1}: stop_reason={response.stop_reason}, "
                  f"answer started with: {text[:500]!r}", file=sys.stderr)
            if attempt == 1:
                raise
            messages = messages + [
                {"role": "assistant", "content": text or "(empty)"},
                {"role": "user", "content": "Reply with only the list in <json>[...]</json> tags. "
                                            "If none of the results are buyers, reply <json>[]</json>."},
            ]

    # Keep only companies whose source really is one of the search results (no made-up sources)
    allowed = {r["link"] for r in results}
    companies = [c for c in companies if c.get("source") in allowed]
    return _clean(companies)


def check_website(url: str, timeout: int = 10) -> bool:
    """Return True if the company website exists. Catches made-up or dead links.
    Only asks "does this site answer?", so it also accepts sites with old security certificates."""
    if not url:
        return False
    if not url.startswith("http"):
        url = "https://" + url
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                             "(KHTML, like Gecko) Chrome/120 Safari/537.36"}
    lenient = ssl.create_default_context()
    lenient.check_hostname = False
    lenient.verify_mode = ssl.CERT_NONE
    for context in (None, lenient):
        try:
            request = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(request, timeout=timeout, context=context) as response:
                return response.status < 500
        except urllib.error.HTTPError as e:
            # The server answered, so the site exists (many block automated visits with 403 etc.)
            return e.code < 500 and e.code not in (404, 410)
        except Exception:
            continue
    return False


def verify_websites(companies: list) -> list:
    """Step 1b: open every website at the same time and mark the ones that work."""
    if not companies:
        return companies
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda c: check_website(c.get("website", "")), companies))
    for company, ok in zip(companies, results):
        company["website_ok"] = ok
    # Best fit first; among equal scores, working websites first
    return sorted(companies, key=lambda c: (-_score(c), not c.get("website_ok")))


def _draft_one(seller, product, company, language, usage):
    response = ask(
        max_tokens=1500,
        messages=[{
            "role": "user",
            "content": EMAIL_PROMPT.format(
                seller=seller,
                product=product,
                company=json.dumps(company, ensure_ascii=False),
                language=language,
            ),
        }],
    )
    usage.add(response)
    return {"company": company.get("name", ""), "email": _text_from(response).strip()}


def draft_emails(seller: str, product: str, companies: list, top: int = 3,
                 language: str = "English", usage: Usage | None = None):
    """Step 2: write a first email to each of the top companies (in parallel, to save time)."""
    usage = usage or Usage()
    chosen = companies[:top]
    with ThreadPoolExecutor(max_workers=max(1, len(chosen))) as pool:
        return list(pool.map(lambda c: _draft_one(seller, product, c, language, usage), chosen))


def friendly_error(e: Exception) -> str:
    """Turn API errors into a message a non-technical user can act on."""
    text = str(e)
    if isinstance(e, anthropic.AuthenticationError):
        return f"API key wrong. Check {settings()['key_env']}. / API 密钥错误，请检查 {settings()['key_env']}。"
    if "insufficient" in text.lower() and "balance" in text.lower():
        return "Not enough balance. Top up your API account. / 余额不足，请给 API 账户充值。"
    if "credit balance" in text.lower():
        return "Not enough API credits. Add funds in the Claude Console. / API 余额不足，请在 Claude Console 充值。"
    if isinstance(e, anthropic.RateLimitError):
        return "Too many requests. Wait a minute and try again. / 请求太频繁，请等一分钟再试。"
    if isinstance(e, ValueError):
        return text
    return f"Something went wrong: {text} / 出错了，请重试。"
