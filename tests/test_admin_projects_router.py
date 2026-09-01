from __future__ import annotations

from app.models import ChatMessage, ChatSession, StudyResult


def test_list_get_patch_project(client, make_project):
    project = make_project("Admin Test Project")

    list_resp = client.get("/api/admin/projects")
    assert list_resp.status_code == 200
    body = list_resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == project.id
    assert body["items"][0]["active_study_count"] == 0
    assert body["items"][0]["active_chat_session_count"] == 0

    get_resp = client.get(f"/api/admin/projects/{project.id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["deleted_at"] is None

    patch_resp = client.patch(f"/api/admin/projects/{project.id}", json={"status": "archived"})
    assert patch_resp.status_code == 200
    assert patch_resp.json()["status"] == "archived"


def test_soft_delete_project_cascades_and_restore_respects_independent_deletes(
    client, db_session, make_project
):
    """Soft-deleting a project must cascade to its studies/sessions/messages,
    but restoring it must not resurrect a child that was already deleted
    independently beforehand."""
    project = make_project("Cascade Project")

    independent_study = StudyResult(project_id=project.id, status="completed")
    cascaded_study = StudyResult(project_id=project.id, status="completed")
    session = ChatSession(project_id=project.id, title="Session")
    db_session.add_all([independent_study, cascaded_study, session])
    db_session.commit()

    message = ChatMessage(session_id=session.id, role="user", content="hi")
    db_session.add(message)
    db_session.commit()

    # Delete one study independently, before the project-level cascade delete.
    delete_independent_resp = client.delete(f"/api/admin/studies/{independent_study.id}")
    assert delete_independent_resp.status_code == 200
    independent_deleted_at = delete_independent_resp.json()["deleted_at"]
    assert independent_deleted_at is not None

    # Cascade-delete the project.
    delete_project_resp = client.delete(f"/api/admin/projects/{project.id}")
    assert delete_project_resp.status_code == 200
    assert delete_project_resp.json()["deleted_at"] is not None

    # Public endpoints treat the project as gone.
    assert client.get(f"/api/projects/{project.id}").status_code == 404

    # Admin list excludes it by default, includes it with include_deleted=true.
    active_ids = [p["id"] for p in client.get("/api/admin/projects").json()["items"]]
    assert project.id not in active_ids
    all_ids = [
        p["id"]
        for p in client.get("/api/admin/projects", params={"include_deleted": True}).json()[
            "items"
        ]
    ]
    assert project.id in all_ids

    db_session.refresh(cascaded_study)
    db_session.refresh(session)
    db_session.refresh(message)
    assert cascaded_study.deleted_at is not None
    assert session.deleted_at is not None
    assert message.deleted_at is not None

    # Restore the project — only children deleted at the same moment come back.
    restore_resp = client.post(f"/api/admin/projects/{project.id}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None
    assert restore_resp.json()["active_study_count"] == 1
    assert restore_resp.json()["active_chat_session_count"] == 1

    db_session.refresh(independent_study)
    db_session.refresh(cascaded_study)
    db_session.refresh(session)
    db_session.refresh(message)
    assert independent_study.deleted_at is not None, "independently deleted study must stay deleted"
    assert cascaded_study.deleted_at is None
    assert session.deleted_at is None
    assert message.deleted_at is None

    assert client.get(f"/api/projects/{project.id}").status_code == 200
