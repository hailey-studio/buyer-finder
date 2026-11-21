"""Simple web interface for Buyer Finder. Run with:  streamlit run app.py"""

import os

import pandas as pd
import streamlit as st

st.set_page_config(page_title="Buyer Finder", page_icon="🌍", layout="wide")


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

# Optional password, so strangers can't use up the API credits
password = _secret("APP_PASSWORD")
if password:
    entered = st.text_input("Password", type="password")
    if entered != password:
        st.info("Enter the password to use Buyer Finder.")
        st.stop()

from buyer_finder import Usage, draft_emails, friendly_error, research_buyers, verify_websites  # noqa: E402

TEXT = {
    "English": {
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
        "warn": "Companies marked ⚠️ may be outdated or wrong. Always check the website and source before you reach out.",
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
        "unverified": "⚠ AI summary, not checked word for word. Open the source to confirm.",
        "no_evidence": "No quote found. Check the source before relying on this.",
        "source": "Source",
        "next": "Suggested next step",
        "find_people": "Find their buyer on LinkedIn →",
        "site_ok": "✅ Website opens",
        "site_bad": "⚠️ Website not confirmed",
        "email": "First email draft",
        "only_ok": "Only show companies with a working website",
        "cost": "Estimated cost of this run: {cur}{cost:.3f} ({searches} web searches, {tokens:,} tokens)",
    },
    "中文": {
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
        "warn": "标了 ⚠️ 的公司可能信息过时或有误。联系之前，请先打开官网和来源链接核实。",
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
        "unverified": "⚠ 这是 AI 的概括，没有逐字核对。请打开来源确认。",
        "no_evidence": "没有找到原文证据。联系之前请先看来源链接。",
        "source": "来源",
        "next": "建议下一步",
        "find_people": "在 LinkedIn 上找采购负责人 →",
        "site_ok": "✅ 官网能打开",
        "site_bad": "⚠️ 官网未确认",
        "email": "开发信草稿",
        "only_ok": "只显示官网能打开的公司",
        "cost": "本次运行估算花费：{cur}{cost:.3f}（网页搜索 {searches} 次，共 {tokens:,} 个 tokens）",
    },
}

lang = st.radio("Language / 界面语言", list(TEXT), horizontal=True)
T = TEXT[lang]

st.title("🌍 Buyer Finder")
st.caption(T["caption"])

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
    except Exception as e:
        status.update(label=T["error"], state="error")
        st.error(friendly_error(e))
        st.stop()
    status.update(label=T["done"].format(n=len(companies)), state="complete", expanded=False)
    # Keep results, so clicking "Download" (which reloads the page) doesn't wipe them
    st.session_state["result"] = {"companies": companies, "drafts": drafts, "country": country, "usage": usage}

result = st.session_state.get("result")


def stars(score) -> str:
    full = int(round(float(score or 0)))
    return "★" * full + "☆" * (5 - full)


if result:
    companies = result["companies"]
    emails = {d["company"]: d["email"] for d in result["drafts"]}
    ok = sum(1 for c in companies if c.get("website_ok"))
    st.subheader(T["found"].format(n=len(companies), country=result["country"], ok=ok))
    only_ok = st.toggle(T["only_ok"], value=False)

    for c in companies:
        if only_ok and not c.get("website_ok"):
            continue
        with st.container(border=True):
            left, right = st.columns([3, 1])
            place = " · ".join(x for x in (c.get("city"), c.get("type")) if x)
            left.markdown(f"**{c.get('name', '')}**  \n{place}")
            right.markdown(f"<span style='color:#d4a017;font-size:1.2em'>{stars(c.get('fit_score'))}</span>  \n"
                           f"{c.get('intent', '')}", unsafe_allow_html=True)
            site = c.get("website")
            if site:
                label = T["site_ok"] if c.get("website_ok") else T["site_bad"]
                st.markdown(f"{label} · [{site}]({site})")
            else:
                st.markdown(T["site_bad"])
            st.markdown(f"**{T['why']}:** {c.get('why_fit', '')}")
            with st.expander(T["details"]):
                st.markdown(f"**{T['sells']}:** {c.get('what_they_sell', '')}")
                st.markdown(f"**{T['evidence']}:**")
                if c.get("evidence"):
                    st.markdown(f"> {c['evidence']}")
                    st.caption(T["verified"] if c.get("evidence_verified") else T["unverified"])
                else:
                    st.caption(T["no_evidence"])
                if c.get("source"):
                    st.markdown(f"**{T['source']}:** [{c['source']}]({c['source']})")
                st.markdown(f"**{T['next']}:** {c.get('next_step', '')}")
                st.markdown(f"[{T['find_people']}]({c.get('linkedin_search', '')})")
                if c.get("name") in emails:
                    st.markdown(f"**{T['email']}:**")
                    st.code(emails[c["name"]], language=None, wrap_lines=True)

    df = pd.DataFrame(companies)
    order = ["name", "intent", "fit_score", "website_ok", "type", "city", "what_they_sell",
             "why_fit", "evidence", "evidence_verified", "next_step", "website", "linkedin_search", "source"]
    df = df[[c for c in order if c in df.columns] + [c for c in df.columns if c not in order]]
    st.download_button(T["download"], df.to_csv(index=False).encode("utf-8-sig"), f"buyers_{result['country']}.csv")

    u = result["usage"]
    st.caption(T["cost"].format(cur=u.currency, cost=u.cost, searches=u.searches, tokens=u.input_tokens + u.output_tokens))
    st.info(T["warn"])
