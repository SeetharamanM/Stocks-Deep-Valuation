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

from src.valuation_pack import build_pack
from src.metrics import triangulate, scenario_expected_value
from src.prompts import ASSUMPTIONS_SYSTEM, narrative_system

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
    triangulation = triangulate(assumptions.get("triangulation") or [])
    price = pack["meta"]["current_price"]
    scenario = scenario_expected_value(assumptions.get("scenarios") or [], price)

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
    narrative = client.complete_json(narrative_system(), user2)

    return {
        "pack": pack,
        "triangulation": triangulation,
        "scenario": scenario,
        "narrative": narrative.get("sections", {}),
        "rating": narrative.get("rating"),
        "fair_value": narrative.get("fair_value"),
        "target_price": narrative.get("target_price"),
        "conviction": narrative.get("conviction"),
        "assumptions": assumptions,
    }
