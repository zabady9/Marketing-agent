from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel


class Citation(BaseModel):
    url: str
    title: str
    snippet: str


class ClaimType(StrEnum):
    """Per-claim sourcing classification shown to the reader alongside every
    figure/entity/statement in the report — what kind of claim this is and
    why it should (or shouldn't) be trusted at face value."""

    VERIFIED_FACT = "verified_fact"             # backed by a resolved citation/URL
    ASSUMPTION = "assumption"                    # user- or system-assumed input, not measured
    CALCULATED_ESTIMATE = "calculated_estimate"  # deterministic math (see CalcTrace)
    FORECAST = "forecast"                        # projection/extrapolation (e.g. CAGR)
    OPINION = "opinion"                          # LLM qualitative judgment/recommendation
    UNAVAILABLE = "unavailable"                  # explicit no-data marker, never a guess
