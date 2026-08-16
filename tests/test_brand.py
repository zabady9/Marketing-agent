import pytest


SUBJECT_PAYLOAD = {
    "subject_name": "Acme Corp",
    "legal_name": "Acme Corporation",
    "industry": "SaaS",
    "tracked_competitors": [
        {
            "name": "Rival Co",
            "description": "Main competitor in the SMB space",
            "notes": "Strong brand recognition",
        }
    ],
    "areas_of_interest": ["market size trends", "competitive position"],
    "business_lines": [
        {"name": "Analytics Platform", "description": "Core SaaS product", "notes": None}
    ],
}


@pytest.mark.asyncio
async def test_upsert_then_get_subject(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Subject WS"})
    workspace_id = ws.json()["id"]

    resp = await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject", json=SUBJECT_PAYLOAD
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_name"] == "Acme Corp"
    assert body["legal_name"] == "Acme Corporation"
    assert body["industry"] == "SaaS"
    assert body["workspace_id"] == workspace_id
    assert len(body["tracked_competitors"]) == 1
    assert body["tracked_competitors"][0]["name"] == "Rival Co"
    assert body["areas_of_interest"] == ["market size trends", "competitive position"]
    assert body["setup_status"] == "in_progress"

    resp2 = await test_client.get(f"/api/workspaces/{workspace_id}/analysis-subject")
    assert resp2.status_code == 200
    assert resp2.json()["subject_name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_second_put_updates_subject(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Subject WS 2"})
    workspace_id = ws.json()["id"]

    await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject", json=SUBJECT_PAYLOAD
    )

    resp = await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject",
        json={"subject_description": "Updated description"},
    )
    assert resp.status_code == 200
    assert resp.json()["subject_description"] == "Updated description"
    assert resp.json()["subject_name"] == "Acme Corp"


@pytest.mark.asyncio
async def test_get_subject_not_set(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Empty Subject WS"})
    workspace_id = ws.json()["id"]
    resp = await test_client.get(f"/api/workspaces/{workspace_id}/analysis-subject")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_partial_update_preserves_existing_fields(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Partial Subject WS"})
    workspace_id = ws.json()["id"]

    await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject", json=SUBJECT_PAYLOAD
    )

    resp = await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject",
        json={"subject_description": "Brief overview"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["subject_description"] == "Brief overview"
    assert body["subject_name"] == "Acme Corp"
    assert body["industry"] == "SaaS"


@pytest.mark.asyncio
async def test_setup_status_can_be_set(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Setup Status WS"})
    workspace_id = ws.json()["id"]

    await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject", json=SUBJECT_PAYLOAD
    )

    resp = await test_client.put(
        f"/api/workspaces/{workspace_id}/analysis-subject",
        json={"setup_status": "active"},
    )
    assert resp.status_code == 200
    assert resp.json()["setup_status"] == "active"
