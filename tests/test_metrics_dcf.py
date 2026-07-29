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
    assert "terminal_over_70pct" in res

def test_sensitivity_grid_shape():
    grid = sensitivity_grid(base_fcff=150.0, growth_path=[0.12]*5,
                            waccs=[0.10,0.11,0.12,0.13,0.14],
                            gs=[0.03,0.04,0.05,0.055,0.06],
                            net_debt=-140.0, shares=5.53)
    assert len(grid) == 5 and all(len(row) == 5 for row in grid)
    assert grid[0][0] > grid[4][0]

def test_terminal_growth_ge_wacc_raises():
    import pytest
    with pytest.raises(ValueError):
        dcf_valuation(base_fcff=150.0, growth_path=[0.15]*5, wacc=0.10,
                      terminal_growth=0.10, net_debt=-140.0, shares=5.53)

def test_sensitivity_grid_handles_invalid_cell_as_none():
    grid = sensitivity_grid(base_fcff=150.0, growth_path=[0.12]*5,
                            waccs=[0.05, 0.12],
                            gs=[0.05, 0.03],
                            net_debt=-140.0, shares=5.53)
    # wacc=0.05 paired with g=0.05 => terminal_growth >= wacc => None, not a crash
    assert grid[0][0] is None
    assert grid[1][1] is not None
