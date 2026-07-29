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
    """Two-stage DCF: explicit projection + Gordon-growth terminal value.

    Raises ValueError if terminal_growth >= wacc: the Gordon-growth
    denominator (wacc - terminal_growth) would be zero or negative, which
    blows up or inverts the terminal value into economic nonsense. Callers
    (e.g. sensitivity_grid) must catch this per-cell rather than letting one
    bad (wacc, g) combination crash an entire grid.
    """
    if terminal_growth >= wacc:
        raise ValueError(
            f"terminal_growth ({terminal_growth}) must be < wacc ({wacc}); "
            "otherwise the Gordon-growth terminal value is undefined/negative."
        )
    flows = _project_fcff(base_fcff, growth_path)
    pv_explicit = sum(f / (1+wacc)**(i+1) for i, f in enumerate(flows))
    tv = flows[-1]*(1+terminal_growth) / (wacc - terminal_growth)
    pv_tv = tv / (1+wacc)**len(flows)
    ev = pv_explicit + pv_tv
    equity_value = ev - net_debt
    return {
        "enterprise_value": ev,
        "pv_explicit": pv_explicit, "pv_terminal": pv_tv,
        "terminal_value_pct": pv_tv/ev if ev else None,
        "terminal_over_70pct": (pv_tv/ev > 0.70) if ev else None,
        "equity_value": equity_value,
        "fair_value_per_share": equity_value/shares if shares else None,
    }


def sensitivity_grid(base_fcff, growth_path, waccs, gs, net_debt, shares):
    """Grid of fair_value_per_share over (wacc rows x terminal-growth cols).

    Any (wacc, g) cell where g >= wacc is economically invalid for the
    Gordon-growth terminal value; dcf_valuation raises ValueError for that
    cell, which is caught here and recorded as None rather than crashing
    the whole grid.
    """
    grid = []
    for w in waccs:
        row = []
        for g in gs:
            try:
                row.append(dcf_valuation(base_fcff, growth_path, w, g,
                                         net_debt, shares)["fair_value_per_share"])
            except ValueError:
                row.append(None)
        grid.append(row)
    return grid


def implied_growth(price_per_share, base_fcff, wacc, terminal_growth,
                   net_debt, shares, years=5, lo=-0.20, hi=0.60, tol=1e-4):
    """Bisect for the flat annual growth rate that reprices the DCF to
    price_per_share. Returns a plain float (the growth rate, or the nearer
    bound if the price is outside the achievable range at [lo, hi]).

    See `implied_growth_detail` for a version that also flags when the
    true implied growth lies outside [lo, hi] instead of silently returning
    a wrong-looking midpoint.
    """
    detail = implied_growth_detail(price_per_share, base_fcff, wacc, terminal_growth,
                                   net_debt, shares, years, lo, hi, tol)
    return detail["growth"]


def implied_growth_detail(price_per_share, base_fcff, wacc, terminal_growth,
                          net_debt, shares, years=5, lo=-0.20, hi=0.60, tol=1e-4):
    """Bisection solver for implied growth, with an explicit out-of-bounds flag.

    If price_per_share lies outside [fv(lo), fv(hi)] (the achievable range
    at the bisection bounds), the true implied growth is outside [lo, hi]
    and bisection cannot converge on it correctly. Rather than silently
    returning a misleading midpoint, we return the bound closest to the
    target with `out_of_bounds=True` and `bound_hit` naming which bound.
    """
    def fv(g):
        return dcf_valuation(base_fcff, [g]*years, wacc, terminal_growth,
                             net_debt, shares)["fair_value_per_share"]

    v_lo, v_hi = fv(lo), fv(hi)
    if v_hi < price_per_share:
        return {"growth": hi, "out_of_bounds": True, "bound_hit": "hi"}
    if v_lo > price_per_share:
        return {"growth": lo, "out_of_bounds": True, "bound_hit": "lo"}

    a, b = lo, hi
    mid = (a + b) / 2
    for _ in range(200):
        mid = (a + b) / 2
        v = fv(mid)
        if abs(v - price_per_share) < tol * max(1.0, price_per_share):
            return {"growth": mid, "out_of_bounds": False, "bound_hit": None}
        if v < price_per_share:
            a = mid
        else:
            b = mid
    return {"growth": (a + b) / 2, "out_of_bounds": False, "bound_hit": None}
