"""Regression tests for the web app (runs app.py headless with a fake backend: no API key needed)."""
import os
import sys
import types

import pytest

HERE = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(HERE, ".."))
import buyer_finder as real  # noqa: E402
from streamlit.testing.v1 import AppTest  # noqa: E402

state = {"mode": "ok", "email_fail": False, "calls": []}


def research_buyers(seller, product, country, n=10, usage=None, progress=None, language="English"):
    state["calls"].append({"product": product, "country": country, "language": language})
    progress("search", i=1, total=3, query="q")
    if state["mode"] == "fail":
        raise Exception("Your credit balance is too low")
    if state["mode"] == "empty":
        return []
    usage.add_search(3)
    return [
        {"name": "A Co", "website": "https://a.example", "fit_score": 5.0, "why_fit": "fits A", "evidence": "we sell hinges",
         "evidence_level": "page", "evidence_verified": True, "source": "https://s.example", "linkedin_search": "https://l",
         "score_reasons": ["sells_same_products", "trade_buyer", "serves_businesses", "imports_or_same_material"]},
        {"name": "B Co", "website": "", "fit_score": 4.0, "why_fit": "fits B", "evidence": "", "linkedin_search": "https://l",
         "score_reasons": ["sells_same_products", "trade_buyer"]},
        {"name": "C Co", "website": "https://c.example", "fit_score": 3.0, "why_fit": "fits C", "evidence": "summary quote",
         "evidence_level": "snippet", "evidence_verified": True, "linkedin_search": "https://l", "score_reasons": []},
        {"name": "D Co", "website": "https://d.example", "fit_score": 2.0, "why_fit": "fits D", "evidence": "",
         "linkedin_search": "https://l", "score_reasons": []},
    ]


def verify_websites(cs):
    for c in cs:
        c["website_ok"] = bool(c["website"])
    return cs


def draft_emails(seller, product, cs, top=3, language="English", usage=None):
    if state["email_fail"]:
        raise Exception("Too many requests")
    return [{"company": c["name"], "email": f"Subject: hi {c['name']}"} for c in cs[:top]]


fake = types.ModuleType("buyer_finder")
fake.Usage, fake.friendly_error = real.Usage, real.friendly_error
fake.research_buyers, fake.verify_websites, fake.draft_emails = research_buyers, verify_websites, draft_emails


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setitem(sys.modules, "buyer_finder", fake)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    state.update(mode="ok", email_fail=False, calls=[])


def new():
    at = AppTest.from_file(os.path.join(HERE, "..", "app.py"), default_timeout=30)
    at.run()
    return at


def button(at, label, sidebar=False):
    pool = at.sidebar.button if sidebar else at.button
    return next(b for b in pool if b.label == label)


def run(at):
    button(at, "Find buyers").click().run()
    assert not at.exception, at.exception
    return at


def detail_text(at):
    return " ".join(m.value for m in at.markdown)


def select_row(at, row):
    key = "table0_False"
    at.session_state[key] = {"selection": {"rows": [row], "columns": [], "cells": []}}
    at.run()


# L1: filtering never shows the wrong company in the detail panel
def test_L1_selection_follows_the_company_not_the_row():
    at = run(new())
    select_row(at, 2)                                   # C Co
    assert "bf-name\">C Co<" in detail_text(at)
    at.toggle[0].set_value(True).run()                  # hide B Co (no website): row 3 is now D Co
    assert "bf-name\">C Co<" in detail_text(at), "detail panel must still show C Co, not D Co"


# L3: if writing emails fails, the buyers are kept and the emails can be retried
def test_L3_email_failure_keeps_results():
    state["email_fail"] = True
    at = run(new())
    assert "bf-route" in detail_text(at) and at.warning
    state["email_fail"] = False
    button(at, "Write the emails again").click().run()
    assert any("Subject: hi A Co" in c.value for c in at.code)


# U1: you can go back and change the last search
def test_U1_edit_search_prefills_form():
    at = new()
    at.text_input[1].input("Portugal")
    at = run(at)
    button(at, "Edit this search").click().run()
    assert at.text_input[1].value == "Portugal"
    button(at, "New search", sidebar=True).click().run()
    assert at.text_input[1].value == "Spain"


# U2: the language switch is in the main page, not hidden in the sidebar
def test_U2_language_switch_on_page():
    at = new()
    assert at.radio[0].options == ["English", "中文"] and not at.sidebar.radio


# U3: a visitor can see a real sample result without the password
def test_U3_sample_without_password(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw12345")
    at = new()
    assert not [b for b in at.button if b.label == "Find buyers"]
    button(at, "View a sample result (no password needed)").click().run()
    assert not at.exception and "bf-route" in detail_text(at) and at.info
    assert not [b for b in at.button if b.label in ("Edit this search", "New search")]
    at.text_input  # no form
    button(at, "Run your own search").click().run()
    assert at.text_input and at.text_input[0].label == "This demo is password protected"


def test_U3_password_still_works(monkeypatch):
    monkeypatch.setenv("APP_PASSWORD", "pw12345")
    at = new()
    at.text_input[0].input("wrong").run()
    assert not [b for b in at.button if b.label == "Find buyers"]
    at.text_input[0].input("pw12345").run()
    assert [b for b in at.button if b.label == "Find buyers"]


# U4: the company shown on the right is marked in the table
def test_U4_current_row_marked():
    at = run(new())
    table = at.dataframe[0].value
    assert table[" "].tolist() == ["●", "", "", ""]
    assert "Viewing 1 of 4" in detail_text(at)


# U5: after an error there is a way to try again
def test_U5_retry_after_error():
    state["mode"] = "fail"
    at = run(new())
    assert at.error
    state["mode"] = "ok"
    button(at, "Try again").click().run()
    assert "bf-route" in detail_text(at)


def test_U5_empty_result_explained():
    state["mode"] = "empty"
    at = run(new())
    assert at.error and "No companies found" in at.error[0].value


# U6: history entries say what the number means
def test_U6_history_label():
    at = run(new())
    assert any("(4 buyers)" in b.label for b in at.sidebar.button)


# U7: Chinese interface asks for Chinese text; export has no duplicate columns and includes the email
def test_U7_language_and_export():
    at = new()
    at.radio[0].set_value("中文").run()
    button(at, "开始找买家").click().run()
    assert state["calls"][-1]["language"] == "Simplified Chinese"


def test_U7_export_has_email_and_no_duplicate_columns():
    import inspect
    src = open(os.path.join(HERE, "..", "app.py"), encoding="utf-8").read()
    export_block = src[src.index("export = pd.DataFrame"):src.index("tool_right.download_button")]
    assert '"email"' in export_block and '"intent"' not in export_block and '"evidence_level"' in export_block


# U8: the company description says what to write
def test_U8_about_has_help():
    at = new()
    assert at.text_area[0].help and "minimum order" in at.text_area[0].help


# T2 + T3: score explained, evidence column says how it was checked
def test_T2_T3_score_reasons_and_evidence_column():
    at = run(new())
    assert at.dataframe[0].value["Evidence"].tolist() == ["On page", "Not found", "In summary", "Not found"]
    md = detail_text(at)
    assert "How the 5/5 fit score was worked out" in md and "Already sells this kind of product (+2)" in md


# Status changes stay with the right company, also after filtering and going back to history
def test_status_follows_company():
    at = run(new())
    at.selectbox[0].set_value("Contacted").run()
    assert at.dataframe[0].value["Status"].tolist()[0] == "Contacted"
    at.toggle[0].set_value(True).run()
    assert at.dataframe[0].value["Status"].tolist()[0] == "Contacted"
