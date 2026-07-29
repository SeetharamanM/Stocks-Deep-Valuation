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

Respond with JSON only, matching this shape exactly:

{
  "drivers": [            // exactly 5 objects, one per forecast year
    {"revenue_growth": 0.14, "ebit_margin": 0.172, "tax_rate": 0.20,
     "capex_pct_sales": 0.11, "wc_change_pct": 0.10, "dep_pct_sales": 0.028}
  ],
  "terminal_growth": 0.05,
  "scenarios": [          // exactly 3; probabilities must sum to 1.0
    {"name": "Bear", "value": 0, "prob": 0.25},
    {"name": "Base", "value": 0, "prob": 0.55},
    {"name": "Bull", "value": 0, "prob": 0.20}
  ],
  "triangulation": [      // per-method fair values and weights
    {"name": "DCF", "value": 0, "weight": 0.5}
  ],
  "model_choice": "DCF",
  "rationale": {"drivers": "...", "scenarios": "...", "triangulation": "..."}
}

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

Respond with JSON only:

{{
  "sections": {{"1": "<html>", "2": "<html>", ... "11": "<html>"}},
  "rating": "STRONG BUY|BUY|HOLD|SELL|STRONG SELL",
  "fair_value": 0,
  "target_price": 0,
  "conviction": "High|Medium|Low"
}}

Each section value is an HTML fragment (use <p>, <table>, <ul>, <b>) that will be
embedded directly into a report tab. Cover exactly the eleven sections of the
methodology, in order. Section 6 (reverse DCF) is the most important paragraph:
state whether the market's implied expectation is achievable, conservative or
heroic, and why, against the supplied ceilings.
"""


def narrative_system():
    return NARRATIVE_SYSTEM.format(methodology=methodology())
