"""
Tests for the artifact download endpoint — the first binary-file response in
this codebase (every other file-serving route returns markdown text). No
mocking needed: this writes a real small file to a temp dir and asserts the
response's headers/bytes, mirroring tests/test_export.py's router-test style.
"""

from __future__ import annotations

import tempfile

from app.models import Artifact


class TestDownloadArtifactEndpoint:
    def test_downloads_pptx_with_correct_headers_and_bytes(self, client, db_session, make_project):
        project = make_project()
        with tempfile.NamedTemporaryFile(suffix=".pptx", delete=False) as f:
            f.write(b"PK\x03\x04fake pptx zip bytes")
            path = f.name

        artifact = Artifact(
            project_id=project.id, format="pptx", title="My Deck", filename="a.pptx",
            storage_path=path, size_bytes=20, spec_json={"title": "My Deck", "slides": []},
        )
        db_session.add(artifact)
        db_session.commit()

        resp = client.get(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}/download")

        assert resp.status_code == 200
        assert resp.headers["content-type"] == (
            "application/vnd.openxmlformats-officedocument.presentationml.presentation"
        )
        # Starlette's FileResponse RFC-5987-encodes a filename containing a
        # space rather than emitting a plain quoted filename= param.
        assert "filename*=utf-8''My%20Deck.pptx" in resp.headers["content-disposition"]
        assert resp.content.startswith(b"PK\x03\x04")

    def test_404_for_unknown_artifact(self, client, make_project):
        project = make_project()
        resp = client.get(f"/api/projects/{project.id}/chat/artifacts/nonexistent/download")
        assert resp.status_code == 404

    def test_404_when_artifact_belongs_to_a_different_project(self, client, db_session, make_project):
        project_a = make_project("A")
        project_b = make_project("B")
        with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
            f.write(b"fake docx bytes")
            path = f.name

        artifact = Artifact(
            project_id=project_a.id, format="docx", title="Doc", filename="a.docx",
            storage_path=path, size_bytes=10, spec_json={"title": "Doc", "sections": []},
        )
        db_session.add(artifact)
        db_session.commit()

        resp = client.get(f"/api/projects/{project_b.id}/chat/artifacts/{artifact.id}/download")
        assert resp.status_code == 404
