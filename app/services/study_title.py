from __future__ import annotations

import asyncio
import json
import logging

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Mirrors detect_single_tool_intent/detect_language's bounded-latency,
# safe-fallback shape — title generation is a nice-to-have on top of an
# already-completed report, never something a slow/failed LLM call should be
# allowed to block or fail the report over.
_TITLE_TIMEOUT_SECONDS = 6.0
_MAX_TITLE_LEN = 160

# Same idea as chat_agent.py's _STUDY_CONTEXT_VERBOSE_KEYS (not imported
# directly — chat_agent.py imports FROM this module's callers, so importing
# back would be circular): strip citation/trace noise the model doesn't need
# to write a title, keep the substantive numbers/narrative.
_VERBOSE_KEYS = frozenset(
    {"citations", "calculation_trace", "claim_type", "claim_types", "search_queries_used", "methodology"}
)


def _trim(value: object) -> object:
    if isinstance(value, dict):
        return {k: _trim(v) for k, v in value.items() if k not in _VERBOSE_KEYS}
    if isinstance(value, list):
        return [_trim(v) for v in value]
    return value


class _TitleResult(BaseModel):
    title: str


async def generate_study_title(
    *,
    business_description: str,
    report_label: str,
    sections: dict,
    output_language: str,
    google_api_key: str,
    cheap_model: str,
) -> str | None:
    """A short, SPECIFIC title reflecting this run's actual findings (e.g.
    "Competitive Landscape: 5 Direct Rivals in the US Meal-Kit Market"), not
    a generic category label repeated across every run of the same
    capability. Returns None on any failure/timeout — callers must already
    have a deterministic fallback title, this is purely additive."""
    context_parts = []
    for section_name, envelope in (sections or {}).items():
        if section_name == "glossary":
            continue
        data = envelope.get("data") if isinstance(envelope, dict) else None
        if not data:
            continue
        context_parts.append(f"### {section_name}\n{json.dumps(_trim(data), ensure_ascii=False)}")

    if not context_parts:
        return None  # nothing substantive to title yet (e.g. every phase failed)

    human_content = f"Business: {business_description}\nReport: {report_label}\n\n" + "\n\n".join(
        context_parts
    )
    try:
        result: _TitleResult = await asyncio.wait_for(
            _gemini_generate_title(report_label, output_language, human_content, google_api_key, cheap_model),
            timeout=_TITLE_TIMEOUT_SECONDS,
        )
    except Exception:
        logger.warning("Study title generation failed; falling back", exc_info=True)
        return None

    title = result.title.strip().strip('"').strip()
    if not title:
        return None
    return title if len(title) <= _MAX_TITLE_LEN else title[: _MAX_TITLE_LEN - 3].rstrip() + "..."


async def _gemini_generate_title(
    report_label: str,
    output_language: str,
    human_content: str,
    google_api_key: str,
    cheap_model: str,
) -> _TitleResult:
    llm = ChatGoogleGenerativeAI(model=cheap_model, google_api_key=google_api_key, temperature=0.4)
    structured = llm.with_structured_output(_TitleResult)
    return await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You write short, specific report titles for a business feasibility "
                    "study tool. Given a business description, which report this is "
                    f"({report_label}), and the report's actual data, write ONE title "
                    "(max ~12 words) that reflects the SPECIFIC findings in this run — "
                    "name the concrete number, verdict, or standout fact, not just the "
                    "report category. E.g. 'Competitive Landscape: 5 Direct Rivals in the "
                    "US Meal-Kit Market', not 'Competitive Analysis Report'. Two different "
                    "runs of the same report type must read as different titles if their "
                    "data differs. No quotes, no trailing period, no markdown. "
                    f"Write the title in language: {output_language}."
                )
            ),
            HumanMessage(content=human_content),
        ]
    )
