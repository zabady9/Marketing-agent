from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.postiz import PostizError

MOCK_INTEGRATIONS = [
    {"id": "int-1", "name": "Twitter @acme", "type": "x"},
    {"id": "int-2", "name": "LinkedIn ACME Corp", "type": "linkedin"},
]


def _mock_postiz(integrations=None, error=None) -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    if error:
        client.list_integrations = AsyncMock(side_effect=error)
    else:
        client.list_integrations = AsyncMock(return_value=integrations or [])
    return client


@pytest.mark.asyncio
async def test_list_connections_success(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Conn WS"})
    workspace_id = ws.json()["id"]

    with patch("app.routers.connections.PostizClient", return_value=_mock_postiz(MOCK_INTEGRATIONS)):
        resp = await test_client.get(f"/api/workspaces/{workspace_id}/connections")

    assert resp.status_code == 200
    body = resp.json()
    assert body["workspace_id"] == workspace_id
    assert len(body["connections"]) == 2
    assert body["connections"][0]["id"] == "int-1"


@pytest.mark.asyncio
async def test_list_connections_empty(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Empty Conn WS"})
    workspace_id = ws.json()["id"]

    with patch("app.routers.connections.PostizClient", return_value=_mock_postiz([])):
        resp = await test_client.get(f"/api/workspaces/{workspace_id}/connections")

    assert resp.status_code == 200
    assert resp.json()["connections"] == []


@pytest.mark.asyncio
async def test_list_connections_postiz_error_returns_502(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Err Conn WS"})
    workspace_id = ws.json()["id"]

    with patch(
        "app.routers.connections.PostizClient",
        return_value=_mock_postiz(error=PostizError("upstream error", 500)),
    ):
        resp = await test_client.get(f"/api/workspaces/{workspace_id}/connections")

    assert resp.status_code == 502


@pytest.mark.asyncio
async def test_list_connections_workspace_not_found(test_client):
    resp = await test_client.get("/api/workspaces/no-such-ws/connections")
    assert resp.status_code == 404
