"""Render the valuation pack + narrative into a standalone HTML report.

Two rules drive this module:

* Chart.js is inlined, not linked, so the file opens offline from disk.
* Every computed figure is rendered here from the pack, independently of what
  the model wrote. If the narrative is thin, the numbers are still all present
  and correctly labelled -- prose can never be the only carrier of a figure.
"""

import html
import json
import pathlib

from jinja2 import Template

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_TEMPLATE = _ROOT / "templates" / "report.html.j2"
_CHARTJS = _ROOT / "static" / "chartjs.min.js"

SECTION_TITLES = [
    "Valuation Snapshot", "Valuation Base", "Relative Valuation",
    "Historical Bands", "Intrinsic Valuation", "Reverse DCF",
    "Triangulation", "Scenario Analysis", "Recommendation",
    "Risks to the Valuation", "Conclusion",
]

SECTOR_LABELS = {
    "non-financial": "Non-financial — DCF primary",
    "bank-nbfc": "Bank / NBFC — justified P/B primary",
    "amc": "Asset manager — P/E and P/AUM primary",
    "conglomerate": "Conglomerate — sum-of-the-parts primary",
}

UNAVAILABLE = '<span class="assumption">not available — see note</span>'


# --------------------------------------------------------------------------
# formatting helpers.  Every one returns the disclosure string when the value
# is missing, so a None can never silently render as a blank cell.
# --------------------------------------------------------------------------

def rs(v, dp=2):
    if v is None:
        return UNAVAILABLE
    return f"₹{v:,.{dp}f}"


def num(v, dp=2, suffix=""):
    if v is None:
        return UNAVAILABLE
    return f"{v:,.{dp}f}{suffix}"


def pct(v, dp=1):
    if v is None:
        return UNAVAILABLE
    return f"{v * 100:,.{dp}f}%"


def mult(v, dp=2):
    if v is None:
        return UNAVAILABLE
    return f"{v:,.{dp}f}x"


def note(text, formula):
    """A figure label carrying its formula in the title attribute (hover)."""
    return f'<span class="f-note" title="{html.escape(formula)}">{text}</span>'


def _rows(pairs):
    return "".join(f"<tr><td>{k}</td><td>{v}</td></tr>" for k, v in pairs)


def _table(caption, head, body, foot="", cls=""):
    cls = f' class="{cls}"' if cls else ""
    foot = f"<tfoot>{foot}</tfoot>" if foot else ""
    return (f'<div class="tbl-wrap"><table{cls}><caption>{caption}</caption>'
            f"<thead>{head}</thead><tbody>{body}</tbody>{foot}</table></div>")


def _callout(tag, text, warn=False):
    cls = "callout warn" if warn else "callout"
    return f'<div class="{cls}"><span class="tag">{tag}</span>{text}</div>'


def _signal(value, cheap, rich):
    """Colour a multiple green/amber/red against cheap and rich thresholds."""
    if value is None:
        return UNAVAILABLE
    if value <= cheap:
        return f'<span class="sig-under">{mult(value)}</span>'
    if value >= rich:
        return f'<span class="sig-over">{mult(value)}</span>'
    return f'<span class="sig-fair">{mult(value)}</span>'


def _heat_colour(v, lo, hi, price):
    """Green where the modelled value exceeds price, red where it falls short."""
    if v is None:
        return "#efe9dd", "#4a5058"
    if price and price > 0:
        ratio = max(-1.0, min(1.0, (v / price - 1.0)))
    else:
        span = (hi - lo) or 1.0
        ratio = ((v - lo) / span) * 2 - 1
    if ratio >= 0:
        a = 0.10 + 0.62 * ratio
        return f"rgba(28,107,69,{a:.2f})", "#0d2b1c" if ratio < 0.5 else "#f7f4ee"
    a = 0.10 + 0.62 * (-ratio)
    return f"rgba(155,44,34,{a:.2f})", "#3a0f0b" if -ratio < 0.5 else "#f7f4ee"


# --------------------------------------------------------------------------
# per-section computed blocks
# --------------------------------------------------------------------------

def _s1_snapshot(pack):
    m, rel, ret = pack["meta"], pack["relative"], pack["returns"]
    body = _rows([
        ("Sector basis", SECTOR_LABELS.get(m.get("sector"), m.get("sector", "—"))),
        ("Current price", rs(m.get("current_price"))),
        ("Market capitalisation", f'{rs(m.get("market_cap"), 0)} Cr'),
        ("Enterprise value", f'{rs(rel.get("enterprise_value"), 0)} Cr'),
        (note("Trailing P/E", "Price ÷ EPS (latest FY)"), mult(rel.get("pe_current"))),
        (note("Return on equity", "PAT ÷ average shareholders' equity"), pct(ret.get("roe"))),
        (note("Return on invested capital", "EBIT×(1−tax) ÷ (equity + borrowings)"), pct(ret.get("roic"))),
    ])
    return _table("Key reference figures", "<tr><th>Item</th><th>Value</th></tr>", body)


def _s2_base(pack):
    b = pack["base"]
    body = _rows([
        (f'Reported PAT (FY{b.get("latest_fy")})', f'{rs(b.get("reported_pat_latest"), 2)} Cr'),
        (note("EPS — latest FY", "PAT ÷ diluted shares"), rs(b.get("eps_latest_fy"))),
        (note("EPS — TTM", "Sum of last four quarterly PAT ÷ diluted shares"), rs(b.get("eps_ttm"))),
        (note("Book value per share", "(Equity capital + reserves) ÷ diluted shares"), rs(b.get("bvps"))),
        (note("Net debt per share", "(Borrowings − cash) ÷ diluted shares"), rs(b.get("net_debt_per_share"))),
        ("Net cash position", f'{rs(b.get("net_cash"), 2)} Cr'),
        ("Diluted share count", num(b.get("diluted_shares_cr"), 2, " Cr")),
        (note("Effective tax rate", "Tax ÷ PBT, latest FY"), pct(b.get("effective_tax_rate"))),
        (note("FCF / PAT conversion", "Σ FCF (5 yr) ÷ Σ PAT (5 yr)"), pct(b.get("fcf_pat_conversion"))),
    ])
    out = _table("Valuation base — the inputs everything rests on",
                 "<tr><th>Item</th><th>Value</th></tr>", body)

    fcf = b.get("fcf_series") or []
    if fcf:
        rows = "".join(
            f'<tr><td>FY{r.get("year")}</td><td>{num(r.get("capex"), 2)}</td>'
            f'<td>{num(r.get("fcf"), 2)}</td></tr>' for r in fcf)
        out += _table("Free cash flow — last five fiscal years (₹ Cr)",
                      "<tr><th>Year</th><th>Capex (estimated)</th><th>FCF</th></tr>", rows)
        out += '<div class="chartbox"><canvas id="fcfChart" height="110"></canvas></div>'
        method = fcf[-1].get("method")
        if method:
            out += _callout("Capex is an estimate, not a reported figure", html.escape(str(method)))

    tax = b.get("effective_tax_rate")
    if tax is not None and tax < 0.22:
        out += _callout(
            "Tax rate caveat",
            f"The effective tax rate of {pct(tax)} sits well below the 25.17% statutory rate. "
            "The forecast fades it toward statutory rather than assuming the concession persists.",
            warn=True)
    return out


def _s3_relative(pack):
    rel, ret = pack["relative"], pack["returns"]
    bands = pack["bands"]
    body = _rows([
        (note("P/E (trailing)", "Price ÷ EPS"), _signal(rel.get("pe_current"), 15, 30)),
        (note("P/B", "Price ÷ book value per share"), _signal(rel.get("pb_current"), 2, 5)),
        (note("EV/EBITDA", "EV ÷ (EBIT + depreciation)"), _signal(rel.get("ev_ebitda_current"), 10, 20)),
        (note("EV/EBIT", "EV ÷ (PBT + interest − other income)"), _signal(rel.get("ev_ebit_current"), 12, 24)),
        (note("EV/Sales", "EV ÷ revenue"), mult(rel.get("ev_sales_current"))),
        (note("P/Sales", "Market cap ÷ revenue"), mult(rel.get("p_sales_current"))),
        (note("Dividend yield", "Dividend ÷ market cap"), pct(rel.get("dividend_yield"), 2)),
        (note("FCF yield", "Free cash flow ÷ market cap"), pct(rel.get("fcf_yield"), 2)),
    ])
    out = _table("Current multiples", "<tr><th>Multiple</th><th>Current</th></tr>", body)

    hist = _rows([
        ("Current P/E", mult(bands.get("current_pe"))),
        ("Own 5-year median P/E", mult(bands.get("median_pe_5y"))),
        ("Own 10-year median P/E", mult(bands.get("median_pe_10y"))),
        (note("Position vs 10-yr median", "(current − median) ÷ standard deviation"),
         num(bands.get("current_z"), 2, " SD")),
    ])
    out += _table("Against its own history",
                  "<tr><th>Reference</th><th>Value</th></tr>", hist)
    out += '<div class="chartbox"><canvas id="peerChart" height="110"></canvas></div>'
    out += _callout(
        "Peer set",
        "No peer multiples were supplied with this run. The chart above compares the "
        "company against its own historical medians only. Supply peer tickers in the form "
        "to populate a true peer comparison — the methodology asks for three to five "
        "genuine comparables of broadly similar size and business model.")
    return out


def _s4_bands(pack):
    b = pack["bands"]
    years = b.get("pe_years") or []
    hist = b.get("pe_history") or []
    rows = "".join(f"<tr><td>FY{y}</td><td>{mult(v)}</td></tr>"
                   for y, v in zip(years, hist))
    out = _table("Yearly P/E used for the band (loss-making years excluded)",
                 "<tr><th>Year</th><th>P/E</th></tr>", rows)
    summary = _rows([
        ("10-year median", mult(b.get("median_pe_10y"))),
        ("5-year median", mult(b.get("median_pe_5y"))),
        ("Standard deviation", num(b.get("sd_pe"), 2)),
        ("+1 SD band", mult(b.get("upper_band"))),
        ("−1 SD band", mult(b.get("lower_band_display"))),
        ("Current", mult(b.get("current_pe"))),
        ("Current position", num(b.get("current_z"), 2, " SD from median")),
    ])
    out += _table("Band summary", "<tr><th>Statistic</th><th>Value</th></tr>", summary)
    out += '<div class="chartbox"><canvas id="bandChart" height="130"></canvas></div>'
    if b.get("band_skewed"):
        raw = b.get("lower_band")
        out += _callout(
            "This band is a weak anchor",
            f"The −1 SD band computes to {num(raw, 2)}, i.e. below zero, because the P/E series is "
            "strongly right-skewed by a re-rating. A negative P/E floor is meaningless, so it is "
            "displayed clipped at zero. Treat mean-reversion to this band with caution: the "
            "distribution is not symmetric and the older years describe a differently-valued company.",
            warn=True)
    return out


def _s5_intrinsic(pack):
    d = pack["dcf"]
    if not d.get("viable", False):
        return _callout(
            "A DCF could not be anchored on current cash flows",
            html.escape(str(d.get("reason", "Normalised free cash flow was not positive."))) +
            " No fabricated substitute has been inserted. The triangulation therefore leans on "
            "earnings- and asset-based methods, and the weights in Section 7 reflect that.",
            warn=True)

    a = d.get("assumptions", {})
    drivers = a.get("drivers") or []
    head = ("<tr><th>Year</th><th>Revenue growth</th><th>EBIT margin</th><th>Tax rate</th>"
            "<th>Capex % sales</th><th>ΔWC % of Δrevenue</th></tr>")
    rows = "".join(
        f"<tr><td>Year {i}</td><td>{pct(dr.get('revenue_growth'))}</td>"
        f"<td>{pct(dr.get('ebit_margin'))}</td><td>{pct(dr.get('tax_rate'))}</td>"
        f"<td>{pct(dr.get('capex_pct_sales'))}</td><td>{pct(dr.get('wc_change_pct'))}</td></tr>"
        for i, dr in enumerate(drivers, 1))
    out = _table("Forecast drivers — stated assumptions, not reported figures", head, rows)

    proj = d.get("projection") or []
    phead = ("<tr><th>Year</th><th>Revenue</th><th>EBIT</th><th>NOPAT</th><th>D&amp;A</th>"
             "<th>Capex</th><th>ΔWC</th><th>FCFF</th><th>PV</th></tr>")
    prows = "".join(
        f"<tr><td>Year {i}</td><td>{num(r.get('revenue'), 0)}</td><td>{num(r.get('ebit'), 0)}</td>"
        f"<td>{num(r.get('nopat'), 0)}</td><td>{num(r.get('d_and_a'), 0)}</td>"
        f"<td>{num(r.get('capex'), 0)}</td><td>{num(r.get('delta_wc'), 0)}</td>"
        f"<td>{num(r.get('fcff'), 1)}</td><td>{num(r.get('pv'), 1)}</td></tr>"
        for i, r in enumerate(proj, 1))
    out += _table("Explicit forecast period (₹ Crore)", phead, prows)

    disc = _rows([
        (note("Risk-free rate + β × ERP = cost of equity", "CAPM: rf + β × equity risk premium"),
         pct(d.get("coe"))),
        ("Beta used", num(d.get("beta"), 2)),
        (note("Post-tax cost of debt", "Assumed pre-tax cost × (1 − effective tax rate)"),
         pct(d.get("cost_of_debt_post_tax"))),
        (note("WACC", "Equity and debt weighted at market values"), pct(d.get("wacc"))),
        ("Terminal growth", pct(d.get("terminal_growth"))),
        ("Terminal capex basis", str(a.get("terminal_capex_basis", "—"))),
        (note("PV of explicit period", "Σ discounted FCFF, years 1–5"), f'{rs(d.get("pv_explicit"), 0)} Cr'),
        (note("PV of terminal value", "Terminal FCFF ÷ (WACC − g), discounted"), f'{rs(d.get("pv_terminal"), 0)} Cr'),
        ("Enterprise value", f'{rs(d.get("enterprise_value"), 0)} Cr'),
        (note("Less net debt", "Borrowings − cash; negative means net cash added"), f'{rs(d.get("net_debt"), 0)} Cr'),
        ("Equity value", f'{rs(d.get("equity_value"), 0)} Cr'),
    ])
    foot = (f'<tr><td>Fair value per share</td><td><u>{rs(d.get("fair_value_per_share"))}</u></td></tr>')
    out += _table("Discount rate and value bridge",
                  "<tr><th>Item</th><th>Value</th></tr>", disc, foot)

    tv = d.get("terminal_value_pct")
    if d.get("terminal_over_70pct"):
        out += _callout(
            "Terminal value dominates this valuation",
            f"{pct(tv)} of enterprise value sits in the terminal value, above the 70% threshold. "
            "This valuation is therefore largely an assumption about the far future rather than "
            "an analysis of the near one. Weight it accordingly.", warn=True)

    grid = d.get("sensitivity_grid") or {}
    cells, waccs, gs = grid.get("grid"), grid.get("waccs"), grid.get("gs")
    if cells and waccs and gs:
        flat = [v for row in cells for v in row if v is not None]
        lo, hi = (min(flat), max(flat)) if flat else (0, 1)
        price = pack["meta"].get("current_price")
        head = "<tr><th>WACC ＼ g</th>" + "".join(f"<th>{pct(g)}</th>" for g in gs) + "</tr>"
        body = ""
        for w, row in zip(waccs, cells):
            body += f"<tr><th>{pct(w)}</th>"
            for v in row:
                bg, fg = _heat_colour(v, lo, hi, price)
                shown = num(v, 0) if v is not None else "—"
                body += f'<td style="background:{bg};color:{fg}">{shown}</td>'
            body += "</tr>"
        out += _table("Sensitivity — fair value per share (₹). Green above current price, red below.",
                      head, body, cls="heat")
    return out


def _s6_reverse(pack):
    r = pack.get("reverse_dcf", {})
    ret = pack["returns"]
    if not r.get("available", False):
        return _callout(
            "Reverse DCF unavailable",
            html.escape(str(r.get("reason", "The forward model could not be anchored."))) +
            " No implied growth rate has been invented in its place.", warn=True)

    implied = r.get("growth")
    sgr, groic = ret.get("sgr"), ret.get("g_from_reinvestment")
    body = _rows([
        (note("Growth the market is implying", "Solved so modelled value = current price"),
         f"<b>{pct(implied)}</b>"),
        (note("Sustainable growth rate ceiling", "ROE × (1 − payout ratio)"), pct(sgr)),
        (note("Reinvestment × ROIC ceiling", "(1 − payout) × ROIC"), pct(groic)),
    ])
    out = _table("What the market is already paying for",
                 "<tr><th>Measure</th><th>Rate</th></tr>", body)

    if implied is not None and sgr is not None and groic is not None:
        ceiling = min(sgr, groic)
        if implied > ceiling:
            gap = implied - ceiling
            out += _callout(
                "The implied expectation exceeds what the company can self-fund",
                f"The market is implying {pct(implied)} growth against a binding ceiling of "
                f"{pct(ceiling)} — a gap of {pct(gap)}. Growth above that ceiling cannot be funded "
                "from retained earnings at current returns on capital, so delivering it requires "
                "either external capital (diluting existing holders), a step-up in ROIC, or a lower "
                "payout. On the company's present economics this is a demanding assumption.",
                warn=True)
        else:
            out += _callout(
                "The implied expectation sits within the self-funding ceiling",
                f"The market is implying {pct(implied)} growth against a ceiling of {pct(ceiling)}. "
                "The market is not paying up for growth that must be financed externally.")
    if r.get("out_of_bounds"):
        out += _callout(
            "Solver hit a bound",
            f"The implied growth lies outside the search range and was reported at the "
            f"{r.get('bound_hit')} bound. Read it as 'at least/at most' rather than a point estimate.",
            warn=True)
    return out


def _s7_triangulation(result):
    tri = result.get("triangulation") or {}
    methods = tri.get("methods") or []
    if not methods:
        return _callout("No triangulation supplied", "The analysis pass returned no method weights.")
    tw = tri.get("total_weight") or 1
    rows = "".join(
        f'<tr><td>{html.escape(str(m.get("name")))}</td><td>{rs(m.get("value"))}</td>'
        f'<td>{pct((m.get("weight") or 0) / tw)}</td>'
        f'<td>{rs((m.get("value") or 0) * (m.get("weight") or 0) / tw)}</td>'
        f'<td style="text-align:left">{html.escape(str(m.get("rationale") or m.get("basis") or ""))}</td></tr>'
        for m in methods)
    foot = (f'<tr><td>Blended fair value</td><td colspan="2"></td>'
            f'<td><u>{rs(tri.get("blended"))}</u></td><td></td></tr>')
    out = _table("Fair value triangulation — values computed here, weights chosen by the analysis pass",
                 "<tr><th>Method</th><th>Fair value</th><th>Weight</th><th>Contribution</th>"
                 "<th>Rationale for weight</th></tr>",
                 rows, foot)
    out += '<div class="chartbox"><canvas id="triChart" height="120"></canvas></div>'
    lo, hi = tri.get("low"), tri.get("high")
    if lo is not None and hi is not None:
        out += _callout(
            "Honest uncertainty band",
            f"Method outputs span {rs(lo)} to {rs(hi)}. That range, not the blended point estimate, "
            "is the real statement of confidence — position sizing should reflect its width.")
    dropped = tri.get("dropped")
    if dropped:
        out += _callout("Methods excluded",
                        "Dropped for want of a computable value: " +
                        html.escape(", ".join(str(d) for d in dropped)) +
                        ". Weights were renormalised over the remainder.")
    return out


def _s8_scenarios(result, pack):
    sc = result.get("scenario") or {}
    rows_data = sc.get("scenarios") or []
    if not rows_data:
        return _callout("No scenarios supplied", "The analysis pass returned no scenario set.")
    rows = "".join(
        f'<tr><td>{html.escape(str(s.get("name")))}</td>'
        f'<td style="text-align:left">{html.escape(str(s.get("assumptions") or ""))}</td>'
        f'<td>{rs(s.get("value"))}</td>'
        f'<td>{pct(s.get("move_pct"))}</td><td>{pct(s.get("prob"), 0)}</td></tr>'
        for s in rows_data)
    ev = sc.get("expected_value")
    foot = (f'<tr><td>Probability-weighted expected value</td><td></td><td><u>{rs(ev)}</u></td>'
            f'<td>{pct(sc.get("upside_pct"))}</td><td>100%</td></tr>')
    out = _table("Scenario analysis — each scenario re-run through the same DCF engine",
                 "<tr><th>Scenario</th><th>Key assumptions</th><th>Fair value</th>"
                 "<th>Move vs price</th><th>Probability</th></tr>",
                 rows, foot)
    out += '<div class="chartbox"><canvas id="scenChart" height="120"></canvas></div>'
    if sc.get("prob_sum_ok") is False:
        out += _callout("Probabilities do not sum to 100%",
                        f'They sum to {pct(sc.get("prob_sum"), 0)}. The expected value above is '
                        "computed on the stated probabilities as given.", warn=True)
    price = pack["meta"].get("current_price")
    if ev is not None and price:
        bear = min((s.get("value") or 0) for s in rows_data)
        downside = bear / price - 1
        upside = ev / price - 1
        out += _callout(
            "Payoff shape",
            f"Expected value implies {pct(upside)} against the current price, with the bear case at "
            f"{pct(downside)}. An asymmetric payoff matters more than a high base-case target.")
    return out


def _s9_recommendation(result, pack):
    price = pack["meta"].get("current_price")
    fv, tp = result.get("fair_value"), result.get("target_price")
    body = _rows([
        ("Rating", f'<b>{html.escape(str(result.get("rating") or "—"))}</b>'),
        ("Fair value", f"<u>{rs(fv)}</u>" if fv is not None else UNAVAILABLE),
        ("Target price", f"<u>{rs(tp)}</u>" if tp is not None else UNAVAILABLE),
        ("Current price", rs(price)),
        (note("Implied move to target", "(target ÷ price) − 1"),
         pct(tp / price - 1) if (tp and price) else UNAVAILABLE),
        ("Conviction", html.escape(str(result.get("conviction") or "—"))),
    ])
    return _table("Recommendation summary", "<tr><th>Item</th><th>Value</th></tr>", body)


def _s10_risks(pack):
    d = pack["dcf"]
    if not d.get("viable"):
        return ""
    grid = d.get("sensitivity_grid") or {}
    cells, waccs = grid.get("grid"), grid.get("waccs")
    if not cells or not waccs:
        return ""
    flat = [v for row in cells for v in row if v is not None]
    if not flat:
        return ""
    return _callout(
        "Quantified sensitivity",
        f"Across the WACC and terminal-growth grid the fair value ranges from {rs(min(flat), 0)} to "
        f"{rs(max(flat), 0)} per share. The discount rate and the terminal growth assumption are "
        "therefore the two largest single sources of valuation error, ahead of any operating "
        "assumption in the explicit forecast.")


def build_computed_sections(result):
    pack = result["pack"]
    return {
        1: _s1_snapshot(pack),
        2: _s2_base(pack),
        3: _s3_relative(pack),
        4: _s4_bands(pack),
        5: _s5_intrinsic(pack),
        6: _s6_reverse(pack),
        7: _s7_triangulation(result),
        8: _s8_scenarios(result, pack),
        9: _s9_recommendation(result, pack),
        10: _s10_risks(pack),
        11: "",
    }


def build_chart_data(result):
    pack = result["pack"]
    price = pack["meta"].get("current_price")
    bands = pack["bands"]
    years = bands.get("pe_years") or []
    hist = bands.get("pe_history") or []
    n = len(hist)

    def flat(v):
        return [v] * n if (v is not None and n) else []

    band = {
        "labels": [f"FY{y}" for y in years],
        "pe": hist,
        "median": flat(bands.get("median_pe_10y")),
        "up": flat(bands.get("upper_band")),
        "dn": flat(bands.get("lower_band_display")),
        "current": flat(bands.get("current_pe")),
    }

    scen_rows = (result.get("scenario") or {}).get("scenarios") or []
    scen = {
        "labels": [s.get("name") for s in scen_rows],
        "values": [s.get("value") for s in scen_rows],
        "current": [price] * len(scen_rows),
    }

    tri_methods = (result.get("triangulation") or {}).get("methods") or []
    blended = (result.get("triangulation") or {}).get("blended")
    tri = {
        "labels": [m.get("name") for m in tri_methods],
        "values": [m.get("value") for m in tri_methods],
        "blended": [blended] * len(tri_methods),
        "current": [price] * len(tri_methods),
    }

    rel = pack["relative"]
    peer_labels = ["Current", "5-yr median", "10-yr median"]
    peer_values = [rel.get("pe_current"), bands.get("median_pe_5y"), bands.get("median_pe_10y")]
    peer = {
        "labels": peer_labels, "values": peer_values, "metric": "P/E (x)",
        "colors": ["rgba(122,31,26,.8)", "rgba(18,40,63,.6)", "rgba(18,40,63,.4)"],
    }

    fcf_rows = pack["base"].get("fcf_series") or []
    fcf = {"labels": [f'FY{r.get("year")}' for r in fcf_rows],
           "values": [r.get("fcf") for r in fcf_rows]}

    return {"band": band, "scen": scen, "tri": tri, "peer": peer, "fcf": fcf}


def _sig_colour(rating):
    r = (rating or "").upper()
    if "SELL" in r:
        return "#9b2c22"
    if "BUY" in r:
        return "#1c6b45"
    return "#a9741a"


def render_report(result, out_path):
    template = Template(_TEMPLATE.read_text(encoding="utf-8"))
    chartjs = _CHARTJS.read_text(encoding="utf-8")

    pack = result["pack"]
    meta = pack["meta"]
    price = meta.get("current_price")
    target = result.get("target_price")
    upside = (target / price - 1) if (target and price) else 0.0

    lo, hi = meta.get("low_52w"), meta.get("high_52w")
    range_52w = f"₹{lo:,.0f} – ₹{hi:,.0f}" if (lo and hi) else "not available"

    narrative = result.get("narrative") or {}
    sections = {i: narrative.get(str(i), narrative.get(i, "")) for i in range(1, 12)}

    html_out = template.render(
        company=meta.get("company", "—"),
        sector_label=SECTOR_LABELS.get(meta.get("sector"), meta.get("sector", "")),
        price=f"{price:,.2f}" if price else "—",
        mcap=f'{meta.get("market_cap"):,.0f}' if meta.get("market_cap") else "—",
        range_52w=range_52w,
        latest_fy=meta.get("latest_fy", "—"),
        as_of=meta.get("as_of") or "date not stated by source",
        price_source=meta.get("current_price_source", "supplied data"),
        rating=result.get("rating") or "—",
        conviction=result.get("conviction") or "—",
        fair_value=f'{result.get("fair_value"):,.0f}' if result.get("fair_value") else "—",
        target_price=f"{target:,.0f}" if target else "—",
        blended_fv=f'{(result.get("triangulation") or {}).get("blended"):,.0f}'
                   if (result.get("triangulation") or {}).get("blended") else "—",
        upside_pct=upside,
        upside_str=f"{upside * 100:+.1f}%" if target and price else "—",
        sig_color=_sig_colour(result.get("rating")),
        section_titles=SECTION_TITLES,
        sections=sections,
        computed=build_computed_sections(result),
        chartjs_inline=chartjs,
        chart_data=json.dumps(build_chart_data(result), default=str),
    )
    out = pathlib.Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_out, encoding="utf-8")
    return str(out)
