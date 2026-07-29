from src.screener_parser import parse_screener
from src.metrics import valuation_base

def test_valuation_base():
    fin = parse_screener("Aurionpro Sol.xlsx")
    base = valuation_base(fin)
    assert abs(base["eps_latest_fy"] - (209.31 / 5.53)) < 0.05
    assert base["eps_ttm"] > 0
    bvps = (53.80 + 1683.74) / 5.53
    assert abs(base["bvps"] - bvps) < 0.5
    ndps = (60.68 - 204.99) / 5.53
    assert abs(base["net_debt_per_share"] - ndps) < 0.5
    assert abs(base["effective_tax_rate"] - (40.69 / 252.47)) < 0.005
    assert "fcf_series" in base and len(base["fcf_series"]) >= 3
