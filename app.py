"""Local Flask front-end for the valuation pipeline.

Run with `python app.py`; it opens http://localhost:5000 in a browser.
Uploaded files and generated reports stay on this machine.
"""

import os
import pathlib
import threading
import traceback
import webbrowser

from flask import Flask, render_template, request, send_file
from werkzeug.utils import secure_filename

from config import config

UPLOAD_DIR = "uploads"
OUT_DIR = "outputs"
OVERRIDE_FIELDS = ("price", "market_cap", "low_52w", "high_52w", "beta")


def _float_or_none(raw):
    raw = (raw or "").strip().replace(",", "")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _save_upload(storage, upload_dir):
    name = secure_filename(storage.filename or "")
    if not name:
        return None
    path = os.path.join(upload_dir, name)
    storage.save(path)
    return path


BACKENDS = {"claude": "Claude (Anthropic)", "deepseek": "DeepSeek"}


def _build_client(form):
    """LLM client for the backend chosen on the form.

    A key or model typed into the form is used for that run only and is never
    stored; otherwise the configured (.env / secrets) values apply.
    """
    from src.llm_client import get_client

    backend = (form.get("llm_backend") or config.LLM_BACKEND).strip().lower()
    if backend not in BACKENDS:
        raise ValueError(f"Unknown LLM backend {backend!r}; choose claude or deepseek.")
    typed_key = (form.get("api_key") or "").strip()
    typed_model = (form.get("model") or "").strip()
    if backend == "deepseek":
        key = typed_key or config.DEEPSEEK_API_KEY
        model = typed_model or config.DEEPSEEK_MODEL
        extra = {"base_url": config.DEEPSEEK_BASE_URL}
    else:
        key = typed_key or config.ANTHROPIC_API_KEY
        model = typed_model or config.ANTHROPIC_MODEL
        extra = {}
    if not key:
        raise ValueError(f"No API key for {BACKENDS[backend]}. Enter one on the form "
                         f"or set it in .env / Streamlit secrets.")
    return get_client(backend, model, key, max_tokens=config.LLM_MAX_TOKENS, **extra)


def _default_pipeline(form, files, out_dir):
    from src.screener_parser import parse_screener
    from src.web_data import build_market_data
    from src.pdf_extractor import extract_context
    from src.analyst import run_analysis
    from src.report import render_report
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(out_dir, exist_ok=True)

    xlsx_path = _save_upload(files["xlsx"], UPLOAD_DIR)
    if not xlsx_path:
        raise ValueError("A Screener.in .xlsx export is required.")

    pdf_paths = []
    for key in ("annual_report", "transcript"):
        storage = files.get(key)
        if storage and storage.filename:
            saved = _save_upload(storage, UPLOAD_DIR)
            if saved:
                pdf_paths.append(saved)

    financials = parse_screener(xlsx_path)
    overrides = {f: _float_or_none(form.get(f)) for f in OVERRIDE_FIELDS}
    market = build_market_data(form["ticker"].strip().upper(),
                               form.get("exchange", "NSE"), overrides)
    pdf_context = extract_context(pdf_paths, max_chars=30000)

    client = _build_client(form)

    rf = _float_or_none(form.get("risk_free_rate")) or config.RISK_FREE_RATE
    erp = _float_or_none(form.get("equity_risk_premium")) or config.EQUITY_RISK_PREMIUM

    result = run_analysis(financials, market, form.get("sector", "non-financial"),
                          pdf_context, client, rf, erp)

    stem = secure_filename(form["stock_name"].strip().replace(" ", "_")) or "Valuation"
    return render_report(result, os.path.join(out_dir, f"{stem}_Valuation.html"))


def create_app(pipeline=_default_pipeline):
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = 64 * 1024 * 1024

    @app.route("/")
    def index():
        return render_template("index.html", backends=BACKENDS,
                               configured=config.available_backends(),
                               default_backend=config.LLM_BACKEND,
                               models={"claude": config.ANTHROPIC_MODEL,
                                       "deepseek": config.DEEPSEEK_MODEL},
                               config_rf=config.RISK_FREE_RATE)

    @app.route("/run", methods=["POST"])
    def run():
        try:
            out = pipeline(request.form, request.files, OUT_DIR)
        except Exception as exc:  # surfaced to the user rather than a bare 500
            return render_template("error.html", error=str(exc),
                                   detail=traceback.format_exc()), 500
        return send_file(str(pathlib.Path(out).resolve()))

    return app


if __name__ == "__main__":
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    create_app().run(port=5000, debug=False)
