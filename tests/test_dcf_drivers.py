import pytest
from src.metrics_dcf import dcf_from_drivers

BASE_DRIVERS = [
    {"revenue_growth":0.15,"ebit_margin":0.17,"tax_rate":0.25,
     "capex_pct_sales":0.10,"wc_change_pct":0.10,"dep_pct_sales":0.03},
] * 5

def test_projection_has_five_years_and_full_lines():
    r = dcf_from_drivers(base_revenue=1411.09, drivers=BASE_DRIVERS, wacc=0.12,
                         terminal_growth=0.05, net_debt=-144.31, shares=5.53)
    assert len(r["projection"]) == 5
    for row in r["projection"]:
        for k in ("revenue","ebit","nopat","d_and_a","capex","delta_wc","fcff","pv"):
            assert k in row
    # revenue compounds correctly
    assert abs(r["projection"][0]["revenue"] - 1411.09*1.15) < 0.01
    assert abs(r["projection"][4]["revenue"] - 1411.09*(1.15**5)) < 0.1

def test_fair_value_positive_and_terminal_disclosed():
    r = dcf_from_drivers(base_revenue=1411.09, drivers=BASE_DRIVERS, wacc=0.12,
                         terminal_growth=0.05, net_debt=-144.31, shares=5.53)
    assert r["fair_value_per_share"] > 0
    assert 0 < r["terminal_value_pct"] < 1
    assert "terminal_over_70pct" in r
    assert "method" in r["assumptions"]

def test_lower_capex_raises_value():
    low = [dict(d, capex_pct_sales=0.05) for d in BASE_DRIVERS]
    high = [dict(d, capex_pct_sales=0.15) for d in BASE_DRIVERS]
    rl = dcf_from_drivers(1411.09, low, 0.12, 0.05, -144.31, 5.53)
    rh = dcf_from_drivers(1411.09, high, 0.12, 0.05, -144.31, 5.53)
    assert rl["fair_value_per_share"] > rh["fair_value_per_share"]

def test_terminal_growth_above_wacc_raises():
    with pytest.raises(ValueError):
        dcf_from_drivers(1411.09, BASE_DRIVERS, wacc=0.05,
                         terminal_growth=0.06, net_debt=0.0, shares=5.53)
