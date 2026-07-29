"""Two-pass LLM analysis.

The ordering here is the whole point of the design:

  1. Python computes every mechanical figure          (build_pack)
  2. the LLM proposes only judgment assumptions        (assumptions pass)
  3. Python recomputes all consequences of those       (build_pack again)
  4. the LLM writes prose around the FINAL numbers     (narrative pass)

Because step 3 sits between the two model calls, no figure in the report can
originate from the LLM -- it can choose assumptions, but Python owns what those
assumptions imply.
"""

import json

from src.valuation_pack import build_pack, scenario_values
from src.metrics import (triangulate, scenario_expected_value,
                         computable_methods, apply_weights)
from src.prompts import (ASSUMPTIONS_SYSTEM, narrative_system,
                         NARRATIVE_BATCHES, RECOMMENDATION_SECTION)

# Keep prompts within a sane token budget; the pack is the important part.
_PDF_BUDGET_PASS1 = 20000
_PDF_BUDGET_PASS2 = 10000


def _json(payload):
    return json.dumps(payload, default=str, indent=1)


def run_analysis(fin, md, sector, pdf_context, client, rf, erp):
    pdf_context = pdf_context or ""

    # Pass 1 -- mechanical figures only, then ask for judgment.
    pack_initial = build_pack(fin, md, sector, rf, erp)
    user1 = (
        "METRICS PACK (already computed -- do not recompute):\n"
        + _json(pack_initial)
        + "\n\nQUALITATIVE CONTEXT FROM FILINGS:\n"
        + pdf_context[:_PDF_BUDGET_PASS1]
    )
    assumptions = client.complete_json(ASSUMPTIONS_SYSTEM, user1)

    # Recompute every consequence of the proposed assumptions in Python.
    pack = build_pack(fin, md, sector, rf, erp, dcf_overrides={
        "drivers": assumptions.get("drivers"),
        "terminal_growth": assumptions.get("terminal_growth", 0.05),
    })
    # Values are computed here, not taken from the model: the model chose the
    # methods and their weights, Python evaluates what each is worth.
    methods = computable_methods(pack)
    triangulation = triangulate(
        apply_weights(methods, assumptions.get("triangulation_weights")))
    price = pack["meta"]["current_price"]
    # Each scenario is re-run through the same DCF engine with its own driver
    # overrides, so the bear/base/bull values are consistent by construction.
    scenario = scenario_expected_value(
        scenario_values(fin, pack, assumptions.get("scenarios")), price)

    # Pass 2 -- prose written against the recomputed figures.
    final_numbers = {
        "pack": pack,
        "triangulation": triangulation,
        "scenario": scenario,
        "model_choice": assumptions.get("model_choice"),
        "assumption_rationale": assumptions.get("rationale"),
    }
    user2 = (
        "FINAL NUMBERS (authoritative -- quote these, never recompute):\n"
        + _json(final_numbers)
        + "\n\nQUALITATIVE CONTEXT FROM FILINGS:\n"
        + pdf_context[:_PDF_BUDGET_PASS2]
    )

    # The verdict rides with whichever batch writes section 9 (Recommendation),
    # so it stays attached to the reasoning that produces it regardless of how
    # the batches are grouped.
    sections, verdict = {}, {}
    for batch in NARRATIVE_BATCHES:
        writes_recommendation = RECOMMENDATION_SECTION in batch
        reply = client.complete_json(
            narrative_system(sections=batch, include_verdict=writes_recommendation),
            user2)
        for key, value in (reply.get("sections") or {}).items():
            sections[str(key)] = value
        if writes_recommendation:
            verdict = reply

    return {
        "pack": pack,
        "triangulation": triangulation,
        "scenario": scenario,
        "narrative": sections,
        "rating": verdict.get("rating"),
        "fair_value": verdict.get("fair_value"),
        "target_price": verdict.get("target_price"),
        "conviction": verdict.get("conviction"),
        "assumptions": assumptions,
    }
