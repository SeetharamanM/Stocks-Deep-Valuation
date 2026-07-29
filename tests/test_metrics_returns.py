from src.screener_parser import parse_screener
from src.metrics import returns_and_ceilings

def test_returns_and_ceilings():
    fin = parse_screener("Aurionpro Sol.xlsx")
    r = returns_and_ceilings(fin)
    eq_2026 = 53.80 + 1683.74
    eq_2025 = 53.71 + 1449.55
    roe = 209.31 / ((eq_2026 + eq_2025) / 2)
    assert abs(r["roe"] - roe) < 0.005
    assert 0 <= r["payout_ratio"] < 1
    assert abs(r["sgr"] - r["roe"] * (1 - r["payout_ratio"])) < 1e-6
    assert r["roic"] is not None
