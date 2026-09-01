from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel


class QCIssue(StrEnum):
    CITATION_GAP = "citation_gap"         # Tier A: figure has no URL citation or calc_trace
    FAITHFULNESS = "faithfulness"         # Tier B: narrative text contradicts source data
    DATA_GAP_MISMATCH = "data_gap_mismatch"  # Tier C: reported gap ≠ actual null field
    CLASSIFICATION_MISMATCH = "classification_mismatch"  # Tier D: claim_type inconsistent with its data
    CITATION_RELEVANCE = "citation_relevance"  # Tier E: citation resolved but doesn't support the claim


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

    # ── Tier D ────────────────────────────────────────────────────────────────
    # Pure-Python structural check: claim_type == verified_fact must have a
    # resolved citation; claim_type == unavailable must have no value. Catches
    # inconsistency, not "did the LLM pick the *right* category" — that's a
    # human-review question the methodology text is meant to support.
    classification_mismatches: int

    # ── Tier E ────────────────────────────────────────────────────────────────
    # LLM back-check (CHEAP_MODEL): for every verified_fact claim, does its
    # resolved citation actually support THIS specific claim (not just resolve
    # topically — e.g. a same-named but different company)? Items that fail
    # are downgraded in place (claim_type + citations rewritten, methodology
    # explains why) before the section payload is built — see citation_qc.py.
    citation_relevance_issues: int

    # ── Summary ───────────────────────────────────────────────────────────────
    flags: list[QCFlag]
    flagged_sections: list[str]           # unique section names with any flag
    total_flags: int

    # ── Coverage manifest (for audit / frontend) ───────────────────────────────
    coverage: dict[str, list[str]]        # keys: tier_a, tier_b, tier_c, out_of_scope
