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
    quarters_net_profit: list = field(default_factory=list)
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

    bs_dt = _find_row(ws, "Report Date", 55, 79)
    bs_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(bs_dt, c).value)]
    bs_years_list = [_year(ws.cell(bs_dt, c).value) for c in bs_cols]
    def brow(lbl): return _series(ws, _find_row(ws, lbl, 55, 79), bs_cols)
    eq, res, bor = brow("Equity Share Capital"), brow("Reserves"), brow("Borrowings")
    cash, shr = brow("Cash & Bank"), brow("No. of Equity Shares")
    bs_years = [BSYear(bs_years_list[i], eq[i] or 0, res[i] or 0, bor[i] or 0,
                       cash[i] or 0, shr[i] or 0) for i in range(len(bs_years_list))
                if (res[i] is not None or eq[i] is not None)]

    cf_dt = _find_row(ws, "Report Date", 80, 89)
    cf_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(cf_dt, c).value)]
    cf_years_list = [_year(ws.cell(cf_dt, c).value) for c in cf_cols]
    cfo = _series(ws, _find_row(ws, "Cash from Operating Activity", 80, 89), cf_cols)
    cfi = _series(ws, _find_row(ws, "Cash from Investing Activity", 80, 89), cf_cols)
    cf_years = [CFYear(cf_years_list[i], cfo[i] or 0, cfi[i] or 0)
                for i in range(len(cf_years_list)) if cfo[i] is not None]

    price_row = _find_row(ws, "PRICE:", 89, 91)
    yearend_price = [v for v in _series(ws, price_row, year_cols) if v is not None]
    adj_row = _find_row(ws, "Adjusted Equity Shares in Cr", 92, ws.max_row)
    adjusted = [v for v in _series(ws, adj_row, year_cols) if v is not None]

    q_dt = _find_row(ws, "Report Date", 40, 54)
    q_cols = [c for c in range(2, ws.max_column + 1) if _year(ws.cell(q_dt, c).value)]
    q_np = _series(ws, _find_row(ws, "Net profit", 40, 54), q_cols)
    q_op = _series(ws, _find_row(ws, "Operating Profit", 40, 54), q_cols)
    q_dates = [ws.cell(q_dt, c).value for c in q_cols]

    return Financials(company, current_price, market_cap, face_value,
                      pnl_years, bs_years, cf_years,
                      list(zip(q_dates, q_np)), list(zip(q_dates, q_op)),
                      adjusted, yearend_price)
