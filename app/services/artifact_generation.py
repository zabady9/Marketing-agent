"""Deterministic drivers that turn a validated outline (app.schemas.artifact)
into a real DOCX/PPTX/PDF file by calling one of the three sibling MCP
services (see app.services.mcp_clients / docker-compose.yml) — never a
freeform sub-agent operating those services' raw tool surface.

Each service's response shape was confirmed against a real running instance
rather than guessed from docs:
- Presenton (pptx): an async job — start_standard_presentation returns a
  task id, get_job_status is polled until "completed", whose data.path is a
  directly-fetchable URL on Presenton's own nginx, downloaded with the same
  bearer key used for the MCP call. See generate_pptx/_poll_presenton_job.
- docgen (pdf): synchronous, delivers the file as inline base64 in the MCP
  result's structuredContent. See generate_pdf/_extract_docgen_inline_bytes.
- mcp-ms-office-documents (docx): NOT yet confirmed against a live run — its
  "LOCAL" storage strategy docs stop short of a concrete example, so
  _extract_bytes_and_filename defensively handles either an embedded blob or
  a filename/path resolved against a shared Docker volume
  (settings.mcp_shared_output_dir). Confirm and simplify once exercised for
  real, the same way generate_pptx/generate_pdf were.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
import uuid
from dataclasses import dataclass

import httpx
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langchain_google_genai import ChatGoogleGenerativeAI

from app.models.artifact import Artifact
from app.schemas.artifact import DocumentOutline, PresentationOutline, SlideContent
from app.services.mcp_clients import get_allowed_tool

logger = logging.getLogger(__name__)

# Wraps every single MCP call (session setup + the call itself), including
# start_standard_presentation — confirmed live that Presenton doesn't return
# a task id instantly; it does real work (LLM outline expansion) first, and
# on a cross-Cloud-Run-service hop this comfortably exceeded 60s, tearing
# down and reopening the MCP session before ever getting a clean response.
_CALL_TIMEOUT_SECONDS = 180
_FILENAME_RE = re.compile(r"[\w.\-/]+\.(?:docx|pptx|pdf)", re.IGNORECASE)
# Confirmed against a real run: a 2-slide deck took ~70s end to end (queued ->
# layout selection -> slide generation -> asset fetch -> completed) — scaled
# up generously for up to 30 slides.
_PRESENTON_POLL_INTERVAL_SECONDS = 4
_PRESENTON_POLL_TIMEOUT_SECONDS = 600


class ArtifactGenerationError(RuntimeError):
    pass


@dataclass
class ArtifactFile:
    path: str
    filename: str
    size_bytes: int


def _outline_to_markdown(outline: DocumentOutline) -> str:
    parts = [f"# {outline.title}", ""]
    for section in outline.sections:
        parts.append(f"## {section.heading}")
        parts.append(section.body)
        parts.append("")
    return "\n".join(parts).strip() + "\n"


def _slide_to_markdown(slide: SlideContent) -> str:
    lines = [f"# {slide.heading}", ""]
    lines.extend(f"- {bullet}" for bullet in slide.bullets)
    if slide.notes:
        lines.append("")
        lines.append(f"_Notes: {slide.notes}_")
    return "\n".join(lines)


def _filename_from_text(text: str) -> str | None:
    match = _FILENAME_RE.search(text)
    return match.group(0) if match else None


async def _invoke(server_name: str, tool_name: str, args: dict) -> ToolMessage:
    tool = await get_allowed_tool(server_name, tool_name)
    call_id = f"{tool_name}-{uuid.uuid4().hex[:8]}"
    try:
        result = await asyncio.wait_for(
            tool.ainvoke({"type": "tool_call", "name": tool_name, "args": args, "id": call_id}),
            timeout=_CALL_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise ArtifactGenerationError(
            f"{server_name}/{tool_name} timed out after {_CALL_TIMEOUT_SECONDS}s"
        ) from exc
    if not isinstance(result, ToolMessage):
        raise ArtifactGenerationError(
            f"Unexpected result type from {server_name}/{tool_name}: {type(result)!r}"
        )
    if result.status == "error":
        raise ArtifactGenerationError(f"{server_name}/{tool_name} failed: {result.content}")
    return result


def _extract_bytes_and_filename(message: ToolMessage, *, shared_output_dir: str) -> tuple[bytes, str]:
    content = message.content
    blocks = content if isinstance(content, list) else [content]
    text_parts: list[str] = []
    for block in blocks:
        if isinstance(block, dict) and block.get("type") == "file" and block.get("base64"):
            filename = block.get("filename") or "artifact"
            return base64.b64decode(block["base64"]), filename
        if isinstance(block, str):
            text_parts.append(block)
        elif isinstance(block, dict) and block.get("type") == "text":
            text_parts.append(str(block.get("text", "")))

    text = "\n".join(p for p in text_parts if p)
    reported_path = _filename_from_text(text)
    if reported_path is None:
        raise ArtifactGenerationError(
            f"Could not determine the generated file's name/path from the tool "
            f"response (no embedded file block and no filename found in text): {text!r}"
        )
    # The reported path (e.g. "/app/output/<id>.docx") is the GENERATING
    # service's own internal path inside its own container — never valid on
    # this backend's filesystem directly, confirmed live (that exact path
    # doesn't exist here). Only the basename is meaningful; resolve it
    # against wherever this backend has the same shared volume mounted.
    filename = os.path.basename(reported_path)
    candidate_path = os.path.join(shared_output_dir, filename)
    if not os.path.isfile(candidate_path):
        raise ArtifactGenerationError(
            f"Tool reported file '{reported_path}' but '{filename}' isn't readable at "
            f"'{candidate_path}' — check that settings.mcp_shared_output_dir matches the "
            "service's mounted output volume."
        )
    with open(candidate_path, "rb") as f:
        return f.read(), filename


def _write_artifact_file(data: bytes, *, storage_dir: str, project_id: str, artifact_id: str, ext: str) -> ArtifactFile:
    project_dir = os.path.join(storage_dir, project_id)
    os.makedirs(project_dir, exist_ok=True)
    filename = f"{artifact_id}.{ext}"
    path = os.path.join(project_dir, filename)
    tmp_path = f"{path}.tmp"
    try:
        with open(tmp_path, "wb") as f:
            f.write(data)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise
    return ArtifactFile(path=path, filename=filename, size_bytes=len(data))


async def _poll_presenton_job(task_id: str) -> dict:
    """Polls get_job_status until Presenton's async presentation.generate job
    reaches a terminal state. Confirmed against real runs: status goes
    "pending" (with a human-readable `message` tracking progress — queued,
    layout selection, slide generation, asset fetch) -> "completed", with
    `data.path` set to a downloadable URL; or -> "error" (e.g. a transient
    503 from Presenton's own upstream text-generation model under high
    demand), with `error` set to a {"status_code", "detail"} dict rather
    than a plain string."""
    elapsed = 0.0
    while elapsed < _PRESENTON_POLL_TIMEOUT_SECONDS:
        message = await _invoke("presenton", "get_job_status", {"id": task_id})
        structured = (message.artifact or {}).get("structured_content") or {}
        status = structured.get("status")
        if status == "completed":
            return structured
        if status in ("failed", "error"):
            error = structured.get("error")
            detail = error.get("detail") if isinstance(error, dict) else error
            raise ArtifactGenerationError(
                f"Presenton presentation generation failed: "
                f"{detail or structured.get('message')}"
            )
        await asyncio.sleep(_PRESENTON_POLL_INTERVAL_SECONDS)
        elapsed += _PRESENTON_POLL_INTERVAL_SECONDS
    raise ArtifactGenerationError(
        f"Presenton presentation generation did not complete within "
        f"{_PRESENTON_POLL_TIMEOUT_SECONDS}s (task {task_id})"
    )


async def _download_presenton_file(url: str, *, presenton_api_key: str) -> bytes:
    """`data.path` from a completed job is a directly-fetchable URL on
    Presenton's own nginx (e.g. http://presenton/app_data/exports/...) —
    reachable from this container over the Docker network. That route is
    gated by an auth_request subrequest that forwards the Authorization
    header through to Presenton's own /api/v1/auth/verify, which accepts the
    same bearer key used for the MCP call — no separate credential needed."""
    headers = {"Authorization": f"Bearer {presenton_api_key}"} if presenton_api_key else {}
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.get(url, headers=headers)
        response.raise_for_status()
        return response.content


async def generate_pptx(
    outline: PresentationOutline,
    *,
    storage_dir: str,
    shared_output_dir: str,
    project_id: str,
    artifact_id: str,
    presenton_api_key: str,
) -> ArtifactFile:
    # Presenton delivers the finished file via a fetchable URL, not a shared
    # volume — shared_output_dir is accepted but unused, kept only so all
    # three generate_* functions share one call shape at the chat_agent.py
    # call sites.
    del shared_output_dir

    start_message = await _invoke(
        "presenton",
        "start_standard_presentation",
        {
            "content": outline.title,
            "slides_markdown": [_slide_to_markdown(slide) for slide in outline.slides],
            "n_slides": len(outline.slides),
            "template": "general",
            "export_as": "pptx",
            "include_title_slide": True,
        },
    )
    started = (start_message.artifact or {}).get("structured_content") or {}
    task_id = started.get("id")
    if not task_id:
        raise ArtifactGenerationError(f"Presenton didn't return a task id: {started}")

    completed = await _poll_presenton_job(task_id)
    file_url = (completed.get("data") or {}).get("path")
    if not file_url:
        raise ArtifactGenerationError(f"Presenton job completed but returned no file path: {completed}")

    data = await _download_presenton_file(file_url, presenton_api_key=presenton_api_key)
    return _write_artifact_file(
        data, storage_dir=storage_dir, project_id=project_id, artifact_id=artifact_id, ext="pptx"
    )


async def generate_docx(
    outline: DocumentOutline, *, storage_dir: str, shared_output_dir: str, project_id: str, artifact_id: str
) -> ArtifactFile:
    markdown = _outline_to_markdown(outline)
    message = await _invoke(
        "office_docs",
        "create_word_from_markdown",
        {"markdown_content": markdown, "file_name": artifact_id, "add_unique_prefix": False},
    )
    data, _ = _extract_bytes_and_filename(message, shared_output_dir=shared_output_dir)
    return _write_artifact_file(
        data, storage_dir=storage_dir, project_id=project_id, artifact_id=artifact_id, ext="docx"
    )


def _extract_docgen_inline_bytes(message: ToolMessage) -> bytes:
    """docgen_render_pdf's response shape is confirmed (unlike the pptx/docx
    servers' — see _extract_bytes_and_filename): every render returns a
    DocumentEnvelope in the MCP result's structuredContent, surfaced here as
    message.artifact["structured_content"]["document"], with `inlineBase64`
    populated whenever the file is at or under DOCGEN_INLINE_MAX_BYTES
    (default 5MB — comfortably above a text report). No shared volume needed
    for this one. Confirmed live against a real docgen-mcp-server response —
    the envelope is nested one level under "document", not top-level."""
    structured = (message.artifact or {}).get("structured_content") or {}
    document = structured.get("document") or {}
    inline = document.get("inlineBase64")
    if not inline:
        raise ArtifactGenerationError(
            "docgen_render_pdf didn't return inline file bytes — the report "
            "likely exceeds DOCGEN_INLINE_MAX_BYTES. Resource-URI fallback "
            "(docgen://document/{id}) isn't implemented; either raise that "
            "env var or add a docgen_get_document/resource-read fallback here."
        )
    return base64.b64decode(inline)


async def generate_pdf(
    markdown: str, title: str, *, storage_dir: str, shared_output_dir: str, project_id: str, artifact_id: str
) -> ArtifactFile:
    # shared_output_dir is accepted but unused here — docgen delivers the
    # file inline, unlike the pptx/docx drivers — kept only so all three
    # generate_* functions share one call signature at the chat_agent.py
    # call sites.
    del shared_output_dir
    message = await _invoke("pdf", "docgen_render_pdf", {"source": {"markdown": markdown}})
    data = _extract_docgen_inline_bytes(message)
    return _write_artifact_file(
        data, storage_dir=storage_dir, project_id=project_id, artifact_id=artifact_id, ext="pdf"
    )


async def revise_artifact(
    artifact: Artifact,
    instructions: str,
    *,
    google_api_key: str,
    reasoning_model: str,
    storage_dir: str,
    shared_output_dir: str,
    new_artifact_id: str,
    presenton_api_key: str = "",
) -> tuple[ArtifactFile, dict]:
    """One-shot structured LLM edit of `artifact.spec_json` (mirrors
    app.services.export.synthesize_chat_export's narrow, non-tool-calling
    call shape), then re-runs the matching deterministic driver. Returns the
    new file plus the revised spec (for the caller to persist onto a new
    Artifact row — this never mutates the original)."""
    schema = PresentationOutline if artifact.format == "pptx" else DocumentOutline
    llm = ChatGoogleGenerativeAI(model=reasoning_model, google_api_key=google_api_key, temperature=0.2)
    structured = llm.with_structured_output(schema)
    revised = await structured.ainvoke(
        [
            SystemMessage(
                content=(
                    "You revise a structured outline for a previously generated "
                    "document/presentation per the user's instructions. Preserve "
                    "everything not asked to change — this is an edit, not a rewrite."
                )
            ),
            HumanMessage(
                content=(
                    f"CURRENT OUTLINE (JSON):\n{json.dumps(artifact.spec_json, ensure_ascii=False)}\n\n"
                    f"REVISION INSTRUCTIONS:\n{instructions}"
                )
            ),
        ]
    )
    common = dict(
        storage_dir=storage_dir,
        shared_output_dir=shared_output_dir,
        project_id=artifact.project_id,
        artifact_id=new_artifact_id,
    )
    if artifact.format == "pptx":
        file = await generate_pptx(revised, presenton_api_key=presenton_api_key, **common)
    elif artifact.format == "docx":
        file = await generate_docx(revised, **common)
    else:
        file = await generate_pdf(_outline_to_markdown(revised), revised.title, **common)
    return file, revised.model_dump()
