"""Regression tests for the backend. Each test is named after the issue it guards (see NOTES.md).
Run:  python -m pytest tests  (no API key or internet needed: every network call is replaced)."""
import ast
import inspect
import os
import sys
import threading
from types import SimpleNamespace as NS

os.environ["BUYER_FINDER_PROVIDER"] = "deepseek"
os.environ.setdefault("DEEPSEEK_API_KEY", "test")
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import buyer_finder as bf  # noqa: E402


def fake_client(*answers):
    """A stand-in for the AI: returns the given texts in order and records every request."""
    calls = []

    class Messages:
        @staticmethod
        def create(**kw):
            calls.append(kw)
            text = answers[min(len(calls) - 1, len(answers) - 1)]
            return NS(content=[NS(type="text", text=text)], stop_reason="end_turn",
                      usage=NS(input_tokens=10, output_tokens=5))
    bf._client = NS(messages=Messages())
    return calls


def no_network(monkeypatch, pages=None):
    pages = pages or {}
    monkeypatch.setattr(bf, "_fetch_text", lambda url, timeout=8: pages.get(url, ""))


# ---------- L2: searches always run in English ----------
def test_L2_country_from_table_without_ai_call(monkeypatch):
    calls = fake_client("unused")
    assert bf.to_english("kitchen hinges", "西班牙", bf.Usage()) == ("kitchen hinges", "Spain")
    assert calls == []


def test_L2_chinese_product_is_translated(monkeypatch):
    fake_client('{"product": "stainless steel kitchen hardware", "country": "Spain"}')
    assert bf.to_english("不锈钢厨房五金", "西班牙", bf.Usage()) == ("stainless steel kitchen hardware", "Spain")


def test_L2_search_queries_are_english(monkeypatch):
    no_network(monkeypatch)
    queries = []
    monkeypatch.setattr(bf, "web_search", lambda q: queries.append(q) or [])
    fake_client('{"product": "stainless steel kitchen hardware", "country": "Spain"}')
    bf.research_buyers("seller", "不锈钢厨房五金", "西班牙", usage=bf.Usage())
    assert queries and all(q.isascii() and "Spain" in q for q in queries), queries


# ---------- L4: a slightly different source link doesn't drop a real buyer ----------
def test_L4_source_link_compared_loosely(monkeypatch):
    no_network(monkeypatch)
    monkeypatch.setattr(bf, "web_search", lambda q: [] if "official" in q or "Madrid" in q else
                        [{"title": "MICEL", "link": "https://www.micel.es/productos", "snippet": "herrajes"}])
    fake_client('<json>[{"name": "MICEL", "website": "https://micel.es", "city": "Madrid",'
                ' "source": "http://micel.es/productos/", "sells_same_products": true}]</json>')
    out = bf.research_buyers("s", "hinges", "Spain", usage=bf.Usage())
    assert [c["name"] for c in out] == ["MICEL"]
    assert out[0]["source"] == "https://www.micel.es/productos"


# ---------- L5: duplicates that only show up after websites are filled in ----------
def test_L5_dedupe_after_websites_found():
    rows = [{"name": "Herrajes Ferramol", "website": "https://ferramol.com", "fit_score": 3.0},
            {"name": "Ferramol S.L.U.", "website": "https://www.ferramol.com", "fit_score": 4.0},
            {"name": "Other", "website": "", "fit_score": 2.0}]
    out = bf._dedupe_by_website(rows)
    assert [c["name"] for c in out] == ["Ferramol S.L.U.", "Other"]


# ---------- L6: Claude gets the same checks as DeepSeek ----------
def test_L6_claude_path_runs_same_checks(monkeypatch):
    no_network(monkeypatch)
    monkeypatch.setattr(bf, "PROVIDER", "claude")
    monkeypatch.setattr(bf, "web_search", lambda q: [])
    called = {}
    real = bf.find_missing_websites
    monkeypatch.setattr(bf, "find_missing_websites", lambda cs, country, usage: called.setdefault("yes", real(cs, country, usage)))
    fake_client('<json>[{"name": "A Co", "website": "", "source": "https://a.example", "evidence": "we sell hinges"}]</json>')
    out = bf.research_buyers("s", "hinges", "Spain", usage=bf.Usage())
    assert "yes" in called and out[0]["evidence_level"] == "none"


# ---------- L7: no unreachable code left behind ----------
def test_L7_no_code_after_return():
    tree = ast.parse(inspect.getsource(bf))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = node.body
            for i, stmt in enumerate(body[:-1]):
                assert not isinstance(stmt, ast.Return), f"unreachable code after return in {node.name}"


# ---------- L8: counting from many threads at once loses nothing ----------
def test_L8_usage_is_thread_safe():
    u = bf.Usage()
    response = NS(usage=NS(input_tokens=1, output_tokens=1, server_tool_use=None))

    def work():
        for _ in range(2000):
            u.add_search()
            u.add(response)
    threads = [threading.Thread(target=work) for _ in range(20)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert u.searches == 40000 and u.input_tokens == 40000


# ---------- T1: evidence is checked against the real page, and the app is told how ----------
def test_T1_evidence_levels(monkeypatch):
    no_network(monkeypatch, {"https://a.example": "<p>Distribuimos bisagras y tiradores de acero inoxidable.</p>"})
    results = [{"link": "https://a.example", "title": "A", "snippet": "x"},
               {"link": "https://b.example", "title": "B", "snippet": "Venta de bisagras para cocina en Madrid"},
               {"link": "https://c.example", "title": "C", "snippet": "nothing here"}]
    cs = [{"source": "https://a.example", "evidence": "bisagras y tiradores de acero inoxidable"},
          {"source": "https://b.example", "evidence": "Venta de bisagras para cocina"},
          {"source": "https://c.example", "evidence": "we import millions of hinges"}]
    bf._check_evidence(cs, results)
    assert [c["evidence_level"] for c in cs] == ["page", "snippet", "none"]
    assert [c["evidence_verified"] for c in cs] == [True, True, False]


def test_T1_fetch_text_strips_html():
    assert bf._fetch_text("not a url") == ""


# ---------- T2: the fit score follows fixed rules ----------
def test_T2_rubric_score_is_deterministic():
    row = {"sells_same_products": True, "exact_products": "true", "trade_buyer": True,
           "imports_or_same_material": "yes"}
    assert bf._rubric_score(dict(row)) == 5.0        # 2 + 1 + 1 + 1
    row.update(sells_same_products=False, imports_or_same_material=False)
    c = dict(row)
    assert bf._rubric_score(c) == 2.0
    assert c["score_reasons"] == ["exact_products", "trade_buyer"]
    assert bf._clean([{"name": "X", **row}])[0]["fit_score"] == 2.0


def test_T2_scores_spread_out():
    """Test 3 (21 Nov): 9 of 10 scored 5/5. A typical general hardware distributor must not reach 5."""
    general_distributor = {"sells_same_products": True, "exact_products": False, "trade_buyer": True,
                           "imports_or_same_material": False}
    assert bf._rubric_score(general_distributor) == 3.0


def test_website_without_https_becomes_a_link():
    out = bf._clean([{"name": "MICEL", "website": "micel.es", "sells_same_products": True}])
    assert out[0]["website"] == "https://micel.es"


# ---------- U7: the AI writes its own text in the interface language ----------
def test_U7_language_reaches_the_prompt(monkeypatch):
    no_network(monkeypatch)
    monkeypatch.setattr(bf, "web_search", lambda q: [{"title": "t", "link": "https://x.example", "snippet": "s"}])
    calls = fake_client("<json>[]</json>")
    bf.research_buyers("s", "hinges", "Spain", usage=bf.Usage(), language="Simplified Chinese")
    assert "in Simplified Chinese" in calls[-1]["messages"][0]["content"]


# ---------- Round 7: an evaluation found 2 false buyers in the published sample ----------
FERRAMOL_PAGE = ("<title>Fabrica de tiradores y pomos para muebles | Ferramol</title>"
                 "<p>FERRAMOL, desde 1979, diseña y fabrica tiradores y pomos.</p>"
                 "<p>Teléfono: +34 962 490 388</p>")
VERDU_PAGE = ("<h2>Somos fabricantes</h2>"
              "<p>Elaboramos nuestros propios diseños y mandamos a fabricar herrajes para muebles bajo nuestra marca.</p>"
              "<p>Distribuimos bisagras, tiradores y sistemas correderos.</p>")
FAJOTA_PT_PAGE = (
    "<p>Fundada em 1978, a Fajota dispõe actualmente de uma área coberta de 6.000 m2 e mais de 45 colaboradores "
    "e dedica-se desde 1988 ao fabrico de componentes para a indústria de frio, desde a sua concepção, produção "
    "e expedição. A Fajota tem como missão responder às necessidades dos seus clientes, fornecendo produtos que "
    "vão ao encontro dos seus requisitos. É hoje possível encontrar os produtos da Fajota em países como Espanha, "
    "França e Brasil. Dobradiças, puxadores e fechos para a indústria do frio com uma produção versátil.</p>"
    "<p>Zona Industrial de Assequins, Ap. 163 * 3754-909 Águeda | Portugal</p>"
    "<p>T +351 234 612 700</p><p>F +351 234 612 701</p>")
FULL_SCORE = {"sells_same_products": True, "exact_products": True, "trade_buyer": True, "imports_or_same_material": True}


def test_R7_manufacturer_sentence_is_flagged(monkeypatch):
    """Herrajes Ferramol was typed "distributor" and scored 5/5, but its homepage says it makes handles."""
    no_network(monkeypatch, {"https://ferramol.com": FERRAMOL_PAGE})
    monkeypatch.setattr(bf, "check_website", lambda url, timeout=10: True)
    c = bf._clean([{"name": "HERRAJES FERRAMOL, S.L.U.", "website": "https://ferramol.com", "type": "distributor",
                    **FULL_SCORE}])[0]
    assert c["fit_score"] == 5.0
    bf.verify_websites([c])
    assert c["website_ok"] is True
    assert c["maker_flag"]["sentence"] == "FERRAMOL, desde 1979, diseña y fabrica tiradores y pomos."
    assert c["maker_flag"]["url"] == "https://ferramol.com"
    assert "trade_buyer" not in c["score_reasons"] and c["fit_score"] == 4.0


def test_R7_oem_buyer_is_not_flagged(monkeypatch):
    """Verdú has hardware made for it under its own brand: that is a buyer for an OEM factory."""
    assert bf.maker_sentence("Elaboramos nuestros propios diseños y mandamos a fabricar herrajes "
                             "para muebles bajo nuestra marca.") == ""
    no_network(monkeypatch, {"https://verduonlinestore.com": VERDU_PAGE})
    monkeypatch.setattr(bf, "check_website", lambda url, timeout=10: True)
    c = bf._clean([{"name": "Verdú (Joaquín Verdú Díaz, S.L.U.)", "website": "https://verduonlinestore.com",
                    **FULL_SCORE}])[0]
    bf.verify_websites([c])
    assert "maker_flag" not in c and c["fit_score"] == 5.0


def test_R7_other_false_positives_are_not_flagged():
    for text in ("Somos distribuidor de fabricantes líderes como Blum y Hettich.",
                 "Tiradores y pomos para fabricantes de muebles y carpinteros.",
                 "Hinges manufactured for us in Asia and sold under our brand.",
                 "We have our hinges made under our own brand.",
                 "Wir lassen unsere Scharniere in Asien fertigen.",
                 "Condena fabricada en acero inoxidable."):
        assert bf.maker_sentence(text) == "", text
    for text in ("Fabricamos bisagras desde 1985.", "We manufacture drawer slides.", "Wir fertigen Scharniere.",
                 "Nous fabriquons des charnières.", "Fabbrichiamo cerniere dal 1970.", "Fabricamos dobradiças."):
        assert bf.maker_sentence(text) == text, text


def test_R7_third_party_page_only_counts_sentences_about_the_company(monkeypatch):
    """A directory page that says another company manufactures must not flag this one."""
    page = "<p>Verdú distribuye herrajes para muebles.</p><p>833 Solar diseña y fabrica estructuras.</p>"
    no_network(monkeypatch, {"https://dir.example/verdu": page})
    cs = [{"name": "Verdú", "source": "https://dir.example/verdu", "evidence": "Verdú distribuye herrajes para muebles"}]
    bf._check_evidence(cs, [])
    assert cs[0]["evidence_level"] == "page" and "maker_flag" not in cs[0]


def test_R7_guessed_site_in_another_country_is_rejected(monkeypatch):
    """Fajota Iberica SL (Spain) was linked to fajota.com, a Portuguese manufacturer in Águeda."""
    no_network(monkeypatch, {"https://fajota.com": FAJOTA_PT_PAGE})
    monkeypatch.setattr(bf, "web_search", lambda q: [])
    c = {"name": "Fajota Iberica Sl", "website": ""}
    bf.find_missing_websites([c], "Spain", bf.Usage())
    assert c["website"] == "" and not c.get("website_guessed")
    rejected = c["websites_rejected"][0]
    assert rejected["url"] == "https://fajota.com" and "Portuguese" in rejected["reason"] and "+351" in rejected["reason"]
    assert "maker_flag" not in c          # the page is not theirs, so it says nothing about them


def test_R7_guessed_site_by_ccTLD_is_rejected_and_right_country_is_kept(monkeypatch):
    assert "domain ends in .pt" in bf.country_mismatch("https://fajota.pt", "Fajota", "Spain")
    assert bf.country_mismatch("https://ferramol.com", FERRAMOL_PAGE, "Spain") == ""
    no_network(monkeypatch, {"https://ferramol.com": FERRAMOL_PAGE})
    monkeypatch.setattr(bf, "web_search", lambda q: [])
    c = {"name": "HERRAJES FERRAMOL, S.L.U.", "website": ""}
    bf.find_missing_websites([c], "Spain", bf.Usage())
    assert c["website"] == "https://ferramol.com" and c["website_guessed"] and c["maker_flag"]
