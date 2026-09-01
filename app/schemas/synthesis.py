from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from app.schemas.common import ClaimType
from app.schemas.report import LocalizedText


class Verdict(StrEnum):
    PROCEED = "proceed"
    PROCEED_WITH_CAUTION = "proceed_with_caution"
    DO_NOT_PROCEED = "do_not_proceed"


class FeasibilitySynthesisOutput(BaseModel):
    study_id: str
    output_language: str
    verdict: Verdict
    confidence_score: float         # from confidence.py — deterministic, never LLM-generated
    confidence_breakdown: dict      # full breakdown dict for frontend display
    executive_summary: LocalizedText
    key_opportunities: list[str]    # 3-5 items in output_language
    key_risks: list[str]            # 3-5 items in output_language
    data_gaps: list[str]            # explicitly listed null/unavailable fields
    contradictions: list[str]       # internal cross-section contradictions, or []
    rationale: LocalizedText        # why this verdict was reached

    claim_types: dict[str, ClaimType] = {
        "verdict": ClaimType.OPINION,
        "confidence_score": ClaimType.CALCULATED_ESTIMATE,
        "key_opportunities": ClaimType.OPINION,
        "key_risks": ClaimType.OPINION,
        "data_gaps": ClaimType.UNAVAILABLE,
        "contradictions": ClaimType.OPINION,
        "rationale": ClaimType.OPINION,
        "executive_summary": ClaimType.OPINION,
    }
