"""End-to-end run with a stub model: no API key, no network, real spreadsheet.

Guards the whole pipeline shape, and asserts the two properties that matter
most for trustworthiness: the report opens offline, and it never presents a
model-authored number as if it were computed.
"""

import os

from src.screener_parser import parse_screener
from src.web_data import MarketData
from src.analyst import run_analysis
from src.report import render_report

DRIVERS = [
    {"revenue_growth": 0.15, "ebit_margin": 0.172, "tax_rate": 0.19,
     "capex_pct_sales": 0.115, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.13, "ebit_margin": 0.172, "tax_rate": 0.21,
     "capex_pct_sales": 0.095, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.11, "ebit_margin": 0.170, "tax_rate": 0.23,
     "capex_pct_sales": 0.075, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.09, "ebit_margin": 0.170, "tax_rate": 0.2517,
     "capex_pct_sales": 0.055, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.07, "ebit_margin": 0.168, "tax_rate": 0.2517,
     "capex_pct_sales": 0.035, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
]


class StubClient:
    def __init__(self):
        self.n = 0

    def complete_json(self, system, user):
        self.n += 1
        if self.n == 1:
            return {
                "drivers": DRIVERS, "terminal_growth": 0.05,
                "scenarios": [{"name": "Bear", "value": 430, "prob": 0.30},
                              {"name": "Base", "value": 620, "prob": 0.50},
                              {"name": "Bull", "value": 880, "prob": 0.20}],
                "triangulation": [{"name": "DCF", "value": 560, "weight": 0.45},
                                  {"name": "P/E band", "value": 690, "weight": 0.35},
                                  {"name": "EV/EBITDA", "value": 640, "weight": 0.20}],
                "model_choice": "DCF",
                "rationale": {"drivers": "capex intensity normalises as the build-out completes"},
            }
        return {
            "sections": {str(i): f"<p>Narrative for section {i}.</p>" for i in range(1, 12)},
            "rating": "HOLD", "fair_value": 620, "target_price": 650,
            "conviction": "Medium",
        }


def test_end_to_end_produces_report(tmp_path):
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1650.0, beta=0.9, as_of="2026-07-27",
                    source={k: "manual" for k in
                            ("price", "market_cap", "low_52w", "high_52w", "beta")})
    result = run_analysis(fin, md, "non-financial", "", StubClient(), 0.069, 0.055)

    out = os.path.join(tmp_path, "Aurionpro_Solutions_Valuation.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()

    assert os.path.getsize(out) > 200_000, "Chart.js should be inlined"
    assert "AURIONPRO" in html and "HOLD" in html
    assert html.count('class="tab-btn') == 11
    assert "Not investment advice" in html

    # Opens offline: nothing may be *loaded* from the network. URLs inside the
    # bundled Chart.js licence banner are inert text, so match on the loading
    # constructs rather than on the substring "http".
    lowered = html.lower()
    for external in ('src="http', "src='http", 'src="//', "@import",
                     '<link', 'href="http', "url(http"):
        assert external not in lowered, f"external resource load found: {external}"


def test_pipeline_recomputes_rather_than_trusting_the_model(tmp_path):
    """The stub proposes a 15% first-year growth; the DCF must reflect it."""
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    beta=0.9, source={})
    result = run_analysis(fin, md, "non-financial", "", StubClient(), 0.069, 0.055)

    dcf = result["pack"]["dcf"]
    assert dcf["viable"] is True
    assert dcf["drivers_source"] == "llm_override"
    # revenue in year 1 = latest revenue grown at the model's 15%
    assert abs(dcf["projection"][0]["revenue"] - 1411.09 * 1.15) < 1.0
    # the DCF fair value is Python's, not the model's claimed 620
    assert dcf["fair_value_per_share"] != result["fair_value"]


def test_report_survives_a_model_that_returns_nothing_useful(tmp_path):
    """A degenerate model response must not produce a blank or broken report."""
    class EmptyClient:
        def complete_json(self, system, user):
            return {}

    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    beta=0.9, source={})
    result = run_analysis(fin, md, "non-financial", "", EmptyClient(), 0.069, 0.055)
    out = os.path.join(tmp_path, "empty.html")
    render_report(result, out)
    html = open(out, encoding="utf-8").read()

    assert html.count('class="tab-btn') == 11
    assert "Book value per share" in html      # computed figures still present
    assert "Not investment advice" in html
