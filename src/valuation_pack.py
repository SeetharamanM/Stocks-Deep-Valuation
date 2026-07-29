from src import metrics
from src.metrics_dcf import (capm_cost_of_equity, wacc as calc_wacc,
                             dcf_valuation, sensitivity_grid, implied_growth_detail,
                             dcf_from_drivers, sensitivity_grid_drivers,
                             implied_growth_from_drivers_detail)
from config import Config


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


def _linear_fade(start, end, years):
    """Linear path from `start` (year 1) to `end` (year `years`), inclusive
    of both endpoints. Used to fade a driver assumption toward a long-run
    steady state over the explicit forecast, rather than holding it flat
    (which is what let a one-off build-out year get projected forever).
    """
    if years <= 1:
        return [end]
    return [start + (end - start) * i / (years - 1) for i in range(years)]


def default_drivers(fin, ret, base, years=5, terminal_growth=0.05):
    """Build a defensible, fully-disclosed default 5-year driver path from
    actuals, per SAFARI_Valuation.txt sec. 5a. This is what the LLM later
    overrides with judgment; every assumption here is a disclosed default,
    not a reported figure.

    - revenue_growth: recent (3yr) sales CAGR, capped at the methodology
      ceiling min(SGR, Reinvestment x ROIC), then faded linearly to
      `terminal_growth` by year 5.
    - ebit_margin: held flat at the latest actual EBIT margin.
    - tax_rate: faded from the current effective rate to the statutory rate
      (Config.STATUTORY_TAX) by year 5 -- a concessional effective rate is
      not assumed to persist in perpetuity.
    - capex_pct_sales: faded from the latest actual capex/sales ratio down
      to the latest depreciation/sales ratio (steady-state floor) by year 5.
      This is the key fix: a single build-out year is no longer projected
      flat forever.
    - wc_change_pct: the Screener Data Sheet as parsed here does not expose
      receivables/inventory movement separately, so this is NOT derived from
      actuals; it defaults to 0.10 of incremental revenue (a conservative,
      disclosed placeholder) for every year.
    - dep_pct_sales: held flat at the latest actual depreciation/sales ratio.
    """
    latest = fin.pnl_years[-1]
    sales_latest = latest.sales

    _, ebit_latest = metrics._ebitda_ebit(fin, latest)
    ebit_margin = ebit_latest / sales_latest if sales_latest else 0.0

    sales_by_year = {p.year: p.sales for p in fin.pnl_years}
    years_sorted = sorted(sales_by_year)
    cagr_3yr = None
    if len(years_sorted) >= 4:
        y_now, y_then = years_sorted[-1], years_sorted[-4]
        s_now, s_then = sales_by_year[y_now], sales_by_year[y_then]
        if s_then and s_then > 0 and s_now > 0:
            cagr_3yr = (s_now / s_then) ** (1/3) - 1

    sgr = ret.get("sgr")
    g_reinvest = ret.get("g_from_reinvestment")
    candidates = [x for x in (sgr, g_reinvest) if x is not None]
    ceiling = min(candidates) if candidates else 0.0
    cagr_for_cap = cagr_3yr if cagr_3yr is not None else ceiling
    growth_capped = cagr_for_cap > ceiling
    start_growth = min(cagr_for_cap, ceiling)
    growth_path = _linear_fade(start_growth, terminal_growth, years)

    eff_tax_now = base["effective_tax_rate"] if base["effective_tax_rate"] is not None else Config.STATUTORY_TAX
    tax_path = _linear_fade(eff_tax_now, Config.STATUTORY_TAX, years)

    fcf_series = base["fcf_series"]
    capex_actual_pct_sales = (fcf_series[-1]["capex"] / sales_latest) if (fcf_series and sales_latest) else 0.0
    dep_pct_sales = (latest.depreciation / sales_latest) if sales_latest else 0.0
    raw_capex_path = _linear_fade(capex_actual_pct_sales, dep_pct_sales, years)
    capex_path = [max(v, dep_pct_sales) for v in raw_capex_path]
    capex_floor_bound = raw_capex_path != capex_path

    wc_change_pct = 0.10
    wc_source = (
        "Screener Data Sheet as parsed here does not expose receivables/inventory "
        "movement separately, so working-capital change cannot be defensibly derived "
        "from actuals; defaulted to 0.10 of incremental revenue for every year."
    )

    drivers = []
    for i in range(years):
        drivers.append({
            "revenue_growth": growth_path[i],
            "ebit_margin": ebit_margin,
            "tax_rate": tax_path[i],
            "capex_pct_sales": capex_path[i],
            "wc_change_pct": wc_change_pct,
            "dep_pct_sales": dep_pct_sales,
        })

    method = (
        f"Default 5-year drivers (disclosed assumptions, not reported figures): "
        f"revenue_growth fades from {start_growth:.4f} "
        f"(3yr sales CAGR {cagr_3yr:.4f} capped at ceiling min(SGR={sgr}, "
        f"g_from_reinvestment={g_reinvest})={ceiling:.4f}"
        f"{' -- cap bound' if growth_capped else ' -- cap did not bind'}) "
        f"to terminal_growth {terminal_growth:.4f} by year {years}. "
        f"ebit_margin held flat at the latest actual {ebit_margin:.4f}. "
        f"tax_rate fades from the current effective rate {eff_tax_now:.4f} to the "
        f"statutory rate {Config.STATUTORY_TAX:.4f} by year {years} (a concessional "
        "effective rate is not assumed to persist in perpetuity). "
        f"capex_pct_sales fades from the latest actual {capex_actual_pct_sales:.4f} "
        f"down to the latest depreciation/sales ratio {dep_pct_sales:.4f} as a "
        "steady-state floor by year "
        f"{years} (this is the key fix: a single build-out year is not projected "
        "flat forever)"
        f"{'; floor bound the fade in at least one year' if capex_floor_bound else ''}. "
        f"wc_change_pct: {wc_source} "
        f"dep_pct_sales held flat at the latest actual {dep_pct_sales:.4f}."
    )

    return {
        "drivers": drivers,
        "method": method,
        "growth_ceiling": ceiling,
        "growth_cagr_3yr": cagr_3yr,
        "growth_capped": growth_capped,
        "sgr": sgr, "g_from_reinvestment": g_reinvest,
        "ebit_margin": ebit_margin,
        "tax_rate_current": eff_tax_now,
        "tax_rate_statutory": Config.STATUTORY_TAX,
        "capex_actual_pct_sales": capex_actual_pct_sales,
        "capex_floor_dep_pct_sales": dep_pct_sales,
        "wc_change_pct": wc_change_pct,
        "wc_source": wc_source,
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
    terminal_capex_pct = overrides.get("terminal_capex_pct")

    # Informational single-year FCFF snapshot -- retained for disclosure and
    # for backward-compatible reporting (e.g. FCF/PAT conversion context),
    # but no longer used to gate DCF viability. A one-year snapshot,
    # compounded flat forever, is exactly what made a mid-build-out company
    # like Aurionpro look permanently cash-negative; the driver-based DCF
    # below fades capex to a steady state instead.
    fcff_info = _normalised_base_fcff(fin, base, ret)
    base_revenue = fin.pnl_years[-1].sales

    override_drivers = overrides.get("drivers")
    if override_drivers:
        drivers = override_drivers
        drivers_source = "llm_override"
        drivers_default_method = None
        driver_disclosure = {}
    else:
        driver_disclosure = default_drivers(fin, ret, base, years=5, terminal_growth=terminal_growth)
        drivers = driver_disclosure["drivers"]
        drivers_source = "default"
        drivers_default_method = driver_disclosure["method"]

    dcf_common = {
        "base_fcff": fcff_info["base_fcff"],
        "base_fcff_method": fcff_info["method"],
        "nopat": fcff_info["nopat"],
        "ebit": fcff_info["ebit"],
        "effective_tax_rate": fcff_info["effective_tax_rate"],
        "depreciation": fcff_info["depreciation"],
        "capex_3yr_avg": fcff_info["capex_3yr_avg"],
        "capex_years_used": fcff_info["capex_years_used"],
        "delta_wc": fcff_info["delta_wc"],
        "base_revenue": base_revenue,
        "drivers_source": drivers_source,
        "drivers_default_method": drivers_default_method,
        "sgr": ret.get("sgr"),
        "g_from_reinvestment": ret.get("g_from_reinvestment"),
        "wacc": w, "coe": coe, "beta": beta,
        "cost_of_debt_post_tax": cod_post_tax,
        "terminal_growth": terminal_growth,
        "terminal_capex_pct": terminal_capex_pct,
        "net_debt": net_debt, "shares": shares,
    }

    try:
        res = dcf_from_drivers(base_revenue, drivers, w, terminal_growth,
                               net_debt, shares, terminal_capex_pct=terminal_capex_pct)
        fv = res.get("fair_value_per_share")
        if fv is None or fv <= 0:
            dcf_pack = {
                "viable": False,
                "reason": (
                    f"Driver-based DCF (5-year explicit forecast with a fading capex "
                    f"path) still produces a non-positive fair value per share ({fv}). "
                    "This is not clamped to a fabricated positive number -- the DCF is "
                    "skipped and triangulation should lean on earnings-based methods "
                    "(P/E bands, EV/EBITDA, justified P/B) instead."
                ),
                **res, **dcf_common,
            }
        else:
            sens_waccs = [w - 0.02, w - 0.01, w, w + 0.01, w + 0.02]
            sens_gs = [max(terminal_growth - 0.02, -0.5), terminal_growth - 0.01,
                       terminal_growth, terminal_growth + 0.01, terminal_growth + 0.02]
            grid = sensitivity_grid_drivers(
                base_revenue, drivers, waccs=sens_waccs, gs=sens_gs,
                net_debt=net_debt, shares=shares, terminal_capex_pct=terminal_capex_pct,
            )
            # Store the axes with the grid; a heat map without labelled axes
            # cannot be read, and the report renders this as a matrix.
            dcf_pack = {
                "viable": True, **res,
                "sensitivity_grid": {"grid": grid, "waccs": sens_waccs, "gs": sens_gs},
                **dcf_common,
            }
    except ValueError as e:
        dcf_pack = {"viable": False, "reason": f"DCF inputs invalid: {e}", **dcf_common}

    if dcf_pack["viable"]:
        price_for_reverse = md.price or fin.current_price
        detail = implied_growth_from_drivers_detail(
            price_per_share=price_for_reverse, base_revenue=base_revenue, drivers=drivers,
            wacc=w, terminal_growth=terminal_growth, net_debt=net_debt, shares=shares,
            terminal_capex_pct=terminal_capex_pct,
        )
        reverse_dcf = {
            "available": True, **detail,
            "sgr": ret.get("sgr"), "g_from_reinvestment": ret.get("g_from_reinvestment"),
        }
    else:
        reverse_dcf = {
            "available": False,
            "reason": "DCF is not viable (see dcf.reason); implied growth cannot be "
                      "solved without a viable driver-based DCF to anchor the model on.",
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


def scenario_values(fin, pack, scenario_specs):
    """Run the DCF once per scenario so Python owns the scenario fair values.

    Each spec supplies driver overrides (and optionally its own terminal
    growth); the model states what changes, Python computes what that is worth.
    """
    from src.metrics_dcf import dcf_from_drivers

    dcf = pack.get("dcf") or {}
    assumptions = dcf.get("assumptions") or {}
    base_drivers = assumptions.get("drivers") or []
    out = []
    for spec in scenario_specs or []:
        overrides = spec.get("driver_overrides") or {}
        drivers = []
        for year_driver in base_drivers:
            merged = dict(year_driver)
            merged.update({k: v for k, v in overrides.items() if v is not None})
            drivers.append(merged)
        tg = spec.get("terminal_growth", dcf.get("terminal_growth"))
        value, note = None, ""
        if drivers and dcf.get("viable"):
            try:
                value = dcf_from_drivers(
                    dcf.get("base_revenue"), drivers, dcf.get("wacc"), tg,
                    dcf.get("net_debt"), dcf.get("shares"),
                    terminal_capex_pct=assumptions.get("terminal_capex_pct"),
                )["fair_value_per_share"]
            except (ValueError, ZeroDivisionError) as exc:
                note = f"not computable: {exc}"
        else:
            note = "no viable DCF to re-run for this scenario"
        out.append({"name": spec.get("name"), "value": value,
                    "prob": spec.get("prob"),
                    "assumptions": spec.get("assumptions", ""),
                    "driver_overrides": overrides,
                    "note": note})
    return out
