"""
Markdown document export — two independent modes sharing one renderer:

Mode A (build_study_markdown): deterministic, no LLM — walks a StudyResult's
already-computed `sections` data straight into markdown, in the same order
StudyReportPage's table of contents uses.

Mode B (synthesize_chat_export): a chat conversation has no fixed structure
to walk, so it needs a synthesis pass — same narrow, non-tool-calling
one-shot-LLM-call shape as app.services.study_title.generate_study_title,
not a full agent turn.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.models import ChatSession, StudyResult

# Same idea as chat_agent.py's _STUDY_CONTEXT_VERBOSE_KEYS (not imported
# directly — see that module's own note on why importing back would be
# circular): strip citation/trace noise a human reader doesn't need.
_VERBOSE_KEYS = frozenset(
    {"citations", "calculation_trace", "claim_type", "claim_types", "search_queries_used", "methodology"}
)

_SECTION_TITLES: dict[str, str] = {
    "executive_summary": "Executive Summary",
    "market_overview": "Market Overview",
    "competitive_landscape": "Competitive Landscape",
    "financial_feasibility": "Financial Feasibility",
    "risk_assessment": "Risk Assessment",
}
_SECTION_ORDER = list(_SECTION_TITLES)


def _humanize(key: str) -> str:
    return key.replace("_", " ").strip().capitalize()


def _render_value(value: object, depth: int) -> list[str]:
    indent = "  " * depth
    lines: list[str] = []
    if isinstance(value, dict):
        for key, val in value.items():
            if key in _VERBOSE_KEYS:
                continue
            if isinstance(val, (dict, list)) and val:
                lines.append(f"{indent}- **{_humanize(key)}**:")
                lines.extend(_render_value(val, depth + 1))
            else:
                lines.append(f"{indent}- **{_humanize(key)}**: {val}")
    elif isinstance(value, list):
        for item in value:
            if isinstance(item, (dict, list)):
                lines.extend(_render_value(item, depth))
            else:
                lines.append(f"{indent}- {item}")
    else:
        lines.append(f"{indent}{value}")
    return lines


def build_study_markdown(studies: list[StudyResult]) -> str:
    """Deterministic markdown for one or more studies — one top-level `#`
    heading per study, sections nested underneath. No LLM involvement."""
    parts: list[str] = []
    for study in studies:
        heading = study.title or f"Study {study.id[:8]}"
        parts.append(f"# {heading}")
        parts.append(
            f"*Status: {study.status} · Verdict: {study.verdict or 'n/a'} · "
            f"Confidence: {study.confidence_score if study.confidence_score is not None else 'n/a'}*"
        )
        parts.append("")
        for section_name in _SECTION_ORDER:
            envelope = (study.sections or {}).get(section_name)
            data = envelope.get("data") if isinstance(envelope, dict) else None
            if not data:
                continue
            parts.append(f"## {_SECTION_TITLES[section_name]}")
            parts.extend(_render_value(data, 0))
            parts.append("")
    return "\n".join(parts).strip() + "\n"


class _ChatExportResult(BaseModel):
    markdown: str


async def synthesize_chat_export(
    session: ChatSession,
    studies: list[StudyResult] | None,
    *,
    google_api_key: str,
    reasoning_model: str,
) -> str:
    """Turns a chat transcript (optionally grounded by specific studies)
    into a structured markdown document via one non-tool-calling LLM call —
    never invents facts beyond what's in the transcript/grounding data."""
    transcript = "\n\n".join(
        f"{m.role.upper()}: {m.content}"
        for m in session.messages
        if m.deleted_at is None and m.role in ("user", "assistant") and m.content
    )
    grounding = f"\n\nGrounding study data:\n{build_study_markdown(studies)}" if studies else ""

    llm = ChatGoogleGenerativeAI(model=reasoning_model, google_api_key=google_api_key, temperature=0.2)
    structured = llm.with_structured_output(_ChatExportResult)
    result: _ChatExportResult = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You turn a business-analyst chat conversation into a clean, "
                    "well-structured markdown document a founder could share with a "
                    "stakeholder — headings, a short summary, and the concrete points "
                    "and figures actually discussed. Do not invent facts that aren't "
                    "in the conversation or grounding data below."
                )
            ),
            HumanMessage(content=f"CONVERSATION:\n{transcript}{grounding}"),
        ]
    )
    return result.markdown
