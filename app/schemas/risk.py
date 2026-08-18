from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Citation
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


class RiskAssessmentOutput(BaseModel):
    study_id: str
    output_language: str
    risks: list[RiskEntry]
    high_critical_count: int      # probability == "high" AND impact == "high"
    narrative: LocalizedText
    search_queries_used: list[str]
    citations: list[Citation]
