from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Citation, ClaimType
from app.schemas.report import LocalizedText


class EstimatedMarketFigure(BaseModel):
    value: float | None = None
    currency: str = "USD"
    unit: str = "USD"  # human-readable unit, e.g. "billion USD"
    source: Literal["estimated"] = "estimated"
    confidence: Literal["high", "medium", "low"] = "medium"
    citations: list[Citation] = []
    # Computed deterministically from (value, citations) by the agent, not the
    # LLM — see market_sizing.py::_classify_figure. verified_fact when a
    # citation resolved, unavailable when value is null.
    claim_type: ClaimType = ClaimType.UNAVAILABLE
    # LLM-authored one-line explanation of how this figure was derived, or why
    # it's null. Empty until the market_sizing prompt requires it.
    methodology: str = ""


class MarketSizingOutput(BaseModel):
    study_id: str
    output_language: str
    tam: EstimatedMarketFigure
    sam: EstimatedMarketFigure
    som: EstimatedMarketFigure
    growth_rate_cagr: float | None = None       # percentage, e.g. 12.5 = 12.5%
    growth_rate_citations: list[Citation] = []
    # A CAGR is always a forward-looking projection — constant, not computed.
    growth_rate_claim_type: ClaimType = ClaimType.FORECAST
    growth_rate_methodology: str = ""
    narrative: LocalizedText
    key_insights: list[str]
    all_citations: list[Citation]
    search_queries_used: list[str]
    review_recommended: bool = False

    claim_types: dict[str, ClaimType] = {
        "key_insights": ClaimType.OPINION,
        "narrative": ClaimType.OPINION,
    }


class CompetitorProfile(BaseModel):
    name: str
    source: Literal["user_provided", "estimated"]
    market_position: Literal["leader", "challenger", "niche", "unknown"] = "unknown"
    strengths: list[str] = []
    weaknesses: list[str] = []
    citations: list[Citation] = []
    # Computed deterministically by the agent — see
    # competitive.py::_classify_competitor.
    claim_type: ClaimType = ClaimType.OPINION
    methodology: str = ""


class CompetitiveAnalysisOutput(BaseModel):
    study_id: str
    output_language: str
    competitors: list[CompetitorProfile]
    key_differentiators: list[str]   # what makes this business unique vs. competitors
    market_gaps: list[str]           # opportunities the user's business could fill
    narrative: LocalizedText
    all_citations: list[Citation]
    search_queries_used: list[str]

    claim_types: dict[str, ClaimType] = {
        "key_differentiators": ClaimType.OPINION,
        "market_gaps": ClaimType.OPINION,
        "narrative": ClaimType.OPINION,
    }
