"""
Tests for chat file attachments: the upload lifecycle routes
(app/routers/attachments.py) in local-storage mode, classification and text
extraction (app/services/attachment_processing.py), the send-time checks in
post_chat_message_endpoint, and how run_chat_turn replays attachments to the
model. Gemini File API calls are mocked; everything else runs for real on a
tmp dir.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime, timedelta

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.outputs import ChatGeneration, ChatResult

import app.config
import app.routers.attachments as attachments_router
import app.services.attachment_processing as processing_module
import app.services.chat_agent as chat_agent_module
from app.models import ChatAttachment, ChatSession
from app.sse import EventQueue


@pytest.fixture(autouse=True)
def _reset_settings_after():
    yield
    app.config._settings = None


@pytest.fixture
def upload_dir(db_session, tmp_path):
    settings = app.config.get_settings()
    settings.upload_storage = "local"
    settings.upload_local_dir = str(tmp_path)
    return tmp_path


@pytest.fixture
def started(monkeypatch):
    """Records start_processing calls instead of spawning a background task
    on the real SessionLocal. Tests then run process_attachment inline."""
    ids: list[str] = []
    monkeypatch.setattr(attachments_router, "start_processing", ids.append)
    return ids


def _make_session(db_session, project) -> ChatSession:
    session = ChatSession(project_id=project.id)
    db_session.add(session)
    db_session.commit()
    return session


def _base(project, session) -> str:
    return f"/api/projects/{project.id}/chat/sessions/{session.id}/attachments"


def _upload(client, project, session, filename: str, data: bytes, content_type: str = "") -> dict:
    created = client.post(
        _base(project, session),
        json={"filename": filename, "content_type": content_type, "size_bytes": len(data)},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    put = client.put(body["upload"]["url"], content=data, headers=body["upload"]["headers"])
    assert put.status_code == 200, put.text
    done = client.post(f"{_base(project, session)}/{body['attachment']['id']}/complete")
    assert done.status_code == 200, done.text
    return done.json()


async def _process(db_session, attachment_id: str) -> ChatAttachment:
    attachment = db_session.get(ChatAttachment, attachment_id)
    await processing_module.process_attachment(db_session, attachment)
    db_session.refresh(attachment)
    return attachment


def _docx_bytes() -> bytes:
    import docx

    document = docx.Document()
    document.add_paragraph("Our coffee cart sells lattes for $4.")
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _zip_bytes() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("a.bin", b"\x00\x01\x02" * 100)
    return buf.getvalue()


class TestUploadLifecycle:
    async def test_text_file_is_extracted(self, client, db_session, make_project, upload_dir, started):
        project = make_project()
        session = _make_session(db_session, project)

        summary = _upload(client, project, session, "notes.txt", b"hello from a text file", "text/plain")

        assert summary["status"] == "processing"
        assert started == [summary["id"]]
        attachment = await _process(db_session, summary["id"])
        assert attachment.status == "ready"
        assert attachment.kind == "text"
        assert attachment.extracted_text == "hello from a text file"
        assert attachment.storage_path.startswith(str(upload_dir))

    async def test_docx_is_extracted(self, client, db_session, make_project, upload_dir, started):
        project = make_project()
        session = _make_session(db_session, project)

        summary = _upload(client, project, session, "pitch.docx", _docx_bytes())
        attachment = await _process(db_session, summary["id"])

        assert attachment.kind == "text"
        assert "lattes for $4" in attachment.extracted_text

    async def test_unknown_binary_is_metadata_only(self, client, db_session, make_project, upload_dir, started):
        project = make_project()
        session = _make_session(db_session, project)

        summary = _upload(client, project, session, "bundle.zip", _zip_bytes())
        attachment = await _process(db_session, summary["id"])

        assert attachment.status == "ready"
        assert attachment.kind == "metadata_only"
        assert attachment.content_type == "application/zip"

    async def test_image_goes_to_gemini(self, client, db_session, make_project, upload_dir, started, monkeypatch):
        calls = []

        def fake_upload(path, content_type, display_name):
            calls.append((content_type, display_name))
            return "https://generativelanguage.googleapis.com/v1beta/files/abc", datetime(2030, 1, 1)

        monkeypatch.setattr(processing_module, "_upload_to_gemini", fake_upload)
        project = make_project()
        session = _make_session(db_session, project)
        png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64

        summary = _upload(client, project, session, "logo.png", png, "image/png")
        attachment = await _process(db_session, summary["id"])

        assert calls == [("image/png", "logo.png")]
        assert attachment.kind == "gemini_file"
        assert attachment.gemini_file_uri.endswith("/files/abc")

    async def test_gemini_failure_marks_failed_but_sendable(
        self, client, db_session, make_project, upload_dir, started, monkeypatch
    ):
        def boom(*args):
            raise RuntimeError("unsupported")

        monkeypatch.setattr(processing_module, "_upload_to_gemini", boom)
        project = make_project()
        session = _make_session(db_session, project)

        summary = _upload(client, project, session, "clip.mp4", b"\x00\x00\x00\x18ftypmp42" + b"\x00" * 32)
        attachment = await _process(db_session, summary["id"])

        assert attachment.status == "failed"
        assert attachment.kind == "metadata_only"
        assert "unsupported" in attachment.error

    def test_filename_is_sanitized(self, client, db_session, make_project, upload_dir):
        project = make_project()
        session = _make_session(db_session, project)

        resp = client.post(
            _base(project, session),
            json={"filename": "../../etc/pass:wd", "content_type": "", "size_bytes": 3},
        )

        assert resp.status_code == 201
        attachment = db_session.get(ChatAttachment, resp.json()["attachment"]["id"])
        assert attachment.filename == "pass_wd"
        assert ".." not in attachment.storage_path

    def test_rejects_oversize(self, client, db_session, make_project, upload_dir):
        project = make_project()
        session = _make_session(db_session, project)
        too_big = app.config.get_settings().max_upload_bytes + 1

        resp = client.post(
            _base(project, session), json={"filename": "big.bin", "size_bytes": too_big}
        )

        assert resp.status_code == 413

    def test_put_larger_than_declared_is_rejected(self, client, db_session, make_project, upload_dir):
        project = make_project()
        session = _make_session(db_session, project)
        body = client.post(_base(project, session), json={"filename": "a.txt", "size_bytes": 2}).json()

        resp = client.put(body["upload"]["url"], content=b"way more than two bytes")

        assert resp.status_code == 413

    def test_complete_without_upload_is_409(self, client, db_session, make_project, upload_dir):
        project = make_project()
        session = _make_session(db_session, project)
        body = client.post(_base(project, session), json={"filename": "a.txt", "size_bytes": 2}).json()

        resp = client.post(f"{_base(project, session)}/{body['attachment']['id']}/complete")

        assert resp.status_code == 409

    def test_404_from_another_session(self, client, db_session, make_project, upload_dir):
        project = make_project()
        session_a = _make_session(db_session, project)
        session_b = _make_session(db_session, project)
        body = client.post(_base(project, session_a), json={"filename": "a.txt", "size_bytes": 2}).json()

        resp = client.get(f"{_base(project, session_b)}/{body['attachment']['id']}")

        assert resp.status_code == 404

    def test_delete_unsent(self, client, db_session, make_project, upload_dir, started):
        project = make_project()
        session = _make_session(db_session, project)
        summary = _upload(client, project, session, "a.txt", b"hi")
        path = db_session.get(ChatAttachment, summary["id"]).storage_path

        resp = client.delete(f"{_base(project, session)}/{summary['id']}")

        assert resp.status_code == 204
        assert client.get(f"{_base(project, session)}/{summary['id']}").status_code == 404
        import os

        assert not os.path.exists(path)


class TestSendChecks:
    def _messages_url(self, project, session) -> str:
        return f"/api/projects/{project.id}/chat/sessions/{session.id}/messages"

    def test_empty_message_without_attachments_is_422(self, client, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)

        resp = client.post(self._messages_url(project, session), json={"content": "  "})

        assert resp.status_code == 422

    def test_still_processing_attachment_is_409(self, client, db_session, make_project, upload_dir, started):
        project = make_project()
        session = _make_session(db_session, project)
        summary = _upload(client, project, session, "a.txt", b"hi")

        resp = client.post(
            self._messages_url(project, session), json={"content": "", "attachment_ids": [summary["id"]]}
        )

        assert resp.status_code == 409

    def test_unknown_attachment_is_404(self, client, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)

        resp = client.post(
            self._messages_url(project, session), json={"content": "x", "attachment_ids": ["nope"]}
        )

        assert resp.status_code == 404


class _CapturingModel(BaseChatModel):
    captured: list = []

    @property
    def _llm_type(self) -> str:
        return "fake-capturing"

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.captured.append(list(messages))
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content="Got your file."))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)


async def _noop_tool_intent(*args, **kwargs):
    return None


def _ready_attachment(db_session, project, session, **fields) -> ChatAttachment:
    attachment = ChatAttachment(
        project_id=project.id, session_id=session.id, storage_path="/nonexistent",
        status="ready", size_bytes=2048, **fields,
    )
    db_session.add(attachment)
    db_session.commit()
    return attachment


class TestChatTurnWithAttachments:
    @pytest.fixture(autouse=True)
    def _fakes(self, db_session, monkeypatch):
        app.config.get_settings().deepagents_enabled = True
        model = _CapturingModel()
        model.captured = []
        monkeypatch.setattr(chat_agent_module, "_build_llm", lambda: model)
        monkeypatch.setattr(chat_agent_module, "detect_single_tool_intent", _noop_tool_intent)
        self.model = model

    def _last_human(self) -> HumanMessage:
        return [m for m in self.model.captured[-1] if isinstance(m, HumanMessage)][-1]

    async def test_replays_each_kind_and_links_message(self, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)
        image = _ready_attachment(
            db_session, project, session, filename="logo.png", content_type="image/png",
            kind="gemini_file", gemini_file_uri="https://x/files/1",
            gemini_file_expires_at=datetime.utcnow() + timedelta(hours=40),
        )
        doc = _ready_attachment(
            db_session, project, session, filename="plan.docx", content_type="application/docx",
            kind="text", extracted_text="Lattes for $4.",
        )
        blob = _ready_attachment(
            db_session, project, session, filename="data.zip", content_type="application/zip",
            kind="metadata_only",
        )

        result = await chat_agent_module.run_chat_turn(
            db_session, project, session, "", EventQueue(), attachment_ids=[image.id, doc.id, blob.id]
        )

        assert result.status == "complete"
        content = self._last_human().content
        assert isinstance(content, list)
        assert {"type": "media", "file_uri": "https://x/files/1", "mime_type": "image/png"} in content
        texts = [p["text"] for p in content if p["type"] == "text"]
        assert any("plan.docx" in t and "Lattes for $4." in t for t in texts)
        assert any("data.zip" in t and "not readable" in t for t in texts)
        db_session.refresh(image)
        assert image.message_id is not None
        assert session.title is not None and "logo.png" in session.title

    async def test_text_only_message_stays_a_plain_string(self, db_session, make_project):
        project = make_project()
        session = _make_session(db_session, project)

        await chat_agent_module.run_chat_turn(db_session, project, session, "hi", EventQueue())

        assert self._last_human().content == "hi"

    async def test_expired_gemini_file_is_reuploaded(self, db_session, make_project, monkeypatch):
        monkeypatch.setattr(
            processing_module, "_upload_to_gemini",
            lambda path, ct, name: ("https://x/files/fresh", datetime.utcnow() + timedelta(hours=48)),
        )
        project = make_project()
        session = _make_session(db_session, project)
        image = _ready_attachment(
            db_session, project, session, filename="old.png", content_type="image/png",
            kind="gemini_file", gemini_file_uri="https://x/files/stale",
            gemini_file_expires_at=datetime.utcnow() - timedelta(hours=1),
        )

        await chat_agent_module.run_chat_turn(
            db_session, project, session, "what is this?", EventQueue(), attachment_ids=[image.id]
        )

        content = self._last_human().content
        assert {"type": "media", "file_uri": "https://x/files/fresh", "mime_type": "image/png"} in content
