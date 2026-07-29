# Deep Valuation Web App — Design Spec

**Date:** 2026-07-29
**Status:** Approved for planning
**Methodology source:** `SAFARI_Valuation.txt` (the "SEETHARAMAN" valuation instruction template)

## 1. Objective

A standalone local web application that produces a deep-dive **valuation & recommendation
report** for a single stock, following the 11-section methodology defined in
`SAFARI_Valuation.txt`. The user supplies a stock name and data files (Screener.in export +
optional PDFs); the app fetches supplementary market data from the web, computes all
valuation metrics in Python, uses an LLM (Claude or DeepSeek) for judgment and prose, and
renders a single self-contained interactive HTML report.

The report is a **valuation deep-dive only**, not a full company analysis. It answers: what
is the company worth, what is the market pricing in, and is the gap actionable.

## 2. Scope

**In scope**
- Local Flask web app with a file-upload form and a results page.
- Parsing Screener.in xlsx exports; extracting text from annual-report and concall-transcript PDFs.
- Auto-fetching latest price / market cap / 52-week range / beta / peer quotes, with manual override.
- Deterministic Python metrics engine covering all quantitative requirements of the spec.
- LLM analysis layer (pluggable: Claude or DeepSeek) for narrative and judgment inputs.
- Rendering the 11-tab interactive HTML report with all required visualisations.
- Sector routing (non-financial / bank-NBFC / AMC / conglomerate) selecting the intrinsic model.
- First end-to-end target: **Aurionpro Solutions** (fintech/IT → DCF path).

**Out of scope (YAGNI)**
- Multi-user auth, cloud deployment, databases, job queues.
- Scraping Screener.in / TradingView (brittle, ToS-sensitive) — replaced by yfinance + manual override.
- Portfolio/multi-stock batch runs (single stock per run).
- Automated trade execution or any brokerage integration (explicitly forbidden).

## 3. Architecture

Local Flask app (`python app.py` → `http://localhost:5000`). No build step, no cloud.
Backend is a layered pipeline; **Python owns all arithmetic, the LLM owns judgment and
prose only.** This enforces the spec's hard rules: distinguish computed figures from
narrative, and never fabricate a figure.

### Pipeline stages (isolated, independently testable modules)

| Module | Responsibility | Uses LLM |
|---|---|---|
| `app.py` | Flask routes, form handling, file uploads, orchestration, serving result | No |
| `screener_parser.py` | Parse Screener xlsx (Data Sheet canonical layout + P&L / Balance Sheet / Cash Flow / Quarters sheets) → structured multi-year financials dict | No |
| `pdf_extractor.py` | pdfplumber text extraction from annual report + transcript → qualitative context, token-capped and section-tagged | No |
| `web_data.py` | yfinance (NSE `.NS` / BSE `.BO`) for latest close, market cap, 52-wk range, beta, peer quotes; optional AlphaVantage REST if key present; manual form values override everything | No |
| `metrics.py` | ALL deterministic calculations (see §5) → structured "valuation pack" JSON with every input and formula recorded | No |
| `analyst.py` | Pluggable LLM backend; produces judgment inputs (assumptions) and section narratives | Yes |
| `report.py` | Merge computed numbers + narrative into the 11-tab standalone HTML with inlined Chart.js → `outputs/<STOCK>_Valuation.html` | No |
| `config.py` | Load `.env`, select LLM backend, constants (statutory tax 25.17%, default ERP, etc.) | No |

### Data flow

```
Form (stock name, ticker, files, manual overrides, sector, LLM choice)
  → screener_parser + pdf_extractor + web_data
  → metrics.py  (pass 1: all mechanical figures)
  → analyst.py  (LLM proposes assumptions: DCF growth/margin path, terminal g,
                 scenario definitions + probabilities, triangulation weights, model choice)
  → metrics.py  (pass 2: recompute DCF / scenarios / triangulation on those assumptions)
  → analyst.py  (LLM writes narrative around the FINAL figures)
  → report.py   → outputs/<STOCK>_Valuation.html
```

### The two-pass principle

1. Python computes everything mechanical from statements + web data.
2. LLM proposes only the *judgment* inputs, each with a one-line rationale.
3. Python recomputes all consequences of those assumptions → final numbers.
4. LLM writes prose around the final numbers.

Every number in the report therefore traces to Python; the LLM cannot silently introduce one.

## 4. Web UI

Single-page form (Flask + Jinja template):
- **Stock name** (e.g. "Aurionpro Solutions") and **ticker** (e.g. `AURIONPRO`, exchange selector NSE/BSE).
- **File uploads:** Screener xlsx (required); annual-report PDF (optional); concall-transcript PDF (optional).
- **Manual overrides (optional):** current price, market cap, 52-wk low/high, peer tickers, peer multiples — blank fields fall back to auto-fetch.
- **Sector / business type** selector → intrinsic-model routing.
- **LLM backend** selector (Claude / DeepSeek), gated by which API key is present in `.env`.
- Submit → progress → link to generated report + "open in browser".

## 5. Metrics engine (`metrics.py`) — quantitative requirements

All from the spec, computed in Python (no LLM). Structured output records source vs computed.

- **Valuation base:** reported PAT/EPS (latest FY + TTM); normalised-EPS bridge (strip exceptionals, one-off other income, non-recurring tax); BVPS and tangible BVPS; net debt/cash per share; diluted share count incl. ESOPs; effective vs statutory tax (25.17%); FCF = CFO − Capex for last 5 FY and FCF/PAT conversion.
- **Relative valuation:** P/E (trailing; forward if provided), P/B, P/Tangible Book, EV/EBITDA, EV/EBIT, EV/Sales, P/Sales, PEG, dividend yield, total shareholder yield (incl. buybacks), FCF yield — each vs own 5-yr & 10-yr median and vs peer median. Peer table: P/E, ROCE (or ROE for financials), Debt/Equity, peer median.
- **Historical bands:** 5-yr & 10-yr median of primary multiple (P/E, or sector-appropriate: P/B for banks, EV/EBITDA for capital-intensive); ±1 SD bands; current position in SDs; re-rating/de-rating detection flag.
- **Intrinsic — DCF (default):** 5-yr explicit FCFF (revenue growth, EBIT margin, tax, capex, WC change per year); CAPM cost of equity (10-yr G-Sec risk-free, ERP, beta); WACC (D/E weights, post-tax cost of debt); terminal value (perpetuity growth, g ≤ ~5–6% nominal GDP), % of EV in TV with >70% flag; EV→equity→per-share bridge; **5×5 WACC × terminal-growth sensitivity grid**.
- **Coherence checks:** SGR = ROE × (1 − payout, incl. buybacks); Expected g = Reinvestment × ROIC. Flag if assumed growth exceeds both.
- **Sector-specific (Section 5b–d):** justified P/B = (ROE − g)/(COE − g) + ROE/ROA/NIM/CASA/credit-cost/PCR/CRAR/cost-income + Internal Capital Generation Rate for banks/NBFCs; SOTP scaffold (per-segment multiple + holdco discount) for conglomerates; DDM for payout > 60%. **Suppress ROCE / EV-EBITDA / capex / CCC metrics for banks/NBFCs/AMCs.**
- **Reverse DCF:** numeric root-solve for the implied growth priced into current price (hold WACC, terminal g, margins reasonable); compare to own estimate and to SGR / Reinvestment×ROIC ceilings.
- **Triangulation:** method × fair value × weight × weighted contribution; blended fair value + honest low–high range.
- **Scenario:** bear/base/bull fair values, upside/downside, probabilities → probability-weighted expected value vs price.

Uses **average shareholders' equity** for ROE. Buybacks included in payout ratio.

## 6. LLM analysis layer (`analyst.py`)

- Pluggable backend selected by config: **Claude** (`anthropic` SDK, e.g. Opus) or **DeepSeek**
  (OpenAI-compatible endpoint). Chosen at runtime by which key is set / user selection.
- Inputs: the computed valuation pack (pass 1), qualitative PDF context, and the
  `SAFARI_Valuation.txt` methodology as system instruction.
- Outputs, as structured JSON:
  - **Assumption set** (fed back to `metrics.py` pass 2): DCF growth/margin/capex path, terminal g,
    scenario definitions + probabilities, triangulation weights, sector-model choice — each with rationale.
  - **Narrative** per section: single-paragraph verdict; normalisation commentary; peer premium/discount
    justification (quantified); band-validity judgment; the reverse-DCF "crux" paragraph; scenario
    assumptions; recommendation + 5–7 numbered rationale points each anchored to a computed figure;
    ranked risks with fair-value impact; <200-word conclusion.
- Guardrail: the LLM is instructed it may **not** introduce numbers; all figures are injected from
  the valuation pack. Report labels figures as *source* vs *computed*.

## 7. Report generator (`report.py`)

Single self-contained `.html` (opens offline, no CDN — **Chart.js bundled inline**). Per spec:
- Corporate colour scheme, professional typography, branded header (company, price, title).
- Prominent recommendation box (rating, fair value, target, horizon), colour-coded signals
  (green undervalued / orange fair / red overvalued).
- **11 sections as separate tabs**, not one long scroll.
- Visualisations: valuation-band chart (multiple over 5–10 yr, median ±1 SD, current marked);
  peer bar chart on primary multiple; DCF sensitivity heat map (WACC × terminal g, colour-scaled);
  scenario chart (bear/base/bull vs current price); triangulation range chart (each method's output
  as a range with blended estimate marked).
- Neat tables; formulas on hover/footnote; page breaks for PDF printing; footer disclaimer +
  data-source attribution. Fair value / target / recommendation highlighted.
- Saved to `outputs/<STOCK>_Valuation.html`.

## 8. Config & secrets

- `.env` (git-ignored) holds `ANTHROPIC_API_KEY` and/or `DEEPSEEK_API_KEY`, optional `ALPHAVANTAGE_API_KEY`.
- `.env.example` scaffolds the names. The user enters key values themselves; the app never prompts for them in plaintext through the assistant.
- Constants in `config.py`: statutory tax 25.17%, default ERP, default 10-yr G-Sec (overridable in form).

## 9. Web data (`web_data.py`)

- **Primary: yfinance** (`.NS` / `.BO` suffix) → latest close (+ date), market cap, 52-wk range, beta, peer quotes.
- Optional AlphaVantage REST if key set. Manual form values override all auto values.
- Where a datum is unavailable: record it as unavailable (never fabricate); the LLM gives a reasoned
  qualitative note per the spec.

## 10. Testing

- `metrics.py`: unit tests against hand-checked Aurionpro figures (EPS, medians, DCF per-share, reverse-DCF implied g).
- `screener_parser.py`: tested against the provided `Aurionpro Sol.xlsx` (Data Sheet row map + statement sheets).
- `web_data.py`: mocked yfinance responses.
- Golden end-to-end run producing `outputs/Aurionpro_Solutions_Valuation.html`, manually reviewed against the reference RIL report structure.

## 11. Directory layout

```
Stock Analysis Deep Valuation/
  app.py
  config.py
  requirements.txt
  .env.example
  src/
    screener_parser.py
    pdf_extractor.py
    web_data.py
    metrics.py
    analyst.py
    report.py
  templates/            # Flask/Jinja form + result
  static/               # Chart.js bundle, css
  tests/
  outputs/              # generated reports
  docs/superpowers/specs/2026-07-29-stock-valuation-webapp-design.md
```

## 12. Important methodology rules (carried from the spec)

- Indian FY = 1 Apr–31 Mar; FY26 = 1 Apr 2025–31 Mar 2026.
- 5 fiscal years for financial data, 10 years for valuation bands where available.
- Latest available annual period for BS/IS/CF; latest close (with date) for price/market metrics.
- State every assumption explicitly; label source vs computed; never fabricate; flag unavailable data.
- ROE on average equity; buybacks in payout; no ROCE/EV-EBITDA/capex metrics for banks/NBFCs/AMCs.
- Objective tone; present the case against the recommendation too.
- Close with the standard disclaimer: analytical method only, not investment advice.

## 13. Constraints / non-negotiables

- The app produces analysis only; it never executes trades or gives personalised advice framed as such — the report carries the "not investment advice" disclaimer.
- Deliverable is a single `.html` file (not markdown, not JSX).
```
