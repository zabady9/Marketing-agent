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


class TestListArtifactsEndpoint:
    def _artifact(self, project_id, title, fmt="docx", **kw):
        return Artifact(
            project_id=project_id, format=fmt, title=title, filename=f"{title}.{fmt}",
            storage_path="/nonexistent", size_bytes=10, spec_json={}, **kw,
        )

    def test_lists_this_projects_files_newest_first_without_deleted(self, client, db_session, make_project):
        from datetime import datetime, timedelta

        project, other = make_project(), make_project("Other")
        now = datetime.utcnow()
        db_session.add_all([
            self._artifact(project.id, "Old", created_at=now - timedelta(hours=1)),
            self._artifact(project.id, "New", fmt="pdf", created_at=now),
            self._artifact(project.id, "Gone", deleted_at=now),
            self._artifact(other.id, "Elsewhere"),
        ])
        db_session.commit()

        resp = client.get(f"/api/projects/{project.id}/chat/artifacts")

        assert resp.status_code == 200
        items = resp.json()
        assert [i["title"] for i in items] == ["New", "Old"]
        assert items[0]["format"] == "pdf" and "created_at" in items[0]
        assert "storage_path" not in items[0]

    def test_404_for_unknown_project(self, client):
        assert client.get("/api/projects/nope/chat/artifacts").status_code == 404


class TestDownloadRebuildsMissingFiles:
    """Files kept on Cloud Run's local disk were wiped by redeploys; a download
    of such a file rebuilds it from its stored outline instead of failing."""

    def _missing(self, db_session, project, fmt="docx"):
        artifact = Artifact(
            project_id=project.id, format=fmt, title="Report", filename=f"x.{fmt}",
            storage_path="./generated_artifacts/gone/x." + fmt, size_bytes=1,
            spec_json={"title": "Report", "sections": [{"heading": "Report", "body": "# Hi"}]},
        )
        db_session.add(artifact)
        db_session.commit()
        return artifact

    def test_missing_file_is_rebuilt_stored_and_served(self, client, db_session, make_project, monkeypatch, tmp_path):
        import app.routers.projects as projects_module
        from app.services.artifact_generation import ArtifactFile

        project = make_project()
        artifact = self._missing(db_session, project)
        rebuilt = tmp_path / "rebuilt.docx"
        rebuilt.write_bytes(b"PK\x03\x04rebuilt")
        calls = []

        async def _fake_regenerate(a, **kw):
            calls.append(a.id)
            return ArtifactFile(path=str(rebuilt), filename="rebuilt.docx", size_bytes=11)

        monkeypatch.setattr(projects_module, "regenerate_artifact_file", _fake_regenerate)

        resp = client.get(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}/download")
        assert resp.status_code == 200
        assert resp.content == b"PK\x03\x04rebuilt"
        db_session.refresh(artifact)
        assert artifact.storage_path == str(rebuilt) and artifact.size_bytes == 11

        # Second download is served from storage — no second rebuild.
        assert client.get(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}/download").status_code == 200
        assert calls == [artifact.id]

    def test_rebuild_failure_returns_a_readable_503(self, client, db_session, make_project, monkeypatch):
        import app.routers.projects as projects_module

        project = make_project()
        artifact = self._missing(db_session, project, fmt="pdf")

        async def _broken(a, **kw):
            raise RuntimeError("docgen down")

        monkeypatch.setattr(projects_module, "regenerate_artifact_file", _broken)
        resp = client.get(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}/download")
        assert resp.status_code == 503
        assert "try again" in resp.json()["detail"]


def test_generated_files_go_to_gcs_in_production(monkeypatch, db_session):
    import app.config
    from app.services import upload_storage

    app.config.get_settings().upload_storage = "gcs"
    try:
        assert upload_storage.generated_file_path("p", "a", "pdf") == "generated/p/a.pdf"
    finally:
        app.config.get_settings().upload_storage = "local"


class TestDeleteArtifactEndpoint:
    def test_soft_deletes_and_hides_the_file(self, client, db_session, make_project):
        project = make_project()
        artifact = Artifact(
            project_id=project.id, format="pdf", title="Old", filename="o.pdf",
            storage_path="/nonexistent", size_bytes=1, spec_json={},
        )
        db_session.add(artifact)
        db_session.commit()

        resp = client.delete(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}")

        assert resp.status_code == 204
        db_session.refresh(artifact)
        assert artifact.deleted_at is not None  # kept, restorable
        assert client.get(f"/api/projects/{project.id}/chat/artifacts").json() == []
        assert client.get(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}/download").status_code == 404
        # Deleting again is a 404, not a second change.
        assert client.delete(f"/api/projects/{project.id}/chat/artifacts/{artifact.id}").status_code == 404

    def test_cannot_delete_another_projects_file(self, client, db_session, make_project):
        owner, other = make_project(), make_project("Other")
        artifact = Artifact(
            project_id=owner.id, format="pdf", title="Mine", filename="m.pdf",
            storage_path="/nonexistent", size_bytes=1, spec_json={},
        )
        db_session.add(artifact)
        db_session.commit()

        assert client.delete(f"/api/projects/{other.id}/chat/artifacts/{artifact.id}").status_code == 404
        db_session.refresh(artifact)
        assert artifact.deleted_at is None
