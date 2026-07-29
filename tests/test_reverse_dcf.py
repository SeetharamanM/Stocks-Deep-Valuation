from src.metrics_dcf import implied_growth

def test_implied_growth_recovers_input():
    from src.metrics_dcf import dcf_valuation
    price = dcf_valuation(base_fcff=100.0, growth_path=[0.10]*5, wacc=0.12,
                          terminal_growth=0.05, net_debt=0.0, shares=1.0)["fair_value_per_share"]
    g = implied_growth(price_per_share=price, base_fcff=100.0, wacc=0.12,
                       terminal_growth=0.05, net_debt=0.0, shares=1.0, years=5)
    assert abs(g - 0.10) < 0.005

def test_implied_growth_out_of_bounds_flagged():
    from src.metrics_dcf import implied_growth_detail
    # An absurdly high price cannot be justified even at the top of the
    # growth range; the solver must say so rather than silently returning
    # a misleading midpoint.
    detail = implied_growth_detail(price_per_share=1_000_000.0, base_fcff=100.0, wacc=0.12,
                                   terminal_growth=0.05, net_debt=0.0, shares=1.0, years=5,
                                   lo=-0.20, hi=0.60)
    assert detail["out_of_bounds"] is True
    assert detail["bound_hit"] == "hi"

    # An absurdly low price similarly can't be justified even at the bottom
    # of the growth range (fair value per share at g=lo is still well above
    # this price, so the true implied growth would have to be below lo).
    detail_lo = implied_growth_detail(price_per_share=10.0, base_fcff=100.0, wacc=0.12,
                                      terminal_growth=0.05, net_debt=0.0, shares=1.0, years=5,
                                      lo=-0.20, hi=0.60)
    assert detail_lo["out_of_bounds"] is True
    assert detail_lo["bound_hit"] == "lo"
