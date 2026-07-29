"""System prompts for the two analysis passes.

The methodology file is the contract for the report's structure and rules, so
it is loaded verbatim rather than paraphrased -- if the analyst edits
SAFARI_Valuation.txt, the prompts follow automatically.
"""

import pathlib

_SPEC_PATH = pathlib.Path(__file__).resolve().parent.parent / "SAFARI_Valuation.txt"


def methodology():
    try:
        return _SPEC_PATH.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "(methodology file unavailable)"


ASSUMPTIONS_SYSTEM = """You are a valuation analyst. You are given metrics that
have ALREADY been computed from audited financial statements. Your job in this
pass is ONLY to propose judgment assumptions. You must not restate, recompute,
or invent any reported figure.

OUTPUT FORMAT -- follow exactly:
Return a single JSON object and nothing else. No preamble, no commentary, no
markdown code fences, and no quoted extracts from the source documents. The
first character of your reply must be '{' and the last must be '}'.

You state ASSUMPTIONS ONLY. You never state a fair value, a target price, or
any other computed amount -- those are calculated from your assumptions after
this pass. Any number you write must be a rate, a ratio or a probability.

The JSON must match this shape exactly:

{
  "drivers": [            // exactly 5 objects, one per forecast year
    {"revenue_growth": 0.14, "ebit_margin": 0.172, "tax_rate": 0.20,
     "capex_pct_sales": 0.11, "wc_change_pct": 0.10, "dep_pct_sales": 0.028}
  ],
  "terminal_growth": 0.05,
  "scenarios": [          // exactly 3; probabilities must sum to 1.0
    {"name": "Bear", "prob": 0.25,
     "assumptions": "what has to go wrong, in one or two sentences",
     "driver_overrides": {"revenue_growth": 0.05, "ebit_margin": 0.14,
                          "capex_pct_sales": 0.12}},
    {"name": "Base", "prob": 0.55, "assumptions": "...", "driver_overrides": {}},
    {"name": "Bull", "prob": 0.20, "assumptions": "...",
     "driver_overrides": {"revenue_growth": 0.18, "ebit_margin": 0.19}}
  ],
  "triangulation_weights": [   // weights only -- values are computed for you
    {"name": "DCF", "weight": 0.5, "rationale": "one line"},
    {"name": "P/E - 5-yr median", "weight": 0.2, "rationale": "one line"},
    {"name": "P/E - 10-yr median", "weight": 0.1, "rationale": "one line"},
    {"name": "Justified P/B", "weight": 0.2, "rationale": "one line"}
  ],
  "model_choice": "DCF",
  "rationale": {"drivers": "...", "scenarios": "...", "triangulation": "..."}
}

Rules for these fields:
- "driver_overrides" replaces the named driver in EVERY forecast year of that
  scenario. Omit a key to leave it at the base-case path. An empty object means
  the scenario uses the base case unchanged.
- "triangulation_weights" may only name methods from this list, and weights
  should sum to 1.0: "DCF", "P/E - 5-yr median", "P/E - 10-yr median",
  "Justified P/B". Weight each by how well it fits THIS business. A method
  that cannot be computed is dropped and the weights renormalised.

Binding constraints:
- Terminal growth must not exceed long-run nominal Indian GDP (~5-6%).
- Assumed revenue growth should be reconciled against the supplied SGR and
  Reinvestment x ROIC ceilings. If you exceed both, justify it in rationale.
- Tax rate should trend toward the 25.17% statutory rate unless there is a
  stated reason a concession persists.
- Weight each valuation method by how well it fits THIS business.
- Every rationale entry is one sentence, referencing the supplied numbers.
"""


NARRATIVE_SYSTEM = """You are a valuation analyst writing a report that follows
this methodology exactly:

{methodology}

You are given FINAL computed numbers. Every quantitative claim you make must use
a number from that payload. Do NOT introduce, recompute, or round-trip any figure
of your own -- the arithmetic is already done and audited. Where a figure is
marked unavailable, say so plainly and give a reasoned qualitative assessment
instead; never fabricate a substitute.

Maintain an objective tone and present the case AGAINST your recommendation as
well as for it. Distinguish figures taken from source from figures computed.

You are writing ONLY these sections in this pass: {sections_wanted}
Do not write any other section. Keep each section self-contained.

OUTPUT FORMAT -- follow exactly:
Return a single JSON object and nothing else. No preamble, no commentary, no
markdown code fences, and no quoted extracts from the source documents. The
first character of your reply must be '{{' and the last must be '}}'. HTML goes
inside the JSON string values, never outside them.

{{
  "sections": {{{sections_shape}}}{verdict_shape}
}}

Each section value is an HTML fragment (use <p>, <table>, <ul>, <b>) that will be
embedded directly into a report tab. Cover exactly the eleven sections of the
methodology, in order. Section 6 (reverse DCF) is the most important paragraph:
state whether the market's implied expectation is achievable, conservative or
heroic, and why, against the supplied ceilings.
"""


VERDICT_SHAPE = """,
  "rating": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "fair_value": 0,
  "target_price": 0,
  "conviction": "High|Medium|Low\""""

# Eleven HTML sections do not fit in one reply on every backend (DeepSeek caps
# output at 8192 tokens), so the narrative is written in batches. The final
# batch also returns the verdict fields, since it writes the recommendation.
NARRATIVE_BATCHES = [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11)]


def narrative_system(sections=None, include_verdict=True):
    sections = list(sections or range(1, 12))
    wanted = ", ".join(str(s) for s in sections)
    shape = ", ".join(f'"{s}": "<html>"' for s in sections)
    return NARRATIVE_SYSTEM.format(
        methodology=methodology(),
        sections_wanted=wanted,
        sections_shape=shape,
        verdict_shape=VERDICT_SHAPE if include_verdict else "",
    )
