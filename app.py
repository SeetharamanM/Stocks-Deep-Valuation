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


def _default_pipeline(form, files, out_dir):
    from src.screener_parser import parse_screener
    from src.web_data import build_market_data
    from src.pdf_extractor import extract_context
    from src.analyst import run_analysis
    from src.report import render_report
    from src.llm_client import get_client

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

    backend = form.get("llm_backend") or config.LLM_BACKEND
    if backend == "deepseek":
        client = get_client("deepseek", config.DEEPSEEK_MODEL,
                            config.DEEPSEEK_API_KEY, config.DEEPSEEK_BASE_URL)
    else:
        client = get_client("claude", config.ANTHROPIC_MODEL, config.ANTHROPIC_API_KEY)

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
        return render_template("index.html", backends=config.available_backends(),
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
