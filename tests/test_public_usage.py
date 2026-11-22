"""Tests for the public free version: limits, logging and hiding secrets. Pure functions, no network."""
import json
import os
import sys
import threading
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import public_usage as pu  # noqa: E402

LIMITS = {"per_visitor": 3, "total": 100}
NOW = datetime(2026, 11, 22, 23, 59, tzinfo=timezone.utc)


def test_defaults_and_config():
    assert pu.read_limits(lambda name: None) == {"per_visitor": 3, "total": 100}
    cfg = {"SEARCHES_PER_VISITOR_PER_DAY": "5", "SEARCHES_PER_DAY_TOTAL": 40}
    assert pu.read_limits(cfg.get) == {"per_visitor": 5, "total": 40}
    bad = {"SEARCHES_PER_VISITOR_PER_DAY": "lots", "SEARCHES_PER_DAY_TOTAL": "-1"}
    assert pu.read_limits(bad.get) == {"per_visitor": 3, "total": 100}


def test_utc_day_uses_utc_not_hong_kong_time():
    hk = timezone(timedelta(hours=8))
    assert pu.utc_day(datetime(2026, 11, 23, 7, 59, tzinfo=hk)) == "2026-11-22"
    assert pu.utc_day(datetime(2026, 11, 23, 8, 0, tzinfo=hk)) == "2026-11-23"


def test_check_limits():
    assert pu.check_limits(LIMITS, 2, 0, 99) is None
    assert pu.check_limits(LIMITS, 3, 0, 0) == "visitor"
    assert pu.check_limits(LIMITS, 0, 3, 0) == "visitor", "a new tab with the same fingerprint is still blocked"
    assert pu.check_limits(LIMITS, 0, 0, 100) == "total"


def test_counter_per_visitor_and_total():
    c = pu.DailyCounters()
    day = "2026-11-22"
    for _ in range(3):
        assert c.try_consume(day, LIMITS, 0, "fp1") is None
    assert c.try_consume(day, LIMITS, 0, "fp1") == "visitor"
    assert c.try_consume(day, LIMITS, 0, "fp2") is None
    assert c.counts(day, "fp1") == (4, 3)


def test_counter_total_cap_and_daily_reset():
    c = pu.DailyCounters()
    small = {"per_visitor": 3, "total": 2}
    assert c.try_consume("2026-11-22", small, 0) is None
    assert c.try_consume("2026-11-22", small, 0) is None
    assert c.try_consume("2026-11-22", small, 0) == "total"
    assert c.try_consume("2026-11-23", small, 0) is None, "a new UTC day starts from zero"
    assert c.counts("2026-11-23") == (1, 0)


def test_counter_is_thread_safe():
    c = pu.DailyCounters()
    results = []
    threads = [threading.Thread(target=lambda: results.append(c.try_consume("d", LIMITS, 0))) for _ in range(150)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert results.count(None) == 100 and c.counts("d")[0] == 100


def test_session_count_resets_on_new_day():
    assert pu.session_count({"day": "2026-11-21", "count": 3}, "2026-11-22") == 0
    assert pu.session_count({"day": "2026-11-22", "count": 2}, "2026-11-22") == 2
    assert pu.session_count(None, "2026-11-22") == 0


def test_fingerprint():
    h = {"X-Forwarded-For": "1.2.3.4, 10.0.0.1", "User-Agent": "Safari"}
    a = pu.fingerprint(h, "2026-11-22")
    assert a == pu.fingerprint({"x-forwarded-for": "1.2.3.4", "user-agent": "Safari"}, "2026-11-22")
    assert a != pu.fingerprint(h, "2026-11-23"), "changes every day"
    assert a != pu.fingerprint({**h, "X-Forwarded-For": "5.6.7.8"}, "2026-11-22")
    assert "1.2.3.4" not in a and len(a) == 16
    assert pu.fingerprint({"User-Agent": "Safari"}, "2026-11-22") is None, "no forwarded IP: session only"


def test_limit_message_is_bilingual_with_wechat():
    for kind in ("visitor", "total"):
        msg = pu.limit_message(kind, LIMITS)
        assert "haileyyy_qz" in msg and "免费搜索" in msg and "free searches" in msg and "—" not in msg


def test_search_record_keeps_only_length():
    r = pu.search_record("Spain", "Stainless steel hinges", now=NOW)
    assert r == {"event": "search", "ts": "2026-11-22T23:59:00+00:00", "country": "Spain", "product_len": 22}


def test_feedback_record_and_log_line():
    r = pu.feedback_record("ab12-0", 0, "  too many\nshops  " + "x" * 300, "España", 10, now=NOW)
    assert r["rating"] == "down" and "\n" not in r["comment"] and len(r["comment"]) == 200
    line = pu.log_line(r)
    assert line.startswith("BF_EVENT ") and "\n" not in line and "España" in line
    assert json.loads(line[len("BF_EVENT "):]) == r


def test_emit_prints_and_posts_only_with_webhook():
    printed, posted = [], []
    rec = pu.search_record("Spain", "x", now=NOW)
    pu.emit(rec, None, printer=printed.append, post=lambda u, r: posted.append((u, r)), background=False)
    assert len(printed) == 1 and posted == []
    pu.emit(rec, "https://hook.example/x", printer=printed.append, post=lambda u, r: posted.append((u, r)),
            background=False)
    assert posted == [("https://hook.example/x", rec)] and "hook.example" not in printed[1]


def test_emit_ignores_webhook_errors():
    def broken(url, record):
        raise OSError("down")
    pu.emit(pu.search_record("Spain", "x"), "https://hook.example", printer=lambda s: None, post=broken,
            background=False)


def test_redact():
    secret = "my-webhook-secret-123"
    text = ("Error 401 at https://serpapi.com/search?api_key=abc123def456ghi key sk-ant-api03-XYZxyz123456 "
            f"Authorization: Bearer eyJhbGciOi.abc posting to {secret}")
    out = pu.redact(text, [secret, None, ""])
    for leaked in ("abc123def456ghi", "XYZxyz123456", "eyJhbGciOi", secret):
        assert leaked not in out
    assert out.startswith("Error 401 at https://serpapi.com/search?api_key=[hidden]")
    assert pu.redact("Too many requests. Wait a minute.") == "Too many requests. Wait a minute."
    assert pu.redact("Missing key: DEEPSEEK_API_KEY") == "Missing key: DEEPSEEK_API_KEY"


def test_stats_from_logs():
    lines = [
        "2026-11-22 10:00:00 some streamlit noise",
        pu.log_line(pu.search_record("Spain", "hinges", now=NOW)),
        "[app] " + pu.log_line(pu.search_record("Spain", "handles", now=NOW)),
        pu.log_line(pu.search_record("Peru", "handles", now=NOW + timedelta(days=1))),
        pu.log_line(pu.limit_record("visitor", now=NOW)),
        pu.log_line(pu.feedback_record("a-0", 0, "", "Spain", 10, now=NOW)),
        pu.log_line(pu.feedback_record("a-0", 1, "changed my mind", "Spain", 10, now=NOW)),
        pu.log_line(pu.feedback_record("b-0", 0, "", "Peru", 8, now=NOW)),
        "BF_EVENT {broken json",
    ]
    s = pu.summarize(pu.parse_events(lines))
    assert s["searches_per_day"] == {"2026-11-22": 2, "2026-11-23": 1}
    assert s["top_countries"][0] == ("Spain", 2)
    assert s["limit_hits"] == {"visitor": 1}
    assert s["feedback"] == {"up": 1, "down": 1}, "latest rating per feedback id counts once"
    assert s["comments"] == [("2026-11-22T23:59:00+00:00", "up", "changed my mind")]
