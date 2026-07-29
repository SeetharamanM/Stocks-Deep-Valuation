from statistics import median, pstdev


def _shares(fin):
    return fin.adjusted_shares_cr[-1]


def _capex_from_movement(bs_t, bs_prev, dep_t):
    """Estimate capex for year t from the fixed-asset-movement identity:

        capex_t = (NetBlock_t + CWIP_t) - (NetBlock_{t-1} + CWIP_{t-1}) + Depreciation_t

    This is the standard proxy used when a cash-flow statement doesn't
    itemise capex separately (as here, where Screener's CFI line bundles
    capex together with acquisitions and investment purchases/sales). It is
    still a disclosed ESTIMATE, not a reported figure: it can be thrown off
    by revaluations, disposals, or reclassifications within Net Block/CWIP
    that aren't really "capex" in the cash sense.

    A year of net asset disposals (or a data quirk) can make the raw
    movement negative; that would imply negative capex, which is not a
    meaningful economic outcome, so the result is clamped to 0.0 and the
    clamp is disclosed via `capex_clamped`.
    """
    nb_t = (bs_t.net_block or 0.0) + (bs_t.cwip or 0.0)
    nb_prev = (bs_prev.net_block or 0.0) + (bs_prev.cwip or 0.0)
    raw_capex = nb_t - nb_prev + (dep_t or 0.0)
    clamped = raw_capex < 0
    capex = max(raw_capex, 0.0)
    method = (
        f"Capex estimated from fixed-asset movement: "
        f"(NetBlock_{bs_t.year}={bs_t.net_block:.2f} + CWIP_{bs_t.year}={bs_t.cwip:.2f}) - "
        f"(NetBlock_{bs_prev.year}={bs_prev.net_block:.2f} + CWIP_{bs_prev.year}={bs_prev.cwip:.2f}) + "
        f"Depreciation_{bs_t.year}={dep_t:.2f} = {raw_capex:.2f}"
        + (" ; clamped to 0.0 (negative movement implies net disposals, not negative capex)"
           if clamped else "")
        + ". This is a disclosed estimate, not a reported capex figure: Screener's "
          "Cash-from-Investing line is not broken out into capex vs. acquisitions/"
          "investment purchases, so fixed-asset movement is used as the best available proxy."
    )
    return capex, method, clamped


def fcf_for_year(fin, year):
    """Compute FCF for a single fiscal year using capex from fixed-asset
    movement (see `_capex_from_movement`), matching CF/BS/PnL rows by year.

    Returns None if the year isn't present in all three statements, or if
    the prior year's balance sheet (needed for the capex movement) isn't
    available. Both `valuation_base` and `relative_multiples` call this
    same helper so the FCF figure they report can never disagree.
    """
    bs_by_year = {b.year: b for b in fin.bs_years}
    pnl_by_year = {p.year: p for p in fin.pnl_years}
    cf_by_year = {c.year: c for c in fin.cf_years}
    if year not in bs_by_year or year not in pnl_by_year or year not in cf_by_year:
        return None
    prev_year = year - 1
    if prev_year not in bs_by_year:
        return None
    bs_t, bs_prev = bs_by_year[year], bs_by_year[prev_year]
    cf_t, pnl_t = cf_by_year[year], pnl_by_year[year]
    capex, method, clamped = _capex_from_movement(bs_t, bs_prev, pnl_t.depreciation)
    fcf = cf_t.cfo - capex
    return {"year": year, "fcf": fcf, "capex": capex, "cfo": cf_t.cfo,
            "capex_clamped": clamped, "method": method}


def valuation_base(fin):
    latest = fin.pnl_years[-1]
    shares = _shares(fin)
    bs = fin.bs_years[-1]

    q = [v for _, v in fin.quarters_net_profit if v is not None][-4:]
    ttm_np = sum(q) if len(q) == 4 else latest.net_profit

    years_common = sorted(set(y.year for y in fin.cf_years)
                          & set(y.year for y in fin.bs_years)
                          & set(y.year for y in fin.pnl_years))
    fcf_series = []
    for year in years_common[-5:]:
        entry = fcf_for_year(fin, year)
        if entry is not None:
            fcf_series.append(entry)

    fcf_years = {x["year"] for x in fcf_series}
    pat_matched = [p.net_profit for p in fin.pnl_years if p.year in fcf_years]
    fcf_pat = (sum(x["fcf"] for x in fcf_series) / sum(pat_matched)) if sum(pat_matched) else None

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


def _ebitda_ebit(fin, p):
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
    fcf_entry = fcf_for_year(fin, latest.year)
    fcf = fcf_entry["fcf"] if fcf_entry is not None else None
    return {
        "pe_current": price / eps if eps else None,
        "pb_current": price / bvps if bvps else None,
        "ev_ebitda_current": ev / ebitda if ebitda else None,
        "ev_ebit_current": ev / ebit if ebit else None,
        "ev_sales_current": ev / latest.sales if latest.sales else None,
        "p_sales_current": fin.market_cap / latest.sales if latest.sales else None,
        "dividend_yield": (latest.dividend / fin.market_cap) if fin.market_cap else None,
        "fcf_yield": (fcf / fin.market_cap) if (fcf is not None and fin.market_cap) else None,
        "enterprise_value": ev,
    }


def _yearly_pe(fin):
    out = []
    n = min(len(fin.yearend_price), len(fin.adjusted_shares_cr), len(fin.pnl_years))
    for i in range(-n, 0):
        eps = fin.pnl_years[i].net_profit / fin.adjusted_shares_cr[i]
        if eps and eps > 0:
            out.append((fin.pnl_years[i].year, fin.yearend_price[i] / eps))
    return out


def historical_bands(fin):
    pe_pairs = _yearly_pe(fin)
    pairs10 = pe_pairs[-10:]
    pairs5 = pe_pairs[-5:]
    pes10 = [pe for _, pe in pairs10]
    pes5 = [pe for _, pe in pairs5]
    years10 = [y for y, _ in pairs10]
    med10 = median(pes10) if pes10 else None
    med5 = median(pes5) if pes5 else None
    sd = pstdev(pes10) if len(pes10) > 1 else 0.0
    cur = relative_multiples(fin)["pe_current"]
    z = (cur - med10) / sd if (sd and med10 is not None and cur) else None
    lower_band = (med10 - sd) if med10 is not None else None
    return {
        "pe_history": pes10,
        "pe_years": years10,
        "median_pe_10y": med10, "median_pe_5y": med5, "sd_pe": sd,
        "upper_band": (med10 + sd) if med10 is not None else None,
        "lower_band": lower_band,
        "lower_band_display": max(lower_band, 0.0) if lower_band is not None else None,
        "band_skewed": (lower_band < 0) if lower_band is not None else False,
        "current_pe": cur, "current_z": z,
    }


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
    _, ebit = _ebitda_ebit(fin, latest)
    eff_tax = latest.tax / latest.pbt if latest.pbt else 0.0
    invested = eq_now + bs_now.borrowings
    roic = (ebit * (1 - eff_tax)) / invested if invested else None
    reinvest = 1 - payout
    g_reinvest = reinvest * roic if roic is not None else None
    return {"roe": roe, "payout_ratio": payout, "sgr": sgr,
            "roic": roic, "g_from_reinvestment": g_reinvest}
