from __future__ import annotations

from app.models import ChatMessage, ChatSession


def test_chat_session_patch_delete_restore_cascades_messages(client, db_session, make_project):
    project = make_project()
    session = ChatSession(project_id=project.id, title="Original title")
    db_session.add(session)
    db_session.commit()

    message = ChatMessage(session_id=session.id, role="user", content="hello")
    db_session.add(message)
    db_session.commit()

    patch_resp = client.patch(
        f"/api/admin/chat-sessions/{session.id}", json={"title": "Renamed"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "Renamed"

    delete_resp = client.delete(f"/api/admin/chat-sessions/{session.id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_at"] is not None

    db_session.refresh(message)
    assert message.deleted_at is not None

    # Public endpoint no longer lists the session or its messages.
    assert session.id not in [
        s["id"] for s in client.get(f"/api/projects/{project.id}/chat/sessions").json()
    ]

    restore_resp = client.post(f"/api/admin/chat-sessions/{session.id}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    db_session.refresh(message)
    assert message.deleted_at is None
    assert session.id in [
        s["id"] for s in client.get(f"/api/projects/{project.id}/chat/sessions").json()
    ]


def test_chat_message_patch_delete_restore(client, db_session, make_project):
    project = make_project()
    session = ChatSession(project_id=project.id)
    db_session.add(session)
    db_session.commit()

    message = ChatMessage(session_id=session.id, role="user", content="original")
    db_session.add(message)
    db_session.commit()

    patch_resp = client.patch(
        f"/api/admin/chat-messages/{message.id}", json={"content": "redacted"}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["content"] == "redacted"

    delete_resp = client.delete(f"/api/admin/chat-messages/{message.id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_at"] is not None

    public_messages = client.get(
        f"/api/projects/{project.id}/chat/sessions/{session.id}/messages"
    ).json()
    assert message.id not in [m["id"] for m in public_messages]

    restore_resp = client.post(f"/api/admin/chat-messages/{message.id}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    public_messages_after = client.get(
        f"/api/projects/{project.id}/chat/sessions/{session.id}/messages"
    ).json()
    assert message.id in [m["id"] for m in public_messages_after]


def test_list_chat_sessions_and_messages_filter_by_project_and_session(
    client, db_session, make_project
):
    project_a = make_project("Project A")
    project_b = make_project("Project B")
    session_a = ChatSession(project_id=project_a.id)
    session_b = ChatSession(project_id=project_b.id)
    db_session.add_all([session_a, session_b])
    db_session.commit()

    db_session.add_all(
        [
            ChatMessage(session_id=session_a.id, role="user", content="a1"),
            ChatMessage(session_id=session_a.id, role="assistant", content="a2"),
            ChatMessage(session_id=session_b.id, role="user", content="b1"),
        ]
    )
    db_session.commit()

    by_project = client.get(
        "/api/admin/chat-sessions", params={"project_id": project_a.id}
    ).json()
    assert by_project["total"] == 1
    assert by_project["items"][0]["id"] == session_a.id

    by_session = client.get(
        "/api/admin/chat-messages", params={"session_id": session_a.id}
    ).json()
    assert by_session["total"] == 2

    by_role = client.get("/api/admin/chat-messages", params={"role": "assistant"}).json()
    assert by_role["total"] == 1
