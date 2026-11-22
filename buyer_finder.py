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
import unicodedata
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
- sells_same_products (true/false: they already sell or distribute this category of product)
- exact_products (true/false: the evidence names the specific products the seller makes, e.g. "hinges"
  or "drawer slides", not only the general category such as "hardware")
- trade_buyer (true/false: importer, distributor or wholesaler that buys in bulk, not only a shop)
- imports_or_same_material (true/false: there is evidence they import, or sell products of the same material)
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
- No em dashes (—). Use short sentences instead.
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
# Version 2 (21 Nov 2026): in test 3, 9 of 10 companies scored 5/5 because "sells to businesses" was true
# for almost every distributor and every company started at 1. Now there is no starting point, and one
# point needs the evidence to name the exact products, so scores spread out.
RUBRIC = (("sells_same_products", 2), ("exact_products", 1), ("trade_buyer", 1), ("imports_or_same_material", 1))


def _truthy(value) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "1")


def _rubric_score(company):
    """The points for each "yes" (0 to 5). None if the model gave no rubric answers."""
    if not any(key in company for key, _ in RUBRIC):
        return None
    reasons = [key for key, _ in RUBRIC if _truthy(company.get(key))]
    company["score_reasons"] = reasons
    return float(min(5, sum(points for key, points in RUBRIC if key in reasons)))


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
    """Download a page and return its visible text as written (one line per block). "" if it can't be opened.
    Callers that compare words use _fold() on it; the original is kept so a sentence can be shown to the user."""
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
    # Block tags become line breaks, so headings and paragraphs stay separate sentences
    raw = re.sub(r"(?i)<(br|/p|/div|/h[1-6]|/li|/td|/tr|/title|/section|/header|/footer)\b[^>]*>", "\n", raw)
    text = html.unescape(re.sub(r"(?s)<[^>]+>", " ", raw))
    return re.sub(r"[ \t\r\f\v]+", " ", text)


def _fold(text: str) -> str:
    """Lower case, accents removed: the form used to compare quotes and names with a page."""
    return (text or "").lower().translate(ACCENTS)


def _quote_pieces(evidence: str) -> list:
    # The model often joins pieces of the page with "...": every piece must be found
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
            raw_page = _fetch_text(c.get("source", ""))
            page = _normalize(_fold(raw_page))
            # The page is already open: look for signs that the company makes this itself
            own_site = _looks_like_official_site(c.get("source", ""), c.get("name", ""))
            flag_maker(c, raw_page, c.get("source", ""), about_company_only=not own_site)
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


# ---------- Does the page say they make this themselves? (round 7) ----------
# The model's "type" field said "distributor" for a company whose own homepage says
# "FERRAMOL, desde 1979, diseña y fabrica tiradores y pomos". So the page text is checked too.
# Patterns run on text that is lower case with all accents removed.
MAKER_CUES = [re.compile(p) for p in (
    # Spanish / Portuguese
    r"\bfabricamos\b", r"\bproduzimos\b",
    r"\b(disena|disenamos|desarrolla|desarrollamos|produce|producimos|crea|creamos|concebe)\s+y\s+fabrica(mos)?\b",
    r"\bsomos\s+(una\s+empresa\s+|uma\s+empresa\s+|los\s+|unos\s+)?(fabricantes?|productores?)\b",
    r"\b(nuestra|nuestras|nossa|nossas|propia|propias|propria)\s+(fabrica|fabricas|planta\s+de\s+produccion)\b",
    r"\b(empresa|compania)\s+(es\s+)?fabricante\b", r"\be\s+uma?\s+(empresa\s+)?fabricante\b",
    r"\b(la\s+empresa|la\s+compania|a\s+empresa)\s+fabrica\b",
    r"\b(dedica-se|dedicamo-nos|se\s+dedica)\b[^.]{0,60}\b(ao\s+fabrico|a\s+la\s+fabricacion|a\s+fabricar)\b",
    # German
    r"\bwir\s+(fertigen|produzieren|entwickeln\s+und\s+(fertigen|produzieren))\b", r"\bwir\s+stellen\b[^.]{0,60}\bher\b",
    r"\b(eigene|eigener|eigenen)\s+(herstellung|fertigung|produktion)\b",
    r"\b(ist|sind)\s+(ein|eine|einer\s+der)?\s*(\w+\s+){0,2}hersteller\b", r"\bunsere?\s+(fabrik|fertigung|produktionsstatte)\b",
    # French
    r"\bnous\s+(fabriquons|produisons|concevons\s+et\s+fabriquons)\b", r"\bnotre\s+usine\b",
    r"\b(sommes|est)\s+(un\s+)?(\w+\s+){0,2}fabricant\b",
    # Italian
    r"\b(fabbrichiamo|produciamo)\b", r"\b(il\s+)?nostro\s+stabilimento\b", r"\bnostra\s+(fabbrica|produzione)\b",
    r"\bsiamo\s+(un\s+|una\s+)?(\w+\s+){0,2}(produttori?|fabbricanti?|azienda\s+produttrice)\b",
    # English
    r"\bwe\s+(design\s+and\s+|develop\s+and\s+)?(manufacture|produce|fabricate)\b", r"\bmanufacture\s+our\b",
    r"\bour\s+(own\s+)?(factory|factories|manufacturing\s+(plant|facility|facilities|site))\b",
    r"\b(we\s+are|is)\s+(a|an|the)\s+(\w+\s+){0,3}manufacturer\b", r"\bin-house\s+(production|manufacturing)\b",
    # A heading that starts with "Factory of ..." / "Manufacturers of ..." (weakest, so last)
    r"^(fabrica|fabricantes?|manufacturers?|hersteller|fabricant|produttori?)\s+(de|of|von|fur|di)\b",
)]

# They have the product made for them under their own brand: that is an OEM buyer, not a manufacturer.
OEM_BUYER_CUES = [re.compile(p) for p in (
    r"\bmandamos\s+(a\s+)?fabricar\b", r"\bencargamos\b[^.]{0,40}\bfabrica", r"\bfabricad[oa]s?\s+para\s+(nosotros|nos)\b",
    r"\b(manufactured|made|produced)\s+for\s+us\b", r"\bhave\b[^.]{0,40}\b(made|manufactured|produced)\s+(under|to|for)\s+our\b",
    r"\b(lassen|liessen)\b[^.]{0,60}\b(fertigen|herstellen|produzieren)\b", r"\bfur\s+uns\s+(gefertigt|hergestellt|produziert)\b",
    r"\bfaisons\s+fabriquer\b", r"\bfabriques?\s+pour\s+nous\b", r"\bfacciamo\s+(produrre|fabbricare)\b",
    r"\b(prodotti|fabbricati)\s+per\s+noi\b",
)]


def _plain(text: str) -> str:
    """Lower case with every accent removed (also ã, ê, ü), for pattern matching in any language."""
    decomposed = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _sentences(text: str) -> list:
    """Split page text into sentences and headings (line breaks, full stops, "|" separators in titles)."""
    text = html.unescape(re.sub(r"<[^>]+>", "\n", text or ""))   # in case raw HTML is passed in
    parts = re.split(r"\n+|(?<=[.!?])\s+|\s\|\s", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p and p.strip()]


def maker_sentence(text: str, name: str = "", about_company_only: bool = False) -> str:
    """The first sentence in which the page says the company makes things itself, or "".
    about_company_only: the page is someone else's (a directory, a reseller), so only sentences
    that name the company count. A sentence next to an OEM cue ("mandamos a fabricar ... bajo nuestra
    marca", "made for us") is ignored: they have products made for them, so they are buyers."""
    sentences = _sentences(text)
    plain = [_plain(s) for s in sentences]
    words = [_plain(w) for w in _name_words(name)] if name else []
    for cue in MAKER_CUES:
        for i, s in enumerate(plain):
            if not cue.search(s):
                continue
            if about_company_only and not any(re.search(rf"\b{re.escape(w)}\b", s) for w in words):
                continue
            nearby = " ".join(plain[max(0, i - 1): i + 2])
            if any(oem.search(nearby) for oem in OEM_BUYER_CUES):
                continue
            return sentences[i][:300]
    return ""


def flag_maker(company: dict, text: str, url: str, about_company_only: bool = False) -> bool:
    """If the page says the company makes this itself, record the sentence in maker_flag.
    A flagged company keeps its place in the list (the page may be wrong, or they may also import),
    but it loses the trade_buyer point and the app does not count it as fully verified."""
    if company.get("maker_flag") or not text:
        return bool(company.get("maker_flag"))
    sentence = maker_sentence(text, company.get("name", ""), about_company_only)
    if not sentence:
        return False
    company["maker_flag"] = {"sentence": sentence, "url": url}
    reasons = company.get("score_reasons")
    if isinstance(reasons, list) and "trade_buyer" in reasons:
        company["score_reasons"] = [r for r in reasons if r != "trade_buyer"]
        company["fit_score"] = float(min(5, sum(p for k, p in RUBRIC if k in company["score_reasons"])))
        company["intent"] = TIERS.get(round(company["fit_score"]), "Low / 低")
    return True


# ---------- Is a guessed website in the right country? (round 7) ----------
# fajota.com was accepted for "Fajota Iberica SL" (Spain) because the name matched, but it is a
# Portuguese manufacturer: Portuguese text, +351 phone number, postal code 3754-909 Águeda.
GENERIC_TLDS = {"com", "net", "org", "eu", "info", "biz", "io", "co", "shop", "store", "online", "site", "global"}
TLD_LANGS = {"es": {"es", "ca"}, "mx": {"es"}, "cl": {"es"}, "co": {"es"}, "pt": {"pt"}, "com.br": {"pt"},
             "de": {"de"}, "fr": {"fr"}, "it": {"it"}, "co.uk": {"en"}, "in": {"en"}, "com.au": {"en"}}
PHONE_CODES = {"es": "34", "pt": "351", "mx": "52", "de": "49", "fr": "33", "it": "39", "com.br": "55",
               "co.uk": "44", "nl": "31", "pl": "48", "cl": "56", "co": "57", "in": "91", "sa": "966",
               "com.tr": "90", "com.au": "61", "jp": "81", "vn": "84"}
POSTAL_PATTERNS = {"pt": r"\b\d{4}-\d{3}\b", "com.br": r"\b\d{5}-\d{3}\b"}
LANG_NAMES = {"es": "Spanish", "pt": "Portuguese", "de": "German", "fr": "French", "it": "Italian", "en": "English"}
# Short words that appear in one language and not in its neighbours (no "la", "de", "a", "con", "una", "e")
STOPWORDS = {
    "es": {"el", "los", "las", "del", "y", "es", "al", "por", "nuestro", "nuestra", "nuestros", "su", "sus", "muy"},
    "pt": {"o", "os", "do", "da", "dos", "das", "e", "com", "uma", "em", "na", "ao", "nao", "sao", "nossa", "nosso"},
    "de": {"der", "die", "das", "und", "mit", "fur", "ist", "wir", "unsere", "ein", "eine", "von", "zu", "auf"},
    "fr": {"le", "les", "des", "et", "avec", "pour", "est", "nous", "notre", "du", "sur", "dans", "vous"},
    "it": {"il", "gli", "della", "delle", "per", "sono", "nostro", "nostra", "che", "di", "anche"},
    "en": {"the", "and", "with", "for", "our", "we", "is", "of", "to", "you", "are"},
}


def _page_language(text: str) -> str:
    """The language most of the page is written in, or "" if there is not enough text to tell."""
    tokens = re.findall(r"[a-z]+", _plain(text))
    counts = {lang: sum(1 for t in tokens if t in words) for lang, words in STOPWORDS.items()}
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    (top, n1), (_, n2) = ranked[0], ranked[1]
    return top if n1 >= 15 and n1 >= 1.5 * n2 else ""


def country_mismatch(url: str, text: str, country: str) -> str:
    """Why a guessed website looks like a company in another country, or "" if nothing points that way.
    Checks the domain ending, the page language and phone/postal codes in the address."""
    target = COUNTRY_TLDS.get((country or "").strip().lower())
    if not target:
        return ""
    host = urllib.parse.urlparse(url if "//" in url else "https://" + url).netloc.lower().split(":")[0]
    reasons = []
    known = set(COUNTRY_TLDS.values()) | {"uk", "br", "tr", "au", "at", "ch", "be", "ar", "pe", "cn", "us"}
    suffix = next((t for t in sorted(known, key=len, reverse=True) if host.endswith("." + t)), "")
    if suffix and suffix != target and suffix not in GENERIC_TLDS:
        reasons.append(f"domain ends in .{suffix}")
    lang = _page_language(text)
    if lang and lang != "en" and target in TLD_LANGS and lang not in TLD_LANGS[target]:
        reasons.append(f"page is in {LANG_NAMES[lang]}")
    # Address: phone numbers and postal codes of another country, and none of the target country.
    # One foreign phone number alone is not enough (a Spanish company can list its Italian branch),
    # so it takes two foreign numbers, or a foreign number plus a foreign postal code.
    found = re.findall(r"\+ ?(\d{2,3})\)?[ .\-]?\(?\d{2,}", text or "")
    foreign = [code for code in found if code in PHONE_CODES.values() and code != PHONE_CODES.get(target)]
    postal = [m.group() for tld, p in POSTAL_PATTERNS.items() if tld != target for m in [re.search(p, text or "")] if m]
    if PHONE_CODES.get(target) not in found and len(foreign) + len(postal) >= 2 and foreign:
        reasons.append("address " + ", ".join([f"+{c}" for c in dict.fromkeys(foreign)] + postal))
    return "; ".join(reasons)


def _mentions_company(text: str, name: str) -> bool:
    """Check that the distinctive words of the company name appear in the page text.
    Used for guessed domains, so a parked page or another company is not accepted."""
    words = [w.translate(ACCENTS) for w in _name_words(name)]
    text = _fold(text)
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
            text = _fetch_text(url)
            if not _mentions_company(text, name):
                continue
            # A matching name is not enough: the site must also look like it is in the target country
            reason = country_mismatch(url, text, country)
            if reason:
                company.setdefault("websites_rejected", []).append(
                    {"url": url, "reason": f"looks like a company outside {country}: {reason}"})
                continue
            company["website"] = url
            company["website_guessed"] = True
            flag_maker(company, text, url)
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
        site = (c.get("website") or "").strip()
        if site and not site.startswith(("http://", "https://")):
            c["website"] = "https://" + site.lstrip("/")   # "micel.es" -> "https://micel.es", so it is a link
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
    # A maker flag can lower a score, so sort again
    return sorted(_dedupe_by_website(companies), key=_score, reverse=True)


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
    """Step 1b: open every website at the same time, mark the ones that work, and check each homepage
    for signs that the company makes this itself (see flag_maker)."""
    if not companies:
        return companies
    def check(company):
        site = company.get("website", "")
        if site and not site.startswith("http"):
            site = "https://" + site
        # One request does both jobs: if the homepage text comes back, the site works and its text
        # is checked for signs that the company makes this itself. Otherwise fall back to the plain check
        # (it also accepts sites that block automated visits with 403 and similar).
        text = _fetch_text(site) if site else ""
        if text.strip():
            flag_maker(company, text, site)
            return True
        return check_website(site)

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(check, companies))
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
