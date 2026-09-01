from __future__ import annotations


def test_admin_patch_delete_restore_memory_entry(client):
    create_resp = client.post("/api/memory", json={"content": "User prefers metric units."})
    assert create_resp.status_code == 201
    entry_id = create_resp.json()["id"]

    patch_resp = client.patch(
        f"/api/admin/memory/{entry_id}", json={"content": "User prefers imperial units."}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["content"] == "User prefers imperial units."

    delete_resp = client.delete(f"/api/admin/memory/{entry_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_at"] is not None

    # Public list no longer shows it.
    assert entry_id not in [e["id"] for e in client.get("/api/memory").json()]

    # Admin list without include_deleted also excludes it; with, includes it.
    assert entry_id not in [e["id"] for e in client.get("/api/admin/memory").json()["items"]]
    all_entries = client.get("/api/admin/memory", params={"include_deleted": True}).json()
    assert entry_id in [e["id"] for e in all_entries["items"]]

    restore_resp = client.post(f"/api/admin/memory/{entry_id}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None
    assert entry_id in [e["id"] for e in client.get("/api/memory").json()]


def test_public_delete_memory_entry_is_now_soft_and_idempotent_404(client):
    create_resp = client.post("/api/memory", json={"content": "Some fact."})
    entry_id = create_resp.json()["id"]

    first_delete = client.delete(f"/api/memory/{entry_id}")
    assert first_delete.status_code == 204

    # Deleting again (already soft-deleted) is a 404, not a crash.
    second_delete = client.delete(f"/api/memory/{entry_id}")
    assert second_delete.status_code == 404

    # But the row is recoverable through the admin restore endpoint.
    restore_resp = client.post(f"/api/admin/memory/{entry_id}/restore")
    assert restore_resp.status_code == 200
    assert entry_id in [e["id"] for e in client.get("/api/memory").json()]
