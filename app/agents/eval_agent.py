"""Automated evaluation of consulting report quality."""
from __future__ import annotations

import logging
import math
import random

from langchain_core.messages import HumanMessage, SystemMessage

from app.agents.eval_schemas import (
    CriterionResult,
    EvalOutput,
    EvidenceGroundingJudge,
    InternalConsistencyJudge,
    RecommendationConsistencyJudge,
)
from app.agents.llm import get_llm

logger = logging.getLogger(__name__)

_VALID_RECOMMENDATIONS = {"proceed", "proceed_with_caution", "do_not_proceed"}

_FLAG_THRESHOLD = 0.5


# ── Item extraction ────────────────────────────────────────────────────────────

def _extract_claim_units(
    analysis_type: str,
    output_dict: dict,
    citations: list[dict],
) -> list[dict]:
    """Return list of {claim, evidence, citation_indices, snippets, unverified}."""
    units: list[dict] = []

    def _add(item: dict, claim_key: str, evidence_key: str | None = None):
        claim = item.get(claim_key) or item.get("observation") or item.get("current_state") or ""
        evidence = item.get(evidence_key, "") if evidence_key else ""
        indices = item.get("citation_indices") or []
        snippets = [
            citations[i]["snippet"] if i < len(citations) else ""
            for i in indices
        ]
        units.append({
            "claim": claim,
            "evidence": evidence,
            "citation_indices": indices,
            "snippets": snippets,
            "unverified": item.get("unverified", False),
        })

    if analysis_type == "swot":
        for section in ["strengths", "weaknesses", "opportunities", "threats"]:
            for item in output_dict.get(section, []):
                _add(item, "point", "evidence")
    elif analysis_type == "pestel":
        for factor in ["political", "economical", "social", "technological", "environmental", "legal"]:
            for item in output_dict.get(factor, []):
                _add(item, "observation", "implication")
    elif analysis_type == "feasibility":
        for section in ["market_size_and_growth", "competitive_landscape", "target_customer", "key_risks"]:
            sect = output_dict.get(section) or {}
            if sect:
                _add(sect, "title", None)
    elif analysis_type == "brand_analysis":
        for section in ["positioning", "messaging", "audience_alignment"]:
            for item in output_dict.get(section, []):
                _add(item, "current_state", "gap_or_strength")
    elif analysis_type == "market_research":
        for item in output_dict.get("segments", []):
            _add(item, "segment_name", None)
        for item in output_dict.get("key_trends", []):
            _add(item, "point", "evidence")
        for item in output_dict.get("competitive_dynamics", []):
            _add(item, "point", "evidence")

    return units


def _all_claims_text(analysis_type: str, output_dict: dict) -> list[str]:
    """Return flat list of all claim strings for internal consistency check."""
    claims: list[str] = []
    if analysis_type == "swot":
        for section in ["strengths", "weaknesses", "opportunities", "threats"]:
            for item in output_dict.get(section, []):
                if item.get("point"):
                    claims.append(item["point"])
    elif analysis_type == "pestel":
        for factor in ["political", "economical", "social", "technological", "environmental", "legal"]:
            for item in output_dict.get(factor, []):
                if item.get("observation"):
                    claims.append(item["observation"])
    return claims


# ── Structural checks ──────────────────────────────────────────────────────────

def _check_citation_support_rate(units: list[dict]) -> CriterionResult:
    if not units:
        return CriterionResult(
            name="citation_support_rate", passed=False, score=0.0,
            detail="No items found in output"
        )
    verified = sum(1 for u in units if not u["unverified"] and len(u["citation_indices"]) > 0)
    rate = verified / len(units)
    passed = rate >= 0.80
    return CriterionResult(
        name="citation_support_rate",
        passed=passed,
        score=rate,
        detail=f"{verified}/{len(units)} items have verified citations ({rate:.0%})",
    )


def _check_section_completeness(analysis_type: str, output_dict: dict) -> CriterionResult:
    issues: list[str] = []

    if analysis_type == "swot":
        for section in ["strengths", "weaknesses", "opportunities", "threats"]:
            if len(output_dict.get(section, [])) < 2:
                issues.append(f"'{section}' has fewer than 2 items")
    elif analysis_type == "pestel":
        for factor in ["political", "economical", "social", "technological", "environmental", "legal"]:
            if not output_dict.get(factor):
                issues.append(f"'{factor}' is empty")
    elif analysis_type == "feasibility":
        for section in ["market_size_and_growth", "competitive_landscape", "target_customer", "key_risks"]:
            sect = output_dict.get(section) or {}
            if not sect or not sect.get("findings"):
                issues.append(f"'{section}' has no findings")
        rec = output_dict.get("recommendation")
        if rec not in _VALID_RECOMMENDATIONS:
            issues.append(f"recommendation '{rec}' is not valid")
        if not output_dict.get("recommendation_rationale"):
            issues.append("recommendation_rationale is empty")
    elif analysis_type == "brand_analysis":
        for section in ["positioning", "messaging", "audience_alignment"]:
            if not output_dict.get(section):
                issues.append(f"'{section}' is empty")
        if not output_dict.get("summary_recommendation"):
            issues.append("summary_recommendation is empty")
    elif analysis_type == "market_research":
        for section in ["market_overview", "segments", "key_trends", "competitive_dynamics"]:
            if not output_dict.get(section):
                issues.append(f"'{section}' is empty")
        if not output_dict.get("strategic_implications"):
            issues.append("strategic_implications is empty")

    passed = len(issues) == 0
    return CriterionResult(
        name="section_completeness",
        passed=passed,
        score=1.0 if passed else 0.0,
        detail="All sections complete" if passed else "; ".join(issues[:2]),
    )


# ── LLM judge checks ───────────────────────────────────────────────────────────

def _sample_for_grounding(units: list[dict]) -> list[dict]:
    checkable = [u for u in units if u["citation_indices"] and any(u["snippets"])]
    n = min(10, max(5, math.ceil(0.30 * len(units))))
    if len(checkable) <= n:
        return checkable
    return random.sample(checkable, n)


def _format_grounding_items(sample: list[dict]) -> str:
    lines = []
    for i, u in enumerate(sample, 1):
        lines.append(f"Item {i}:")
        lines.append(f"  Claim: {u['claim']}")
        if u["evidence"]:
            lines.append(f"  Evidence stated: {u['evidence']}")
        lines.append("  Cited sources:")
        for idx, snippet in zip(u["citation_indices"], u["snippets"]):
            lines.append(f"    [{idx}] {snippet[:250]}")
    return "\n".join(lines)


async def _judge_evidence_grounding(units: list[dict]) -> CriterionResult:
    sample = _sample_for_grounding(units)
    if not sample:
        return CriterionResult(
            name="evidence_grounding", passed=False, score=0.0,
            detail="No items with citations available to ground-check"
        )

    items_text = _format_grounding_items(sample)
    llm = get_llm("cheap").with_structured_output(EvidenceGroundingJudge, method="json_schema")
    messages = [
        SystemMessage(content=(
            "You are auditing a consulting report for citation quality. "
            "For each item, decide whether the provided source snippet actually supports the stated claim. "
            "Be strict: a snippet about a different topic does NOT support the claim. "
            "Return JSON strictly matching the schema."
        )),
        HumanMessage(content=f"Items to check:\n\n{items_text}"),
    ]
    result: EvidenceGroundingJudge = await llm.ainvoke(messages)
    supported = sum(1 for s in result.samples if s.supported)
    score = supported / len(result.samples) if result.samples else 0.0
    return CriterionResult(
        name="evidence_grounding",
        passed=score >= 0.66,
        score=score,
        detail=f"{supported}/{len(result.samples)} sampled claims are grounded in cited sources",
    )


async def _judge_recommendation_consistency(output_dict: dict, citations: list[dict]) -> CriterionResult:
    rec = output_dict.get("recommendation", "")
    rationale = output_dict.get("recommendation_rationale", "")

    def _section_with_snippets(section_key: str) -> str:
        sect = output_dict.get(section_key) or {}
        findings = "\n".join(f"  - {f}" for f in (sect.get("findings") or []))
        indices = sect.get("citation_indices") or []
        snippets = "\n".join(
            f"  [{i}] {citations[i]['snippet'][:200]}"
            for i in indices if i < len(citations)
        )
        return f"{section_key}:\n{findings}\nSources:\n{snippets}"

    risks_text = _section_with_snippets("key_risks")
    market_text = _section_with_snippets("market_size_and_growth")

    llm = get_llm("cheap").with_structured_output(RecommendationConsistencyJudge, method="json_schema")
    messages = [
        SystemMessage(content=(
            "You are reviewing a feasibility recommendation for logical consistency. "
            "Score 0–3: 3=clearly supported by evidence, 2=acceptable, "
            "1=weakly supported or overly optimistic/pessimistic, 0=contradicts evidence. "
            "Return JSON: {\"score\": int 0-3, \"explanation\": \"max 2 sentences\"}"
        )),
        HumanMessage(content=(
            f"Recommendation: {rec}\n"
            f"Rationale: {rationale}\n\n"
            f"{risks_text}\n\n"
            f"{market_text}"
        )),
    ]
    result: RecommendationConsistencyJudge = await llm.ainvoke(messages)
    score = result.score / 3.0
    return CriterionResult(
        name="recommendation_consistency",
        passed=score >= 0.50,
        score=score,
        detail=result.explanation,
    )


async def _judge_internal_consistency(analysis_type: str, output_dict: dict) -> CriterionResult:
    claims = _all_claims_text(analysis_type, output_dict)
    if len(claims) < 2:
        return CriterionResult(
            name="internal_consistency", passed=True, score=1.0,
            detail="Not enough claims to check for contradictions"
        )

    numbered = "\n".join(f"{i+1}. {c}" for i, c in enumerate(claims))
    llm = get_llm("cheap").with_structured_output(InternalConsistencyJudge, method="json_schema")
    messages = [
        SystemMessage(content=(
            f"You are reviewing a {analysis_type.upper()} analysis for internal contradictions. "
            "Identify pairs where one claim directly says X is true and another says X is false or the opposite. "
            "Score 0–3: 3=no contradictions, 2=minor, 1=notable, 0=major contradictions. "
            "Return JSON: {\"contradictions\": [{\"a\": str, \"b\": str, \"why\": str}], \"consistency_score\": int 0-3}"
        )),
        HumanMessage(content=f"All claims:\n{numbered}"),
    ]
    result: InternalConsistencyJudge = await llm.ainvoke(messages)
    score = result.consistency_score / 3.0
    n_contra = len(result.contradictions)
    detail = "No contradictions found" if n_contra == 0 else f"{n_contra} contradiction(s) found"
    return CriterionResult(
        name="internal_consistency",
        passed=score >= 0.66,
        score=score,
        detail=detail,
    )


def _na_criterion(name: str) -> CriterionResult:
    return CriterionResult(name=name, passed=True, score=1.0, detail="Not applicable for this analysis type")


# ── Public entry point ─────────────────────────────────────────────────────────

async def run_eval(
    analysis_type: str,
    output_dict: dict,
    citations: list[dict],
) -> EvalOutput:
    """Run structural + LLM-judge checks and return a scored EvalOutput."""
    units = _extract_claim_units(analysis_type, output_dict, citations)

    # Structural checks (always run)
    citation_rate = _check_citation_support_rate(units)
    completeness = _check_section_completeness(analysis_type, output_dict)

    # LLM-judge checks
    grounding = await _judge_evidence_grounding(units)

    if analysis_type == "feasibility":
        rec_consistency = await _judge_recommendation_consistency(output_dict, citations)
        int_consistency = _na_criterion("internal_consistency")
    elif analysis_type in ("swot", "pestel"):
        rec_consistency = _na_criterion("recommendation_consistency")
        int_consistency = await _judge_internal_consistency(analysis_type, output_dict)
    else:
        rec_consistency = _na_criterion("recommendation_consistency")
        int_consistency = _na_criterion("internal_consistency")

    criteria = [citation_rate, completeness, grounding, rec_consistency, int_consistency]

    overall_score = sum(c.score for c in criteria) / len(criteria)

    # Hard gate: citation_support_rate failure forces passed=False
    passed = overall_score >= 0.75 and citation_rate.passed

    flags = [
        _flag_message(c) for c in criteria
        if c.score < _FLAG_THRESHOLD and not c.detail.startswith("Not applicable")
    ]

    return EvalOutput(
        criteria=criteria,
        overall_score=round(overall_score, 3),
        passed=passed,
        flags=flags,
    )


def _flag_message(c: CriterionResult) -> str:
    messages = {
        "citation_support_rate": f"Only {c.score:.0%} of claims have verified citations (need ≥80%)",
        "section_completeness": f"Incomplete sections: {c.detail}",
        "evidence_grounding": f"Low citation grounding: {c.detail}",
        "recommendation_consistency": f"Weak recommendation support: {c.detail}",
        "internal_consistency": f"Internal contradictions found: {c.detail}",
    }
    return messages.get(c.name, f"{c.name} failed: {c.detail}")
