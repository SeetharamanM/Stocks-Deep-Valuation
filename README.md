# Deep Valuation

A local web app that turns a Screener.in export into a deep-dive valuation and
recommendation report, following the methodology in `SAFARI_Valuation.txt`.

Output is a single self-contained `.html` file that opens in any browser with no
network connection.

## Setup

```bash
pip install -r requirements.txt
```

Copy `.env.example` to `.env` and set **one** API key:

```
LLM_BACKEND=claude
ANTHROPIC_API_KEY=sk-ant-...
```

or

```
LLM_BACKEND=deepseek
DEEPSEEK_API_KEY=sk-...
```

`.env` is git-ignored. The app reads the key; nothing else sees it.

## Run

```bash
python app.py
```

Opens `http://localhost:5000`. Supply:

- **Stock name and ticker** (e.g. Aurionpro Solutions / `AURIONPRO`, NSE)
- **Screener.in xlsx export** — required, the source of all financial data
- **Annual report / earnings-call PDFs** — optional, qualitative context only
- **Market data overrides** — optional; blank fields are fetched from Yahoo Finance
- **Business type** — routes the intrinsic model (DCF, justified P/B, SOTP, DDM)

The report lands in `outputs/<Stock_Name>_Valuation.html`.

## Deploy to Streamlit Community Cloud

`streamlit_app.py` runs the same pipeline as `app.py` behind a Streamlit UI.

1. Run it locally first: `streamlit run streamlit_app.py`
   (keys come from `.env` or `.streamlit/secrets.toml`).
2. At share.streamlit.io, choose **Create app**, then pick this repository,
   the branch, and `streamlit_app.py` as the main file.
3. Under **Advanced settings**, paste the contents of
   `.streamlit/secrets.toml.example` with your real key filled in.
   **Set `APP_PASSWORD`**: anyone who opens a public app spends your API credits.
4. Deploy. The report shows in the page and has a download button.
   Uploads and outputs live on the container's disk only until it restarts.

## How it works

```
Screener xlsx ─┐
PDFs ──────────┼─→ parse ─→ metrics (pure Python) ─→ LLM: assumptions only
market data ───┘                     ↑                        │
                                     └──── recompute ─────────┘
                                              │
                                    LLM: prose around final numbers
                                              │
                                     standalone HTML report
```

**Python owns every number.** The model is asked only for judgment — the forecast
drivers, scenario probabilities, and method weights — and each of those is fed
back through the Python engine before anything is written. The prose is then
generated against the recomputed figures. No figure in the report originates
from the model.

Where a datum cannot be obtained it is reported as unavailable. Nothing is
clamped, defaulted, or invented to make a model produce a tidier answer.

## Modules

| File | Responsibility |
|---|---|
| `src/screener_parser.py` | Reads the Screener "Data Sheet" template into typed year series |
| `src/web_data.py` | Yahoo Finance quotes; manual form values take precedence |
| `src/pdf_extractor.py` | Token-capped text extraction for qualitative context |
| `src/metrics.py` | Valuation base, multiples, historical bands, returns, triangulation |
| `src/metrics_dcf.py` | CAPM/WACC, driver-based DCF, sensitivity grid, reverse DCF |
| `src/valuation_pack.py` | Assembles the audited figure set handed to model and report |
| `src/llm_client.py` | Pluggable Claude / DeepSeek backend |
| `src/analyst.py` | Two-pass orchestration (assumptions → recompute → prose) |
| `src/report.py` | Renders the 11-tab standalone HTML |

## Tests

```bash
python -m pytest -q
```

53 tests. They run with no API key and no network: the model is stubbed and
market data is injected, so the metrics engine is verified against hand-checked
figures from the bundled Aurionpro spreadsheet.

## Known limitations

- **Capex is estimated**, not reported. Screener's export does not itemise it, so
  it is derived from fixed-asset movement (`ΔNet Block + ΔCWIP + depreciation`).
  Every cash-flow figure carries this disclosure.
- **Working-capital change** is not reliably derivable from the export; the
  forecast uses a stated percentage of incremental revenue.
- **Peer comparison is not automated.** The report charts the company against its
  own historical medians and says so. A genuine peer set has to be supplied.
- **Yahoo Finance coverage of Indian tickers is patchy** — beta in particular is
  often missing. Override manually when you have better data.
- **SOTP and DDM are routed but not fully modelled**; conglomerate and high-payout
  cases currently fall back to the relative and earnings-based methods.

## Disclaimer

Analytical method only. Not investment advice. The output is a mechanical model
plus a written interpretation; it takes no account of any individual's
circumstances.
