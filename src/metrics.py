from statistics import median, pstdev


def _shares(fin):
    return fin.adjusted_shares_cr[-1]


def _capex_and_fcf(cf):
    """Derive a capex proxy and FCF for one CFYear.

    Capex is not itemised in the Screener Data Sheet, so we proxy it as the
    magnitude of Cash-from-Investing (CFI). This is a real approximation:
    CFI also bundles acquisitions and purchases/sales of investments, so FCF
    computed this way can be badly understated (or overstated) for an
    acquisitive company or one that parks cash in investments. The method
    string is kept on every result so downstream reporting can disclose it.

    If CFI is positive (net divestment / net inflow from investing in the
    year), treating -CFI as capex would produce a nonsensical negative capex
    that inflates FCF. In that case we treat capex as 0.0 for the year and
    say so explicitly.
    """
    if cf.cfi is not None and cf.cfi > 0:
        capex = 0.0
        method = ("Capex proxy = 0 (CFI was positive/net divestment this "
                  "year, so -CFI would imply negative capex; treated as no "
                  "capex). FCF = CFO.")
    else:
        capex = -cf.cfi if cf.cfi is not None else 0.0
        method = ("FCF = CFO - Capex, where Capex is proxied as the full "
                  "magnitude of Cash-from-Investing (CFI is not broken out "
                  "into capex vs. acquisitions/investments in this data, so "
                  "this proxy can understate FCF for acquisitive years or "
                  "years with large investment purchases).")
    fcf = cf.cfo - capex
    return capex, fcf, method


def valuation_base(fin):
    latest = fin.pnl_years[-1]
    shares = _shares(fin)
    bs = fin.bs_years[-1]

    q = [v for _, v in fin.quarters_net_profit if v is not None][-4:]
    ttm_np = sum(q) if len(q) == 4 else latest.net_profit

    fcf_series = []
    for cf in fin.cf_years[-5:]:
        capex, fcf, method = _capex_and_fcf(cf)
        fcf_series.append({"year": cf.year, "fcf": fcf, "capex": capex, "method": method})

    pat_5 = [p.net_profit for p in fin.pnl_years[-5:]]
    fcf_pat = (sum(x["fcf"] for x in fcf_series) / sum(pat_5)) if sum(pat_5) else None

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
    _, fcf, _ = _capex_and_fcf(fin.cf_years[-1])
    return {
        "pe_current": price / eps if eps else None,
        "pb_current": price / bvps if bvps else None,
        "ev_ebitda_current": ev / ebitda if ebitda else None,
        "ev_ebit_current": ev / ebit if ebit else None,
        "ev_sales_current": ev / latest.sales if latest.sales else None,
        "p_sales_current": fin.market_cap / latest.sales if latest.sales else None,
        "dividend_yield": (latest.dividend / fin.market_cap) if fin.market_cap else None,
        "fcf_yield": (fcf / fin.market_cap) if fin.market_cap else None,
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
    return {
        "pe_history": pes10,
        "pe_years": years10,
        "median_pe_10y": med10, "median_pe_5y": med5, "sd_pe": sd,
        "upper_band": (med10 + sd) if med10 is not None else None,
        "lower_band": (med10 - sd) if med10 is not None else None,
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
