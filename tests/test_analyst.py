from src.screener_parser import parse_screener
from src.web_data import MarketData
from src.analyst import run_analysis

DRIVERS = [
    {"revenue_growth": 0.14, "ebit_margin": 0.172, "tax_rate": 0.20,
     "capex_pct_sales": 0.11, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.12, "ebit_margin": 0.172, "tax_rate": 0.22,
     "capex_pct_sales": 0.09, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.10, "ebit_margin": 0.172, "tax_rate": 0.24,
     "capex_pct_sales": 0.07, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.08, "ebit_margin": 0.172, "tax_rate": 0.2517,
     "capex_pct_sales": 0.05, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
    {"revenue_growth": 0.06, "ebit_margin": 0.172, "tax_rate": 0.2517,
     "capex_pct_sales": 0.035, "wc_change_pct": 0.10, "dep_pct_sales": 0.028},
]


class FakeClient:
    """Stands in for Claude/DeepSeek: pass 1 returns assumptions, pass 2 prose."""

    def __init__(self):
        self.calls = 0
        self.seen_user = []

    def complete_json(self, system, user):
        self.calls += 1
        self.seen_user.append(user)
        if self.calls == 1:
            return {"drivers": DRIVERS, "terminal_growth": 0.05,
                    "scenarios": [{"name": "Bear", "value": 400, "prob": 0.30},
                                  {"name": "Base", "value": 600, "prob": 0.50},
                                  {"name": "Bull", "value": 900, "prob": 0.20}],
                    "triangulation": [{"name": "DCF", "value": 520, "weight": 0.5},
                                      {"name": "Relative", "value": 700, "weight": 0.5}],
                    "model_choice": "DCF",
                    "rationale": {"drivers": "capex normalises as build-out completes"}}
        return {"sections": {str(i): f"<p>Section {i}.</p>" for i in range(1, 12)},
                "rating": "HOLD", "fair_value": 610, "target_price": 640,
                "conviction": "Medium"}


def _fin_md():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    return fin, md


def test_run_analysis_two_pass():
    fin, md = _fin_md()
    client = FakeClient()
    result = run_analysis(fin, md, sector="non-financial", pdf_context="",
                          client=client, rf=0.069, erp=0.055)
    assert client.calls == 2, "must make an assumptions pass and a narrative pass"
    assert result["rating"] == "HOLD"
    assert result["triangulation"]["blended"] > 0
    assert result["scenario"]["expected_value"] > 0
    assert "pack" in result and "narrative" in result
    assert len(result["narrative"]) == 11


def test_llm_drivers_are_actually_used_in_recomputed_pack():
    """The LLM proposes drivers; Python recomputes the DCF from them."""
    fin, md = _fin_md()
    result = run_analysis(fin, md, "non-financial", "", FakeClient(), 0.069, 0.055)
    used = result["pack"]["dcf"]["assumptions"]["drivers"]
    assert used[0]["revenue_growth"] == 0.14
    assert result["pack"]["dcf"]["drivers_source"] == "llm_override"


def test_narrative_pass_receives_final_numbers():
    """Prose must be written against recomputed figures, not the first-pass ones."""
    fin, md = _fin_md()
    client = FakeClient()
    run_analysis(fin, md, "non-financial", "", client, 0.069, 0.055)
    second_prompt = client.seen_user[1]
    assert "FINAL NUMBERS" in second_prompt
    assert "triangulation" in second_prompt.lower()
