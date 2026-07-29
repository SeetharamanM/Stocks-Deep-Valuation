from src import metrics
from src.metrics_dcf import (capm_cost_of_equity, wacc as calc_wacc,
                             dcf_valuation, sensitivity_grid, implied_growth_detail)


def _normalised_base_fcff(fin, base, ret):
    """Normalised FCFF anchored on earnings, not on one noisy cash-flow year.

    FCFF = NOPAT + Depreciation - Capex(3yr avg) - dWorkingCapital

    NOPAT = EBIT x (1 - effective_tax_rate) for the latest FY.

    Capex uses the 3-year average of the fixed-asset-movement capex
    estimates already in `base["fcf_series"]` (see metrics.fcf_for_year),
    rather than the single latest year, specifically to damp a one-off
    acquisition/capex spike. Delta-working-capital is NOT reliably
    derivable from the Screener Data Sheet (no separate receivables/payables
    movement is exposed cleanly across the years we have), so it is set to
    0.0 and that assumption is disclosed in the method string -- it is not
    silently omitted.

    CRITICAL: if the resulting normalised FCFF is <= 0, this function does
    NOT clamp it to a small positive placeholder. It returns the (possibly
    negative) number as-is; the caller must treat that as "DCF not viable"
    rather than fabricate a base cash flow to force a number out of the model.
    """
    latest = fin.pnl_years[-1]
    ebit = latest.pbt + latest.interest - latest.other_income
    eff_tax = base["effective_tax_rate"] if base["effective_tax_rate"] is not None else 0.25
    nopat = ebit * (1 - eff_tax)

    fcf_series = base["fcf_series"]
    capex_window = fcf_series[-3:] if len(fcf_series) >= 3 else fcf_series
    capex_years = [x["year"] for x in capex_window]
    capex_avg3 = (sum(x["capex"] for x in capex_window) / len(capex_window)) if capex_window else 0.0

    delta_wc = 0.0
    base_fcff = nopat + latest.depreciation - capex_avg3 - delta_wc

    method = (
        f"Normalised FCFF = NOPAT + Depreciation - Capex(3yr avg) - dWorkingCapital = "
        f"{nopat:.2f} + {latest.depreciation:.2f} - {capex_avg3:.2f} - {delta_wc:.2f} = {base_fcff:.2f}. "
        f"NOPAT = EBIT({ebit:.2f}) x (1 - effective_tax_rate {eff_tax:.4f}) for FY{latest.year}. "
        f"Capex is the 3-year average ({', '.join(str(y) for y in capex_years)}) of the "
        "fixed-asset-movement capex estimate (see metrics.fcf_for_year), used instead of the "
        "single latest year to damp an acquisition/capex spike. "
        "dWorkingCapital is NOT reliably derivable from this dataset and is set to 0.0 -- "
        "this is a disclosed simplification, not a computed figure."
    )
    return {
        "base_fcff": base_fcff, "method": method, "nopat": nopat, "ebit": ebit,
        "effective_tax_rate": eff_tax, "depreciation": latest.depreciation,
        "capex_3yr_avg": capex_avg3, "capex_years_used": capex_years, "delta_wc": delta_wc,
    }


def _growth_path(ret, dcf_overrides):
    """Default DCF growth assumption, capped at the SGR/ROIC ceiling.

    Per the methodology, assumed growth must not exceed EITHER the
    sustainable growth rate (SGR = ROE x retention) OR the
    reinvestment-implied growth (Reinvestment x ROIC). Absent an explicit
    override, the ceiling itself is used as the assumed growth (there is no
    other independent growth estimate in this dataset); `growth_capped`
    records whether an override (or the ceiling logic) actually bound.
    """
    overrides = dcf_overrides or {}
    sgr = ret.get("sgr")
    g_reinvest = ret.get("g_from_reinvestment")
    candidates = [x for x in (sgr, g_reinvest) if x is not None]
    ceiling = min(candidates) if candidates else 0.0

    years = int(overrides.get("years", 5))
    requested = overrides.get("growth", ceiling)
    capped = requested > ceiling
    assumed = min(requested, ceiling)
    return {
        "growth_path": [assumed] * years,
        "growth_ceiling": ceiling,
        "growth_requested": requested,
        "growth_capped": capped,
        "sgr": sgr, "g_from_reinvestment": g_reinvest,
    }


def build_pack(fin, md, sector, rf, erp, dcf_overrides=None):
    base = metrics.valuation_base(fin)
    rel = metrics.relative_multiples(fin)
    bands = metrics.historical_bands(fin)
    ret = metrics.returns_and_ceilings(fin)

    beta = md.beta if md.beta is not None else 1.0
    coe = capm_cost_of_equity(rf, erp, beta)
    bs = fin.bs_years[-1]
    cod_post_tax = 0.09 * (1 - (base["effective_tax_rate"] or 0.25))
    w = calc_wacc(coe, cod_post_tax, fin.market_cap, max(bs.borrowings, 1e-6))
    net_debt = bs.borrowings - bs.cash
    shares = base["diluted_shares_cr"]

    overrides = dcf_overrides or {}
    terminal_growth = overrides.get("terminal_growth", 0.05)

    fcff_info = _normalised_base_fcff(fin, base, ret)
    growth_info = _growth_path(ret, dcf_overrides)
    base_fcff = fcff_info["base_fcff"]

    dcf_common = {
        "base_fcff": base_fcff,
        "base_fcff_method": fcff_info["method"],
        "nopat": fcff_info["nopat"],
        "ebit": fcff_info["ebit"],
        "effective_tax_rate": fcff_info["effective_tax_rate"],
        "depreciation": fcff_info["depreciation"],
        "capex_3yr_avg": fcff_info["capex_3yr_avg"],
        "capex_years_used": fcff_info["capex_years_used"],
        "delta_wc": fcff_info["delta_wc"],
        "growth_path": growth_info["growth_path"],
        "growth_ceiling": growth_info["growth_ceiling"],
        "growth_capped": growth_info["growth_capped"],
        "sgr": growth_info["sgr"],
        "g_from_reinvestment": growth_info["g_from_reinvestment"],
        "wacc": w, "coe": coe, "beta": beta,
        "cost_of_debt_post_tax": cod_post_tax,
        "terminal_growth": terminal_growth,
        "net_debt": net_debt, "shares": shares,
    }

    if base_fcff is None or base_fcff <= 0:
        dcf_pack = {
            "viable": False,
            "reason": (
                f"Normalised FCFF is {base_fcff:.2f} Cr (<= 0). Aurionpro-style "
                "companies in a heavy capex/acquisition build-out phase can have "
                "genuinely negative normalised free cash flow; a DCF cannot be "
                "reliably anchored on current cash flows in that case. This is "
                "NOT clamped to a fabricated positive number -- the DCF is "
                "skipped and triangulation should lean on earnings-based methods "
                "(P/E bands, EV/EBITDA, justified P/B) instead."
                if base_fcff is not None else
                "Normalised FCFF could not be computed (insufficient data)."
            ),
            **dcf_common,
        }
    else:
        try:
            res = dcf_valuation(base_fcff, growth_info["growth_path"], w,
                                terminal_growth, net_debt, shares)
            grid = sensitivity_grid(
                base_fcff, growth_info["growth_path"],
                waccs=[w - 0.02, w - 0.01, w, w + 0.01, w + 0.02],
                gs=[max(terminal_growth - 0.02, -0.5), terminal_growth - 0.01,
                    terminal_growth, terminal_growth + 0.01, terminal_growth + 0.02],
                net_debt=net_debt, shares=shares,
            )
            dcf_pack = {"viable": True, **res, "sensitivity_grid": grid, **dcf_common}
        except ValueError as e:
            dcf_pack = {"viable": False, "reason": f"DCF inputs invalid: {e}", **dcf_common}

    if dcf_pack["viable"]:
        price_for_reverse = md.price or fin.current_price
        detail = implied_growth_detail(
            price_per_share=price_for_reverse, base_fcff=base_fcff, wacc=w,
            terminal_growth=terminal_growth, net_debt=net_debt, shares=shares,
            years=len(growth_info["growth_path"]),
        )
        reverse_dcf = {"available": True, **detail}
    else:
        reverse_dcf = {
            "available": False,
            "reason": "DCF is not viable (see dcf.reason); implied growth cannot be "
                      "solved without a positive base cash flow to anchor the model on.",
        }

    price_used = md.price if md.price is not None else fin.current_price
    price_source = "market_data" if md.price is not None else "screener_xlsx"

    pack = {
        "meta": {
            "company": fin.company_name, "sector": sector,
            "current_price": price_used, "current_price_source": price_source,
            "market_cap": fin.market_cap,
            "low_52w": md.low_52w, "high_52w": md.high_52w,
            "as_of": md.as_of, "sources": md.source, "latest_fy": base["latest_fy"],
        },
        "base": base, "relative": rel, "bands": bands, "returns": ret,
        "dcf": dcf_pack, "reverse_dcf": reverse_dcf,
    }

    if sector in ("bank-nbfc", "bank", "nbfc"):
        pack["justified_pb"] = metrics.justified_pb(
            ret["roe"] if ret["roe"] is not None else 0.0, terminal_growth, coe
        )

    return pack
