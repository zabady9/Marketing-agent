from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Citation, ClaimType
from app.schemas.report import LocalizedText


class RiskLevel(StrEnum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class RiskCategory(StrEnum):
    MARKET = "market"
    FINANCIAL = "financial"
    OPERATIONAL = "operational"
    REGULATORY = "regulatory"
    COMPETITIVE = "competitive"
    TECHNOLOGY = "technology"


class RiskEntry(BaseModel):
    risk_description: str   # in output_language
    category: RiskCategory
    probability: RiskLevel
    impact: RiskLevel
    mitigation: str         # concrete steps in output_language
    # Per-entry citation — previously resolved by risk.py but discarded before
    # reaching the output; now threaded through so individual risks are sourceable.
    citations: list[Citation] = []
    # Computed deterministically by the agent — see risk.py::_classify_risk.
    claim_type: ClaimType = ClaimType.OPINION
    methodology: str = ""


class RiskAssessmentOutput(BaseModel):
    study_id: str
    output_language: str
    risks: list[RiskEntry]
    high_critical_count: int      # probability == "high" AND impact == "high"
    narrative: LocalizedText
    search_queries_used: list[str]
    citations: list[Citation]

    claim_types: dict[str, ClaimType] = {
        # Pure-Python count over already-classified risks, not an LLM guess.
        "high_critical_count": ClaimType.CALCULATED_ESTIMATE,
        "narrative": ClaimType.OPINION,
    }
