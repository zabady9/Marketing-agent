from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.agents.schemas import ContentOutput, CriticOutput
from app.models.action_log import ActionLog
from app.models.content_plan import ContentPlan
from app.models.enums import PlanStatus
from app.models.post import Post

NEW_CONTENT = ContentOutput(
    content="Regenerated content",
    hashtags=["#regen"],
    suggested_time="10:00",
)

CRITIC_APPROVED = CriticOutput(approved=True, issues=[])
CRITIC_REJECTED = CriticOutput(
    approved=False, issues=["tone"], fixed_body="Fixed body text"
)


def _mock_agents(content=NEW_CONTENT, critic=CRITIC_APPROVED):
    content_agent = MagicMock()
    content_agent.write = AsyncMock(return_value=content)
    critic_agent = MagicMock()
    critic_agent.review = AsyncMock(return_value=critic)
    return content_agent, critic_agent


async def _seed_post(workspace_id: str, status: str = "pending_approval") -> str:
    from tests.conftest import _TestSessionLocal

    async with _TestSessionLocal() as db:
        plan = ContentPlan(
            workspace_id=workspace_id,
            goal="test",
            status=PlanStatus.ready.value,
        )
        db.add(plan)
        await db.flush()

        post = Post(
            plan_id=plan.id,
            workspace_id=workspace_id,
            day=2,
            theme="Regen theme",
            format="thread",
            angle="Regen angle",
            content="Old content",
            hashtags=["#old"],
            suggested_time="09:00",
            status=status,
        )
        db.add(post)
        await db.commit()
        await db.refresh(post)
        return post.id


@pytest.mark.asyncio
async def test_regenerate_returns_202(test_client):
    ws = await test_client.post("/api/workspaces", json={"name": "Regen WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    content_agent, critic_agent = _mock_agents()
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        resp = await test_client.post(f"/api/posts/{post_id}:regenerate")
    assert resp.status_code == 202
    assert resp.json()["id"] == post_id


@pytest.mark.asyncio
async def test_regenerate_updates_post_content(test_client):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    ws = await test_client.post("/api/workspaces", json={"name": "Regen Update WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    content_agent, critic_agent = _mock_agents()
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        await regenerate_post(
            post_id=post_id, note="make it punchier", session_factory=_TestSessionLocal
        )

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        assert post.content == "Regenerated content"
        assert post.hashtags == ["#regen"]
        assert post.suggested_time == "10:00"


@pytest.mark.asyncio
async def test_regenerate_with_note_passed_to_content_agent(test_client):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    ws = await test_client.post("/api/workspaces", json={"name": "Regen Note WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    content_agent, critic_agent = _mock_agents()
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        await regenerate_post(
            post_id=post_id, note="funnier tone", session_factory=_TestSessionLocal
        )

    content_agent.write.assert_awaited_once()
    _, kwargs = content_agent.write.call_args
    assert kwargs.get("revision_hint") == "funnier tone"


@pytest.mark.asyncio
async def test_regenerate_approved_post_resets_to_pending(test_client):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    ws = await test_client.post("/api/workspaces", json={"name": "Regen Approved WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id, status="approved")

    content_agent, critic_agent = _mock_agents()
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        await regenerate_post(post_id=post_id, session_factory=_TestSessionLocal)

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        assert post.status == "pending_approval"


@pytest.mark.asyncio
async def test_regenerate_critic_rejected_uses_fixed_body(test_client):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    ws = await test_client.post("/api/workspaces", json={"name": "Regen Fix WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    content_agent, critic_agent = _mock_agents(critic=CRITIC_REJECTED)
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        await regenerate_post(post_id=post_id, session_factory=_TestSessionLocal)

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        assert post.content == "Fixed body text"


@pytest.mark.asyncio
async def test_regenerate_logs_action(test_client, db_session):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    ws = await test_client.post("/api/workspaces", json={"name": "Regen Log WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    content_agent, critic_agent = _mock_agents()
    with (
        patch("app.services.regenerate._content_agent", content_agent),
        patch("app.services.regenerate._critic_agent", critic_agent),
    ):
        await regenerate_post(post_id=post_id, note="try again", session_factory=_TestSessionLocal)

    result = await db_session.execute(
        select(ActionLog).where(
            ActionLog.workspace_id == workspace_id,
            ActionLog.action == "regenerate_post",
        )
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.payload["note"] == "try again"
    assert log.payload["post_id"] == post_id


@pytest.mark.asyncio
async def test_regenerate_nonexistent_post_is_noop(test_client):
    from tests.conftest import _TestSessionLocal
    from app.services.regenerate import regenerate_post

    await regenerate_post(post_id="no-such-id", session_factory=_TestSessionLocal)
    # no exception raised; silently exits
