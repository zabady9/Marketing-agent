from __future__ import annotations


def test_create_get_patch_delete_restore_study(client, make_project):
    project = make_project()

    create_resp = client.post(
        "/api/admin/studies",
        json={"project_id": project.id, "status": "completed", "title": "SWOT", "goal": "g"},
    )
    assert create_resp.status_code == 201
    study = create_resp.json()
    assert study["project_id"] == project.id
    assert study["deleted_at"] is None

    get_resp = client.get(f"/api/admin/studies/{study['id']}")
    assert get_resp.status_code == 200

    patch_resp = client.patch(
        f"/api/admin/studies/{study['id']}", json={"title": "PESTEL", "report": {"steps": []}}
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["title"] == "PESTEL"
    assert patch_resp.json()["report"] == {"steps": []}

    delete_resp = client.delete(f"/api/admin/studies/{study['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted_at"] is not None

    # Public endpoint no longer lists it.
    public_list = client.get(f"/api/projects/{project.id}/studies").json()
    assert study["id"] not in [s["id"] for s in public_list]
    assert client.get(f"/api/projects/{project.id}/studies/{study['id']}").status_code == 404

    restore_resp = client.post(f"/api/admin/studies/{study['id']}/restore")
    assert restore_resp.status_code == 200
    assert restore_resp.json()["deleted_at"] is None

    public_list_after_restore = client.get(f"/api/projects/{project.id}/studies").json()
    assert study["id"] in [s["id"] for s in public_list_after_restore]


def test_list_studies_filters(client, make_project):
    project_a = make_project("Project A")
    project_b = make_project("Project B")

    client.post(
        "/api/admin/studies",
        json={"project_id": project_a.id, "status": "completed"},
    )
    client.post(
        "/api/admin/studies",
        json={"project_id": project_a.id, "status": "failed"},
    )
    client.post(
        "/api/admin/studies",
        json={"project_id": project_b.id, "status": "completed"},
    )

    by_project = client.get("/api/admin/studies", params={"project_id": project_a.id}).json()
    assert by_project["total"] == 2

    by_status = client.get("/api/admin/studies", params={"status": "failed"}).json()
    assert by_status["total"] == 1
