"""Streamlit front-end for the valuation pipeline (for Streamlit Community Cloud).

Runs the same pipeline as the Flask app (`app.py`). Run locally with
`streamlit run streamlit_app.py`. On Streamlit Cloud, API keys come from the
app's Secrets settings; locally they come from `.env` or
`.streamlit/secrets.toml`.
"""

import os

import streamlit as st

# Streamlit secrets -> environment, before config.py reads the environment.
try:
    for _k, _v in st.secrets.items():
        if isinstance(_v, (str, int, float)) and not os.environ.get(_k):
            os.environ[_k] = str(_v)
except Exception:  # no secrets file is fine; .env may supply the keys
    pass

from app import OUT_DIR, _default_pipeline  # noqa: E402
from config import config  # noqa: E402


class _Upload:
    """Adapts a Streamlit UploadedFile to the Werkzeug FileStorage interface."""

    def __init__(self, uploaded):
        self.filename = uploaded.name
        self._data = uploaded.getvalue()

    def save(self, path):
        with open(path, "wb") as fh:
            fh.write(self._data)


st.set_page_config(page_title="Deep Valuation", layout="wide")
st.title("Deep Valuation")

password = os.environ.get("APP_PASSWORD", "")
if password and st.session_state.get("authed") is not True:
    entered = st.text_input("Password", type="password")
    if entered != password:
        if entered:
            st.error("Wrong password.")
        st.stop()
    st.session_state["authed"] = True

backends = config.available_backends()
if not backends:
    st.warning("No LLM API key configured. Add ANTHROPIC_API_KEY or "
               "DEEPSEEK_API_KEY to the app's secrets.")

with st.form("valuation"):
    c1, c2, c3 = st.columns([2, 1, 1])
    stock_name = c1.text_input("Stock name", placeholder="Aurionpro Solutions")
    ticker = c2.text_input("Ticker", placeholder="AURIONPRO")
    exchange = c3.selectbox("Exchange", ["NSE", "BSE"])
    sector = st.selectbox(
        "Business type",
        ["non-financial", "bank-nbfc", "amc", "conglomerate"],
        format_func={"non-financial": "Non-financial — DCF",
                     "bank-nbfc": "Bank / NBFC — justified P/B",
                     "amc": "Asset manager — P/E and P/AUM",
                     "conglomerate": "Conglomerate — sum-of-the-parts"}.get)

    xlsx = st.file_uploader("Screener.in export (.xlsx) — required", type=["xlsx"])
    annual_report = st.file_uploader("Annual report (PDF, optional)", type=["pdf"])
    transcript = st.file_uploader("Earnings-call transcript (PDF, optional)", type=["pdf"])

    with st.expander("Market data overrides (blank = fetch from Yahoo Finance)"):
        o1, o2, o3, o4, o5 = st.columns(5)
        price = o1.text_input("Price (₹)")
        market_cap = o2.text_input("Market cap (₹ Cr)")
        low_52w = o3.text_input("52-week low")
        high_52w = o4.text_input("52-week high")
        beta = o5.text_input("Beta")
        r1, r2 = st.columns(2)
        risk_free_rate = r1.text_input("Risk-free rate", placeholder=str(config.RISK_FREE_RATE))
        equity_risk_premium = r2.text_input("Equity risk premium",
                                            placeholder=str(config.EQUITY_RISK_PREMIUM))

    llm_backend = st.selectbox("LLM backend", backends or ["claude"])
    submitted = st.form_submit_button("Run valuation", type="primary")

if submitted:
    if not (stock_name and ticker and xlsx):
        st.error("Stock name, ticker and the Screener .xlsx are required.")
        st.stop()
    form = dict(stock_name=stock_name, ticker=ticker, exchange=exchange,
                sector=sector, price=price, market_cap=market_cap,
                low_52w=low_52w, high_52w=high_52w, beta=beta,
                risk_free_rate=risk_free_rate,
                equity_risk_premium=equity_risk_premium,
                llm_backend=llm_backend)
    files = {"xlsx": _Upload(xlsx)}
    if annual_report:
        files["annual_report"] = _Upload(annual_report)
    if transcript:
        files["transcript"] = _Upload(transcript)

    with st.spinner("Running the analysis — this can take a few minutes…"):
        try:
            out_path = _default_pipeline(form, files, OUT_DIR)
        except Exception as exc:
            st.error(f"Valuation failed: {exc}")
            st.exception(exc)
            st.stop()

    with open(out_path, "rb") as fh:
        html = fh.read()
    st.session_state["report"] = (os.path.basename(out_path), html)

if "report" in st.session_state:
    name, html = st.session_state["report"]
    st.success(f"Report ready: {name}")
    st.download_button("Download report (.html)", html, file_name=name,
                       mime="text/html")
    st.components.v1.html(html.decode("utf-8"), height=900, scrolling=True)
