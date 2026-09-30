"""
Tests for app.services.artifact_generation's deterministic drivers — every
MCP call is mocked at app.services.mcp_clients.get_allowed_tool, so these
never make a real HTTP call to the Presenton/mcp-ms-office-documents/PDF
sibling services (that's covered separately by the optional, explicitly-
marked integration test against the real docker-compose stack).
"""

from __future__ import annotations

import base64
import os
import tempfile
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import ToolMessage

import app.services.artifact_generation as artifact_generation_module
from app.schemas.artifact import DocumentOutline, DocumentSection, PresentationOutline, SlideContent
from app.services.artifact_generation import (
    ArtifactGenerationError,
    generate_docx,
    generate_pdf,
    generate_pptx,
)


def _file_result(*, base64: str, filename: str) -> ToolMessage:
    return ToolMessage(
        content=[{"type": "file", "base64": base64, "filename": filename}],
        tool_call_id="call-1",
        status="success",
    )


def _text_result(text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id="call-1", status="success")


def _error_result(text: str) -> ToolMessage:
    return ToolMessage(content=text, tool_call_id="call-1", status="error")


def _presenton_result(structured: dict) -> ToolMessage:
    """Mirrors Presenton's real job envelope, confirmed against a live run —
    surfaced by langchain-mcp-adapters as .artifact["structured_content"],
    same as docgen's DocumentEnvelope."""
    return ToolMessage(
        content=[{"type": "text", "text": str(structured)}],
        artifact={"structured_content": structured},
        tool_call_id="call-1",
        status="success",
    )


@pytest.fixture
def tmp_dirs():
    with tempfile.TemporaryDirectory() as storage_dir, tempfile.TemporaryDirectory() as shared_dir:
        yield storage_dir, shared_dir


class TestGeneratePptx:
    async def test_polls_until_completed_then_downloads_file(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        payload = b"fake pptx bytes"

        start_tool = AsyncMock()
        start_tool.ainvoke = AsyncMock(
            return_value=_presenton_result({"id": "task-1", "status": "pending"})
        )
        status_tool = AsyncMock()
        status_tool.ainvoke = AsyncMock(
            side_effect=[
                _presenton_result({"id": "task-1", "status": "pending", "message": "Generating slides"}),
                _presenton_result(
                    {
                        "id": "task-1",
                        "status": "completed",
                        "data": {"path": "http://presenton/app_data/exports/x.pptx"},
                    }
                ),
            ]
        )

        async def _get_tool(server_name, tool_name):
            assert server_name == "presenton"
            return {"start_standard_presentation": start_tool, "get_job_status": status_tool}[tool_name]

        monkeypatch.setattr(artifact_generation_module, "get_allowed_tool", _get_tool)
        monkeypatch.setattr(artifact_generation_module, "_PRESENTON_POLL_INTERVAL_SECONDS", 0)
        download_mock = AsyncMock(return_value=payload)
        monkeypatch.setattr(artifact_generation_module, "_download_presenton_file", download_mock)

        outline = PresentationOutline(
            title="Deck", slides=[SlideContent(heading="Intro", bullets=["a", "b"])]
        )
        result = await generate_pptx(
            outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
            project_id="proj-1", artifact_id="art-1", presenton_api_key="key-123",
        )

        assert result.filename == "art-1.pptx"
        with open(result.path, "rb") as f:
            assert f.read() == payload
        download_mock.assert_awaited_once_with(
            "http://presenton/app_data/exports/x.pptx", presenton_api_key="key-123"
        )
        # The first status poll (still "pending") must not be mistaken for done.
        assert status_tool.ainvoke.await_count == 2

    async def test_raises_when_job_status_is_failed(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        start_tool = AsyncMock()
        start_tool.ainvoke = AsyncMock(
            return_value=_presenton_result({"id": "task-1", "status": "pending"})
        )
        status_tool = AsyncMock()
        status_tool.ainvoke = AsyncMock(
            return_value=_presenton_result(
                {"id": "task-1", "status": "failed", "error": "template not found"}
            )
        )

        async def _get_tool(server_name, tool_name):
            return {"start_standard_presentation": start_tool, "get_job_status": status_tool}[tool_name]

        monkeypatch.setattr(artifact_generation_module, "get_allowed_tool", _get_tool)
        monkeypatch.setattr(artifact_generation_module, "_PRESENTON_POLL_INTERVAL_SECONDS", 0)

        outline = PresentationOutline(title="Deck", slides=[SlideContent(heading="Intro", bullets=["a"])])
        with pytest.raises(ArtifactGenerationError, match="template not found"):
            await generate_pptx(
                outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
                project_id="proj-1", artifact_id="art-1", presenton_api_key="key-123",
            )

    async def test_raises_readable_message_when_error_is_a_status_dict(self, tmp_dirs, monkeypatch):
        """Regression test: a real run returned status="error" (not "failed")
        with error={"status_code": 503, "detail": "..."} rather than a plain
        string — the human-readable detail must surface, not a raw dict repr."""
        storage_dir, shared_dir = tmp_dirs
        start_tool = AsyncMock()
        start_tool.ainvoke = AsyncMock(
            return_value=_presenton_result({"id": "task-1", "status": "pending"})
        )
        status_tool = AsyncMock()
        status_tool.ainvoke = AsyncMock(
            return_value=_presenton_result(
                {
                    "id": "task-1",
                    "status": "error",
                    "error": {"status_code": 503, "detail": "This model is currently experiencing high demand."},
                }
            )
        )

        async def _get_tool(server_name, tool_name):
            return {"start_standard_presentation": start_tool, "get_job_status": status_tool}[tool_name]

        monkeypatch.setattr(artifact_generation_module, "get_allowed_tool", _get_tool)
        monkeypatch.setattr(artifact_generation_module, "_PRESENTON_POLL_INTERVAL_SECONDS", 0)

        outline = PresentationOutline(title="Deck", slides=[SlideContent(heading="Intro", bullets=["a"])])
        with pytest.raises(ArtifactGenerationError, match="experiencing high demand"):
            await generate_pptx(
                outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
                project_id="proj-1", artifact_id="art-1", presenton_api_key="key-123",
            )

    async def test_raises_on_mcp_error_result_from_start_call(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        tool = AsyncMock()
        tool.ainvoke = AsyncMock(return_value=_error_result("Presenton is down"))
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        outline = PresentationOutline(title="Deck", slides=[SlideContent(heading="Intro", bullets=["a"])])
        with pytest.raises(ArtifactGenerationError, match="Presenton is down"):
            await generate_pptx(
                outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
                project_id="proj-1", artifact_id="art-1", presenton_api_key="key-123",
            )


class TestGenerateDocx:
    async def test_resolves_filename_reported_in_text_against_shared_output_dir(
        self, tmp_dirs, monkeypatch
    ):
        storage_dir, shared_dir = tmp_dirs
        payload = b"fake docx bytes"
        with open(os.path.join(shared_dir, "art-2.docx"), "wb") as f:
            f.write(payload)

        tool = AsyncMock()
        tool.ainvoke = AsyncMock(return_value=_text_result("File created: art-2.docx"))
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        outline = DocumentOutline(title="Report", sections=[DocumentSection(heading="Overview", body="Text.")])
        result = await generate_docx(
            outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
            project_id="proj-1", artifact_id="art-2",
        )

        assert result.filename == "art-2.docx"
        with open(result.path, "rb") as f:
            assert f.read() == payload

    async def test_reported_absolute_path_is_resolved_by_basename_only(self, tmp_dirs, monkeypatch):
        """Regression test: mcp-ms-office-documents reports its OWN internal
        container path (e.g. "/app/output/<id>.docx") — confirmed live that
        treating that path as directly readable on this backend's filesystem
        fails, since it's a different container. Only the basename is
        meaningful, resolved against our own shared_output_dir."""
        storage_dir, shared_dir = tmp_dirs
        payload = b"fake docx bytes"
        with open(os.path.join(shared_dir, "art-9.docx"), "wb") as f:
            f.write(payload)

        tool = AsyncMock()
        tool.ainvoke = AsyncMock(
            return_value=_text_result("File created: /app/output/art-9.docx")
        )
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        outline = DocumentOutline(title="Report", sections=[DocumentSection(heading="Overview", body="Text.")])
        result = await generate_docx(
            outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
            project_id="proj-1", artifact_id="art-9",
        )

        assert result.filename == "art-9.docx"
        with open(result.path, "rb") as f:
            assert f.read() == payload

    async def test_raises_when_reported_file_is_not_on_disk(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        tool = AsyncMock()
        tool.ainvoke = AsyncMock(return_value=_text_result("File created: missing.docx"))
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        outline = DocumentOutline(title="Report", sections=[DocumentSection(heading="Overview", body="Text.")])
        with pytest.raises(ArtifactGenerationError, match="isn't readable"):
            await generate_docx(
                outline, storage_dir=storage_dir, shared_output_dir=shared_dir,
                project_id="proj-1", artifact_id="art-3",
            )


def _docgen_result(*, inline_base64: str | None) -> ToolMessage:
    """Mirrors docgen_render_pdf's real DocumentEnvelope shape — delivered as
    MCP structuredContent, surfaced by langchain-mcp-adapters as the
    ToolMessage's `.artifact["structured_content"]["document"]`, not a
    content block. Confirmed live against a real docgen-mcp-server response —
    the envelope is nested one level under "document", not top-level."""
    document = {"documentId": "doc-1", "pageCount": 1}
    if inline_base64 is not None:
        document["inlineBase64"] = inline_base64
    return ToolMessage(
        content="Rendered 1-page PDF.",
        artifact={"structured_content": {"document": document}},
        tool_call_id="call-1",
        status="success",
    )


class TestGeneratePdf:
    async def test_writes_inline_base64_from_structured_content(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        payload = b"%PDF-1.4 fake"
        tool = AsyncMock()
        tool.ainvoke = AsyncMock(
            return_value=_docgen_result(inline_base64=base64.b64encode(payload).decode())
        )
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        result = await generate_pdf(
            "# Report\n\nBody.", "Report",
            storage_dir=storage_dir, shared_output_dir=shared_dir,
            project_id="proj-1", artifact_id="art-4",
        )
        assert result.filename == "art-4.pdf"
        with open(result.path, "rb") as f:
            assert f.read() == payload

    async def test_raises_when_report_exceeds_inline_size_limit(self, tmp_dirs, monkeypatch):
        storage_dir, shared_dir = tmp_dirs
        tool = AsyncMock()
        tool.ainvoke = AsyncMock(return_value=_docgen_result(inline_base64=None))
        monkeypatch.setattr(
            artifact_generation_module, "get_allowed_tool", AsyncMock(return_value=tool)
        )

        with pytest.raises(ArtifactGenerationError, match="didn't return inline file bytes"):
            await generate_pdf(
                "# Report\n\nBody.", "Report",
                storage_dir=storage_dir, shared_output_dir=shared_dir,
                project_id="proj-1", artifact_id="art-4",
            )


class TestWriteArtifactFileAtomicity:
    def test_failure_mid_write_leaves_no_partial_file_at_final_path(self, tmp_dirs, monkeypatch):
        storage_dir, _ = tmp_dirs

        real_open = open

        def _boom(path, mode="r", *a, **kw):
            if str(path).endswith(".tmp"):
                raise OSError("disk full")
            return real_open(path, mode, *a, **kw)

        monkeypatch.setattr("builtins.open", _boom)
        with pytest.raises(OSError):
            artifact_generation_module._write_artifact_file(
                b"data", storage_dir=storage_dir, project_id="proj-1", artifact_id="art-5", ext="pptx"
            )
        final_path = os.path.join(storage_dir, "proj-1", "art-5.pptx")
        assert not os.path.exists(final_path)
