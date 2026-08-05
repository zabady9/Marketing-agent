from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ConsultingAnalysisRequest(BaseModel):
    analysis_type: Literal["swot", "pestel", "feasibility", "brand_analysis", "market_research"]
    context: str | None = None


class ConsultRequest(BaseModel):
    question: str


class ConsultingAnalysisResponse(BaseModel):
    id: str
    workspace_id: str
    analysis_type: str
    status: str
    results: dict | None
    error: str | None
    created_at: str
    classified_as: str | None = None
