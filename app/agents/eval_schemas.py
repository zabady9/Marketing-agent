"""Schemas for consulting report evaluation output."""
from __future__ import annotations

from pydantic import BaseModel


class CriterionResult(BaseModel):
    name: str
    passed: bool
    score: float   # 0.0–1.0
    detail: str    # one sentence


class EvalOutput(BaseModel):
    criteria: list[CriterionResult]
    overall_score: float   # mean of criterion scores — diagnostic only
    passed: bool           # overall_score >= 0.75 AND citation_support_rate.passed
    flags: list[str]       # human-readable issues for display


# --- LLM judge intermediate schemas (used with with_structured_output) ---

class EvidenceSample(BaseModel):
    claim: str
    supported: bool
    explanation: str


class EvidenceGroundingJudge(BaseModel):
    samples: list[EvidenceSample]


class RecommendationConsistencyJudge(BaseModel):
    score: int   # 0–3
    explanation: str


class InternalConsistencyContradiction(BaseModel):
    a: str
    b: str
    why: str


class InternalConsistencyJudge(BaseModel):
    contradictions: list[InternalConsistencyContradiction]
    consistency_score: int   # 0–3
