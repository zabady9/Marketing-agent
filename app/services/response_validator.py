"""Post-generation response validator with section-level repair loop.

Validates the synthesized markdown against expected structural requirements per
intent type. On failure, regenerates only the missing section (not the full
answer) by calling the generator once more with the existing context + a targeted
repair prompt. A second failure injects a [⚠ section incomplete] marker.

Inline arithmetic check
-----------------------
Whether the synthesis contains bare computed numbers without a prior calculate()
tool call is checked as a SOFT WARNING only — it is appended to the warnings
list but does NOT trigger a repair loop, because numbers cited verbatim from
tool-retrieved sources (e.g. a revenue figure returned by get_market_data) would
produce false positives.
"""
from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

# Expected structural requirements per intent.
# "required_sections": heading keywords that must appear in the markdown.
# "min_citations": minimum count of [S<n>] or [K<n>] citation references.
INTENT_SCHEMA: dict[str, dict] = {
    "swot": {
        "required_sections": ["strengths", "weaknesses", "opportunities", "threats"],
        "min_citations": 3,
    },
    "pestel": {
        "required_sections": ["political", "economic", "social", "technological", "environmental", "legal"],
        "min_citations": 3,
    },
    "feasibility": {
        "required_sections": ["market", "competitive", "recommendation"],
        "min_citations": 2,
    },
    "market_research": {
        "required_sections": ["overview", "segments", "trends"],
        "min_citations": 2,
    },
    "general_analysis": {
        "required_sections": ["findings", "implications"],
        "min_citations": 2,
    },
    "competitive_analysis": {
        "required_sections": ["findings", "position"],
        "min_citations": 2,
    },
    "gap_analysis": {
        "required_sections": ["gaps", "findings"],
        "min_citations": 2,
    },
    "subject_analysis": {
        "required_sections": ["positioning", "findings"],
        "min_citations": 2,
    },
    "strategic_recommendation": {
        "required_sections": ["findings", "recommendations"],
        "min_citations": 1,
    },
}

# Regex matching citation references like [S1], [S12], [K3]
_CITATION_RE = re.compile(r"\[[SK]\d+\]")

# Regex detecting a likely inline arithmetic result (number with %, × or ratio)
# without a [S/K<n>] citation immediately nearby — soft check only.
_INLINE_MATH_RE = re.compile(r"\b\d+\.?\d*\s*%|\b\d+\.?\d*\s*×|\bCAGR\b", re.IGNORECASE)


def _missing_sections(synthesis: str, required: list[str]) -> list[str]:
    lower = synthesis.lower()
    return [s for s in required if s.lower() not in lower]


def _citation_count(synthesis: str) -> int:
    return len(_CITATION_RE.findall(synthesis))


def _has_uncited_math(synthesis: str) -> bool:
    """Soft check: returns True if there are math-style figures with no citations nearby."""
    if not _INLINE_MATH_RE.search(synthesis):
        return False
    return _citation_count(synthesis) == 0


async def validate_and_repair(
    synthesis: str,
    intent: str,
    generator_fn: Callable[[str], object] | None = None,
) -> tuple[str, list[str]]:
    """Validate synthesis structure and attempt a single repair pass on failure.

    Parameters
    ----------
    synthesis:
        The full text produced by the synthesis LLM call.
    intent:
        The classified intent (used to look up INTENT_SCHEMA).
    generator_fn:
        An async callable that accepts a repair prompt string and returns the
        repaired section text. If None, skipped (warnings only, no repair).

    Returns
    -------
    (repaired_synthesis, warnings)
        warnings is a list of plain-English strings describing any issues found
        (both hard failures and soft hints). An empty list means clean.
    """
    schema = INTENT_SCHEMA.get(intent)
    if not schema:
        return synthesis, []

    warnings: list[str] = []
    repaired = synthesis

    # ── Hard check 1: required sections ────────────────────────────────────────
    missing = _missing_sections(synthesis, schema["required_sections"])
    if missing:
        missing_str = ", ".join(missing)
        logger.info("Validator: missing sections [%s] for intent=%s", missing_str, intent)

        if generator_fn is not None:
            repair_prompt = (
                f"The analysis is missing these required sections: {missing_str}. "
                f"Add them now. Base your content only on what was already established "
                f"in the analysis above — do not introduce new facts. "
                f"Use the same language and citation format ([S<n>]) as the rest of the response."
            )
            try:
                repair_text = await generator_fn(repair_prompt)
                if repair_text:
                    repaired = repaired + "\n\n" + str(repair_text)
                    # Re-check after repair
                    still_missing = _missing_sections(repaired, schema["required_sections"])
                    if still_missing:
                        for s in still_missing:
                            repaired += f"\n\n**{s.capitalize()}**\n[⚠ section incomplete]"
                        warnings.append(f"Could not auto-repair missing sections: {', '.join(still_missing)}")
                else:
                    for s in missing:
                        repaired += f"\n\n**{s.capitalize()}**\n[⚠ section incomplete]"
                    warnings.append(f"Repair returned empty for sections: {missing_str}")
            except Exception as exc:
                logger.warning("Repair pass failed: %s", exc)
                for s in missing:
                    repaired += f"\n\n**{s.capitalize()}**\n[⚠ section incomplete]"
                warnings.append(f"Repair failed ({exc}); sections marked incomplete: {missing_str}")
        else:
            for s in missing:
                repaired += f"\n\n**{s.capitalize()}**\n[⚠ section incomplete]"
            warnings.append(f"Missing required sections (no repair available): {missing_str}")

    # ── Hard check 2: minimum citations ────────────────────────────────────────
    n_citations = _citation_count(repaired)
    min_required = schema["min_citations"]
    if n_citations < min_required:
        warnings.append(
            f"Low citation count: found {n_citations}, expected ≥{min_required}. "
            "Consider verifying key claims against source references."
        )

    # ── Soft check: uncited math ────────────────────────────────────────────────
    if _has_uncited_math(repaired):
        warnings.append(
            "Soft: synthesis contains numeric ratios/percentages but no citation references. "
            "Verify that derived figures were computed via the calculate() tool."
        )

    return repaired, warnings
