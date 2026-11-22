"""Web interface for Buyer Finder. Run with:  streamlit run app.py"""

import html
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

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

.bf-crumb { color: var(--steel); font-size: 14px; margin: 8px 0 0; }
.bf-viewing { color: var(--steel); font-size: 12.5px; margin: 0 0 4px; }
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
        "about_help": "What you make, materials, certifications, minimum order, OEM or ODM, markets you already sell to. The more specific, the better the matches.",
        "edit_search": "Edit this search",
        "back_new": "New search",
        "crumb_searches": "Searches",
        "sample_button": "View a sample result (no password needed)",
        "sample_banner": "Sample result from a real search on 21 Nov 2026, saved so you can look around without waiting. Statuses you set here are not saved.",
        "sample_unlock": "Run your own search",
        "cancel": "Cancel search",
        "retry": "Try again",
        "retry_emails": "Write the emails again",
        "email_failed": "The buyers were found, but the emails could not be written: {err}",
        "viewing": "Viewing {i} of {n}",
        "ev_page": "On page", "ev_snippet": "In summary", "ev_none": "Not found",
        "level_page": "Found word for word on the source page.",
        "level_snippet": "Found in the search result summary of this page. The page itself could not be opened, so open it to confirm.",
        "score_title": "How the {score}/5 fit score was worked out",
        "rubric": {"sells_same_products": "Already sells this kind of product (+2)",
                   "exact_products": "Sells the exact products you make (+1)",
                   "trade_buyer": "Importer, distributor or wholesaler (+1)",
                   "imports_or_same_material": "Already imports, or sells the same material (+1)"},
        "score_old": "Scored by an earlier version, before the scoring rules were added.",
        "hist_count": "{n} buyers",
        "summary_sample": "{n} buyers found. {both} are fully verified (evidence checked, website confirmed, no sign they make the product themselves).",
        "maker_warn": "Page suggests they manufacture this themselves, may be a competitor. Check before you reach out.",
        "maker_chip": "Possible manufacturer",
        "maker_said": "The page says:",
        "site_rejected": "Guessed website {url} was not used: {reason}.",
        "content_lang": "English",
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
        "summary": "{n} buyers found in {secs} seconds. {both} are fully verified (evidence checked, website confirmed, no sign they make the product themselves). Cost {cost}, or {per} per verified buyer.",
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
        "about_help": "写清楚：做什么产品、材质、认证、起订量、能否 OEM/ODM、已经出口到哪些市场。越具体，匹配越准。",
        "edit_search": "修改这次搜索",
        "back_new": "新搜索",
        "crumb_searches": "搜索记录",
        "sample_button": "查看示例结果（不需要密码）",
        "sample_banner": "这是 2026 年 11 月 21 日一次真实搜索的结果，保存下来方便直接查看，不用等待。在这里改的状态不会保存。",
        "sample_unlock": "自己搜索一次",
        "cancel": "取消搜索",
        "retry": "重试",
        "retry_emails": "重新写开发信",
        "email_failed": "买家已经找到，但开发信没能写出来：{err}",
        "viewing": "正在查看第 {i} 家，共 {n} 家",
        "ev_page": "网页原文", "ev_snippet": "搜索摘要", "ev_none": "未找到",
        "level_page": "已在来源网页上逐字找到这句话。",
        "level_snippet": "这句话出现在该网页的搜索结果摘要里，但网页本身打不开，请自己打开确认。",
        "score_title": "匹配度 {score}/5 是怎么算的",
        "rubric": {"sells_same_products": "已经在卖同类产品（+2）",
                   "exact_products": "卖的正是你做的这几样产品（+1）",
                   "trade_buyer": "是进口商、分销商或批发商（+1）",
                   "imports_or_same_material": "已经在进口，或卖同样材质的产品（+1）"},
        "score_old": "这是旧版本打的分，当时还没有评分规则。",
        "hist_count": "{n} 家",
        "summary_sample": "找到 {n} 家买家，其中 {both} 家完全核实（证据已核对、官网已确认、没有迹象表明他们自己生产这类产品）。",
        "maker_warn": "网页显示他们自己生产这类产品，可能是同行。联系之前请先核实。",
        "maker_chip": "可能是生产商",
        "maker_said": "网页原文：",
        "site_rejected": "按名称猜到的网站 {url} 没有采用：{reason}。",
        "content_lang": "Simplified Chinese",
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
        "summary": "用时 {secs} 秒，找到 {n} 家买家，其中 {both} 家完全核实（证据已核对、官网已确认、没有迹象表明他们自己生产这类产品）。花费 {cost}，平均每家核实买家 {per}。",
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


# ---------- Top bar: language switch on the right, on every page (like most web apps) ----------
_, lang_col = st.columns([6, 1.4])
lang = lang_col.radio("Language / 界面语言", list(TEXT), horizontal=True, label_visibility="collapsed", key="lang")
T = TEXT[lang]
e = html.escape
ss = st.session_state
ss.setdefault("history", [])      # every search in this session
ss.setdefault("current", None)    # index of the search on screen; None = search form
ss.setdefault("status", {})       # "search id|company uid" -> status index
ss.setdefault("selected", {})     # search id -> uid of the company shown in the detail panel
ss.setdefault("form", None)       # values to pre-fill the search form with (for "Edit this search")
ss.setdefault("run_now", False)   # a search is waiting to run
ss.setdefault("run_error", "")

SAMPLE_PATH = Path(__file__).parent / "sample_result.json"


def footer_html() -> str:
    return (f'<div class="bf-footer">{e(T["footer"])} <a href="{GITHUB_URL}" target="_blank">'
            f'{e(T["source_code"])}</a></div>')


def head():
    st.markdown(f'<div class="bf-head"><p class="mark">Buyer Finder</p><p class="lede">{e(T["tagline"])}</p></div>',
                unsafe_allow_html=True)


def load_sample():
    """A saved real result, so a visitor can see what the tool does without a password or a wait."""
    if not SAMPLE_PATH.exists():
        return None
    data = json.loads(SAMPLE_PATH.read_text(encoding="utf-8"))
    data["id"] = "sample"
    data["usage"] = SimpleNamespace(**data["usage"])
    return data


# ---------- Password (optional), with a sample result open to everyone ----------
password = _secret("APP_PASSWORD")
locked = bool(password) and not ss.get("unlocked")
sample = load_sample()
if locked and not ss.get("sample_mode"):
    head()
    entered = st.text_input(T["pw_title"], type="password", placeholder="••••••••")
    if entered == password:
        # Remember the visitor for this session and hide the password box
        ss["unlocked"] = True
        st.rerun()
    st.caption(T["pw_body"])
    if sample and st.button(T["sample_button"], type="primary"):
        ss["sample_mode"] = True
        st.rerun()
    st.markdown(footer_html(), unsafe_allow_html=True)
    st.stop()

from buyer_finder import Usage, draft_emails, friendly_error, research_buyers, verify_websites  # noqa: E402


def short_label(h) -> str:
    product = h["product"] if len(h["product"]) <= 28 else h["product"][:27].rstrip(" ,(") + "…"
    return f'{h["country"]}: {product} ({T["hist_count"].format(n=len(h["companies"]))})'


# ---------- Sidebar: navigation and history, like Apollo or HubSpot ----------
with st.sidebar:
    st.markdown('<p class="bf-side-mark">Buyer Finder</p>', unsafe_allow_html=True)
    if not locked:
        if st.button(T["new_search"], type="primary", width="stretch", key="side_new"):
            ss["current"], ss["form"], ss["run_error"], ss["sample_mode"] = None, None, "", False
            st.rerun()
        st.markdown(f'<p class="bf-side-title">{e(T["recent"])}</p>', unsafe_allow_html=True)
        if not ss["history"]:
            st.caption(T["no_recent"])
        for i in reversed(range(len(ss["history"]))):
            if st.button(short_label(ss["history"][i]), key=f"hist{i}", width="stretch",
                         type="tertiary" if i == ss["current"] else "secondary"):
                ss["current"], ss["sample_mode"] = i, False
                st.rerun()
        st.caption(T["session_note"])
    st.markdown(footer_html(), unsafe_allow_html=True)


def run_search(inputs: dict):
    """Run one search. Shows live progress; a click on Cancel stops it (Streamlit stops the running script)."""
    if st.button(T["cancel"], key="cancel"):
        ss["run_now"] = False
        st.rerun()
    usage = Usage()
    started = time.time()
    status = st.status(T["working"], expanded=True)

    def show_progress(stage, **details):
        key = {"search": "step_search", "results": "step_results", "pick": "step_pick",
               "websites": "step_websites", "claude_search": "step_claude"}.get(stage)
        if key:
            status.write(T[key].format(**details))

    try:
        companies = research_buyers(inputs["seller"], inputs["product"], inputs["country"], n=inputs["n"],
                                    usage=usage, progress=show_progress, language=T["content_lang"])
        if companies:
            status.write(T["step_verify"])
            companies = verify_websites(companies)
    except Exception as ex:
        status.update(label=T["error"], state="error")
        ss["run_now"], ss["run_error"] = False, friendly_error(ex)
        st.rerun()
    if not companies:
        status.update(state="error")
        ss["run_now"], ss["run_error"] = False, T["none"]
        st.rerun()
    for uid, c in enumerate(companies):
        c["uid"] = uid
    result = {"id": len(ss["history"]), "companies": companies, "drafts": [], "email_error": "",
              "country": inputs["country"], "product": inputs["product"], "inputs": inputs, "usage": usage}
    # The buyers are saved first, so a failure while writing emails never throws them away
    status.write(T["step_draft"].format(top=min(inputs["top"], len(companies))))
    write_emails(result)
    result["seconds"] = round(time.time() - started)
    ss["history"].append(result)
    ss["current"], ss["run_now"], ss["run_error"] = len(ss["history"]) - 1, False, ""
    st.rerun()


def write_emails(result):
    inputs = result["inputs"]
    email_language = ("English" if inputs["email_idx"] == 0
                      else f"the main business language of {inputs['country']}")
    good = [c for c in result["companies"]
            if c.get("website_ok") and not c.get("website_guessed") and not c.get("maker_flag")] \
        or result["companies"]
    try:
        result["drafts"] = draft_emails(inputs["seller"], inputs["product"], good, top=inputs["top"],
                                        language=email_language, usage=result["usage"])
        result["email_error"] = ""
    except Exception as ex:
        result["email_error"] = friendly_error(ex)


# ---------- Search form ----------
if ss["current"] is None and not ss.get("sample_mode"):
    head()
    st.markdown(f'<p class="bf-flow">{T["flow"]}</p>', unsafe_allow_html=True)
    f = ss["form"] or {}
    with st.form("inputs"):
        seller = st.text_area(T["about"], f.get("seller", T["about_default"]), help=T["about_help"])
        col1, col2 = st.columns(2)
        product = col1.text_input(T["product"], f.get("product", T["product_default"]))
        country = col2.text_input(T["country"], f.get("country", "Spain" if lang == "English" else "西班牙"))
        col3, col4, col5 = st.columns(3)
        n = col3.slider(T["how_many"], 5, 20, f.get("n", 10))
        top = col4.slider(T["top"], 1, 5, f.get("top", 3))
        email_choice = col5.radio(T["email_lang"], T["email_options"], index=f.get("email_idx", 0))
        run = st.form_submit_button(T["run"])

    if run:
        if not product.strip() or not country.strip():
            st.warning(T["missing"])
            st.stop()
        ss["form"] = {"seller": seller, "product": product.strip(), "country": country.strip(), "n": n,
                      "top": top, "email_idx": T["email_options"].index(email_choice)}
        ss["run_now"], ss["run_error"] = True, ""
        st.rerun()
    if ss["run_error"]:
        st.error(ss["run_error"])
        if ss["form"] and st.button(T["retry"], key="retry"):
            ss["run_now"], ss["run_error"] = True, ""
            st.rerun()
    if ss["run_now"] and ss["form"]:
        run_search(ss["form"])
    elif sample and st.button(T["sample_button"], key="sample_from_form", type="tertiary"):
        ss["sample_mode"] = True
        st.rerun()
    st.stop()

# ---------- Results: table on the left, detail panel on the right ----------
is_sample = bool(ss.get("sample_mode")) and (locked or ss["current"] is None)
result = sample if is_sample else ss["history"][ss["current"]]
rid = result["id"]

if is_sample:
    st.info(T["sample_banner"])
    if locked:
        if st.button(T["sample_unlock"], key="unlock"):
            ss["sample_mode"] = False
            st.rerun()

# Breadcrumb and actions: you can always go back or change the search
crumb, act1, act2 = st.columns([4, 1.3, 1.1])
crumb.markdown(f'<p class="bf-crumb">{e(T["crumb_searches"])} / {e(short_label(result))}</p>',
               unsafe_allow_html=True)
if not locked:
    if not is_sample and act1.button(T["edit_search"], key="edit", width="stretch"):
        ss["form"], ss["current"] = dict(result["inputs"]), None
        st.rerun()
    if act2.button(T["back_new"], key="top_new", width="stretch"):
        ss["form"], ss["current"], ss["sample_mode"] = None, None, False
        st.rerun()


def safe_link(url: str) -> str:
    return url if (url or "").startswith(("http://", "https://")) else ""


def status_of(c) -> int:
    return ss["status"].get(f'{rid}|{c.get("uid")}', 0)


companies = result["companies"]
emails = {d["company"]: d["email"] for d in result["drafts"]}
u = result["usage"]
both = sum(1 for c in companies
           if c.get("evidence_verified") and c.get("website_ok") and not c.get("website_guessed")
           and not c.get("maker_flag"))
cost_known = getattr(u, "cost", None) is not None
cost = f"{u.currency}{u.cost:.3f}" if cost_known else ""
secs = result.get("seconds")
if not cost_known:
    summary = T["summary_sample"].format(n=len(companies), both=both)
elif both:
    summary = T["summary"].format(n=len(companies), secs=secs if secs is not None else "?", both=both,
                                  cost=cost, per=f"{u.currency}{u.cost / both:.4f}")
else:
    summary = T["summary_none"].format(n=len(companies), secs=secs if secs is not None else "?", cost=cost)
if secs is None and cost_known:
    summary = summary.split(". ", 1)[-1] if lang == "English" else summary.split("，", 1)[-1]
st.markdown(
    f'<div class="bf-route"><div class="what">{e(result.get("product", ""))} '
    f'<span class="to">{e(T["route_to"])} {e(result["country"])}</span></div></div>'
    f'<p class="bf-summary">{e(summary)}</p>',
    unsafe_allow_html=True)

if result.get("email_error"):
    st.warning(T["email_failed"].format(err=result["email_error"]))
    if not is_sample and st.button(T["retry_emails"], key="retry_emails"):
        with st.spinner(T["drafting"]):
            write_emails(result)
        st.rerun()

tool_left, tool_right = st.columns([3, 1])
only_ok = tool_left.toggle(T["only_ok"], value=False, key=f"only{rid}")
shown = [c for c in companies if c.get("website_ok") or not only_ok]

EV = {"page": T["ev_page"], "snippet": T["ev_snippet"]}
export = pd.DataFrame([{
    "name": c.get("name", ""), "status": T["statuses"][status_of(c)], "fit_score": c.get("fit_score"),
    "score_reasons": "; ".join(c.get("score_reasons", [])), "website": c.get("website", ""),
    "website_ok": c.get("website_ok"), "website_guessed": bool(c.get("website_guessed")),
    "type": c.get("type", ""), "city": c.get("city", ""), "what_they_sell": c.get("what_they_sell", ""),
    "why_fit": c.get("why_fit", ""), "evidence": c.get("evidence", ""),
    "evidence_level": c.get("evidence_level", "none"), "next_step": c.get("next_step", ""),
    "email": emails.get(c.get("name"), ""), "linkedin_search": c.get("linkedin_search", ""),
    "source": c.get("source", ""),
    "maker_flag": (c.get("maker_flag") or {}).get("sentence", ""),
    "websites_rejected": "; ".join(f'{r["url"]} ({r["reason"]})' for r in c.get("websites_rejected", [])),
} for c in companies])
tool_right.download_button(T["export"], export.to_csv(index=False).encode("utf-8-sig"),
                           f"buyers_{result['country']}.csv", width="stretch")

# Which company is open in the detail panel is remembered by its id, not by its row number,
# so filtering or re-sorting never shows the wrong company.
uids = [c["uid"] for c in shown]
current_uid = ss["selected"].get(rid)
if current_uid not in uids:
    current_uid = uids[0] if uids else None

table = pd.DataFrame([{
    " ": "●" if c["uid"] == current_uid else "",
    T["col_company"]: ("⚠ " if c.get("maker_flag") else "") + c.get("name", ""),
    T["col_fit"]: float(c.get("fit_score") or 0),
    T["col_status"]: T["statuses"][status_of(c)],
    T["col_website"]: safe_link(c.get("website", "")),
    T["col_evidence"]: EV.get(c.get("evidence_level"), T["ev_none"]),
} for c in shown])

# Table and detail panel share one height, so the page stays balanced; the detail panel scrolls inside
PANEL_HEIGHT = max(430, min(39 + 35 * len(shown), 600))
left, right = st.columns([3, 2], gap="medium")
with left:
    event = st.dataframe(
        table, hide_index=True, width="stretch", height=PANEL_HEIGHT,
        on_select="rerun", selection_mode="single-row", key=f"table{rid}_{only_ok}",
        column_config={
            " ": st.column_config.TextColumn(" ", width=26),
            T["col_company"]: st.column_config.TextColumn(T["col_company"], width=165),
            T["col_fit"]: st.column_config.ProgressColumn(T["col_fit"], min_value=0, max_value=5, format="%d/5", width=75),
            T["col_status"]: st.column_config.TextColumn(T["col_status"], width=80),
            T["col_evidence"]: st.column_config.TextColumn(T["col_evidence"], width=85),
            T["col_website"]: st.column_config.LinkColumn(T["col_website"], display_text=r"https?://(?:www\.)?([^/]+)", width=100),
        },
    )
rows = event.selection.rows if event and event.selection else []
if rows and rows[0] < len(shown) and shown[rows[0]]["uid"] != current_uid:
    ss["selected"][rid] = shown[rows[0]]["uid"]
    st.rerun()

with right:
    if not shown:
        st.caption(T["none"])
    else:
        c = next(x for x in shown if x["uid"] == current_uid)
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
            if c.get("maker_flag"):
                badges += f'<span class="no">{e(T["maker_chip"])}</span>'
            score = float(c.get("fit_score") or 0)
            position = T["viewing"].format(i=uids.index(c["uid"]) + 1, n=len(shown))
            st.markdown(
                f"""<p class="bf-viewing">{e(position)}</p>
                <div class="bf-detail-top"><div><div class="bf-name">{e(c.get('name', ''))}</div>
                <div class="bf-meta">{meta}</div><div class="bf-status">{badges}</div></div>
                <div class="bf-fit"><div class="num">{score:.0f}<small>/5</small></div></div></div>""",
                unsafe_allow_html=True)
            maker = c.get("maker_flag")
            if maker:
                st.warning(T["maker_warn"])
                st.caption(f'{T["maker_said"]} "{maker.get("sentence", "")}"')
                if safe_link(maker.get("url", "")):
                    st.markdown(f'[{maker["url"]}]({maker["url"]})')
            key = f'{rid}|{c["uid"]}'
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
                for r in c.get("websites_rejected", []):
                    st.caption(T["site_rejected"].format(url=r.get("url", ""), reason=r.get("reason", "")))
                if safe_link(c.get("linkedin_search", "")):
                    st.markdown(f"[{T['find_people']}]({c['linkedin_search']})")
                st.markdown(f"**{T['score_title'].format(score=f'{score:.0f}')}**")
                if "score_reasons" in c:
                    lines = [f"✓ {T['rubric'][k]}" for k in T["rubric"] if k in c["score_reasons"]] \
                        + [f"✗ {T['rubric'][k]}" for k in T["rubric"] if k not in c["score_reasons"]]
                    st.markdown("  \n".join(e(x) for x in lines))
                else:
                    st.caption(T["score_old"])
            with tab2:
                level = c.get("evidence_level", "none")
                if c.get("evidence"):
                    st.markdown(f"> {c['evidence']}")
                    st.caption({"page": T["level_page"], "snippet": T["level_snippet"]}.get(level, T["unverified"]))
                else:
                    st.caption(T["no_evidence"])
                if safe_link(c.get("source", "")):
                    st.markdown(f"[{T['source']}]({c['source']})")
            with tab3:
                if c.get("name") in emails:
                    st.code(emails[c["name"]], language=None, wrap_lines=True)
                else:
                    st.caption(T["no_email"])

cost_line = (T["cost"].format(cur=u.currency, cost=u.cost, searches=u.searches,
                             tokens=u.input_tokens + u.output_tokens) if cost_known else "")
st.markdown(f'<p class="bf-note">{e(T["warn"])} {e(cost_line)}</p>', unsafe_allow_html=True)
