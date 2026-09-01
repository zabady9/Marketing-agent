"""
Unit tests for citation_qc.py's Tier D check: claim_type must be structurally
consistent with the value/citations it describes. Pure Python, no LLM.
"""

from app.agents.citation_qc import _check_claim_type
from app.schemas.common import ClaimType


class TestCheckClaimType:
    def test_verified_fact_with_citation_is_clean(self):
        assert _check_claim_type("market_overview", "TAM", ClaimType.VERIFIED_FACT, True, True) is None

    def test_verified_fact_without_citation_is_flagged(self):
        flag = _check_claim_type("market_overview", "TAM", ClaimType.VERIFIED_FACT, True, False)
        assert flag is not None
        assert flag.issue == "classification_mismatch"
        assert "verified_fact" in flag.detail

    def test_unavailable_with_no_value_is_clean(self):
        assert _check_claim_type("market_overview", "SAM", ClaimType.UNAVAILABLE, False, False) is None

    def test_unavailable_with_a_value_is_flagged(self):
        flag = _check_claim_type("market_overview", "SAM", ClaimType.UNAVAILABLE, True, False)
        assert flag is not None
        assert "unavailable" in flag.detail

    def test_opinion_and_assumption_never_flagged_regardless_of_citation(self):
        # Tier D only constrains verified_fact/unavailable — opinion and
        # assumption carry no citation/value expectation to check.
        assert _check_claim_type("risk_assessment", "risk:x", ClaimType.OPINION, True, False) is None
        assert _check_claim_type("financial_feasibility", "capex", ClaimType.ASSUMPTION, True, False) is None
