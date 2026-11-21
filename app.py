"""Web interface for Buyer Finder. Run with:  streamlit run app.py"""

import html
import os
import time

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Buyer Finder: AI buyer research for exporters", page_icon="🌍", layout="wide",
                   initial_sidebar_state="expanded")

GITHUB_URL = "https://github.com/hailey-studio/buyer-finder"

STYLE = """
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@500;600;700&display=swap');
:root { --ink: #1E2A38; --steel: #5F6E7D; --rule: #D5DBDF; --paper: #F4F6F5; --stamp: #2449A8;
        --ok: #2E7D4F; --caution: #9A6416; }
html, body, [class*="css"], .stMarkdown, button, input, textarea, label {
  font-family: 'IBM Plex Sans', 'PingFang SC', 'Hiragino Sans GB', sans-serif; }
#MainMenu, footer, [data-testid="stDecoration"] { visibility: hidden; }
.block-container { max-width: 1280px; padding-top: 2.4rem; }
h1, h2, h3 { font-family: 'IBM Plex Sans Condensed', 'PingFang SC', sans-serif; color: var(--ink); }

.bf-head { border-bottom: 2px solid var(--ink); padding-bottom: 14px; margin-bottom: 22px; }
.bf-head .mark { font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 700; font-size: 34px;
  color: var(--ink); letter-spacing: -0.3px; margin: 0; line-height: 1.1; }
.bf-head .lede { color: var(--steel); font-size: 16.5px; margin: 6px 0 0; max-width: 62ch; }
.bf-flow { color: var(--steel); font-size: 14px; margin: 0 0 18px; max-width: 75ch; line-height: 1.6; }
.bf-flow b { color: var(--ink); font-weight: 600; }

[data-testid="stForm"] { border: 1px solid var(--rule) !important; border-radius: 6px !important; background: #fff; }
.stFormSubmitButton button { background: var(--stamp); color: #fff; border: none; border-radius: 4px;
  padding: 9px 22px; font-weight: 600; }
.stFormSubmitButton button:hover { background: #1b3a8a; color: #fff; }
.stFormSubmitButton button:focus-visible { outline: 3px solid #9db4ee; outline-offset: 2px; }

.bf-route { margin: 30px 0 4px; }
.bf-route .what { font-family: 'IBM Plex Sans Condensed', 'PingFang SC', sans-serif; font-weight: 700;
  font-size: 28px; line-height: 1.15; color: var(--ink); max-width: 42ch; }
.bf-route .to { color: var(--stamp); }
.bf-summary { color: var(--steel); font-size: 15.5px; margin: 8px 0 18px; max-width: 75ch; }

.bf-row { display: grid; grid-template-columns: 34px 1fr auto; gap: 14px; padding: 18px 0 6px;
  border-top: 1px solid var(--rule); }
.bf-rank { font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 600; font-size: 20px; color: var(--steel); }
.bf-name { font-weight: 600; font-size: 18px; color: var(--ink); }
.bf-meta { color: var(--steel); font-size: 14px; margin-top: 2px; }
.bf-meta a { color: var(--stamp); }
.bf-status { font-size: 13.5px; margin-top: 6px; }
.bf-status span { margin-right: 16px; white-space: nowrap; }
.bf-status .ok::before, .bf-status .no::before { content: ""; display: inline-block; width: 8px; height: 8px;
  border-radius: 50%; margin-right: 6px; vertical-align: 1px; }
.bf-status .ok { color: var(--ok); } .bf-status .ok::before { background: var(--ok); }
.bf-status .no { color: var(--caution); } .bf-status .no::before { background: var(--caution); }
.bf-fit { text-align: right; min-width: 92px; }
.bf-fit .num { font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 700; font-size: 26px; color: var(--ink); line-height: 1; }
.bf-fit .num small { font-size: 14px; color: var(--steel); font-weight: 500; }
.bf-fit .bar { display: flex; gap: 3px; justify-content: flex-end; margin-top: 6px; }
.bf-fit .bar i { width: 12px; height: 5px; background: var(--rule); border-radius: 1px; }
.bf-fit .bar i.on { background: var(--stamp); }
.bf-why { color: var(--ink); font-size: 15px; line-height: 1.55; margin: 8px 0 4px; max-width: 75ch; }
[class*="st-key-bfrow"] [data-testid="stExpander"] details { border: none !important; border-left: 2px solid var(--rule) !important;
  border-radius: 0 !important; margin-left: 48px; width: calc(100% - 48px); background: transparent; }
[class*="st-key-bfrow"] [data-testid="stExpander"] summary { color: var(--stamp); font-size: 14px; }
.bf-note { color: var(--steel); font-size: 13.5px; margin-top: 10px; max-width: 75ch; }

.bf-footer { color: var(--steel); font-size: 12.5px; margin: 28px 0 12px; padding-top: 12px; border-top: 1px solid var(--rule); }
[data-testid="stSidebar"] { background: #fff; border-right: 1px solid var(--rule); }
[data-testid="stSidebar"] .stButton button { justify-content: flex-start; text-align: left; font-size: 13.5px; }
.bf-side-mark { font-family: 'IBM Plex Sans Condensed', sans-serif; font-weight: 700; font-size: 22px; color: var(--ink); margin: 4px 0 12px; }
.bf-side-title { color: var(--steel); font-size: 13px; font-weight: 600; margin: 20px 0 6px; }
.bf-detail-top { display: flex; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
[class*="st-key-bfdetail"] { background: #fff; }
.bf-footer a { color: var(--stamp); }
@media (max-width: 700px) { .bf-route .what { font-size: 28px; } .bf-row { grid-template-columns: 26px 1fr; }
  .bf-fit { grid-column: 2; text-align: left; } .bf-fit .bar { justify-content: flex-start; }
  [class*="st-key-bfrow"] [data-testid="stExpander"] details { margin-left: 0; width: 100%; } }
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""
st.markdown(STYLE, unsafe_allow_html=True)


def _secret(name):
    """Read a value from Streamlit secrets (online) or environment variables (local)."""
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass  # no secrets file when running locally
    return os.getenv(name)


# Online: copy keys and the provider switch from Streamlit secrets into the environment
for name in ("BUYER_FINDER_PROVIDER", "ANTHROPIC_API_KEY", "DEEPSEEK_API_KEY", "SERPAPI_API_KEY"):
    if _secret(name):
        os.environ[name] = _secret(name)

TEXT = {
    "English": {
        "new_search": "New search",
        "recent": "Recent searches",
        "no_recent": "Your searches in this session will appear here.",
        "statuses": ["New", "Contacted", "Replied", "Not a fit"],
        "status_label": "Status",
        "col_company": "Company", "col_fit": "Fit", "col_city": "City", "col_type": "Type",
        "col_website": "Website", "col_evidence": "Evidence", "col_status": "Status",
        "ev_yes": "Checked", "ev_no": "Not checked",
        "export": "Export CSV",
        "pick_row": "Select a row to see the evidence, next step and email draft.",
        "session_note": "Searches and statuses are kept while this tab is open.",
        "tagline": "Tell it what your factory makes and where you want to sell. It finds importers and distributors there, shows the evidence for each one, and drafts a first email.",
        "flow": "<b>1</b> Search the web for buyers &nbsp; <b>2</b> Drop competitors, marketplaces and directories &nbsp; <b>3</b> Check each quote against its source and confirm the website &nbsp; <b>4</b> Draft emails for the best matches",
        "route_to": "to",
        "summary": "{n} buyers found in {secs} seconds. {both} are fully verified (evidence checked and website confirmed). Cost {cost}, or {per} per verified buyer.",
        "summary_none": "{n} buyers found in {secs} seconds. None is fully verified yet: open the source of each one before reaching out. Cost {cost}.",
        "tab_overview": "Overview", "tab_evidence": "Evidence", "tab_email": "Email draft",
        "no_email": "No draft for this company. Emails are written for the top matches with a working website.",
        "rank_fit": "fit",
        "pw_title": "This demo is password protected",
        "pw_body": "Ask Hailey for the password.",
        "footer": "Built by Hailey Qiu with Python, Streamlit and DeepSeek or Claude.",
        "source_code": "Source code on GitHub",
        "caption": "Describe what you sell and where. The agent searches the web for real buyers, checks their websites and drafts your first emails.",
        "about": "About your company",
        "about_default": "A factory in Zhejiang, China making stainless steel kitchen hardware. 15 years of export experience, OEM available.",
        "product": "Product",
        "product_default": "Stainless steel kitchen hardware (hinges, handles, drawer slides)",
        "country": "Target country",
        "how_many": "How many companies",
        "top": "Draft emails for the top",
        "email_lang": "Email language",
        "email_options": ["English", "The buyer's local language"],
        "run": "Find buyers",
        "searching": "Searching the web for buyers... (about 1 minute)",
        "checking": "Checking websites...",
        "drafting": "Drafting emails...",
        "error": "Something went wrong:",
        "found": "{n} potential buyers in {country} ({ok} with a working website)",
        "download": "Download CSV",
        "drafts": "First email drafts",
        "warn": "Companies without a confirmed website or checked evidence may be outdated or wrong. Open the source before you reach out.",
        "missing": "Please fill in the product and the target country.",
        "none": "No companies found. Try a broader product description or another country.",
        "working": "Finding buyers...",
        "done": "Done: {n} buyers found",
        "step_search": "Searching the web ({i}/{total}): {query}",
        "step_results": "Found {count} web pages. Removing duplicates and directories...",
        "step_pick": "AI is reading the pages and picking real buyers...",
        "step_websites": "Looking up official websites for {count} companies...",
        "step_claude": "Claude is searching the web (about 1 minute)...",
        "step_verify": "Checking that each website opens...",
        "step_draft": "Writing {top} first emails...",
        "details": "Details",
        "sells": "What they sell",
        "why": "Why they fit",
        "evidence": "Evidence",
        "verified": "✔ Quote checked against the source page",
        "chip_ev": "Evidence checked",
        "chip_no_ev": "Evidence not checked",
        "unverified": "⚠ AI summary, not checked word for word. Open the source to confirm.",
        "no_evidence": "No quote found. Check the source before relying on this.",
        "source": "Source",
        "next": "Suggested next step",
        "find_people": "Find their purchasing manager on LinkedIn",
        "site_ok": "Website opens",
        "site_guess": "Website matched by name, please confirm",
        "site_bad": "Website not confirmed",
        "email": "First email draft",
        "only_ok": "Only show companies with a working website",
        "cost": "Estimated cost of this run: {cur}{cost:.3f} ({searches} web searches, {tokens:,} tokens)",
    },
    "中文": {
        "new_search": "新搜索",
        "recent": "最近的搜索",
        "no_recent": "这次打开页面后的搜索记录会显示在这里。",
        "statuses": ["新线索", "已联系", "已回复", "不合适"],
        "status_label": "状态",
        "col_company": "公司", "col_fit": "匹配度", "col_city": "城市", "col_type": "类型",
        "col_website": "官网", "col_evidence": "证据", "col_status": "状态",
        "ev_yes": "已核对", "ev_no": "未核对",
        "export": "导出 CSV",
        "pick_row": "点选表格里的一行，查看证据、建议下一步和开发信。",
        "session_note": "搜索记录和状态在这个页面打开期间保留。",
        "tagline": "填写你的工厂做什么、想卖到哪个国家。它会找出当地的进口商和分销商，给出每一家的证据，并起草第一封开发信。",
        "flow": "<b>1</b> 上网搜索买家 &nbsp; <b>2</b> 去掉同行、平台和名录网站 &nbsp; <b>3</b> 逐字核对证据，确认官网 &nbsp; <b>4</b> 为最匹配的几家写开发信",
        "route_to": "销往",
        "summary": "用时 {secs} 秒，找到 {n} 家买家，其中 {both} 家完全核实（证据已核对且官网已确认）。花费 {cost}，平均每家核实买家 {per}。",
        "summary_none": "用时 {secs} 秒，找到 {n} 家买家，目前还没有完全核实的。联系之前请先打开每家的来源核对。花费 {cost}。",
        "tab_overview": "概览", "tab_evidence": "证据", "tab_email": "开发信",
        "no_email": "这家没有开发信草稿。开发信只为官网能打开、匹配度最高的几家撰写。",
        "rank_fit": "匹配度",
        "pw_title": "这个演示需要密码",
        "pw_body": "请向 Hailey 要密码。",
        "footer": "Hailey Qiu 制作，使用 Python、Streamlit 和 DeepSeek 或 Claude。",
        "source_code": "GitHub 源代码",
        "caption": "填写你卖什么、想卖到哪里。AI 会上网搜索真实买家，核验对方网站，并帮你写好第一封开发信。",
        "about": "公司介绍",
        "about_default": "浙江一家不锈钢厨房五金工厂，15 年出口经验，可做 OEM。",
        "product": "产品",
        "product_default": "不锈钢厨房五金（铰链、拉手、抽屉滑轨）",
        "country": "目标国家",
        "how_many": "找几家公司",
        "top": "给排名前几家写开发信",
        "email_lang": "开发信语言",
        "email_options": ["英语", "买家所在国的语言"],
        "run": "开始找买家",
        "searching": "正在上网搜索买家……（约 1 分钟）",
        "checking": "正在核验网站……",
        "drafting": "正在写开发信……",
        "error": "出错了：",
        "found": "在{country}找到 {n} 家潜在买家（其中 {ok} 家网站可以打开）",
        "download": "下载 CSV 表格",
        "drafts": "开发信草稿",
        "warn": "官网未确认或证据未核对的公司，信息可能过时或有误。联系之前请先打开来源链接核实。",
        "missing": "请填写产品和目标国家。",
        "none": "没有找到公司。试试把产品描述写宽一些，或换一个国家。",
        "working": "正在找买家……",
        "done": "完成：找到 {n} 家买家",
        "step_search": "正在搜索网页（{i}/{total}）：{query}",
        "step_results": "找到 {count} 个网页，正在去掉重复和名录网站……",
        "step_pick": "AI 正在阅读网页，挑出真正的买家……",
        "step_websites": "正在为 {count} 家公司查找官网……",
        "step_claude": "Claude 正在上网搜索（约 1 分钟）……",
        "step_verify": "正在检查每个官网能否打开……",
        "step_draft": "正在写 {top} 封开发信……",
        "details": "详情",
        "sells": "他们卖什么",
        "why": "推荐理由",
        "evidence": "证据",
        "verified": "✔ 已核对：这句话确实出现在来源网页里",
        "chip_ev": "证据已核对",
        "chip_no_ev": "证据未核对",
        "unverified": "⚠ 这是 AI 的概括，没有逐字核对。请打开来源确认。",
        "no_evidence": "没有找到原文证据。联系之前请先看来源链接。",
        "source": "来源",
        "next": "建议下一步",
        "find_people": "在 LinkedIn 上找采购负责人",
        "site_ok": "官网能打开",
        "site_guess": "官网按名称匹配，请确认",
        "site_bad": "官网未确认",
        "email": "开发信草稿",
        "only_ok": "只显示官网能打开的公司",
        "cost": "本次运行估算花费：{cur}{cost:.3f}（网页搜索 {searches} 次，共 {tokens:,} 个 tokens）",
    },
}


st.sidebar.markdown('<p class="bf-side-mark">Buyer Finder</p>', unsafe_allow_html=True)
lang = st.sidebar.radio("Language / 界面语言", list(TEXT), horizontal=True, label_visibility="collapsed")
T = TEXT[lang]
e = html.escape
ss = st.session_state
ss.setdefault("history", [])      # every search in this session
ss.setdefault("current", None)    # index of the search on screen, None = new search form
ss.setdefault("status", {})       # "search id|company" -> status index


def footer_html() -> str:
    return (f'<div class="bf-footer">{e(T["footer"])} <a href="{GITHUB_URL}" target="_blank">'
            f'{e(T["source_code"])}</a></div>')


# Optional password, so strangers can't use up the API credits
password = _secret("APP_PASSWORD")
if password and not ss.get("unlocked"):
    st.markdown(f'<div class="bf-head"><p class="mark">Buyer Finder</p><p class="lede">{e(T["tagline"])}</p></div>',
                unsafe_allow_html=True)
    entered = st.text_input(T["pw_title"], type="password", placeholder="••••••••")
    if entered == password:
        # Remember the visitor for this session and hide the password box
        ss["unlocked"] = True
        st.rerun()
    st.caption(T["pw_body"])
    st.markdown(footer_html(), unsafe_allow_html=True)
    st.stop()

from buyer_finder import Usage, draft_emails, friendly_error, research_buyers, verify_websites  # noqa: E402

# ---------- Sidebar: like the left navigation in Apollo or HubSpot ----------
with st.sidebar:
    if st.button(T["new_search"], type="primary", width="stretch"):
        ss["current"] = None
        st.rerun()
    st.markdown(f'<p class="bf-side-title">{e(T["recent"])}</p>', unsafe_allow_html=True)
    if not ss["history"]:
        st.caption(T["no_recent"])
    for i in reversed(range(len(ss["history"]))):
        h = ss["history"][i]
        short = h["product"] if len(h["product"]) <= 30 else h["product"][:29].rstrip(" ,(") + "…"
        label = f'{h["country"]}: {short}, {len(h["companies"])}'
        if st.button(label, key=f"hist{i}", width="stretch",
                     type="secondary" if i != ss["current"] else "tertiary"):
            ss["current"] = i
            st.rerun()
    st.caption(T["session_note"])
    st.markdown(footer_html(), unsafe_allow_html=True)

# ---------- New search ----------
if ss["current"] is None:
    st.markdown(f'<div class="bf-head"><p class="mark">Buyer Finder</p><p class="lede">{e(T["tagline"])}</p></div>',
                unsafe_allow_html=True)
    st.markdown(f'<p class="bf-flow">{T["flow"]}</p>', unsafe_allow_html=True)

    with st.form("inputs"):
        seller = st.text_area(T["about"], T["about_default"])
        col1, col2 = st.columns(2)
        product = col1.text_input(T["product"], T["product_default"])
        country = col2.text_input(T["country"], "Spain" if lang == "English" else "西班牙")
        col3, col4, col5 = st.columns(3)
        n = col3.slider(T["how_many"], 5, 20, 10)
        top = col4.slider(T["top"], 1, 5, 3)
        email_choice = col5.radio(T["email_lang"], T["email_options"])
        run = st.form_submit_button(T["run"])

    if run:
        if not product.strip() or not country.strip():
            st.warning(T["missing"])
            st.stop()
        email_language = "English" if email_choice == T["email_options"][0] else f"the main business language of {country}"
        usage = Usage()
        started = time.time()
        status = st.status(T["working"], expanded=True)

        def show_progress(stage, **details):
            key = {"search": "step_search", "results": "step_results", "pick": "step_pick",
                   "websites": "step_websites", "claude_search": "step_claude"}.get(stage)
            if key:
                status.write(T[key].format(**details))

        try:
            companies = research_buyers(seller, product, country, n=n, usage=usage, progress=show_progress)
            if not companies:
                status.update(state="error")
                st.warning(T["none"])
                st.stop()
            status.write(T["step_verify"])
            companies = verify_websites(companies)
            status.write(T["step_draft"].format(top=min(top, len(companies))))
            good = [c for c in companies if c.get("website_ok")] or companies
            drafts = draft_emails(seller, product, good, top=top, language=email_language, usage=usage)
        except Exception as ex:
            status.update(label=T["error"], state="error")
            st.error(friendly_error(ex))
            st.stop()
        status.update(label=T["done"].format(n=len(companies)), state="complete", expanded=False)
        ss["history"].append({"id": len(ss["history"]), "companies": companies, "drafts": drafts,
                              "country": country, "product": product, "usage": usage,
                              "seconds": round(time.time() - started)})
        ss["current"] = len(ss["history"]) - 1
        st.rerun()
    st.stop()

# ---------- Results: table on the left, detail panel on the right ----------
result = ss["history"][ss["current"]]


def safe_link(url: str) -> str:
    return url if (url or "").startswith(("http://", "https://")) else ""


def status_of(c) -> int:
    return ss["status"].get(f'{result["id"]}|{c.get("name", "")}', 0)


companies = result["companies"]
emails = {d["company"]: d["email"] for d in result["drafts"]}
ok = sum(1 for c in companies if c.get("website_ok"))
checked = sum(1 for c in companies if c.get("evidence_verified"))
u = result["usage"]

both = sum(1 for c in companies
           if c.get("evidence_verified") and c.get("website_ok") and not c.get("website_guessed"))
cost = f"{u.currency}{u.cost:.3f}"
summary = (T["summary"].format(n=len(companies), secs=result.get("seconds", "?"), both=both, cost=cost,
                               per=f"{u.currency}{u.cost / both:.4f}") if both else
           T["summary_none"].format(n=len(companies), secs=result.get("seconds", "?"), cost=cost))
st.markdown(
    f'<div class="bf-route"><div class="what">{e(result.get("product", ""))} '
    f'<span class="to">{e(T["route_to"])} {e(result["country"])}</span></div></div>'
    f'<p class="bf-summary">{e(summary)}</p>',
    unsafe_allow_html=True)

tool_left, tool_right = st.columns([3, 1])
only_ok = tool_left.toggle(T["only_ok"], value=False, key=f"only{result['id']}")
shown = [c for c in companies if c.get("website_ok") or not only_ok]

export = pd.DataFrame([{**c, "status": T["statuses"][status_of(c)]} for c in companies])
order = ["name", "status", "intent", "fit_score", "website_ok", "type", "city", "what_they_sell",
         "why_fit", "evidence", "evidence_verified", "next_step", "website", "linkedin_search", "source"]
export = export[[c for c in order if c in export.columns] + [c for c in export.columns if c not in order]]
tool_right.download_button(T["export"], export.to_csv(index=False).encode("utf-8-sig"),
                           f"buyers_{result['country']}.csv", width="stretch")

table = pd.DataFrame([{
    T["col_company"]: c.get("name", ""),
    T["col_fit"]: float(c.get("fit_score") or 0),
    T["col_status"]: T["statuses"][status_of(c)],
    T["col_website"]: safe_link(c.get("website", "")),
    T["col_evidence"]: bool(c.get("evidence_verified")),
} for c in shown])

# Table and detail panel share one height, so the page stays balanced; the detail panel scrolls inside
PANEL_HEIGHT = max(430, min(39 + 35 * len(shown), 600))
left, right = st.columns([7, 5], gap="medium")
with left:
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=PANEL_HEIGHT,
        on_select="rerun", selection_mode="single-row", key=f"table{result['id']}",
        column_config={
            T["col_company"]: st.column_config.TextColumn(T["col_company"], width=190),
            T["col_fit"]: st.column_config.ProgressColumn(T["col_fit"], min_value=0, max_value=5, format="%d/5", width=80),
            T["col_status"]: st.column_config.TextColumn(T["col_status"], width=90),
            T["col_evidence"]: st.column_config.CheckboxColumn(T["col_evidence"], width=80),
            T["col_website"]: st.column_config.LinkColumn(T["col_website"], display_text=r"https?://(?:www\.)?([^/]+)", width=130),
        },
    )
rows = event.selection.rows if event and event.selection else []
pick = rows[0] if rows else 0

with right:
    if not shown:
        st.caption(T["none"])
    else:
        c = shown[min(pick, len(shown) - 1)]
        with st.container(border=True, key="bfdetail", height=PANEL_HEIGHT):
            site = safe_link(c.get("website", ""))
            meta = ", ".join(e(x) for x in (c.get("type"), c.get("city")) if x)
            if site:
                meta += f' &nbsp; <a href="{e(site)}" target="_blank">{e(site.split("//", 1)[-1].rstrip("/"))}</a>'
            site_ok = bool(site and c.get("website_ok"))
            guessed = site_ok and c.get("website_guessed")
            site_label = T["site_guess"] if guessed else (T["site_ok"] if site_ok else T["site_bad"])
            badges = (f'<span class="{"ok" if site_ok and not guessed else "no"}">{e(site_label)}</span>'
                      f'<span class="{"ok" if c.get("evidence_verified") else "no"}">'
                      f'{e(T["chip_ev"] if c.get("evidence_verified") else T["chip_no_ev"])}</span>')
            score = float(c.get("fit_score") or 0)
            st.markdown(
                f"""<div class="bf-detail-top"><div><div class="bf-name">{e(c.get('name', ''))}</div>
                <div class="bf-meta">{meta}</div><div class="bf-status">{badges}</div></div>
                <div class="bf-fit"><div class="num">{score:.0f}<small>/5</small></div></div></div>""",
                unsafe_allow_html=True)
            key = f'{result["id"]}|{c.get("name", "")}'
            new_status = st.selectbox(T["status_label"], T["statuses"], index=status_of(c), key=f"st_{key}")
            if T["statuses"].index(new_status) != status_of(c):
                ss["status"][key] = T["statuses"].index(new_status)
                st.rerun()
            tab1, tab2, tab3 = st.tabs([T["tab_overview"], T["tab_evidence"], T["tab_email"]])
            with tab1:
                st.markdown(f"**{T['why']}**  \n{c.get('why_fit', '')}")
                if c.get("what_they_sell"):
                    st.markdown(f"**{T['sells']}**  \n{c['what_they_sell']}")
                st.markdown(f"**{T['next']}**  \n{c.get('next_step', '')}")
                if safe_link(c.get("linkedin_search", "")):
                    st.markdown(f"[{T['find_people']}]({c['linkedin_search']})")
            with tab2:
                if c.get("evidence"):
                    st.markdown(f"> {c['evidence']}")
                    st.caption(T["verified"] if c.get("evidence_verified") else T["unverified"])
                else:
                    st.caption(T["no_evidence"])
                if safe_link(c.get("source", "")):
                    st.markdown(f"[{T['source']}]({c['source']})")
            with tab3:
                if c.get("name") in emails:
                    st.code(emails[c["name"]], language=None, wrap_lines=True)
                else:
                    st.caption(T["no_email"])
        if not rows:
            st.caption(T["pick_row"])

st.markdown(f'<p class="bf-note">{e(T["warn"])} '
            f'{e(T["cost"].format(cur=u.currency, cost=u.cost, searches=u.searches, tokens=u.input_tokens + u.output_tokens))}</p>',
            unsafe_allow_html=True)
