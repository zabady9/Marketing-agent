"""Unit tests for eval_agent structural checks (no LLM calls)."""
import pytest
from unittest.mock import AsyncMock, patch

from app.agents.eval_agent import (
    _check_citation_support_rate,
    _check_section_completeness,
    _extract_claim_units,
    run_eval,
)
from app.agents.eval_schemas import CriterionResult

# ── Fixtures ───────────────────────────────────────────────────────────────────

CITATIONS = [
    {"title": "Source A", "url": "http://a.com", "snippet": "Some data about market A"},
    {"title": "Source B", "url": "http://b.com", "snippet": "Some data about market B"},
    {"title": "Source C", "url": "http://c.com", "snippet": "Some data about market C"},
]


def _swot_dict(strengths=None, weaknesses=None, opps=None, threats=None):
    def _item(point, verified=True, indices=None):
        return {
            "point": point,
            "evidence": "test evidence",
            "citation_indices": indices if indices is not None else ([0] if verified else []),
            "unverified": not verified,
        }

    return {
        "strengths": strengths if strengths is not None else [_item("S1"), _item("S2")],
        "weaknesses": weaknesses if weaknesses is not None else [_item("W1"), _item("W2")],
        "opportunities": opps if opps is not None else [_item("O1"), _item("O2")],
        "threats": threats if threats is not None else [_item("T1"), _item("T2")],
    }


def _feasibility_dict(recommendation="proceed"):
    def _sect(title, findings=None, verified=True):
        return {
            "title": title,
            "findings": findings or ["finding 1"],
            "citation_indices": [0] if verified else [],
            "unverified": not verified,
        }

    return {
        "market_size_and_growth": _sect("Market"),
        "competitive_landscape": _sect("Comp"),
        "target_customer": _sect("Customer"),
        "key_risks": _sect("Risks"),
        "recommendation": recommendation,
        "recommendation_rationale": "Clear rationale",
    }


# ── citation_support_rate ──────────────────────────────────────────────────────

def test_citation_support_rate_all_verified():
    units = _extract_claim_units("swot", _swot_dict(), CITATIONS)
    result = _check_citation_support_rate(units)
    assert result.passed is True
    assert result.score == 1.0


def test_citation_support_rate_all_unverified():
    swot = _swot_dict(
        strengths=[{"point": "S", "evidence": "e", "citation_indices": [], "unverified": True}],
        weaknesses=[{"point": "W", "evidence": "e", "citation_indices": [], "unverified": True}],
        opps=[{"point": "O", "evidence": "e", "citation_indices": [], "unverified": True}],
        threats=[{"point": "T", "evidence": "e", "citation_indices": [], "unverified": True}],
    )
    units = _extract_claim_units("swot", swot, CITATIONS)
    result = _check_citation_support_rate(units)
    assert result.passed is False
    assert result.score == 0.0


def test_citation_support_rate_boundary_exactly_80_pct():
    """8 items, 8 verified → 100% → pass. 8 items, 6 verified → 75% → fail."""
    items_6_verified = [
        {"point": f"S{i}", "evidence": "e", "citation_indices": [0], "unverified": False}
        for i in range(6)
    ] + [
        {"point": "X", "evidence": "e", "citation_indices": [], "unverified": True},
        {"point": "Y", "evidence": "e", "citation_indices": [], "unverified": True},
    ]
    swot = {
        "strengths": items_6_verified[:2],
        "weaknesses": items_6_verified[2:4],
        "opportunities": items_6_verified[4:6],
        "threats": items_6_verified[6:],
    }
    units = _extract_claim_units("swot", swot, CITATIONS)
    result = _check_citation_support_rate(units)
    assert result.passed is False
    assert abs(result.score - 0.75) < 0.01


def test_citation_support_rate_no_items():
    result = _check_citation_support_rate([])
    assert result.passed is False
    assert result.score == 0.0


# ── section_completeness ───────────────────────────────────────────────────────

def test_swot_completeness_pass():
    result = _check_section_completeness("swot", _swot_dict())
    assert result.passed is True
    assert result.score == 1.0


def test_swot_completeness_fail_empty_section():
    swot = _swot_dict(threats=[])  # threats has 0 items
    result = _check_section_completeness("swot", swot)
    assert result.passed is False
    assert "threats" in result.detail


def test_swot_completeness_fail_single_item_section():
    swot = _swot_dict(
        strengths=[{"point": "Only one", "evidence": "e", "citation_indices": [0], "unverified": False}]
    )
    result = _check_section_completeness("swot", swot)
    assert result.passed is False
    assert "strengths" in result.detail


def test_feasibility_completeness_valid_recommendation():
    result = _check_section_completeness("feasibility", _feasibility_dict("proceed_with_caution"))
    assert result.passed is True


def test_feasibility_completeness_invalid_recommendation():
    result = _check_section_completeness("feasibility", _feasibility_dict("maybe"))
    assert result.passed is False
    assert "maybe" in result.detail


def test_feasibility_completeness_empty_rationale():
    d = _feasibility_dict()
    d["recommendation_rationale"] = ""
    result = _check_section_completeness("feasibility", d)
    assert result.passed is False


# ── hard gate: citation_support_rate forces passed=False ──────────────────────

@pytest.mark.asyncio
async def test_hard_gate_citation_failure_overrides_high_overall_score():
    """citation_support_rate fails → EvalOutput.passed must be False even if other criteria score 1.0."""
    # Build SWOT where all items are unverified → citation_support_rate fails
    bad_swot = {
        "strengths": [{"point": "S", "evidence": "e", "citation_indices": [], "unverified": True},
                      {"point": "S2", "evidence": "e", "citation_indices": [], "unverified": True}],
        "weaknesses": [{"point": "W", "evidence": "e", "citation_indices": [], "unverified": True},
                       {"point": "W2", "evidence": "e", "citation_indices": [], "unverified": True}],
        "opportunities": [{"point": "O", "evidence": "e", "citation_indices": [], "unverified": True},
                          {"point": "O2", "evidence": "e", "citation_indices": [], "unverified": True}],
        "threats": [{"point": "T", "evidence": "e", "citation_indices": [], "unverified": True},
                    {"point": "T2", "evidence": "e", "citation_indices": [], "unverified": True}],
    }

    # Patch LLM judges to return perfect scores so overall_score would be high without the gate
    perfect_grounding = AsyncMock(return_value=CriterionResult(
        name="evidence_grounding", passed=True, score=1.0, detail="all good"
    ))
    perfect_consistency = AsyncMock(return_value=CriterionResult(
        name="internal_consistency", passed=True, score=1.0, detail="no contradictions"
    ))

    with (
        patch("app.agents.eval_agent._judge_evidence_grounding", perfect_grounding),
        patch("app.agents.eval_agent._judge_internal_consistency", perfect_consistency),
    ):
        eval_output = await run_eval("swot", bad_swot, CITATIONS)

    citation_criterion = next(c for c in eval_output.criteria if c.name == "citation_support_rate")
    assert citation_criterion.passed is False
    assert eval_output.passed is False   # hard gate
    assert len(eval_output.flags) > 0


# ── flags ──────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_flags_populated_when_citation_rate_low():
    all_unverified_swot = {
        section: [
            {"point": f"{section[0]}{i}", "evidence": "e", "citation_indices": [], "unverified": True}
            for i in range(2)
        ]
        for section in ["strengths", "weaknesses", "opportunities", "threats"]
    }

    with (
        patch("app.agents.eval_agent._judge_evidence_grounding", AsyncMock(
            return_value=CriterionResult(name="evidence_grounding", passed=True, score=1.0, detail="ok")
        )),
        patch("app.agents.eval_agent._judge_internal_consistency", AsyncMock(
            return_value=CriterionResult(name="internal_consistency", passed=True, score=1.0, detail="ok")
        )),
    ):
        result = await run_eval("swot", all_unverified_swot, CITATIONS)

    assert len(result.flags) >= 1
    assert any("citation" in f.lower() for f in result.flags)
