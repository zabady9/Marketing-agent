"""
Deterministic confidence_score computation — never LLM-generated.

Formula (weights are constants, not tunable per study):
  40% citation_score      — fraction of citeable claims with a URL citation or calc_trace
  30% risk_score          — 1 - 0.15 per high×high risk (floor 0)
  20% completeness_score  — fraction of intake fields that were user-provided (not estimated)
  10% pipeline_score      — (7 - fatal_failures) / 7

Null market figures (SAM=null, SOM=null) drag both citation_score (no citation)
and implicitly appear in completeness via their review_recommended flag.

Usage:
    inp = build_confidence_input(fi, market, competitive, financial, risk_output, [])
    bd  = compute_confidence_score(inp)
    print(bd.final_score, bd.breakdown_dict())
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ConfidenceInput:
    # ── Citation quality ──────────────────────────────────────────────────────
    # A "claim" is any figure that should be backed by a URL or calc_trace.
    # Market: TAM, SAM, SOM, CAGR  (nulls count as uncited — gap, not absence)
    # Competitive: one entry per competitor profile
    # Financial: one entry per CalculatedFigure (always has calc_trace → always cited)
    # Risk / Synthesis: added in Phase 5+
    total_citeable_claims: int
    cited_claims: int

    # ── Risk ─────────────────────────────────────────────────────────────────
    high_critical_risks: int = 0   # probability == "high" AND impact == "high"

    # ── Completeness (intake fields) ─────────────────────────────────────────
    total_intake_fields: int = 8
    user_provided_intake_fields: int = 8

    # ── Pipeline ─────────────────────────────────────────────────────────────
    fatal_agent_failures: list[str] = field(default_factory=list)


@dataclass
class ConfidenceBreakdown:
    citation_score: float        # 0–1
    risk_score: float            # 0–1
    completeness_score: float    # 0–1
    pipeline_score: float        # 0–1
    final_score: float           # 0–1 (weighted)

    # Supporting data (for display / audit)
    cited_claims: int
    total_citeable_claims: int
    high_critical_risks: int
    user_provided_intake_fields: int
    total_intake_fields: int
    fatal_agent_failures: list[str]

    def breakdown_dict(self) -> dict:
        return {
            "final_score": self.final_score,
            "components": {
                "citation_quality": {
                    "weight": 0.40,
                    "raw_score": self.citation_score,
                    "weighted": round(0.40 * self.citation_score, 3),
                    "cited_claims": self.cited_claims,
                    "total_citeable_claims": self.total_citeable_claims,
                },
                "risk_penalty": {
                    "weight": 0.30,
                    "raw_score": self.risk_score,
                    "weighted": round(0.30 * self.risk_score, 3),
                    "high_critical_risks": self.high_critical_risks,
                },
                "completeness": {
                    "weight": 0.20,
                    "raw_score": self.completeness_score,
                    "weighted": round(0.20 * self.completeness_score, 3),
                    "user_provided": self.user_provided_intake_fields,
                    "total": self.total_intake_fields,
                },
                "pipeline": {
                    "weight": 0.10,
                    "raw_score": self.pipeline_score,
                    "weighted": round(0.10 * self.pipeline_score, 3),
                    "fatal_failures": self.fatal_agent_failures,
                },
            },
        }


def compute_confidence_score(inp: ConfidenceInput) -> ConfidenceBreakdown:
    citation_score = (
        inp.cited_claims / inp.total_citeable_claims
        if inp.total_citeable_claims > 0
        else 0.0
    )
    risk_score = max(0.0, 1.0 - inp.high_critical_risks * 0.15)
    completeness_score = (
        inp.user_provided_intake_fields / inp.total_intake_fields
        if inp.total_intake_fields > 0
        else 0.5
    )
    pipeline_score = max(0.0, (7 - len(inp.fatal_agent_failures)) / 7)

    final_score = round(
        0.40 * citation_score
        + 0.30 * risk_score
        + 0.20 * completeness_score
        + 0.10 * pipeline_score,
        2,
    )

    return ConfidenceBreakdown(
        citation_score=round(citation_score, 3),
        risk_score=round(risk_score, 3),
        completeness_score=round(completeness_score, 3),
        pipeline_score=round(pipeline_score, 3),
        final_score=final_score,
        cited_claims=inp.cited_claims,
        total_citeable_claims=inp.total_citeable_claims,
        high_critical_risks=inp.high_critical_risks,
        user_provided_intake_fields=inp.user_provided_intake_fields,
        total_intake_fields=inp.total_intake_fields,
        fatal_agent_failures=inp.fatal_agent_failures,
    )


def build_confidence_input(
    *,
    # Market sizing (nulls explicitly counted as uncited, not skipped)
    market_tam_cited: bool = False,
    market_sam_null: bool = False,    # null = uncited gap
    market_som_null: bool = False,    # null = uncited gap
    market_cagr_cited: bool = False,
    # Competitive: one bool per competitor profile
    competitive_cited_count: int = 0,
    competitive_total_count: int = 0,
    # Financial: always cited via calc_trace (6 figures)
    financial_figure_count: int = 6,
    # Risk: one bool per risk entry (Phase 5+)
    risk_cited_count: int = 0,
    risk_total_count: int = 0,
    # Risk severity (Phase 5+)
    high_critical_risks: int = 0,
    # Intake field completeness
    user_provided_intake_fields: int = 8,
    total_intake_fields: int = 8,
    # Pipeline
    fatal_agent_failures: list[str] | None = None,
) -> ConfidenceInput:
    """
    Build a ConfidenceInput from per-section evidence flags.
    Null market figures count as uncited claims, visibly dragging down citation_score.
    """
    # Market claims: TAM, SAM, SOM, CAGR = 4 slots regardless of null
    market_cited = int(market_tam_cited) + int(not market_sam_null) + int(not market_som_null) + int(market_cagr_cited)
    market_total = 4  # always 4 attempted slots

    total_citeable = market_total + competitive_total_count + financial_figure_count + risk_total_count
    total_cited = market_cited + competitive_cited_count + financial_figure_count + risk_cited_count

    return ConfidenceInput(
        total_citeable_claims=total_citeable,
        cited_claims=total_cited,
        high_critical_risks=high_critical_risks,
        total_intake_fields=total_intake_fields,
        user_provided_intake_fields=user_provided_intake_fields,
        fatal_agent_failures=fatal_agent_failures or [],
    )
