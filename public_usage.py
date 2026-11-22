"""Usage limits, search and feedback logging for the public free version.

Streamlit Community Cloud has no database and its disk is wiped on restart, so:
- counters live in memory (they reset when the app restarts or goes to sleep),
- every search and every piece of feedback is printed as one JSON line to the app logs,
  and also sent to FEEDBACK_WEBHOOK_URL if that secret is set.

Everything here is plain Python with no Streamlit import, so it can be tested without a browser.
Read the stats from a saved log file with:  python public_usage.py stats logs.txt
"""

import hashlib
import json
import re
import sys
import threading
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timezone

DEFAULT_PER_VISITOR = 3
DEFAULT_TOTAL = 100
LOG_PREFIX = "BF_EVENT "
WECHAT = "haileyyy_qz"

LIMIT_MESSAGES = {
    "visitor": ("今天的 {n} 次免费搜索已经用完了。想要人工核对过的完整报告，可以加微信 " + WECHAT + "。",
                "Your {n} free searches for today are used up. For a full report checked by hand, "
                "add me on WeChat: " + WECHAT + "."),
    "total": ("今天的免费搜索名额已经用完了，明天再来试试。想要人工核对过的完整报告，可以加微信 " + WECHAT + "。",
              "Today's free searches are used up, please try again tomorrow. For a full report checked by hand, "
              "add me on WeChat: " + WECHAT + "."),
}


def utc_day(now=None) -> str:
    """The UTC date used as the counter key, e.g. '2026-11-22'. A new day starts at 08:00 Hong Kong time."""
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).strftime("%Y-%m-%d")


def read_limits(get) -> dict:
    """Read both limits with `get(name)` (st.secrets or env). Missing or invalid values use the defaults."""
    def number(name, default):
        try:
            value = int(str(get(name)).strip())
            return value if value >= 0 else default
        except (TypeError, ValueError):
            return default
    return {"per_visitor": number("SEARCHES_PER_VISITOR_PER_DAY", DEFAULT_PER_VISITOR),
            "total": number("SEARCHES_PER_DAY_TOTAL", DEFAULT_TOTAL)}


def fingerprint(headers: dict, day: str, salt: str = "") -> str | None:
    """A rough visitor id: hash of client IP + browser, changing every day. Nothing readable is kept.

    Only the X-Forwarded-For / X-Real-Ip header is used for the IP. The raw connection IP is not used,
    because behind Streamlit's proxy it can be the same for every visitor, which would make all
    visitors share 3 searches. With no forwarded IP we return None and fall back to the browser session.
    """
    h = {str(k).lower(): str(v) for k, v in (headers or {}).items()}
    ip = (h.get("x-forwarded-for", "").split(",")[0] or h.get("x-real-ip", "")).strip()
    if not ip:
        return None
    raw = "|".join([salt, day, ip, h.get("user-agent", ""), h.get("accept-language", "")])
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class DailyCounters:
    """In-memory counters keyed by UTC day: one total for the app and one per visitor fingerprint.

    Thread safe, because Streamlit serves each visitor in its own thread. Old days are dropped.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.day = ""
        self.total = 0
        self.visitors = defaultdict(int)

    def _roll(self, day):
        if day != self.day:
            self.day, self.total, self.visitors = day, 0, defaultdict(int)

    def counts(self, day, fp=None) -> tuple[int, int]:
        with self._lock:
            self._roll(day)
            return self.total, (self.visitors.get(fp, 0) if fp else 0)

    def try_consume(self, day, limits, session_count, fp=None) -> str | None:
        """Count one search if both limits allow it. Returns None if allowed, else 'visitor' or 'total'."""
        with self._lock:
            self._roll(day)
            blocked = check_limits(limits, session_count, self.visitors.get(fp, 0) if fp else 0, self.total)
            if blocked is None:
                self.total += 1
                if fp:
                    self.visitors[fp] += 1
            return blocked

    def reset(self):
        with self._lock:
            self.day, self.total, self.visitors = "", 0, defaultdict(int)


COUNTERS = DailyCounters()   # one per running app; resets when the app restarts


def check_limits(limits, session_count, fingerprint_count, total_count) -> str | None:
    """Which limit blocks the next search, if any. The visitor count is the higher of session and fingerprint."""
    if total_count >= limits["total"]:
        return "total"
    if max(session_count, fingerprint_count) >= limits["per_visitor"]:
        return "visitor"
    return None


def session_count(record: dict | None, day: str) -> int:
    """Searches this browser session made today. `record` is {'day': ..., 'count': ...} from session state."""
    return record["count"] if record and record.get("day") == day else 0


def limit_message(kind: str, limits: dict) -> str:
    zh, en = LIMIT_MESSAGES[kind]
    return f"{zh.format(n=limits['per_visitor'])}\n\n{en.format(n=limits['per_visitor'])}"


# ---------- Logging ----------

def _ts(now=None) -> str:
    return (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds")


def search_record(country: str, product: str, now=None) -> dict:
    """One line per search. Only the country and the length of the product text: no company details."""
    return {"event": "search", "ts": _ts(now), "country": (country or "").strip()[:60],
            "product_len": len((product or "").strip())}


def limit_record(kind: str, now=None) -> dict:
    """Someone wanted to search but a limit stopped them: shows demand for paid reports."""
    return {"event": "limit_hit", "ts": _ts(now), "limit": kind}


def feedback_record(feedback_id: str, rating: int | None, comment: str, country: str, n_results: int,
                    now=None) -> dict:
    """rating comes from st.feedback('thumbs'): 1 = up, 0 = down. The comment is cut to one short line."""
    one_line = " ".join((comment or "").split())[:200]
    return {"event": "feedback", "ts": _ts(now), "id": feedback_id,
            "rating": {1: "up", 0: "down"}.get(rating), "comment": one_line,
            "country": (country or "").strip()[:60], "n_results": n_results}


def log_line(record: dict) -> str:
    return LOG_PREFIX + json.dumps(record, ensure_ascii=False, sort_keys=True)


def _post(url: str, record: dict, timeout: float = 5):
    req = urllib.request.Request(url, data=json.dumps(record, ensure_ascii=False).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    urllib.request.urlopen(req, timeout=timeout).close()


def emit(record: dict, webhook_url: str | None = None, printer=None, post=None, background: bool = True):
    """Print the record as one log line; if a webhook is set, also POST it as JSON.

    The webhook runs in a background thread and any error is ignored, so a slow or broken
    webhook never slows down or breaks the app. The webhook URL itself is never printed.
    """
    (printer or (lambda s: print(s, flush=True)))(log_line(record))
    if not webhook_url:
        return
    send = post or _post

    def go():
        try:
            send(webhook_url, record)
        except Exception:
            pass
    if background:
        threading.Thread(target=go, daemon=True).start()
    else:
        go()


# ---------- Hiding secrets in error messages ----------

_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{8,}"),                                   # DeepSeek / Anthropic style keys
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9_\-\.]{8,}"),
    # key=..., token: ... (the value must contain a digit, so names like DEEPSEEK_API_KEY stay readable)
    re.compile(r"(?i)((?:api[_-]?key|x-api-key|key|token)\s*[=:]\s*[\"']?)(?=[A-Za-z_\-\.]*\d)[A-Za-z0-9_\-\.]{8,}"),
]


def redact(text: str, secrets=()) -> str:
    """Replace any known secret value and anything that looks like an API key with [hidden]."""
    text = str(text or "")
    for s in secrets:
        if s and len(str(s)) >= 6:
            text = text.replace(str(s), "[hidden]")
    for p in _KEY_PATTERNS:
        text = p.sub(lambda m: (m.group(1) if m.groups() else "") + "[hidden]", text)
    return text


# ---------- Reading stats back from the logs ----------

def parse_events(lines) -> list[dict]:
    """Pull our JSON events out of a Streamlit Cloud log download. Other lines are skipped."""
    events = []
    for line in lines:
        i = line.find(LOG_PREFIX)
        if i < 0:
            continue
        try:
            events.append(json.loads(line[i + len(LOG_PREFIX):]))
        except json.JSONDecodeError:
            continue
    return events


def summarize(events) -> dict:
    """Searches per day, top countries, limit hits, and feedback (latest rating per feedback id)."""
    searches = [e for e in events if e.get("event") == "search"]
    latest = {}
    for e in events:
        if e.get("event") == "feedback":
            latest[e.get("id")] = e
    ratings = Counter(e.get("rating") for e in latest.values() if e.get("rating"))
    return {
        "searches_per_day": dict(sorted(Counter(e["ts"][:10] for e in searches).items())),
        "top_countries": Counter(e.get("country", "") for e in searches).most_common(10),
        "limit_hits": dict(Counter(e.get("limit") for e in events if e.get("event") == "limit_hit")),
        "feedback": {"up": ratings.get("up", 0), "down": ratings.get("down", 0)},
        "comments": [(e["ts"], e.get("rating"), e["comment"]) for e in latest.values() if e.get("comment")],
    }


if __name__ == "__main__":
    if len(sys.argv) != 3 or sys.argv[1] != "stats":
        sys.exit("Usage: python public_usage.py stats <log file>")
    with open(sys.argv[2], encoding="utf-8", errors="replace") as f:
        print(json.dumps(summarize(parse_events(f)), ensure_ascii=False, indent=2))
