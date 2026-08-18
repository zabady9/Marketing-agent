from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class QCIssue(StrEnum):
    CITATION_GAP = "citation_gap"         # Tier A: figure has no URL citation or calc_trace
    FAITHFULNESS = "faithfulness"         # Tier B: narrative text contradicts source data
    DATA_GAP_MISMATCH = "data_gap_mismatch"  # Tier C: reported gap ≠ actual null field


class QCSeverity(StrEnum):
    WARNING = "warning"   # flagged but report continues
    ERROR = "error"       # would block in strict mode; currently flag-and-continue


class QCFlag(BaseModel):
    section: str          # e.g. "market_overview", "contradictions"
    claim: str            # brief excerpt of what was flagged (≤ 120 chars)
    issue: QCIssue
    severity: QCSeverity
    detail: str           # human-readable explanation


class CitationQCOutput(BaseModel):
    # ── Tier A ────────────────────────────────────────────────────────────────
    citation_support_rate: float          # cited_claims / total_citeable_claims (Tier A only)
    citation_threshold: float = 0.80
    citation_threshold_passed: bool

    # ── Tier B ────────────────────────────────────────────────────────────────
    faithfulness_issues: int              # count of Tier B flags
    # executive_summary receives ERROR-severity (not WARNING) because it is the most
    # user-facing section — a fabricated figure there is more harmful than in a sub-section.
    # When False, frontends MUST show a blocking warning overlay rather than displaying
    # the summary text directly. QC cannot retract an already-sent section_ready event,
    # so this field is the downstream signal to gate display.
    executive_summary_trusted: bool       # False if any faithfulness flag hit exec summary
    contradictions_in_scope: bool = True  # explicit: contradictions ARE checked
    contradictions_verified: bool         # True when at least one contradiction exists and was checked
    contradictions_faithful: bool | None  # None if no contradictions; True/False otherwise

    # ── Tier C ────────────────────────────────────────────────────────────────
    data_gap_mismatches: int              # reported gaps that don't match actual nulls

    # ── Summary ───────────────────────────────────────────────────────────────
    flags: list[QCFlag]
    flagged_sections: list[str]           # unique section names with any flag
    total_flags: int

    # ── Coverage manifest (for audit / frontend) ───────────────────────────────
    coverage: dict[str, list[str]]        # keys: tier_a, tier_b, tier_c, out_of_scope
