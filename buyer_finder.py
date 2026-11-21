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

import html
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
import threading
from dataclasses import dataclass, field

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
    # Several threads add to the same counters at once, so updates go through a lock
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False, compare=False)

    def add(self, response):
        u = getattr(response, "usage", None)
        if u is None:
            return
        tools = getattr(u, "server_tool_use", None)
        with self._lock:
            self.input_tokens += getattr(u, "input_tokens", 0) or 0
            self.output_tokens += getattr(u, "output_tokens", 0) or 0
            self.searches += (getattr(tools, "web_search_requests", 0) or 0) if tools else 0

    def add_search(self, count: int = 1):
        with self._lock:
            self.searches += count

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
- what_they_sell (one sentence, in {language})
- why_fit (one sentence, specific to this seller, in {language})
- next_step (one short, practical tip for how to approach this company, in {language})
- sells_same_products (true/false: they already sell or distribute this kind of product)
- trade_buyer (true/false: importer, distributor or wholesaler that buys in bulk, not only a shop)
- serves_businesses (true/false: they sell to businesses such as manufacturers, installers or retailers)
- imports_or_same_material (true/false: they already import, or sell products of the same material or quality)
- source (the URL where you found it)
- evidence (a short quote, at most 25 words, copied WORD FOR WORD from the source text,
  that shows this company sells or distributes this kind of product; "" if there is none)

Only include companies that BUY or DISTRIBUTE this kind of product. Leave out
manufacturers and suppliers that would compete with the seller, B2B marketplaces
(e.g. Alibaba, Made-in-China), directories and yellow pages, job sites and social media pages.

Every company must have ALL the fields above. Answer each true/false field from the
evidence you have; if you are not sure, use false. The evidence stays in its original language.

Return ONLY a JSON array inside <json></json> tags."""

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


# Fit score rubric: the model answers four yes/no questions, the code adds up the points.
# The same answers always give the same score, and the app can show why.
RUBRIC = (("sells_same_products", 2), ("trade_buyer", 1), ("serves_businesses", 1), ("imports_or_same_material", 1))


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def _rubric_score(company):
    """1 point to start, plus the points for each "yes". None if the model gave no rubric answers."""
    if not any(key in company for key, _ in RUBRIC):
        return None
    reasons = [key for key, _ in RUBRIC if _truthy(company.get(key))]
    company["score_reasons"] = reasons
    return float(min(5, 1 + sum(points for key, points in RUBRIC if key in reasons)))


def _score(company) -> float:
    """fit_score as a number from 0 to 5, even if the model wrote "4", "4/5", "4 out of 5" or "high"."""
    value = next((company[k] for k in ("fit_score", "score", "fit", "rating", "fitScore")
                  if company.get(k) not in (None, "")), 0)
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

# Sites that list companies but are not the company's own website (found in real test runs).
DIRECTORY_DOMAINS = NOT_A_BUYER_DOMAINS + (
    "infojobs.", "brandfetch.", "rocketreach.", "prospeo.", "zoominfo.", "construying.",
    "furnscout.", "aecoctrade.", "empresite.", "eleconomista.", "einforma.", "axesor.",
    "infoempresa.", "dnb.com", "crunchbase.", "opencorporates.", "cylex", "infobel.",
    "datoscif.", "iberinform.", "libreborme.", "emis.com", "signalhire.", "apollo.io",
    "lusha.", "kompass.", "google.", "bing.", "maps.", "wikipedia.", "pinterest.",
)

LEGAL_WORDS = {"sl", "slu", "sa", "sau", "s", "l", "u", "a", "ltd", "llc", "inc", "gmbh", "srl",
               "spa", "group", "grupo", "co", "company", "the", "de", "y", "and", "del", "la", "el",
               # Common trade words: too generic to prove a domain belongs to this company
               "herrajes", "distribuciones", "distribution", "distribuidora", "comercial", "industrial",
               "industrias", "hardware", "handles", "kitchen", "import", "export", "trading", "international",
               "iberica", "iberia", "spain", "espana", "españa", "fabricados", "suministros", "solutions"}


def _name_words(name: str) -> list:
    """Distinctive words in a company name, e.g. "Herrajes Ferramol S.L.U." -> ["herrajes", "ferramol"]."""
    plain = re.sub(r"\(.*?\)", " ", name.lower())
    words = re.findall(r"[a-z0-9áéíóúñü]+", plain)
    return [w for w in words if w not in LEGAL_WORDS and len(w) >= 4]


ACCENTS = str.maketrans("áéíóúñüàèòç", "aeiounuaeoc")


def _all_name_words(name: str) -> set:
    """Every word in the name, generic ones included (used to read domains like herrajesmonastil.es)."""
    words = re.findall(r"[a-z0-9áéíóúñüàèòç]+", name.lower().translate(ACCENTS))
    return {w for w in words if len(w) >= 2}


def _made_of(label: str, words: set) -> bool:
    """True if the label can be split entirely into words from the name, e.g. "herrajesmonastil"."""
    if not label:
        return True
    return any(label.startswith(w) and _made_of(label[len(w):], words) for w in words)


def _looks_like_official_site(link: str, name: str) -> bool:
    """True if the link is not a directory and its domain name is built from the company's own name.
    Accepts monastil.es, herrajesmonastil.es, verdu-herrajes.com; rejects cauchoverdu.com (another company)."""
    host = urllib.parse.urlparse(link if "//" in link else "https://" + link).netloc.lower()
    host = host.replace("www.", "")
    if not host or any(d in host for d in DIRECTORY_DOMAINS):
        return False
    label = host.split(".")[0].translate(ACCENTS).replace("-", "")
    distinctive = [w.translate(ACCENTS) for w in _name_words(name)]
    if not any(w in label for w in distinctive):
        return False
    if _made_of(label, _all_name_words(name)):
        return True
    return any(label.startswith(w) and len(w) >= 5 for w in distinctive)


def _domain_in_path(link: str) -> str:
    """Directory pages like brandfetch.com/micel.es carry the real domain in the path."""
    first = urllib.parse.urlparse(link).path.strip("/").split("/")[0]
    return f"https://{first}" if re.fullmatch(r"[a-z0-9-]+(\.[a-z0-9-]+)+", first or "") else ""


def check_given_websites(companies: list) -> None:
    """The model sometimes puts a directory or a reseller's page in the website field.
    Keep a website only if it looks like the company's own; otherwise clear it so it gets looked up."""
    for c in companies:
        site, name = c.get("website") or "", c.get("name", "")
        if not site or _looks_like_official_site(site, name):
            continue
        fixed = _domain_in_path(site)
        c["website"] = fixed if fixed and _looks_like_official_site(fixed, name) else ""


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9áéíóúñü]+", " ", (text or "").lower()).strip()


BROWSER_HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
                                 "(KHTML, like Gecko) Chrome/120 Safari/537.36"}


def _fetch_text(url: str, timeout: int = 8) -> str:
    """Download a page and return its visible text (lower case, accents removed). "" if it can't be opened."""
    if not (url or "").startswith(("http://", "https://")):
        return ""
    lenient = ssl.create_default_context()
    lenient.check_hostname = False
    lenient.verify_mode = ssl.CERT_NONE
    try:
        request = urllib.request.Request(url, headers=BROWSER_HEADERS)
        with urllib.request.urlopen(request, timeout=timeout, context=lenient) as r:
            raw = r.read(600_000).decode("utf-8", "ignore")
    except Exception:
        return ""
    raw = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return text.lower().translate(ACCENTS)


def _quote_pieces(evidence: str) -> list:
    # The model often joins pieces of the page with "..." — every piece must be found
    pieces = [_normalize(p.translate(ACCENTS)) for p in re.split(r"\.\.\.|…", evidence or "")]
    return [p for p in pieces if p]


def _check_evidence(companies: list, results: list) -> None:
    """Check every quote, and record how it was checked:
    "page"    = found word for word on the source page itself (the page was opened)
    "snippet" = the page could not be opened, but the quote is in the search result summary of that page
    "none"    = not found, so it may be the AI's own wording.
    evidence_verified is True for "page" and "snippet"; the app shows which one."""
    by_link = {r["link"]: _normalize(f"{r['title']} {r['snippet']}".translate(ACCENTS)) for r in results}

    def check(c):
        pieces = _quote_pieces(c.get("evidence", ""))
        level = "none"
        if pieces and sum(len(p) for p in pieces) >= 12:
            page = _normalize(_fetch_text(c.get("source", "")))
            if page and all(p in page for p in pieces):
                level = "page"
            elif all(p in by_link.get(c.get("source"), "") for p in pieces):
                level = "snippet"
        c["evidence_level"] = level
        c["evidence_verified"] = level != "none"

    if companies:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(check, companies))


COUNTRY_TLDS = {
    "spain": "es", "españa": "es", "西班牙": "es", "mexico": "mx", "méxico": "mx", "墨西哥": "mx",
    "germany": "de", "德国": "de", "france": "fr", "法国": "fr", "italy": "it", "意大利": "it",
    "portugal": "pt", "葡萄牙": "pt", "netherlands": "nl", "荷兰": "nl", "poland": "pl", "波兰": "pl",
    "united kingdom": "co.uk", "uk": "co.uk", "英国": "co.uk", "brazil": "com.br", "巴西": "com.br",
    "chile": "cl", "智利": "cl", "colombia": "co", "哥伦比亚": "co", "india": "in", "印度": "in",
    "saudi arabia": "sa", "沙特": "sa", "沙特阿拉伯": "sa", "turkey": "com.tr", "土耳其": "com.tr",
    "australia": "com.au", "澳大利亚": "com.au", "japan": "jp", "日本": "jp", "vietnam": "vn", "越南": "vn",
}


def _page_mentions(url: str, name: str) -> bool:
    """Open a page and check that the distinctive words of the company name appear in it.
    Used for guessed domains, so a parked page or another company is not accepted."""
    words = [w.translate(ACCENTS) for w in _name_words(name)]
    text = _fetch_text(url)
    if not words or not text:
        return False
    if any(p in text for p in ("domain is for sale", "dominio en venta", "buy this domain", "parked")):
        return False
    # Every distinctive word must appear (up to two), so "almir.es" of another Almir is not accepted
    return all(w in text for w in dict.fromkeys(words[:2]))


def _guess_domains(name: str, country: str) -> list:
    """Likely domains built only from the company name, e.g. "Fajota Iberica S.L." -> fajota.es, fajotaiberica.es."""
    distinctive = [w.translate(ACCENTS) for w in _name_words(name)]
    if not distinctive:
        return []
    every = [w for w in re.findall(r"[a-z0-9]+", name.lower().translate(ACCENTS))
             if w not in LEGAL_WORDS or w in ("herrajes", "distribuciones", "comercial", "industrial")]
    labels = [distinctive[0], "".join(distinctive), "".join(every), "-".join(every)]
    tld = COUNTRY_TLDS.get(country.strip().lower())
    tlds = [tld, "com"] if tld and tld != "com" else ["com"]
    seen, result = set(), []
    for label in labels:
        for t in tlds:
            domain = f"{label}.{t}"
            if 3 <= len(label) <= 40 and domain not in seen:
                seen.add(domain)
                result.append(f"https://{domain}")
    return result[:6]


def find_missing_websites(companies: list, country: str, usage: "Usage") -> list:
    """For companies without a trustworthy website, try three ways, stopping at the first that works:
    1. search "name country official website"   2. search "name city"
    3. guess domains from the name and keep one only if the page mentions the company.
    A search result is only accepted if its domain is built from the company's own name."""
    missing = [c for c in companies if not c.get("website")]
    if not missing:
        return companies

    def from_search(query, name):
        try:
            results = web_search(query)
        except ValueError:
            return ""
        usage.add_search()
        for r in results:
            if _looks_like_official_site(r["link"], name):
                parts = urllib.parse.urlparse(r["link"])
                return f"{parts.scheme}://{parts.netloc}"
        return ""

    def lookup(company):
        name = company.get("name", "")
        queries = [f"{name} {country} official website"]
        if company.get("city"):
            queries.append(f"{name} {company['city']}")
        for q in queries:
            site = from_search(q, name)
            if site:
                company["website"] = site
                return
        for url in _guess_domains(name, country):
            if _page_mentions(url, name):
                company["website"] = url
                company["website_guessed"] = True
                return

    with ThreadPoolExecutor(max_workers=5) as pool:
        list(pool.map(lookup, missing))
    return companies


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
        rubric = _rubric_score(c)
        c["fit_score"] = rubric if rubric is not None else _score(c)
        c["intent"] = TIERS.get(round(c["fit_score"]), "Low / 低")
        c["linkedin_search"] = _linkedin_search(c)
        result.append(c)
    return sorted(result, key=_score, reverse=True)


COUNTRY_NAMES_EN = {
    "西班牙": "Spain", "墨西哥": "Mexico", "德国": "Germany", "法国": "France", "意大利": "Italy",
    "葡萄牙": "Portugal", "荷兰": "Netherlands", "波兰": "Poland", "英国": "United Kingdom", "美国": "United States",
    "巴西": "Brazil", "智利": "Chile", "哥伦比亚": "Colombia", "印度": "India", "沙特": "Saudi Arabia",
    "沙特阿拉伯": "Saudi Arabia", "土耳其": "Turkey", "澳大利亚": "Australia", "日本": "Japan", "越南": "Vietnam",
    "加拿大": "Canada", "阿联酋": "United Arab Emirates", "南非": "South Africa", "俄罗斯": "Russia",
}


def to_english(product: str, country: str, usage: "Usage") -> tuple:
    """Searches work best in English: a Chinese product or country name would return Chinese pages.
    Known country names are translated from a table; anything else is translated by the model."""
    country_en = COUNTRY_NAMES_EN.get(country.strip(), country.strip())
    if product.isascii() and country_en.isascii():
        return product.strip(), country_en
    response = ask([{"role": "user", "content":
                     "Translate into short, plain English as used in international trade. Return only JSON "
                     f'like {{"product": "...", "country": "..."}}.\nproduct: {product}\ncountry: {country_en}'}], 300)
    usage.add(response)
    try:
        data = json.loads(re.search(r"\{.*\}", _text_from(response), re.S).group())
        return (data.get("product") or product).strip(), (data.get("country") or country_en).strip()
    except Exception:
        return product.strip(), country_en


def research_buyers(seller: str, product: str, country: str, n: int = 10,
                    max_searches: int = 5, usage: Usage | None = None, progress=None,
                    language: str = "English"):
    """Step 1: find potential buyers (list of dicts), using whichever provider is switched on.
    progress(stage, **details) is called at each step so the app can show what is happening.
    language is the language for the AI's own text (what they sell, why they fit, next step)."""
    usage = usage or Usage()
    progress = progress or (lambda stage, **details: None)
    product, country = to_english(product, country, usage)
    if PROVIDER == "claude":
        progress("claude_search")
        companies = _research_with_claude(seller, product, country, n, max_searches, usage, language)
        return _finish(companies, [], country, usage, progress)
    return _research_with_search_api(seller, product, country, n, usage, progress, language)


def _norm_url(url: str) -> str:
    """Compare links loosely: http/https, www., a trailing slash or #anchor don't make them different."""
    url = (url or "").strip().lower().split("#")[0]
    url = re.sub(r"^https?://", "", url).replace("www.", "", 1)
    return url.rstrip("/")


def _dedupe_by_website(companies: list) -> list:
    """After websites are filled in, two rows can turn out to be the same company: keep the better one."""
    best = {}
    for c in companies:
        host = urllib.parse.urlparse(c.get("website") or "").netloc.lower().replace("www.", "")
        key = host or f'name:{(c.get("name") or "").lower().strip()}'
        if key not in best or c.get("fit_score", 0) > best[key].get("fit_score", 0):
            best[key] = c
    kept = set(map(id, best.values()))
    return [c for c in companies if id(c) in kept]


def _finish(companies, results, country, usage, progress) -> list:
    """Same checks for every provider: clean, check websites and evidence, fill in websites, dedupe."""
    companies = _clean(companies)
    check_given_websites(companies)
    _check_evidence(companies, results)
    missing = sum(1 for c in companies if not c.get("website"))
    if missing:
        progress("websites", count=missing)
    companies = find_missing_websites(companies, country, usage)
    return _dedupe_by_website(companies)


def _research_with_claude(seller, product, country, n, max_searches, usage, language="English"):
    """Claude searches the web itself (built-in web search tool)."""
    messages = [{
        "role": "user",
        "content": RESEARCH_PROMPT.format(seller=seller, product=product, country=country, n=n, language=language),
    }]
    tools = [{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}]

    # Long searches can pause mid-way ("pause_turn"); send the partial answer back to continue.
    for _ in range(3):
        response = ask(messages, 8000, tools=tools)
        usage.add(response)
        if getattr(response, "stop_reason", None) != "pause_turn":
            break
        messages = messages + [{"role": "assistant", "content": response.content}]

    return _extract_json(_text_from(response))


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


def _research_with_search_api(seller, product, country, n, usage, progress=None, language="English"):
    """Search the web first (DeepSeek Search or SerpAPI), then let the model pick real buyers from the results."""
    progress = progress or (lambda stage, **details: None)
    results, seen = [], set()
    queries = search_queries(product, country)
    for i, q in enumerate(queries, 1):
        progress("search", i=i, total=len(queries), query=q)
        usage.add_search()
        for r in web_search(q):
            if r["link"] and r["link"] not in seen:
                seen.add(r["link"])
                results.append(r)
    progress("results", count=len(results))
    if not results:
        return []

    listing = "\n".join(f"[{i}] {r['title']}\n    URL: {r['link']}\n    {r['snippet']}"
                        for i, r in enumerate(results[:40], 1))
    messages = [{"role": "user", "content": PICK_PROMPT.format(
        seller=seller, product=product, country=country, n=n, results=listing, language=language)}]
    progress("pick")
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

    # Keep only companies whose source really is one of the search results (no made-up sources).
    # Links are compared loosely, so a missing "/" or "www." doesn't throw a real buyer away.
    by_norm = {_norm_url(r["link"]): r["link"] for r in results}
    kept = []
    for c in companies:
        link = by_norm.get(_norm_url(c.get("source", "")))
        if link:
            c["source"] = link
            kept.append(c)
    return _finish(kept, results, country, usage, progress)


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
