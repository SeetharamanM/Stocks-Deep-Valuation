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
    """Stands in for Claude/DeepSeek.

    Pass 1 returns assumptions. The narrative then arrives in batches, so the
    fake honours whichever sections the prompt asks for -- a fake that always
    returned all eleven would hide a batching bug.
    """

    def __init__(self):
        self.calls = 0
        self.seen_user = []
        self.seen_system = []

    @staticmethod
    def _requested(system):
        marker = "writing ONLY these sections in this pass:"
        line = system.split(marker, 1)[1].splitlines()[0]
        return [s.strip() for s in line.split(",") if s.strip()]

    def complete_json(self, system, user):
        self.calls += 1
        self.seen_user.append(user)
        self.seen_system.append(system)
        if self.calls == 1:
            return {"drivers": DRIVERS, "terminal_growth": 0.05,
                    "scenarios": [{"name": "Bear", "value": 400, "prob": 0.30},
                                  {"name": "Base", "value": 600, "prob": 0.50},
                                  {"name": "Bull", "value": 900, "prob": 0.20}],
                    "triangulation": [{"name": "DCF", "value": 520, "weight": 0.5},
                                      {"name": "Relative", "value": 700, "weight": 0.5}],
                    "model_choice": "DCF",
                    "rationale": {"drivers": "capex normalises as build-out completes"}}
        wanted = self._requested(system)
        reply = {"sections": {s: f"<p>Section {s}.</p>" for s in wanted}}
        if "11" in wanted:
            reply.update({"rating": "HOLD", "fair_value": 610,
                          "target_price": 640, "conviction": "Medium"})
        return reply


def _fin_md():
    fin = parse_screener("Aurionpro Sol.xlsx")
    md = MarketData(ticker="AURIONPRO", price=735.4, market_cap=4076.37,
                    low_52w=500.0, high_52w=1600.0, beta=0.9, source={})
    return fin, md


def test_run_analysis_two_pass():
    from src.prompts import NARRATIVE_BATCHES
    fin, md = _fin_md()
    client = FakeClient()
    result = run_analysis(fin, md, sector="non-financial", pdf_context="",
                          client=client, rf=0.069, erp=0.055)
    assert client.calls == 1 + len(NARRATIVE_BATCHES), \
        "one assumptions pass plus one call per narrative batch"
    assert result["rating"] == "HOLD"
    assert result["triangulation"]["blended"] > 0
    assert result["scenario"]["expected_value"] > 0
    assert "pack" in result and "narrative" in result
    assert len(result["narrative"]) == 11


def test_every_section_is_requested_exactly_once():
    """Batching must cover 1-11 with no gaps and no duplicates."""
    from src.prompts import NARRATIVE_BATCHES
    covered = [s for batch in NARRATIVE_BATCHES for s in batch]
    assert sorted(covered) == list(range(1, 12))
    assert len(covered) == len(set(covered))


def test_narrative_batches_are_small_enough_for_a_capped_backend():
    """No batch may be so large that an 8192-token backend truncates it."""
    from src.prompts import NARRATIVE_BATCHES
    assert all(len(b) <= 4 for b in NARRATIVE_BATCHES)


def test_verdict_comes_from_the_batch_that_writes_the_recommendation():
    fin, md = _fin_md()
    client = FakeClient()
    run_analysis(fin, md, "non-financial", "", client, 0.069, 0.055)
    # only the final batch's prompt asks for the verdict fields
    verdict_prompts = [s for s in client.seen_system[1:] if '"rating"' in s]
    assert len(verdict_prompts) == 1
    assert "9" in FakeClient._requested(verdict_prompts[0])


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
