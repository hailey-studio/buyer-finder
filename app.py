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
        "warn": "Rows with website_ok = False may be outdated or wrong. Always check the website and source before you reach out.",
        "missing": "Please fill in the product and the target country.",
        "none": "No companies found. Try a broader product description or another country.",
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
        "warn": "website_ok 为 False 的公司可能信息过时或有误。联系之前，请先打开网站和来源链接核实。",
        "missing": "请填写产品和目标国家。",
        "none": "没有找到公司。试试把产品描述写宽一些，或换一个国家。",
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
    try:
        with st.spinner(T["searching"]):
            companies = research_buyers(seller, product, country, n=n, usage=usage)
        if not companies:
            st.warning(T["none"])
            st.stop()
        with st.spinner(T["checking"]):
            companies = verify_websites(companies)
        with st.spinner(T["drafting"]):
            good = [c for c in companies if c.get("website_ok")] or companies
            drafts = draft_emails(seller, product, good, top=top, language=email_language, usage=usage)
    except Exception as e:
        st.error(friendly_error(e))
        st.stop()
    # Keep results, so clicking "Download" (which reloads the page) doesn't wipe them
    st.session_state["result"] = {"companies": companies, "drafts": drafts, "country": country, "usage": usage}

result = st.session_state.get("result")
if result:
    df = pd.DataFrame(result["companies"])
    ok = int(df["website_ok"].sum()) if "website_ok" in df else 0
    st.subheader(T["found"].format(n=len(df), country=result["country"], ok=ok))
    order = ["name", "intent", "fit_score", "website_ok", "type", "city", "what_they_sell",
             "why_fit", "next_step", "website", "linkedin_search", "source"]
    df = df[[c for c in order if c in df.columns] + [c for c in df.columns if c not in order]]
    st.dataframe(
        df,
        width="stretch",
        column_config={
            "website": st.column_config.LinkColumn("website"),
            "linkedin_search": st.column_config.LinkColumn("LinkedIn", display_text="Find buyer →"),
            "source": st.column_config.LinkColumn("source", display_text="source"),
        },
    )
    st.download_button(T["download"], df.to_csv(index=False).encode("utf-8-sig"), f"buyers_{result['country']}.csv")

    st.subheader(T["drafts"])
    for d in result["drafts"]:
        with st.expander(d["company"]):
            st.text(d["email"])

    u = result["usage"]
    st.caption(T["cost"].format(cur=u.currency, cost=u.cost, searches=u.searches, tokens=u.input_tokens + u.output_tokens))
    st.info(T["warn"])
