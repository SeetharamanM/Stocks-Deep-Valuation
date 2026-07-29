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


def dcf_from_drivers(base_revenue, drivers, wacc, terminal_growth,
                     net_debt, shares, terminal_capex_pct=None):
    """Driver-based 5-year explicit-forecast DCF (SAFARI_Valuation.txt sec. 5a).

    Unlike `dcf_valuation` (which compounds a single base_fcff at a flat
    growth rate -- appropriate only once a company's reinvestment intensity
    has already normalised), this builds the FCFF for each forecast year
    from its own revenue growth, EBIT margin, tax rate, capex/sales and
    working-capital-change assumptions. This lets a capex-heavy build-out
    year fade toward a steady-state reinvestment rate over the explicit
    forecast instead of being projected flat forever, which is what made
    the single-cash-flow model produce a permanently negative FCFF for
    companies mid capex cycle (see Aurionpro).

    drivers: list of 5 dicts, one per forecast year:
        revenue_growth   float
        ebit_margin      float
        tax_rate         float
        capex_pct_sales  float
        wc_change_pct    float  (applied to INCREMENTAL revenue)
        dep_pct_sales    float, optional -- defaults to the last dict's
                         dep_pct_sales, or 0.0 if never supplied.

    Terminal value: perpetuity growth on a terminal-year FCFF where capex
    has normalised to steady state -- either `terminal_capex_pct * revenue`
    if supplied, or (the standard assumption) capex == D&A, i.e. growth
    beyond the explicit forecast is funded only by incremental working
    capital, not by net new fixed-asset investment.

    Raises ValueError if terminal_growth >= wacc, matching dcf_valuation.
    """
    if terminal_growth >= wacc:
        raise ValueError(
            f"terminal_growth ({terminal_growth}) must be < wacc ({wacc}); "
            "otherwise the Gordon-growth terminal value is undefined/negative."
        )

    last_dep_pct = 0.0
    for d in drivers:
        if d.get("dep_pct_sales") is not None:
            last_dep_pct = d["dep_pct_sales"]

    projection = []
    revenue_prev = base_revenue
    for i, d in enumerate(drivers):
        revenue = revenue_prev * (1 + d["revenue_growth"])
        ebit = revenue * d["ebit_margin"]
        nopat = ebit * (1 - d["tax_rate"])
        dep_pct = d.get("dep_pct_sales")
        dep_pct = dep_pct if dep_pct is not None else last_dep_pct
        d_and_a = revenue * dep_pct
        capex = revenue * d["capex_pct_sales"]
        delta_wc = (revenue - revenue_prev) * d["wc_change_pct"]
        fcff = nopat + d_and_a - capex - delta_wc
        discount_factor = 1 / (1 + wacc) ** (i + 1)
        pv = fcff * discount_factor
        projection.append({
            "year": i + 1, "revenue": revenue, "ebit": ebit, "nopat": nopat,
            "d_and_a": d_and_a, "capex": capex, "delta_wc": delta_wc,
            "fcff": fcff, "discount_factor": discount_factor, "pv": pv,
            "revenue_growth": d["revenue_growth"], "ebit_margin": d["ebit_margin"],
            "tax_rate": d["tax_rate"], "capex_pct_sales": d["capex_pct_sales"],
            "wc_change_pct": d["wc_change_pct"], "dep_pct_sales": dep_pct,
        })
        revenue_prev = revenue

    pv_explicit = sum(row["pv"] for row in projection)

    last = projection[-1]
    revenue_term = last["revenue"] * (1 + terminal_growth)
    nopat_term = last["nopat"] * (1 + terminal_growth)
    d_and_a_term = revenue_term * last["dep_pct_sales"]
    if terminal_capex_pct is not None:
        capex_term = revenue_term * terminal_capex_pct
        terminal_capex_basis = f"terminal_capex_pct override = {terminal_capex_pct:.4f} of terminal-year revenue"
    else:
        capex_term = d_and_a_term
        terminal_capex_basis = "capex = D&A in the terminal year (steady-state: growth funded only by working capital, not net new fixed assets)"
    delta_wc_term = (revenue_term - last["revenue"]) * last["wc_change_pct"]
    terminal_fcff = nopat_term + d_and_a_term - capex_term - delta_wc_term

    tv = terminal_fcff / (wacc - terminal_growth)
    pv_terminal = tv / (1 + wacc) ** len(projection)

    ev = pv_explicit + pv_terminal
    equity_value = ev - net_debt
    terminal_value_pct = pv_terminal / ev if ev else None

    method = (
        f"5-year driver-based DCF (SAFARI sec. 5a): each year's FCFF = "
        "NOPAT + D&A - Capex - dWorkingCapital, built from that year's own "
        "revenue growth, EBIT margin, tax rate, capex/sales and "
        "wc-change/incremental-revenue assumptions (see 'projection' for the "
        "full per-year table). Terminal value uses perpetuity growth on a "
        f"terminal-year FCFF where {terminal_capex_basis}."
    )

    return {
        "projection": projection,
        "pv_explicit": pv_explicit,
        "pv_terminal": pv_terminal,
        "enterprise_value": ev,
        "terminal_value_pct": terminal_value_pct,
        "terminal_over_70pct": (terminal_value_pct > 0.70) if terminal_value_pct is not None else None,
        "equity_value": equity_value,
        "fair_value_per_share": equity_value / shares if shares else None,
        "terminal_fcff": terminal_fcff,
        "terminal": {
            "revenue": revenue_term, "nopat": nopat_term, "d_and_a": d_and_a_term,
            "capex": capex_term, "delta_wc": delta_wc_term, "fcff": terminal_fcff,
        },
        "assumptions": {
            "drivers": drivers, "wacc": wacc, "terminal_growth": terminal_growth,
            "terminal_capex_pct": terminal_capex_pct,
            "terminal_capex_basis": terminal_capex_basis,
            "method": method,
        },
    }


def sensitivity_grid_drivers(base_revenue, drivers, waccs, gs, net_debt, shares,
                             terminal_capex_pct=None):
    """Driver-based analogue of `sensitivity_grid`: re-runs `dcf_from_drivers`
    across a (wacc x terminal-growth) matrix instead of the single-cash-flow
    `dcf_valuation`. Any (wacc, g) cell where g >= wacc raises inside
    `dcf_from_drivers`; that is caught here and recorded as None so one
    invalid combination doesn't crash the whole grid.
    """
    grid = []
    for w in waccs:
        row = []
        for g in gs:
            try:
                res = dcf_from_drivers(base_revenue, drivers, w, g, net_debt, shares,
                                       terminal_capex_pct=terminal_capex_pct)
                row.append(res["fair_value_per_share"])
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


def implied_growth_from_drivers_detail(price_per_share, base_revenue, drivers, wacc,
                                       terminal_growth, net_debt, shares,
                                       terminal_capex_pct=None,
                                       lo=-0.20, hi=0.60, tol=1e-4):
    """Reverse DCF against the driver-based model: bisect for the single
    flat revenue_growth rate (applied uniformly across all forecast years)
    that reprices `dcf_from_drivers` to `price_per_share`, holding every
    other driver (ebit_margin, tax_rate, capex_pct_sales, wc_change_pct,
    dep_pct_sales) and terminal_growth fixed at whatever was passed in
    `drivers`.

    Mirrors `implied_growth_detail`'s out-of-bounds handling: if the price
    can't be justified even at `hi` (or is undercut even at `lo`), that is
    flagged explicitly via `out_of_bounds`/`bound_hit` rather than silently
    returning a misleading midpoint.
    """
    def fv(g):
        g_drivers = [dict(d, revenue_growth=g) for d in drivers]
        return dcf_from_drivers(base_revenue, g_drivers, wacc, terminal_growth,
                                net_debt, shares,
                                terminal_capex_pct=terminal_capex_pct)["fair_value_per_share"]

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
