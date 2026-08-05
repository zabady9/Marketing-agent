"""Pydantic schemas for structured LLM output from consulting agents."""
from __future__ import annotations

from pydantic import BaseModel


class Citation(BaseModel):
    title: str
    url: str
    snippet: str


class SWOTItem(BaseModel):
    point: str
    evidence: str
    citation_indices: list[int]
    unverified: bool = False


class SWOTOutput(BaseModel):
    strengths: list[SWOTItem]
    weaknesses: list[SWOTItem]
    opportunities: list[SWOTItem]
    threats: list[SWOTItem]


class PESTELItem(BaseModel):
    factor: str
    observation: str
    implication: str
    citation_indices: list[int]
    unverified: bool = False


class PESTELOutput(BaseModel):
    political: list[PESTELItem]
    economical: list[PESTELItem]
    social: list[PESTELItem]
    technological: list[PESTELItem]
    environmental: list[PESTELItem]
    legal: list[PESTELItem]


class FeasibilitySection(BaseModel):
    title: str
    findings: list[str]
    citation_indices: list[int]
    unverified: bool = False


class FeasibilityOutput(BaseModel):
    market_size_and_growth: FeasibilitySection
    competitive_landscape: FeasibilitySection
    target_customer: FeasibilitySection
    key_risks: FeasibilitySection
    recommendation: str
    recommendation_rationale: str


class BrandItem(BaseModel):
    dimension: str
    current_state: str
    gap_or_strength: str
    recommendation: str
    citation_indices: list[int]
    unverified: bool = False


class BrandAnalysisOutput(BaseModel):
    positioning: list[BrandItem]
    messaging: list[BrandItem]
    audience_alignment: list[BrandItem]
    summary_recommendation: str


class MarketSegment(BaseModel):
    segment_name: str
    size_estimate: str
    growth_trend: str
    key_players: list[str]
    citation_indices: list[int]
    unverified: bool = False


class MarketResearchOutput(BaseModel):
    market_overview: FeasibilitySection
    segments: list[MarketSegment]
    key_trends: list[SWOTItem]
    competitive_dynamics: list[SWOTItem]
    strategic_implications: str
