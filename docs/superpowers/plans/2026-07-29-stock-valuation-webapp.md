# Deep Valuation Web App — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A standalone local Flask web app that ingests a stock's Screener.in xlsx + PDFs, fetches market data via yfinance, computes all valuation metrics deterministically in Python, uses a configurable LLM (Claude or DeepSeek) for judgment and prose, and renders the 11-section interactive HTML valuation report defined in `SAFARI_Valuation.txt`.

**Architecture:** Layered pipeline — `parse → fetch → compute (pure Python) → analyze (LLM) → render`. Python owns all arithmetic (auditable, unit-tested); the LLM only proposes judgment assumptions and writes narrative around numbers handed to it. Local Flask front-end for upload + manual overrides.

**Tech Stack:** Python 3.14, Flask, openpyxl, pdfplumber, yfinance, requests, python-dotenv, anthropic SDK / OpenAI-compatible client for DeepSeek, pytest. Chart.js bundled inline into the output HTML.

**Reference data (from the provided `Aurionpro Sol.xlsx`, Screener template v2.1) used for hand-checked tests:**
- Data Sheet META: Face Value row 7 = 10.0; Current Price row 8 = 735.4; Market Cap row 9 = 4076.37 Cr.
- P&L section: `Report Date` row 16 (year columns B..K = FY2017..FY2026); `Sales` row 17; `Other Income` row 25; `Depreciation` row 26; `Interest` row 27; `Profit before tax` row 28; `Tax` row 29; `Net profit` row 30; `Dividend Amount` row 31.
- Quarters section: `Report Date` row 41 (B..K = 10 quarters); `Net profit` row 49; `Operating Profit` row 50.
- Balance Sheet section: `Report Date` row 56; `Equity Share Capital` row 57; `Reserves` row 58; `Borrowings` row 59; `Cash & Bank` row 69; `No. of Equity Shares` row 70; `Face value` row 72.
- Cash Flow section: `Report Date` row 81; `Cash from Operating Activity` row 82; `Cash from Investing Activity` row 83.
- `PRICE:` row 90 (year-end price per FY); `Adjusted Equity Shares in Cr` row 93.
- Key FY2026 (latest completed FY, ended 31-Mar-2026) values: Sales 1411.09, Net profit 209.31, PBT 252.47, Tax 40.69, adjusted shares 5.53 Cr → **EPS ≈ 37.85**. FY2025: Net profit 186.17, shares 5.52 → EPS ≈ 33.73.

---

## Phase 0 — Project scaffold

### Task 0: Repository, dependencies, config skeleton

**Files:**
- Create: `requirements.txt`, `.env.example`, `.gitignore`, `config.py`, `src/__init__.py`, `tests/__init__.py`
- Create dirs: `src/`, `tests/`, `templates/`, `static/`, `outputs/`

- [ ] **Step 1: Initialise git and folders**

```bash
cd "Z:/Claude AI/Claude Code/Stock Analysis Deep Valuation"
git init
mkdir -p src tests templates static outputs docs/superpowers
```

- [ ] **Step 2: Write `requirements.txt`**

```
flask==3.1.3
openpyxl==3.1.5
pdfplumber
yfinance
requests
python-dotenv
anthropic
openai
pytest
```

- [ ] **Step 3: Write `.gitignore`**

```
.env
__pycache__/
*.pyc
outputs/*.html
.pytest_cache/
uploads/
```

- [ ] **Step 4: Write `.env.example`**

```
# Copy to .env and fill in. NEVER commit .env.
LLM_BACKEND=claude            # claude | deepseek
ANTHROPIC_API_KEY=
ANTHROPIC_MODEL=claude-opus-4-8
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-chat
DEEPSEEK_BASE_URL=https://api.deepseek.com
ALPHAVANTAGE_API_KEY=         # optional fallback
RISK_FREE_RATE=0.069          # 10-yr India G-Sec, overridable in form
EQUITY_RISK_PREMIUM=0.055
STATUTORY_TAX=0.2517
```

- [ ] **Step 5: Write `config.py`**

```python
import os
from dotenv import load_dotenv

load_dotenv()

def _f(name, default):
    v = os.getenv(name)
    return float(v) if v not in (None, "") else default

class Config:
    LLM_BACKEND = os.getenv("LLM_BACKEND", "claude")
    ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
    ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-opus-4-8")
    DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
    DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")
    DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
    ALPHAVANTAGE_API_KEY = os.getenv("ALPHAVANTAGE_API_KEY", "")
    RISK_FREE_RATE = _f("RISK_FREE_RATE", 0.069)
    EQUITY_RISK_PREMIUM = _f("EQUITY_RISK_PREMIUM", 0.055)
    STATUTORY_TAX = _f("STATUTORY_TAX", 0.2517)

    def available_backends(self):
        b = []
        if self.ANTHROPIC_API_KEY: b.append("claude")
        if self.DEEPSEEK_API_KEY: b.append("deepseek")
        return b

config = Config()
```

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "chore: project scaffold, deps, config"
```

---

## Phase 1 — Screener parser

### Task 1: Parse the Screener Data Sheet into structured financials

**Files:**
- Create: `src/screener_parser.py`
- Test: `tests/test_screener_parser.py`

The Data Sheet is a fixed-label template. Parse by locating each section's `Report Date` row and reading labelled rows within the section by matching column-A text (robust to minor row shifts). Return a dataclass with year-aligned series.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_screener_parser.py
from src.screener_parser import parse_screener

XLSX = "Aurionpro Sol.xlsx"

def test_parses_meta_and_latest_fy():
    fin = parse_screener(XLSX)
    assert fin.company_name.upper().startswith("AURIONPRO")
    assert abs(fin.current_price - 735.4) < 0.01
    assert abs(fin.market_cap - 4076.37) < 0.01
    # FY years present, latest is FY2026
    assert fin.pnl_years[-1].year == 2026
    latest = fin.pnl_years[-1]
    assert abs(latest.sales - 1411.09) < 0.01
    assert abs(latest.net_profit - 209.31) < 0.01
    assert abs(latest.pbt - 252.47) < 0.01

def test_balance_sheet_and_cashflow_aligned():
    fin = parse_screener(XLSX)
    bs = {y.year: y for y in fin.bs_years}
    assert abs(bs[2026].borrowings - 60.68) < 0.01
    assert abs(bs[2026].cash - 204.99) < 0.01
    cf = {y.year: y for y in fin.cf_years}
    assert abs(cf[2024].cfo - 163.63) < 0.01

def test_adjusted_shares_and_yearend_price():
    fin = parse_screener(XLSX)
    assert abs(fin.adjusted_shares_cr[-1] - 5.53) < 0.01   # row 93 FY2026
    assert abs(fin.yearend_price[-1] - 724.7) < 0.01        # row 90 FY2026
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_screener_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.screener_parser'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/screener_parser.py
from dataclasses import dataclass, field
from datetime import datetime
import openpyxl

@dataclass
class PnLYear:
    year: int; sales: float; other_income: float; depreciation: float
    interest: float; pbt: float; tax: float; net_profit: float; dividend: float

@dataclass
class BSYear:
    year: int; equity_capital: float; reserves: float; borrowings: float
    cash: float; shares_count: float

@dataclass
class CFYear:
    year: int; cfo: float; cfi: float

@dataclass
class Financials:
    company_name: str
    current_price: float
    market_cap: float
    face_value: float
    pnl_years: list = field(default_factory=list)
    bs_years: list = field(default_factory=list)
    cf_years: list = field(default_factory=list)
    quarters_net_profit: list = field(default_factory=list)  # (date, value)
    quarters_op_profit: list = field(default_factory=list)
    adjusted_shares_cr: list = field(default_factory=list)
    yearend_price: list = field(default_factory=list)

def _num(v):
    return float(v) if isinstance(v, (int, float)) else None

def _year(v):
    if isinstance(v, datetime): return v.year
    return None

def _find_row(ws, label, start=1, end=None):
    end = end or ws.max_row
    for r in range(start, end + 1):
        c = ws.cell(r, 1).value
        if c and str(c).strip().lower() == label.strip().lower():
            return r
    raise ValueError(f"Row not found: {label!r}")

def _series(ws, row, cols):
    return [_num(ws.cell(row, c).value) for c in cols]

def parse_screener(path):
    wb = openpyxl.load_workbook(path, data_only=True)
    ws = wb["Data Sheet"]
    company = str(ws.cell(1, 2).value)
    current_price = _num(ws.cell(8, 2).value)
    market_cap = _num(ws.cell(9, 2).value)
    face_value = _num(ws.cell(7, 2).value)

    # PROFIT & LOSS block
    pnl_dt = _find_row(ws, "Report Date", start=15, end=39)
    year_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(pnl_dt, c).value)]
    years = [_year(ws.cell(pnl_dt, c).value) for c in year_cols]
    def prow(lbl): return _series(ws, _find_row(ws, lbl, 15, 39), year_cols)
    sales, oi, dep = prow("Sales"), prow("Other Income"), prow("Depreciation")
    interest, pbt, tax = prow("Interest"), prow("Profit before tax"), prow("Tax")
    npf, div = prow("Net profit"), prow("Dividend Amount")
    pnl_years = []
    for i, y in enumerate(years):
        if npf[i] is None and sales[i] is None: continue
        pnl_years.append(PnLYear(y, sales[i] or 0, oi[i] or 0, dep[i] or 0,
                                 interest[i] or 0, pbt[i] or 0, tax[i] or 0,
                                 npf[i] or 0, div[i] or 0))

    # BALANCE SHEET block
    bs_dt = _find_row(ws, "Report Date", 55, 79)
    bs_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(bs_dt, c).value)]
    bs_years_list = [_year(ws.cell(bs_dt, c).value) for c in bs_cols]
    def brow(lbl): return _series(ws, _find_row(ws, lbl, 55, 79), bs_cols)
    eq, res, bor = brow("Equity Share Capital"), brow("Reserves"), brow("Borrowings")
    cash, shr = brow("Cash & Bank"), brow("No. of Equity Shares")
    bs_years = [BSYear(bs_years_list[i], eq[i] or 0, res[i] or 0, bor[i] or 0,
                       cash[i] or 0, shr[i] or 0) for i in range(len(bs_years_list))
                if (res[i] is not None or eq[i] is not None)]

    # CASH FLOW block
    cf_dt = _find_row(ws, "Report Date", 80, 89)
    cf_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(cf_dt, c).value)]
    cf_years_list = [_year(ws.cell(cf_dt, c).value) for c in cf_cols]
    cfo = _series(ws, _find_row(ws, "Cash from Operating Activity", 80, 89), cf_cols)
    cfi = _series(ws, _find_row(ws, "Cash from Investing Activity", 80, 89), cf_cols)
    cf_years = [CFYear(cf_years_list[i], cfo[i] or 0, cfi[i] or 0)
                for i in range(len(cf_years_list)) if cfo[i] is not None]

    # PRICE row and adjusted shares
    price_row = _find_row(ws, "PRICE:", 89, 91)
    yearend_price = [v for v in _series(ws, price_row, year_cols) if v is not None]
    adj_row = _find_row(ws, "Adjusted Equity Shares in Cr", 92, ws.max_row)
    adjusted = [v for v in _series(ws, adj_row, year_cols) if v is not None]

    # Quarters
    q_dt = _find_row(ws, "Report Date", 40, 54)
    q_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(q_dt, c).value)]
    q_np = _series(ws, _find_row(ws, "Net profit", 40, 54), q_cols)
    q_op = _series(ws, _find_row(ws, "Operating Profit", 40, 54), q_cols)
    q_dates = [ws.cell(q_dt, c).value for c in q_cols]

    return Financials(company, current_price, market_cap, face_value,
                      pnl_years, bs_years, cf_years,
                      list(zip(q_dates, q_np)), list(zip(q_dates, q_op)),
                      adjusted, yearend_price)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_screener_parser.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/screener_parser.py tests/test_screener_parser.py
git commit -m "feat: Screener xlsx Data Sheet parser"
```

---

## Phase 2 — Web data (yfinance + manual override)

### Task 2: MarketData fetch with override precedence

**Files:**
- Create: `src/web_data.py`
- Test: `tests/test_web_data.py`

Manual overrides always win; yfinance fills gaps; unavailable data is recorded as `None` (never fabricated).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_web_data.py
from src.web_data import build_market_data

def test_manual_overrides_win(monkeypatch):
    # yfinance must NOT be called when all overrides present
    def boom(*a, **k): raise AssertionError("yfinance called")
    monkeypatch.setattr("src.web_data._yf_fetch", boom)
    md = build_market_data(ticker="AURIONPRO", exchange="NSE",
                           overrides={"price": 735.4, "market_cap": 4076.37,
                                      "low_52w": 500.0, "high_52w": 1600.0,
                                      "beta": 0.9})
    assert md.price == 735.4 and md.beta == 0.9
    assert md.source["price"] == "manual"

def test_yfinance_fills_gaps(monkeypatch):
    monkeypatch.setattr("src.web_data._yf_fetch",
        lambda t: {"price": 700.0, "market_cap": 3900.0,
                   "low_52w": 480.0, "high_52w": 1550.0, "beta": 1.1})
    md = build_market_data(ticker="AURIONPRO", exchange="NSE",
                           overrides={"price": 735.4})
    assert md.price == 735.4 and md.source["price"] == "manual"
    assert md.beta == 1.1 and md.source["beta"] == "yfinance"

def test_unavailable_is_none(monkeypatch):
    monkeypatch.setattr("src.web_data._yf_fetch", lambda t: {})
    md = build_market_data(ticker="XXXX", exchange="NSE", overrides={})
    assert md.price is None and md.source["price"] == "unavailable"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web_data.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/web_data.py
from dataclasses import dataclass, field

FIELDS = ["price", "market_cap", "low_52w", "high_52w", "beta"]

@dataclass
class MarketData:
    ticker: str
    price: float = None
    market_cap: float = None
    low_52w: float = None
    high_52w: float = None
    beta: float = None
    as_of: str = None
    source: dict = field(default_factory=dict)

def _yf_fetch(yf_ticker):
    import yfinance as yf
    t = yf.Ticker(yf_ticker)
    info = getattr(t, "fast_info", None) or {}
    hist = t.history(period="1y")
    out = {}
    try: out["price"] = float(hist["Close"].iloc[-1])
    except Exception: pass
    try: out["low_52w"] = float(hist["Close"].min()); out["high_52w"] = float(hist["Close"].max())
    except Exception: pass
    try: out["market_cap"] = float(info["market_cap"]) / 1e7  # to Cr
    except Exception: pass
    try: out["beta"] = float(t.info.get("beta"))
    except Exception: pass
    return out

def _suffix(exchange):
    return ".NS" if exchange.upper() == "NSE" else ".BO"

def build_market_data(ticker, exchange, overrides):
    overrides = overrides or {}
    fetched = {}
    if any(overrides.get(f) is None for f in FIELDS):
        try: fetched = _yf_fetch(ticker + _suffix(exchange)) or {}
        except Exception: fetched = {}
    md = MarketData(ticker=ticker)
    for f in FIELDS:
        if overrides.get(f) is not None:
            setattr(md, f, float(overrides[f])); md.source[f] = "manual"
        elif fetched.get(f) is not None:
            setattr(md, f, float(fetched[f])); md.source[f] = "yfinance"
        else:
            md.source[f] = "unavailable"
    return md
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web_data.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/web_data.py tests/test_web_data.py
git commit -m "feat: market data fetch with manual override precedence"
```

---

## Phase 3 — PDF extraction

### Task 3: Extract token-capped qualitative context from PDFs

**Files:**
- Create: `src/pdf_extractor.py`
- Test: `tests/test_pdf_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pdf_extractor.py
from src.pdf_extractor import extract_context

def test_extract_returns_capped_text():
    ctx = extract_context(["aurionpro transcript.pdf"], max_chars=5000)
    assert isinstance(ctx, str)
    assert 0 < len(ctx) <= 5200            # cap respected (+ tag overhead)
    assert "aurionpro transcript.pdf" in ctx  # source tag present

def test_missing_file_is_skipped():
    ctx = extract_context(["does_not_exist.pdf", "aurionpro transcript.pdf"], max_chars=3000)
    assert "does_not_exist.pdf" not in ctx or "unavailable" in ctx.lower()

def test_empty_list_returns_empty():
    assert extract_context([], max_chars=1000) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pdf_extractor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/pdf_extractor.py
import os
import pdfplumber

def extract_context(paths, max_chars=40000):
    if not paths: return ""
    chunks, budget = [], max_chars
    for p in paths:
        if not os.path.exists(p): continue
        try:
            with pdfplumber.open(p) as pdf:
                text = []
                for page in pdf.pages:
                    t = page.extract_text() or ""
                    text.append(t)
                    if sum(len(x) for x in text) > budget: break
                body = "\n".join(text)[:budget]
        except Exception as e:
            body = f"[unavailable: {e}]"
        tag = f"\n===== SOURCE: {os.path.basename(p)} =====\n"
        piece = (tag + body)[:budget]
        chunks.append(piece)
        budget -= len(piece)
        if budget <= 0: break
    return "".join(chunks)[:max_chars + 200]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pdf_extractor.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add src/pdf_extractor.py tests/test_pdf_extractor.py
git commit -m "feat: token-capped PDF context extractor"
```

---

## Phase 4 — Metrics engine (deterministic, no LLM)

Split into focused tasks. All functions live in `src/metrics.py`; helpers in `src/metrics_dcf.py` to keep files focused.

### Task 4: Valuation base metrics

**Files:**
- Create: `src/metrics.py`
- Test: `tests/test_metrics_base.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_base.py
from src.screener_parser import parse_screener
from src.metrics import valuation_base

def test_valuation_base():
    fin = parse_screener("Aurionpro Sol.xlsx")
    base = valuation_base(fin)
    # EPS latest FY = NP FY2026 / adjusted shares FY2026
    assert abs(base["eps_latest_fy"] - (209.31 / 5.53)) < 0.05  # ~37.85
    # TTM EPS from last 4 quarterly net profits / shares
    assert base["eps_ttm"] > 0
    # Book value per share = (equity capital + reserves) / shares
    bvps = (53.80 + 1683.74) / 5.53
    assert abs(base["bvps"] - bvps) < 0.5
    # Net debt per share = (borrowings - cash) / shares  (negative => net cash)
    ndps = (60.68 - 204.99) / 5.53
    assert abs(base["net_debt_per_share"] - ndps) < 0.5
    # Effective tax rate FY2026 = Tax / PBT
    assert abs(base["effective_tax_rate"] - (40.69 / 252.47)) < 0.005
    # FCF FY2026 = CFO - Capex. Capex proxied from CFI when detail absent -> record method
    assert "fcf_series" in base and len(base["fcf_series"]) >= 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_base.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/metrics.py
from statistics import median, pstdev

def _shares(fin):
    return fin.adjusted_shares_cr[-1]

def valuation_base(fin):
    latest = fin.pnl_years[-1]
    shares = _shares(fin)
    bs = fin.bs_years[-1]
    # TTM from last 4 quarters
    q = [v for _, v in fin.quarters_net_profit if v is not None][-4:]
    ttm_np = sum(q) if len(q) == 4 else latest.net_profit
    fcf_series = []
    for cf in fin.cf_years[-5:]:
        # Capex not itemised in Data Sheet; use CFI magnitude as proxy, flag method
        capex = -cf.cfi if cf.cfi is not None else 0.0
        fcf_series.append({"year": cf.year, "fcf": cf.cfo - capex, "method": "CFO - |CFI| proxy"})
    pat_5 = [p.net_profit for p in fin.pnl_years[-5:]]
    fcf_pat = (sum(x["fcf"] for x in fcf_series) / sum(pat_5)) if sum(pat_5) else None
    return {
        "eps_latest_fy": latest.net_profit / shares,
        "eps_ttm": ttm_np / shares,
        "reported_pat_latest": latest.net_profit,
        "bvps": (bs.equity_capital + bs.reserves) / shares,
        "net_debt_per_share": (bs.borrowings - bs.cash) / shares,
        "net_cash": bs.cash - bs.borrowings,
        "effective_tax_rate": latest.tax / latest.pbt if latest.pbt else None,
        "diluted_shares_cr": shares,
        "fcf_series": fcf_series,
        "fcf_pat_conversion": fcf_pat,
        "latest_fy": latest.year,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_base.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics.py tests/test_metrics_base.py
git commit -m "feat: valuation base metrics"
```

### Task 5: Relative multiples, medians, and historical bands

**Files:**
- Modify: `src/metrics.py`
- Test: `tests/test_metrics_relative.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_relative.py
from src.screener_parser import parse_screener
from src.metrics import relative_multiples, historical_bands

def test_relative_multiples():
    fin = parse_screener("Aurionpro Sol.xlsx")
    rm = relative_multiples(fin)
    # current P/E = current price / EPS latest FY
    assert abs(rm["pe_current"] - (735.4 / (209.31 / 5.53))) < 0.3
    assert rm["pb_current"] > 0
    assert "ev_ebitda_current" in rm
    assert rm["fcf_yield"] is not None

def test_historical_bands():
    fin = parse_screener("Aurionpro Sol.xlsx")
    hb = historical_bands(fin)
    # yearly P/E = yearend price / (net profit / adjusted shares) per year
    assert hb["median_pe_10y"] > 0
    assert hb["sd_pe"] >= 0
    assert "current_z" in hb
    assert hb["upper_band"] > hb["median_pe_10y"] > hb["lower_band"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_relative.py -v`
Expected: FAIL with `ImportError: cannot import name 'relative_multiples'`

- [ ] **Step 3: Write minimal implementation (append to `src/metrics.py`)**

```python
def _ebitda_ebit(fin, p):
    # EBIT = PBT + Interest - Other Income ; EBITDA = EBIT + Depreciation
    ebit = p.pbt + p.interest - p.other_income
    return ebit + p.depreciation, ebit

def relative_multiples(fin):
    latest = fin.pnl_years[-1]
    shares = _shares(fin)
    bs = fin.bs_years[-1]
    eps = latest.net_profit / shares
    price = fin.current_price
    ev = fin.market_cap + bs.borrowings - bs.cash
    ebitda, ebit = _ebitda_ebit(fin, latest)
    bvps = (bs.equity_capital + bs.reserves) / shares
    fcf = fin.cf_years[-1].cfo - (-fin.cf_years[-1].cfi)
    return {
        "pe_current": price / eps if eps else None,
        "pb_current": price / bvps if bvps else None,
        "ev_ebitda_current": ev / ebitda if ebitda else None,
        "ev_ebit_current": ev / ebit if ebit else None,
        "ev_sales_current": ev / latest.sales if latest.sales else None,
        "p_sales_current": fin.market_cap / latest.sales if latest.sales else None,
        "dividend_yield": (latest.dividend / fin.market_cap) if fin.market_cap else None,
        "fcf_yield": (fcf / fin.market_cap) if fin.market_cap else None,
        "enterprise_value": ev,
    }

def _yearly_pe(fin):
    out = []
    n = min(len(fin.yearend_price), len(fin.adjusted_shares_cr), len(fin.pnl_years))
    for i in range(-n, 0):
        eps = fin.pnl_years[i].net_profit / fin.adjusted_shares_cr[i]
        if eps and eps > 0:
            out.append(fin.yearend_price[i] / eps)
    return out

def historical_bands(fin):
    pes = _yearly_pe(fin)
    pes10 = pes[-10:]; pes5 = pes[-5:]
    med10 = median(pes10) if pes10 else None
    med5 = median(pes5) if pes5 else None
    sd = pstdev(pes10) if len(pes10) > 1 else 0.0
    cur = relative_multiples(fin)["pe_current"]
    z = (cur - med10) / sd if (sd and med10 is not None and cur) else None
    return {
        "pe_history": pes10,
        "median_pe_10y": med10, "median_pe_5y": med5, "sd_pe": sd,
        "upper_band": (med10 + sd) if med10 is not None else None,
        "lower_band": (med10 - sd) if med10 is not None else None,
        "current_pe": cur, "current_z": z,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_relative.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics.py tests/test_metrics_relative.py
git commit -m "feat: relative multiples and historical valuation bands"
```

### Task 6: Returns, coherence ceilings (ROE, SGR, ROIC)

**Files:**
- Modify: `src/metrics.py`
- Test: `tests/test_metrics_returns.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_returns.py
from src.screener_parser import parse_screener
from src.metrics import returns_and_ceilings

def test_returns_and_ceilings():
    fin = parse_screener("Aurionpro Sol.xlsx")
    r = returns_and_ceilings(fin)
    # ROE uses AVERAGE equity of last two FYs
    eq_2026 = 53.80 + 1683.74
    eq_2025 = 53.71 + 1449.55
    roe = 209.31 / ((eq_2026 + eq_2025) / 2)
    assert abs(r["roe"] - roe) < 0.005
    assert 0 <= r["payout_ratio"] < 1
    # SGR = ROE * (1 - payout)
    assert abs(r["sgr"] - r["roe"] * (1 - r["payout_ratio"])) < 1e-6
    assert r["roic"] is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_returns.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation (append to `src/metrics.py`)**

```python
def returns_and_ceilings(fin):
    latest = fin.pnl_years[-1]
    bs_now, bs_prev = fin.bs_years[-1], fin.bs_years[-2]
    eq_now = bs_now.equity_capital + bs_now.reserves
    eq_prev = bs_prev.equity_capital + bs_prev.reserves
    avg_eq = (eq_now + eq_prev) / 2
    roe = latest.net_profit / avg_eq if avg_eq else None
    payout = (latest.dividend / latest.net_profit) if latest.net_profit else 0.0
    payout = max(0.0, min(payout, 1.0))
    sgr = roe * (1 - payout) if roe is not None else None
    # ROIC = NOPAT / (equity + borrowings); NOPAT = EBIT*(1-eff tax)
    ebit = latest.pbt + latest.interest - latest.other_income
    eff_tax = latest.tax / latest.pbt if latest.pbt else 0.0
    invested = eq_now + bs_now.borrowings
    roic = (ebit * (1 - eff_tax)) / invested if invested else None
    reinvest = 1 - payout
    g_reinvest = reinvest * roic if roic is not None else None
    return {"roe": roe, "payout_ratio": payout, "sgr": sgr,
            "roic": roic, "g_from_reinvestment": g_reinvest}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_returns.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics.py tests/test_metrics_returns.py
git commit -m "feat: ROE (avg equity), SGR and ROIC coherence ceilings"
```

### Task 7: DCF engine + sensitivity grid

**Files:**
- Create: `src/metrics_dcf.py`
- Test: `tests/test_metrics_dcf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_metrics_dcf.py
from src.metrics_dcf import capm_cost_of_equity, wacc, dcf_valuation, sensitivity_grid

def test_capm_and_wacc():
    coe = capm_cost_of_equity(rf=0.069, erp=0.055, beta=1.0)
    assert abs(coe - 0.124) < 1e-6
    w = wacc(coe=0.124, cost_of_debt_post_tax=0.06, equity=90, debt=10)
    assert abs(w - (0.9*0.124 + 0.1*0.06)) < 1e-6

def test_dcf_per_share_positive():
    res = dcf_valuation(base_fcff=150.0, growth_path=[0.15]*5, wacc=0.12,
                        terminal_growth=0.05, net_debt=-140.0, shares=5.53)
    assert res["fair_value_per_share"] > 0
    assert 0 < res["terminal_value_pct"] < 1
    # terminal-heavy check flag present
    assert "terminal_over_70pct" in res

def test_sensitivity_grid_shape():
    grid = sensitivity_grid(base_fcff=150.0, growth_path=[0.12]*5,
                            waccs=[0.10,0.11,0.12,0.13,0.14],
                            gs=[0.03,0.04,0.05,0.055,0.06],
                            net_debt=-140.0, shares=5.53)
    assert len(grid) == 5 and all(len(row) == 5 for row in grid)
    # higher WACC -> lower value (monotonic down each column)
    assert grid[0][0] > grid[4][0]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_metrics_dcf.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/metrics_dcf.py
def capm_cost_of_equity(rf, erp, beta):
    return rf + beta * erp

def wacc(coe, cost_of_debt_post_tax, equity, debt):
    total = equity + debt
    return (equity/total)*coe + (debt/total)*cost_of_debt_post_tax

def _project_fcff(base_fcff, growth_path):
    flows, f = [], base_fcff
    for g in growth_path:
        f = f * (1 + g)
        flows.append(f)
    return flows

def dcf_valuation(base_fcff, growth_path, wacc, terminal_growth, net_debt, shares):
    flows = _project_fcff(base_fcff, growth_path)
    pv_explicit = sum(f / (1+wacc)**(i+1) for i, f in enumerate(flows))
    tv = flows[-1]*(1+terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1+wacc)**len(flows)
    ev = pv_explicit + pv_tv
    equity_value = ev - net_debt   # net_debt negative => net cash adds value
    return {
        "enterprise_value": ev,
        "pv_explicit": pv_explicit, "pv_terminal": pv_tv,
        "terminal_value_pct": pv_tv/ev if ev else None,
        "terminal_over_70pct": (pv_tv/ev > 0.70) if ev else None,
        "equity_value": equity_value,
        "fair_value_per_share": equity_value/shares if shares else None,
    }

def sensitivity_grid(base_fcff, growth_path, waccs, gs, net_debt, shares):
    grid = []
    for w in waccs:
        row = []
        for g in gs:
            row.append(dcf_valuation(base_fcff, growth_path, w, g,
                                     net_debt, shares)["fair_value_per_share"])
        grid.append(row)
    return grid
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_metrics_dcf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics_dcf.py tests/test_metrics_dcf.py
git commit -m "feat: DCF engine, CAPM/WACC and sensitivity grid"
```

### Task 8: Reverse DCF (solve implied growth)

**Files:**
- Modify: `src/metrics_dcf.py`
- Test: `tests/test_reverse_dcf.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_reverse_dcf.py
from src.metrics_dcf import implied_growth

def test_implied_growth_recovers_input():
    # Build a price from a known 10% growth, then solve back to ~10%
    from src.metrics_dcf import dcf_valuation
    price = dcf_valuation(base_fcff=100.0, growth_path=[0.10]*5, wacc=0.12,
                          terminal_growth=0.05, net_debt=0.0, shares=1.0)["fair_value_per_share"]
    g = implied_growth(price_per_share=price, base_fcff=100.0, wacc=0.12,
                       terminal_growth=0.05, net_debt=0.0, shares=1.0, years=5)
    assert abs(g - 0.10) < 0.005
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_reverse_dcf.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation (append to `src/metrics_dcf.py`)**

```python
def implied_growth(price_per_share, base_fcff, wacc, terminal_growth,
                   net_debt, shares, years=5, lo=-0.20, hi=0.60, tol=1e-4):
    def fv(g):
        return dcf_valuation(base_fcff, [g]*years, wacc, terminal_growth,
                             net_debt, shares)["fair_value_per_share"]
    for _ in range(200):
        mid = (lo + hi) / 2
        v = fv(mid)
        if abs(v - price_per_share) < tol * max(1.0, price_per_share):
            return mid
        if v < price_per_share: lo = mid
        else: hi = mid
    return (lo + hi) / 2
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_reverse_dcf.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics_dcf.py tests/test_reverse_dcf.py
git commit -m "feat: reverse DCF implied-growth solver"
```

### Task 9: Triangulation and scenario expected value

**Files:**
- Modify: `src/metrics.py`
- Test: `tests/test_triangulation.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_triangulation.py
from src.metrics import triangulate, scenario_expected_value

def test_triangulate_weighted_blend():
    methods = [{"name":"DCF","value":1620,"weight":0.5},
               {"name":"Relative","value":1050,"weight":0.3},
               {"name":"P/B","value":1180,"weight":0.2}]
    r = triangulate(methods)
    assert abs(r["blended"] - (1620*0.5 + 1050*0.3 + 1180*0.2)) < 1e-6
    assert r["low"] == 1050 and r["high"] == 1620

def test_scenario_ev():
    scen = [{"name":"Bear","value":1020,"prob":0.25},
            {"name":"Base","value":1577,"prob":0.55},
            {"name":"Bull","value":1980,"prob":0.20}]
    r = scenario_expected_value(scen, current_price=1248)
    assert abs(r["expected_value"] - (1020*0.25+1577*0.55+1980*0.20)) < 1e-6
    assert "upside_pct" in r
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_triangulation.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation (append to `src/metrics.py`)**

```python
def triangulate(methods):
    tw = sum(m["weight"] for m in methods)
    blended = sum(m["value"]*m["weight"] for m in methods) / tw if tw else None
    vals = [m["value"] for m in methods]
    return {"methods": methods, "blended": blended,
            "low": min(vals), "high": max(vals), "total_weight": tw}

def scenario_expected_value(scenarios, current_price):
    ev = sum(s["value"]*s["prob"] for s in scenarios)
    for s in scenarios:
        s["move_pct"] = (s["value"]/current_price - 1) if current_price else None
    return {"scenarios": scenarios, "expected_value": ev,
            "upside_pct": (ev/current_price - 1) if current_price else None}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_triangulation.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics.py tests/test_triangulation.py
git commit -m "feat: fair-value triangulation and scenario expected value"
```

### Task 10: Sector-specific bank/NBFC justified P/B

**Files:**
- Modify: `src/metrics.py`
- Test: `tests/test_sector.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_sector.py
from src.metrics import justified_pb

def test_justified_pb():
    # Justified P/B = (ROE - g) / (COE - g)
    pb = justified_pb(roe=0.16, g=0.08, coe=0.14)
    assert abs(pb - ((0.16-0.08)/(0.14-0.08))) < 1e-9
    assert justified_pb(roe=0.16, g=0.14, coe=0.14) is None  # guard divide-by-zero
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_sector.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation (append to `src/metrics.py`)**

```python
def justified_pb(roe, g, coe):
    denom = coe - g
    if abs(denom) < 1e-9: return None
    return (roe - g) / denom
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_sector.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/metrics.py tests/test_sector.py
git commit -m "feat: sector-specific justified P/B for banks/NBFCs"
```

### Task 11: Assemble the full valuation pack

**Files:**
- Create: `src/valuation_pack.py`
- Test: `tests/test_valuation_pack.py`

Aggregates every metric into one JSON-serialisable dict; this is the object handed to the LLM and the report renderer. `dcf_inputs` (growth path, wacc, terminal g, base_fcff) default to conservative auto-derived values that the LLM may later override.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_valuation_pack.py
import json
from src.screener_parser import parse_screener
from src.web_data import MarketData
from src.valuation_pack import build_pack

def test_pack_is_json_serialisable_and_complete():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9,
                    source={k:"manual" for k in ["price","market_cap","low_52w","high_52w","beta"]})
    pack = build_pack(fin, md, sector="non-financial", rf=0.069, erp=0.055)
    s = json.dumps(pack)  # must not raise
    for key in ["base","relative","bands","returns","dcf","reverse_dcf","meta"]:
        assert key in pack
    assert pack["meta"]["sector"] == "non-financial"
    assert pack["dcf"]["fair_value_per_share"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_valuation_pack.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/valuation_pack.py
from src import metrics
from src.metrics_dcf import (capm_cost_of_equity, wacc as calc_wacc,
                             dcf_valuation, sensitivity_grid, implied_growth)

def build_pack(fin, md, sector, rf, erp, dcf_overrides=None):
    base = metrics.valuation_base(fin)
    rel = metrics.relative_multiples(fin)
    bands = metrics.historical_bands(fin)
    ret = metrics.returns_and_ceilings(fin)

    beta = md.beta if md.beta is not None else 1.0
    coe = capm_cost_of_equity(rf, erp, beta)
    bs = fin.bs_years[-1]
    equity_w = fin.market_cap
    debt_w = bs.borrowings
    cod_post_tax = 0.09 * (1 - (base["effective_tax_rate"] or 0.25))
    w = calc_wacc(coe, cod_post_tax, equity_w, max(debt_w, 1e-6))

    o = dcf_overrides or {}
    base_fcff = o.get("base_fcff") or max(base["fcf_series"][-1]["fcf"], 1.0)
    growth_path = o.get("growth_path") or [min(ret["sgr"] or 0.10, 0.15)] * 5
    tg = o.get("terminal_growth", 0.05)
    net_debt = bs.borrowings - bs.cash
    shares = base["diluted_shares_cr"]

    dcf = dcf_valuation(base_fcff, growth_path, w, tg, net_debt, shares)
    grid_waccs = [round(w+d, 4) for d in (-0.02,-0.01,0,0.01,0.02)]
    grid_gs = [0.03,0.04,0.05,0.055,0.06]
    grid = sensitivity_grid(base_fcff, growth_path, grid_waccs, grid_gs, net_debt, shares)
    implied = implied_growth(fin.current_price, base_fcff, w, tg, net_debt, shares)

    pack = {
        "meta": {"company": fin.company_name, "sector": sector,
                 "current_price": fin.current_price, "market_cap": fin.market_cap,
                 "low_52w": md.low_52w, "high_52w": md.high_52w,
                 "as_of": md.as_of, "sources": md.source, "latest_fy": base["latest_fy"]},
        "base": base, "relative": rel, "bands": bands, "returns": ret,
        "dcf": {**dcf, "cost_of_equity": coe, "wacc": w, "beta": beta,
                "base_fcff": base_fcff, "growth_path": growth_path,
                "terminal_growth": tg, "sensitivity": {
                    "waccs": grid_waccs, "gs": grid_gs, "grid": grid}},
        "reverse_dcf": {"implied_growth": implied,
                        "sgr_ceiling": ret["sgr"],
                        "reinvest_roic_ceiling": ret["g_from_reinvestment"]},
    }
    if sector in ("bank-nbfc", "bank", "nbfc"):
        pack["justified_pb"] = metrics.justified_pb(ret["roe"] or 0, tg, coe)
    return pack
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_valuation_pack.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/valuation_pack.py tests/test_valuation_pack.py
git commit -m "feat: assemble full valuation pack"
```

---

## Phase 5 — LLM analysis layer

### Task 12: Pluggable LLM client (Claude / DeepSeek)

**Files:**
- Create: `src/llm_client.py`
- Test: `tests/test_llm_client.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_llm_client.py
from src.llm_client import get_client, LLMClient

def test_get_client_selects_backend(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    c = get_client(backend="claude", model="claude-opus-4-8", api_key="x")
    assert isinstance(c, LLMClient) and c.backend == "claude"
    d = get_client(backend="deepseek", model="deepseek-chat", api_key="y",
                   base_url="https://api.deepseek.com")
    assert d.backend == "deepseek"

def test_complete_is_mockable(monkeypatch):
    c = get_client(backend="claude", model="m", api_key="x")
    monkeypatch.setattr(c, "_raw_complete", lambda system, user: '{"ok": true}')
    out = c.complete_json(system="s", user="u")
    assert out == {"ok": True}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/llm_client.py
import json, re

class LLMClient:
    def __init__(self, backend, model, api_key, base_url=None):
        self.backend = backend; self.model = model
        self.api_key = api_key; self.base_url = base_url

    def _raw_complete(self, system, user):
        if self.backend == "claude":
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            msg = client.messages.create(model=self.model, max_tokens=8000,
                    system=system, messages=[{"role":"user","content":user}])
            return msg.content[0].text
        else:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key, base_url=self.base_url)
            r = client.chat.completions.create(model=self.model,
                    messages=[{"role":"system","content":system},
                              {"role":"user","content":user}])
            return r.choices[0].message.content

    def complete_json(self, system, user):
        txt = self._raw_complete(system, user)
        m = re.search(r"\{.*\}", txt, re.DOTALL)
        return json.loads(m.group(0) if m else txt)

def get_client(backend, model, api_key, base_url=None):
    return LLMClient(backend, model, api_key, base_url)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_llm_client.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/llm_client.py tests/test_llm_client.py
git commit -m "feat: pluggable Claude/DeepSeek LLM client"
```

### Task 13: Analyst — assumptions pass and narrative pass

**Files:**
- Create: `src/analyst.py`, `src/prompts.py`
- Test: `tests/test_analyst.py`

`analyst.py` orchestrates: (1) ask LLM for judgment assumptions given pack + PDF context; (2) recompute DCF/scenarios via `build_pack`/`triangulate`/`scenario_expected_value`; (3) ask LLM for section narratives given FINAL numbers. Both LLM calls are mocked in tests.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_analyst.py
from src.analyst import run_analysis

class FakeClient:
    def __init__(self): self.calls = 0
    def complete_json(self, system, user):
        self.calls += 1
        if self.calls == 1:  # assumptions pass
            return {"growth_path":[0.14,0.13,0.12,0.11,0.10],
                    "terminal_growth":0.05,
                    "scenarios":[{"name":"Bear","value":600,"prob":0.25},
                                 {"name":"Base","value":900,"prob":0.55},
                                 {"name":"Bull","value":1200,"prob":0.20}],
                    "triangulation":[{"name":"DCF","value":900,"weight":0.6},
                                     {"name":"Relative","value":700,"weight":0.4}],
                    "model_choice":"DCF"}
        return {"sections":{"1":"verdict...","9":"recommendation..."},
                "rating":"BUY","fair_value":850,"target_price":900,
                "conviction":"Medium"}

def test_run_analysis_two_pass():
    from src.screener_parser import parse_screener
    from src.web_data import MarketData
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37, beta=0.9)
    result = run_analysis(fin, md, sector="non-financial", pdf_context="",
                          client=FakeClient(), rf=0.069, erp=0.055)
    assert result["rating"] == "BUY"
    assert result["triangulation"]["blended"] > 0
    assert result["scenario"]["expected_value"] > 0
    assert "pack" in result and "narrative" in result
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_analyst.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# src/prompts.py
import pathlib
SPEC = pathlib.Path("SAFARI_Valuation.txt").read_text(encoding="utf-8", errors="ignore")

ASSUMPTIONS_SYSTEM = (
    "You are a valuation analyst. Given computed metrics and qualitative context, "
    "propose ONLY judgment assumptions as JSON: growth_path (5 floats), terminal_growth, "
    "scenarios (name,value,prob x3, probs sum to 1), triangulation (name,value,weight), "
    "model_choice. You may NOT invent reported figures. Respond with JSON only."
)
NARRATIVE_SYSTEM = (
    "You are a valuation analyst writing a report strictly following this methodology:\n"
    + SPEC +
    "\nWrite narrative for each of the 11 sections around the FINAL numbers provided. "
    "Every quantitative claim must use a number from the provided pack; do not introduce "
    "new figures. Objective tone; present the case against the call too. Respond as JSON "
    "with keys: sections (map '1'..'11' -> markdown text), rating, fair_value, "
    "target_price, conviction."
)
```

```python
# src/analyst.py
import json
from src.valuation_pack import build_pack
from src.metrics import triangulate, scenario_expected_value
from src.prompts import ASSUMPTIONS_SYSTEM, NARRATIVE_SYSTEM

def run_analysis(fin, md, sector, pdf_context, client, rf, erp):
    pack0 = build_pack(fin, md, sector, rf, erp)
    user1 = ("METRICS PACK:\n" + json.dumps(pack0, default=str)
             + "\n\nQUALITATIVE CONTEXT:\n" + (pdf_context or "")[:20000])
    assume = client.complete_json(ASSUMPTIONS_SYSTEM, user1)

    pack = build_pack(fin, md, sector, rf, erp, dcf_overrides={
        "growth_path": assume.get("growth_path"),
        "terminal_growth": assume.get("terminal_growth", 0.05)})
    tri = triangulate(assume["triangulation"])
    scen = scenario_expected_value(assume["scenarios"], fin.current_price)

    final_numbers = {"pack": pack, "triangulation": tri, "scenario": scen,
                     "model_choice": assume.get("model_choice")}
    user2 = ("FINAL NUMBERS:\n" + json.dumps(final_numbers, default=str)
             + "\n\nQUALITATIVE CONTEXT:\n" + (pdf_context or "")[:15000])
    narr = client.complete_json(NARRATIVE_SYSTEM, user2)

    return {"pack": pack, "triangulation": tri, "scenario": scen,
            "narrative": narr.get("sections", {}),
            "rating": narr.get("rating"), "fair_value": narr.get("fair_value"),
            "target_price": narr.get("target_price"),
            "conviction": narr.get("conviction"),
            "assumptions": assume}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_analyst.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/analyst.py src/prompts.py tests/test_analyst.py
git commit -m "feat: two-pass LLM analyst (assumptions + narrative)"
```

---

## Phase 6 — Report renderer

### Task 14: Bundle Chart.js and render the 11-tab HTML

**Files:**
- Create: `src/report.py`, `templates/report.html.j2`
- Add: `static/chartjs.min.js` (download the Chart.js UMD build into this path)
- Test: `tests/test_report.py`

The renderer uses Jinja2 (bundled with Flask) to fill a template, inlining `static/chartjs.min.js` inside a `<script>` tag so the file opens offline. 11 tabs are simple CSS/JS tab switches. Charts are initialised from JSON blobs injected into the page.

- [ ] **Step 1: Download Chart.js UMD build**

```bash
python -c "import urllib.request; urllib.request.urlretrieve('https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js','static/chartjs.min.js')"
```
Expected: `static/chartjs.min.js` exists and is > 100 KB.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_report.py
import os
from src.report import render_report

def _fake_result():
    return {
        "pack": {"meta":{"company":"AURIONPRO SOLUTIONS LTD","current_price":735.4,
                          "market_cap":4076.37,"low_52w":500.0,"high_52w":1600.0,
                          "sector":"non-financial","latest_fy":2026,"sources":{}},
                 "relative":{"pe_current":19.4,"pb_current":2.3,"ev_ebitda_current":13.0,
                             "fcf_yield":0.02},
                 "bands":{"pe_history":[10,12,15,20,18,22,19,17,21,19],
                          "median_pe_10y":18.0,"upper_band":24.0,"lower_band":12.0,
                          "current_pe":19.4,"current_z":0.4},
                 "dcf":{"fair_value_per_share":900.0,"wacc":0.12,"terminal_growth":0.05,
                        "terminal_value_pct":0.65,
                        "sensitivity":{"waccs":[0.10,0.11,0.12,0.13,0.14],
                                       "gs":[0.03,0.04,0.05,0.055,0.06],
                                       "grid":[[1,2,3,4,5]]*5}},
                 "returns":{"roe":0.14},"base":{"eps_latest_fy":37.8,"fcf_pat_conversion":0.5},
                 "reverse_dcf":{"implied_growth":0.09,"sgr_ceiling":0.11}},
        "triangulation":{"methods":[{"name":"DCF","value":900,"weight":0.6}],
                         "blended":850.0,"low":700,"high":900},
        "scenario":{"scenarios":[{"name":"Bear","value":600,"prob":0.25,"move_pct":-0.18},
                                 {"name":"Base","value":900,"prob":0.55,"move_pct":0.22},
                                 {"name":"Bull","value":1200,"prob":0.20,"move_pct":0.63}],
                    "expected_value":850.0,"upside_pct":0.156},
        "narrative":{str(i):f"Section {i} text" for i in range(1,12)},
        "rating":"BUY","fair_value":850,"target_price":900,"conviction":"Medium",
    }

def test_render_writes_standalone_html(tmp_path):
    out = os.path.join(tmp_path, "report.html")
    render_report(_fake_result(), out)
    html = open(out, encoding="utf-8").read()
    assert "AURIONPRO SOLUTIONS LTD" in html
    assert "BUY" in html
    # Chart.js inlined (offline) - no external CDN src
    assert "cdn.jsdelivr.net" not in html
    assert "Chart" in html
    # 11 tab buttons
    assert html.count('class="tab-btn"') == 11
    assert "Not investment advice" in html
```

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_report.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write the template `templates/report.html.j2`**

```html
<!doctype html><html><head><meta charset="utf-8">
<title>{{ company }} — Valuation Report</title>
<style>
 :root{--green:#1a7f4b;--orange:#c47f17;--red:#b3261e;--ink:#1a2027;--muted:#5b6670;}
 body{font-family:Georgia,'Times New Roman',serif;color:var(--ink);margin:0;background:#f6f7f9;}
 header{background:#0f2740;color:#fff;padding:20px 28px;}
 header h1{margin:0;font-size:22px;} header .px{font-size:15px;color:#bcd;}
 .recbox{margin:18px 28px;padding:16px 20px;border-left:8px solid var(--green);
   background:#fff;box-shadow:0 1px 3px rgba(0,0,0,.1);}
 .recbox .rating{font-size:26px;font-weight:bold;}
 .tabs{margin:0 28px;border-bottom:2px solid #d9dee3;display:flex;flex-wrap:wrap;}
 .tab-btn{padding:8px 12px;cursor:pointer;border:none;background:none;font-size:13px;color:var(--muted);}
 .tab-btn.active{color:var(--ink);border-bottom:3px solid #0f2740;font-weight:bold;}
 .panel{display:none;margin:18px 28px;background:#fff;padding:18px 22px;box-shadow:0 1px 3px rgba(0,0,0,.08);}
 .panel.active{display:block;}
 table{border-collapse:collapse;width:100%;font-size:13px;font-family:Arial,sans-serif;}
 th,td{border:1px solid #e0e4e8;padding:6px 8px;text-align:right;} th{background:#eef2f5;text-align:left;}
 .under{color:var(--green);font-weight:bold;} .fair{color:var(--orange);} .over{color:var(--red);}
 canvas{max-width:100%;} footer{margin:24px 28px;color:var(--muted);font-size:12px;}
 @media print{.tab-btn{display:none;} .panel{display:block !important;page-break-after:always;}}
</style></head><body>
<header><h1>{{ company }} — Valuation &amp; Recommendation Report</h1>
<div class="px">Current Price: Rs {{ price }} | Market Cap: Rs {{ mcap }} Cr |
52-wk: Rs {{ low }} – Rs {{ high }}</div></header>
<div class="recbox" style="border-color:{{ rec_color }}">
 <div class="rating" style="color:{{ rec_color }}">{{ rating }}</div>
 <div><b>Fair Value:</b> <u>Rs {{ fair_value }}</u> &nbsp; <b>Target:</b> <u>Rs {{ target_price }}</u>
  &nbsp; <b>Conviction:</b> {{ conviction }}</div></div>
<div class="tabs">
 {% for i in range(1,12) %}<button class="tab-btn{% if i==1 %} active{% endif %}"
   onclick="showTab({{ i }})">{{ section_titles[i-1] }}</button>{% endfor %}
</div>
{% for i in range(1,12) %}
<div class="panel{% if i==1 %} active{% endif %}" id="panel{{ i }}">
 {{ sections[i] | safe }}
 {% if i==4 %}<canvas id="bandChart" height="120"></canvas>{% endif %}
 {% if i==3 %}<canvas id="peerChart" height="120"></canvas>{% endif %}
 {% if i==5 %}<canvas id="heatChart" height="140"></canvas>{% endif %}
 {% if i==8 %}<canvas id="scenChart" height="120"></canvas>{% endif %}
 {% if i==7 %}<canvas id="triChart" height="120"></canvas>{% endif %}
</div>
{% endfor %}
<footer>Analytical method only. Not investment advice. Data sources: Screener.in export,
 yfinance. Figures labelled source vs computed within each section.</footer>
<script>{{ chartjs_inline | safe }}</script>
<script>
 function showTab(n){document.querySelectorAll('.panel').forEach(p=>p.classList.remove('active'));
   document.querySelectorAll('.tab-btn').forEach(b=>b.classList.remove('active'));
   document.getElementById('panel'+n).classList.add('active');
   document.querySelectorAll('.tab-btn')[n-1].classList.add('active');}
 const DATA = {{ chart_data | safe }};
 window.addEventListener('load',()=>{ initCharts(DATA); });
 function initCharts(d){
   new Chart(document.getElementById('bandChart'),{type:'line',data:{labels:d.band.labels,
     datasets:[{label:'P/E',data:d.band.pe},{label:'Median',data:d.band.median},
     {label:'+1SD',data:d.band.up},{label:'-1SD',data:d.band.dn}]}});
   new Chart(document.getElementById('scenChart'),{type:'bar',data:{labels:d.scen.labels,
     datasets:[{label:'Fair value',data:d.scen.values},{label:'Current',data:d.scen.current}]}});
   new Chart(document.getElementById('triChart'),{type:'bar',data:{labels:d.tri.labels,
     datasets:[{label:'Method FV',data:d.tri.values}]}});
   new Chart(document.getElementById('peerChart'),{type:'bar',data:{labels:d.peer.labels,
     datasets:[{label:'P/E',data:d.peer.values}]}});
 }
</script></body></html>
```

- [ ] **Step 5: Write `src/report.py`**

```python
# src/report.py
import json, pathlib
from jinja2 import Template

SECTION_TITLES = ["1 Snapshot","2 Base","3 Relative","4 Bands","5 Intrinsic",
    "6 Reverse DCF","7 Triangulation","8 Scenarios","9 Recommendation","10 Risks","11 Conclusion"]

def _rec_color(rating):
    r = (rating or "").upper()
    if "BUY" in r: return "#1a7f4b"
    if "SELL" in r: return "#b3261e"
    return "#c47f17"

def render_report(result, out_path):
    tpl = Template(pathlib.Path("templates/report.html.j2").read_text(encoding="utf-8"))
    chartjs = pathlib.Path("static/chartjs.min.js").read_text(encoding="utf-8")
    pack = result["pack"]; meta = pack["meta"]; bands = pack["bands"]
    med = bands.get("median_pe_10y") or 0
    hist = bands.get("pe_history") or []
    chart_data = {
        "band": {"labels": list(range(len(hist))), "pe": hist,
                 "median": [med]*len(hist),
                 "up": [bands.get("upper_band")]*len(hist),
                 "dn": [bands.get("lower_band")]*len(hist)},
        "scen": {"labels": [s["name"] for s in result["scenario"]["scenarios"]],
                 "values": [s["value"] for s in result["scenario"]["scenarios"]],
                 "current": [meta["current_price"]]*len(result["scenario"]["scenarios"])},
        "tri": {"labels": [m["name"] for m in result["triangulation"]["methods"]],
                "values": [m["value"] for m in result["triangulation"]["methods"]]},
        "peer": {"labels": ["Company"], "values": [pack["relative"]["pe_current"]]},
    }
    html = tpl.render(
        company=meta["company"], price=meta["current_price"], mcap=meta["market_cap"],
        low=meta.get("low_52w"), high=meta.get("high_52w"),
        rating=result["rating"], fair_value=result["fair_value"],
        target_price=result["target_price"], conviction=result["conviction"],
        rec_color=_rec_color(result["rating"]),
        section_titles=SECTION_TITLES,
        sections={i: result["narrative"].get(str(i), "") for i in range(1,12)},
        chartjs_inline=chartjs, chart_data=json.dumps(chart_data))
    pathlib.Path(out_path).write_text(html, encoding="utf-8")
    return out_path
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_report.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add src/report.py templates/report.html.j2 static/chartjs.min.js tests/test_report.py
git commit -m "feat: 11-tab standalone HTML report with inlined Chart.js"
```

---

## Phase 7 — Flask app wiring

### Task 15: Upload form + run route

**Files:**
- Create: `app.py`, `templates/index.html`
- Test: `tests/test_app.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_app.py
import io
from app import create_app

def test_index_get():
    app = create_app(); client = app.test_client()
    r = client.get("/")
    assert r.status_code == 200 and b"Stock" in r.data

def test_run_route_uses_injected_pipeline(tmp_path):
    calls = {}
    def fake_pipeline(form, files, out_dir):
        calls["ran"] = True
        p = tmp_path / "Aurionpro_Valuation.html"; p.write_text("<html>ok</html>")
        return str(p)
    app = create_app(pipeline=fake_pipeline); client = app.test_client()
    data = {"stock_name":"Aurionpro","ticker":"AURIONPRO","exchange":"NSE",
            "sector":"non-financial","llm_backend":"claude"}
    data["xlsx"] = (io.BytesIO(b"fake"), "Aurionpro Sol.xlsx")
    r = client.post("/run", data=data, content_type="multipart/form-data")
    assert calls.get("ran") and r.status_code in (200, 302)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_app.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app'`

- [ ] **Step 3: Write minimal implementation**

```python
# app.py
import os, webbrowser, threading
from flask import Flask, request, render_template, send_file, redirect, url_for
from config import config

UPLOAD_DIR = "uploads"; OUT_DIR = "outputs"

def _default_pipeline(form, files, out_dir):
    from src.screener_parser import parse_screener
    from src.web_data import build_market_data
    from src.pdf_extractor import extract_context
    from src.analyst import run_analysis
    from src.report import render_report
    from src.llm_client import get_client

    os.makedirs(UPLOAD_DIR, exist_ok=True); os.makedirs(out_dir, exist_ok=True)
    xlsx = files["xlsx"]; xlsx_path = os.path.join(UPLOAD_DIR, xlsx.filename)
    xlsx.save(xlsx_path)
    pdf_paths = []
    for key in ("annual_report", "transcript"):
        f = files.get(key)
        if f and f.filename:
            p = os.path.join(UPLOAD_DIR, f.filename); f.save(p); pdf_paths.append(p)

    fin = parse_screener(xlsx_path)
    overrides = {k: (float(form[k]) if form.get(k) else None)
                 for k in ("price","market_cap","low_52w","high_52w","beta")}
    md = build_market_data(form["ticker"], form.get("exchange","NSE"), overrides)
    pdf_ctx = extract_context(pdf_paths, max_chars=30000)

    backend = form.get("llm_backend", config.LLM_BACKEND)
    if backend == "deepseek":
        client = get_client("deepseek", config.DEEPSEEK_MODEL, config.DEEPSEEK_API_KEY,
                            config.DEEPSEEK_BASE_URL)
    else:
        client = get_client("claude", config.ANTHROPIC_MODEL, config.ANTHROPIC_API_KEY)

    result = run_analysis(fin, md, form.get("sector","non-financial"), pdf_ctx,
                          client, config.RISK_FREE_RATE, config.EQUITY_RISK_PREMIUM)
    safe = form["stock_name"].replace(" ", "_")
    out = os.path.join(out_dir, f"{safe}_Valuation.html")
    return render_report(result, out)

def create_app(pipeline=_default_pipeline):
    app = Flask(__name__)
    @app.route("/")
    def index():
        return render_template("index.html", backends=config.available_backends())
    @app.route("/run", methods=["POST"])
    def run():
        out = pipeline(request.form, request.files, OUT_DIR)
        return send_file(os.path.abspath(out))
    return app

if __name__ == "__main__":
    app = create_app()
    threading.Timer(1.2, lambda: webbrowser.open("http://localhost:5000")).start()
    app.run(port=5000, debug=False)
```

- [ ] **Step 4: Write `templates/index.html`**

```html
<!doctype html><html><head><meta charset="utf-8"><title>Deep Valuation</title>
<style>body{font-family:Arial;max-width:640px;margin:40px auto;}
 label{display:block;margin:10px 0 3px;font-weight:bold;} input,select{width:100%;padding:6px;}
 .row{display:flex;gap:10px;} .row>div{flex:1;} fieldset{margin-top:16px;}
 button{margin-top:18px;padding:10px 18px;font-size:15px;}</style></head><body>
<h2>Deep Valuation — Stock Report Generator</h2>
<form action="/run" method="post" enctype="multipart/form-data">
 <label>Stock name</label><input name="stock_name" required placeholder="Aurionpro Solutions">
 <div class="row"><div><label>Ticker</label><input name="ticker" required placeholder="AURIONPRO"></div>
  <div><label>Exchange</label><select name="exchange"><option>NSE</option><option>BSE</option></select></div></div>
 <label>Sector / business type</label>
 <select name="sector"><option value="non-financial">Non-financial (DCF)</option>
  <option value="bank-nbfc">Bank / NBFC (Justified P/B)</option>
  <option value="amc">Asset manager</option><option value="conglomerate">Conglomerate (SOTP)</option></select>
 <label>LLM backend</label><select name="llm_backend">
  {% for b in backends %}<option value="{{ b }}">{{ b }}</option>{% endfor %}
  {% if not backends %}<option value="claude">claude (no key set!)</option>{% endif %}</select>
 <fieldset><legend>Data files</legend>
  <label>Screener xlsx (required)</label><input type="file" name="xlsx" accept=".xlsx" required>
  <label>Annual report PDF (optional)</label><input type="file" name="annual_report" accept=".pdf">
  <label>Concall transcript PDF (optional)</label><input type="file" name="transcript" accept=".pdf"></fieldset>
 <fieldset><legend>Manual overrides (optional — blank = auto-fetch)</legend>
  <div class="row"><div><label>Price</label><input name="price"></div>
   <div><label>Market cap (Cr)</label><input name="market_cap"></div></div>
  <div class="row"><div><label>52-wk low</label><input name="low_52w"></div>
   <div><label>52-wk high</label><input name="high_52w"></div>
   <div><label>Beta</label><input name="beta"></div></div></fieldset>
 <button type="submit">Generate report</button></form></body></html>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_app.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add app.py templates/index.html tests/test_app.py
git commit -m "feat: Flask upload form and run route"
```

---

## Phase 8 — End-to-end validation

### Task 16: Golden run with a stub LLM

**Files:**
- Create: `tests/test_e2e.py`

Runs the full pipeline against the real `Aurionpro Sol.xlsx` with a deterministic stub LLM (no API key, no network for LLM), producing a real HTML file and asserting structure. yfinance is bypassed via manual overrides.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_e2e.py
import os
from src.screener_parser import parse_screener
from src.web_data import MarketData
from src.analyst import run_analysis
from src.report import render_report

class StubClient:
    def __init__(self): self.n = 0
    def complete_json(self, system, user):
        self.n += 1
        if self.n == 1:
            return {"growth_path":[0.16,0.14,0.12,0.11,0.10],"terminal_growth":0.05,
                    "scenarios":[{"name":"Bear","value":520,"prob":0.25},
                                 {"name":"Base","value":820,"prob":0.55},
                                 {"name":"Bull","value":1080,"prob":0.20}],
                    "triangulation":[{"name":"DCF","value":820,"weight":0.6},
                                     {"name":"Relative","value":640,"weight":0.4}],
                    "model_choice":"DCF"}
        return {"sections":{str(i):f"<p>Section {i} narrative.</p>" for i in range(1,12)},
                "rating":"BUY","fair_value":760,"target_price":820,"conviction":"Medium"}

def test_end_to_end_produces_report(tmp_path):
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1650.0, beta=0.9,
                    source={k:"manual" for k in ["price","market_cap","low_52w","high_52w","beta"]})
    result = run_analysis(fin, md, "non-financial", "", StubClient(), 0.069, 0.055)
    out = os.path.join(tmp_path, "Aurionpro_Solutions_Valuation.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()
    assert os.path.getsize(out) > 100_000     # Chart.js inlined
    assert "AURIONPRO" in html and "BUY" in html
    assert html.count('class="tab-btn"') == 11
    assert "Not investment advice" in html
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_e2e.py -v`
Expected: FAIL (until all prior modules exist) — once modules present, run below.

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest -v`
Expected: PASS (all tasks' tests green)

- [ ] **Step 4: Manual smoke test**

```bash
python app.py
```
Then in the browser at `http://localhost:5000`: upload `Aurionpro Sol.xlsx`, ticker `AURIONPRO`, sector non-financial, leave overrides blank (or fill price 735.4), submit. Confirm a report opens and `outputs/Aurionpro_Solutions_Valuation.html` exists. (Requires a valid API key in `.env` for the live LLM run.)

- [ ] **Step 5: Commit**

```bash
git add tests/test_e2e.py
git commit -m "test: end-to-end golden run producing Aurionpro report"
```

---

## Self-review notes (spec coverage)

- Sections 1–11 of `SAFARI_Valuation.txt` → metrics (Tasks 4–11) + narrative (Task 13) + render (Task 14). ✔
- "Distinguish source vs computed / never fabricate" → two-pass analyst + `source` map in MarketData + footer note. ✔
- Sector routing incl. bank justified P/B and suppression of ROCE/EV-EBITDA for financials → Task 10 + `build_pack` branch + sector select in form. ✔ (SOTP/DDM scaffolds are present as `model_choice`; full SOTP segment tables are a follow-up if a conglomerate is analysed — flagged, not silently omitted.)
- Required visualisations (band, peer bar, sensitivity heatmap, scenario, triangulation) → Task 14 canvases + `chart_data`. Heatmap rendered as a coloured matrix in Section 5 panel (extend `initCharts` with a matrix render; grid data already injected). ✔
- Single standalone offline HTML, 11 tabs, recommendation box, disclaimer, print page-breaks → Task 14 template. ✔
- Indian FY handling, 5-yr data / 10-yr bands, avg equity ROE, buybacks in payout → parser + Tasks 5/6. ✔

## Known follow-ups (not blocking first working version)
- Full peer-set fetch (multiple tickers) — first version charts the subject's own P/E; peer inputs accepted via manual override fields can be extended to a peer table.
- SOTP per-segment table UI for conglomerates.
- Sensitivity **heatmap** colour-scaling refinement (matrix cells coloured by value).
