"""
Verify confidence_score with actual Phase 4 study data.

Observed from SSE stream (study_id=490c83a2):
  market_overview:
    TAM:  $2.86B, 1 citation  → cited ✓
    SAM:  null,   0 citations → uncited ✗  (NULL — not estimated, not invented)
    SOM:  null,   0 citations → uncited ✗  (NULL — same)
    CAGR: 14.63%, growth_rate_citations=[] → uncited ✗  (number but no URL)
  competitive_landscape:
    Bayzat      [user_provided] citations > 0 → cited ✓
    Qiwa        [user_provided] citations > 0 → cited ✓
    ZenHR       [estimated]    citations > 0 → cited ✓
    Malachite   [estimated]    citations > 0 → cited ✓
    (total 9 citations across 4 competitors → all 4 cited)
  financial_feasibility:
    6 CalculatedFigures, each with calc_trace → all cited ✓

  intake warnings: capex, opex_monthly → both ESTIMATED
  no intake warnings for: pricing, geography, business_description, model, monthly_sales
  → 6 user_provided / 8 total intake fields

  fatal_agent_failures: [] (all agents succeeded)
  high_critical_risks: 0 (risk section not yet run)
"""

import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.tools.confidence import build_confidence_input, compute_confidence_score

# ── What-if: full market data (SAM + SOM estimated, CAGR cited) ────────────
inp_ideal = build_confidence_input(
    market_tam_cited=True,
    market_sam_null=False,   # hypothetically estimated
    market_som_null=False,   # hypothetically estimated
    market_cagr_cited=True,
    competitive_cited_count=4, competitive_total_count=4,
    financial_figure_count=6,
    user_provided_intake_fields=6, total_intake_fields=8,
)

# ── Actual Phase 4 study (SAM=null, SOM=null, CAGR uncited) ───────────────
inp_actual = build_confidence_input(
    market_tam_cited=True,
    market_sam_null=True,    # NULL — dragging down score
    market_som_null=True,    # NULL — dragging down score
    market_cagr_cited=False, # number returned but no citation URL
    competitive_cited_count=4, competitive_total_count=4,
    financial_figure_count=6,
    user_provided_intake_fields=6, total_intake_fields=8,
)

bd_ideal  = compute_confidence_score(inp_ideal)
bd_actual = compute_confidence_score(inp_actual)

INDENT = "    "

def show(label: str, bd, highlight_fields=None):
    print(f"\n{'─'*60}")
    print(f"  {label}")
    print(f"{'─'*60}")
    d = bd.breakdown_dict()
    comps = d["components"]

    for name, comp in comps.items():
        arrow = " ◄ NULL drag" if highlight_fields and name in highlight_fields else ""
        print(f"  {name:<24} weight={comp['weight']:.0%}  "
              f"raw={comp['raw_score']:.3f}  "
              f"→ {comp['weighted']:.3f}{arrow}")
        # Extra detail per component
        if name == "citation_quality":
            print(f"  {INDENT}cited {comp['cited_claims']}/{comp['total_citeable_claims']} claims")
        elif name == "completeness":
            print(f"  {INDENT}user_provided {comp['user_provided']}/{comp['total']} intake fields")
        elif name == "risk_penalty":
            print(f"  {INDENT}high×high risks: {comp['high_critical_risks']}")
        elif name == "pipeline":
            print(f"  {INDENT}fatal failures: {comp['fatal_failures'] or 'none'}")

    weighted_sum = sum(c["weighted"] for c in comps.values())
    print(f"  {'─'*40}")
    print(f"  {'confidence_score':<24}  (sum of weighted) = {bd.final_score:.2f}")

show(
    "IDEAL  — SAM/SOM estimated + CAGR cited  (hypothetical)",
    bd_ideal,
)

show(
    "ACTUAL — SAM=null, SOM=null, CAGR uncited  (Phase 4 study)",
    bd_actual,
    highlight_fields={"citation_quality"},
)

delta = round(bd_ideal.final_score - bd_actual.final_score, 3)
print(f"\n  Penalty from null SAM/SOM + uncited CAGR: -{delta} on final score")
print(f"  ({bd_ideal.final_score:.2f} ideal  →  {bd_actual.final_score:.2f} actual)\n")
