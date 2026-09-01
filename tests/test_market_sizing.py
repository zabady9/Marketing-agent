"""
Unit tests for the pure, code-side anti-hallucination logic in
app/agents/market_sizing.py: `_guard` (nulls out a value that has no resolved
citation, regardless of what the LLM claimed) and `_classify_figure` (derives
the ClaimType for a market figure from its final value + citations).

No LLM, no network, no async — these are deterministic helper functions.
"""

from app.agents.market_sizing import _classify_figure, _guard
from app.schemas.common import Citation, ClaimType

_CITATION = Citation(url="https://example.com/report", title="Report", snippet="TAM is $5B")


class TestGuard:
    def test_value_with_no_citation_is_nulled_out(self):
        # This is the exact gap the guard closes: an LLM-claimed value with
        # no resolved citation must never survive into the output.
        assert _guard(5_000_000_000.0, []) is None

    def test_value_with_a_resolved_citation_survives(self):
        assert _guard(5_000_000_000.0, [_CITATION]) == 5_000_000_000.0

    def test_none_value_stays_none_regardless_of_citations(self):
        assert _guard(None, []) is None
        assert _guard(None, [_CITATION]) is None

    def test_zero_is_a_real_value_not_treated_as_falsy_none(self):
        # 0.0 is a legitimate (if unusual) figure — must not be confused with
        # "no value" and must still be guarded like any other value.
        assert _guard(0.0, []) is None
        assert _guard(0.0, [_CITATION]) == 0.0


class TestClassifyFigure:
    def test_null_value_is_unavailable_regardless_of_citations(self):
        assert _classify_figure(None, []) == ClaimType.UNAVAILABLE
        assert _classify_figure(None, [_CITATION]) == ClaimType.UNAVAILABLE

    def test_value_with_citation_is_verified_fact(self):
        assert _classify_figure(5_000_000_000.0, [_CITATION]) == ClaimType.VERIFIED_FACT

    def test_value_with_no_citation_is_assumption(self):
        # Reachable only defensively today — _guard() nulls the value out
        # before this branch is hit in the real pipeline — but the classifier
        # must still degrade sensibly if ever called on unguarded input.
        assert _classify_figure(5_000_000_000.0, []) == ClaimType.ASSUMPTION

    def test_guard_and_classify_compose_to_unavailable_for_an_unsourced_claim(self):
        # The actual pipeline order: guard first, then classify the guarded
        # value — an LLM-claimed-but-unsourced figure ends up UNAVAILABLE,
        # never ASSUMPTION, once both steps run in sequence.
        guarded = _guard(5_000_000_000.0, [])
        assert _classify_figure(guarded, []) == ClaimType.UNAVAILABLE
