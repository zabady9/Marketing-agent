"""
Markdown document export — two independent modes sharing one renderer:

Mode A (build_report_markdown): deterministic, no LLM — renders an analysis
report's steps and blocks straight into markdown. Every block type has a
generic rendering, so any analysis exports completely.

Mode B (synthesize_chat_export): a chat conversation has no fixed structure
to walk, so it needs a synthesis pass — one narrow, non-tool-calling LLM call.
"""

from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

from app.models import ChatSession, StudyResult


def _cell(value: object) -> str:
    return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")


def _md_table(columns: list[str], rows: list[list[object]]) -> list[str]:
    lines = ["| " + " | ".join(_cell(c) for c in columns) + " |", "|" + "---|" * len(columns)]
    lines += ["| " + " | ".join(_cell(c) for c in row) + " |" for row in rows]
    return lines


def _render_block(b: dict) -> list[str]:
    t = b.get("type")
    out: list[str] = [f"#### {b['title']}"] if b.get("title") else []
    if t == "answer":
        out += [f"**{b.get('headline', '')}**", "", b.get("body", ""), f"*Confidence: {b.get('confidence')}*"]
    elif t == "text":
        out.append(b.get("markdown", ""))
    elif t == "stats":
        out += [
            f"- **{i.get('label')}**: {i.get('value')} {i.get('unit', '')}".rstrip()
            + (f" — {i['note']}" if i.get("note") else "")
            + f" *({i.get('basis')})*"
            for i in b.get("items", [])
        ]
    elif t == "chart":
        cols = [b.get("x_label") or ""] + [s["name"] for s in b.get("series", [])]
        rows = [
            [cat] + [s["data"][i] if i < len(s["data"]) else "" for s in b.get("series", [])]
            for i, cat in enumerate(b.get("categories", []))
        ]
        out += _md_table(cols, rows)
    elif t == "table":
        out += _md_table(b.get("columns", []), b.get("rows", []))
        if b.get("caption"):
            out.append(f"*{b['caption']}*")
    elif t == "comparison":
        rows = [[opt] + list(scores) for opt, scores in zip(b.get("options", []), b.get("scores", []))]
        out += _md_table([""] + b.get("criteria", []), rows)
        if b.get("verdict"):
            out.append(f"**{b['verdict']}**")
    elif t == "board":
        for cell in b.get("cells", []):
            out.append(f"**{cell.get('title')}**" + (f" — {cell['subtitle']}" if cell.get("subtitle") else ""))
            out += [
                f"- {i.get('label')}" + (f": {i['detail']}" if i.get("detail") else "")
                for i in cell.get("items", [])
            ]
            out.append("")
    elif t == "matrix":
        out.append(f"*{b.get('x_axis')} (x) vs {b.get('y_axis')} (y), 0-10*")
        out += _md_table(["", "x", "y"], [[p["label"], p["x"], p["y"]] for p in b.get("points", [])])
    elif t == "diagram":
        out += ["```mermaid", b.get("mermaid", ""), "```"]
    elif t == "timeline":
        for ph in b.get("phases", []):
            span = " – ".join(x for x in (ph.get("start"), ph.get("end")) if x)
            out.append(f"**{ph.get('label')}**" + (f" ({span})" if span else ""))
            out += [f"- {i}" for i in ph.get("items", [])]
    elif t == "list":
        for n, i in enumerate(b.get("items", []), start=1):
            bullet = f"{n}." if b.get("style") == "numbered" else "- [ ]" if b.get("style") == "checklist" else "-"
            out.append(f"{bullet} **{i.get('label')}**" + (f": {i['detail']}" if i.get("detail") else ""))
    sources = [c.get("title") or c.get("url") for c in b.get("citations", [])]
    if sources:
        out.append("*Sources: " + "; ".join(sources) + "*")
    out.append("")
    return out


def build_report_markdown(studies: list[StudyResult]) -> str:
    """Deterministic markdown for one or more analyses — one top-level `#`
    heading per analysis, its steps nested underneath. No LLM involvement."""
    parts: list[str] = []
    for study in studies:
        report = study.report or {}
        parts.append(f"# {study.title or report.get('title') or 'Analysis'}")
        if study.goal:
            parts.append(f"*Question: {study.goal}*")
        parts.append("")
        answer = report.get("answer")
        if answer:
            parts += ["## Answer", f"**{answer.get('headline', '')}**", "", answer.get("body", ""), ""]
        for key, heading in (("findings", "Key findings"), ("recommendations", "Recommendations")):
            if report.get(key):
                parts += [f"## {heading}"] + [f"- {x}" for x in report[key]] + [""]
        for step in report.get("steps", []):
            parts.append(f"## {step.get('title')}")
            if step.get("summary"):
                parts += [step["summary"], ""]
            for block in step.get("blocks", []):
                parts += _render_block(block)
        if report.get("sources"):
            parts += ["## Sources"] + [
                f"{n}. [{c.get('title') or c['url']}]({c['url']})" for n, c in enumerate(report["sources"], 1)
            ] + [""]
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
    grounding = f"\n\nGrounding analysis data:\n{build_report_markdown(studies)}" if studies else ""

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
