from src.screener_parser import parse_screener

XLSX = "Aurionpro Sol.xlsx"

def test_parses_meta_and_latest_fy():
    fin = parse_screener(XLSX)
    assert fin.company_name.upper().startswith("AURIONPRO")
    assert abs(fin.current_price - 735.4) < 0.01
    assert abs(fin.market_cap - 4076.37) < 0.01
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
    assert abs(fin.adjusted_shares_cr[-1] - 5.53) < 0.01
    assert abs(fin.yearend_price[-1] - 724.7) < 0.01
