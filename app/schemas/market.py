from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.schemas.common import Citation
from app.schemas.report import LocalizedText


class EstimatedMarketFigure(BaseModel):
    value: float | None = None
    currency: str = "USD"
    unit: str = "USD"  # human-readable unit, e.g. "billion USD"
    source: Literal["estimated"] = "estimated"
    confidence: Literal["high", "medium", "low"] = "medium"
    citations: list[Citation] = []


class MarketSizingOutput(BaseModel):
    study_id: str
    output_language: str
    tam: EstimatedMarketFigure
    sam: EstimatedMarketFigure
    som: EstimatedMarketFigure
    growth_rate_cagr: float | None = None       # percentage, e.g. 12.5 = 12.5%
    growth_rate_citations: list[Citation] = []
    narrative: LocalizedText
    key_insights: list[str]
    all_citations: list[Citation]
    search_queries_used: list[str]
    review_recommended: bool = False


class CompetitorProfile(BaseModel):
    name: str
    source: Literal["user_provided", "estimated"]
    market_position: Literal["leader", "challenger", "niche", "unknown"] = "unknown"
    strengths: list[str] = []
    weaknesses: list[str] = []
    citations: list[Citation] = []


class CompetitiveAnalysisOutput(BaseModel):
    study_id: str
    output_language: str
    competitors: list[CompetitorProfile]
    key_differentiators: list[str]   # what makes this business unique vs. competitors
    market_gaps: list[str]           # opportunities the user's business could fill
    narrative: LocalizedText
    all_citations: list[Citation]
    search_queries_used: list[str]
