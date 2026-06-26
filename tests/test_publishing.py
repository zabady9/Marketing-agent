from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from app.clients.postiz import PostizRateLimitError
from app.models.action_log import ActionLog
from app.models.content_plan import ContentPlan
from app.models.enums import PlanStatus, PostStatus
from app.models.post import Post
from app.services.publishing import AlreadyScheduledError, schedule_post

WHEN = datetime(2026, 7, 1, 9, 0, tzinfo=timezone.utc)


async def _seed_post(workspace_id: str, status: str = "approved") -> str:
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
            day=1,
            theme="Theme",
            format="post",
            angle="Angle",
            content="Post content",
            hashtags=["#tag"],
            suggested_time="09:00",
            status=status,
        )
        db.add(post)
        await db.commit()
        await db.refresh(post)
        return post.id


def _mock_postiz_client(postiz_id: str = "pz-123") -> MagicMock:
    client = MagicMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.schedule_post = AsyncMock(return_value={"id": postiz_id})
    return client


@pytest.mark.asyncio
async def test_schedule_post_success(test_client, db_session):
    from tests.conftest import _TestSessionLocal

    ws = await test_client.post("/api/workspaces", json={"name": "Pub WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    mock_client = _mock_postiz_client("postiz-999")

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()

        with patch("app.services.publishing.PostizClient", return_value=mock_client):
            updated = await schedule_post(
                db=db,
                post=post,
                integration_id="integ-1",
                provider="twitter",
                when=WHEN,
            )

    assert updated.status == PostStatus.scheduled.value
    assert updated.postiz_post_id == "postiz-999"


@pytest.mark.asyncio
async def test_schedule_post_idempotency(test_client):
    from tests.conftest import _TestSessionLocal

    ws = await test_client.post("/api/workspaces", json={"name": "Idem WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    mock_client = _mock_postiz_client()

    # First call succeeds
    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        with patch("app.services.publishing.PostizClient", return_value=mock_client):
            await schedule_post(db=db, post=post, integration_id="i", provider="x", when=WHEN)

    # Second call raises AlreadyScheduledError — post is already scheduled
    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        with pytest.raises(AlreadyScheduledError):
            with patch("app.services.publishing.PostizClient", return_value=mock_client):
                await schedule_post(db=db, post=post, integration_id="i", provider="x", when=WHEN)

    # Postiz API called only once
    mock_client.schedule_post.assert_awaited_once()


@pytest.mark.asyncio
async def test_schedule_post_rate_limit_does_not_change_status(test_client):
    from tests.conftest import _TestSessionLocal

    ws = await test_client.post("/api/workspaces", json={"name": "RL WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    mock_client = MagicMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_client.schedule_post = AsyncMock(side_effect=PostizRateLimitError("rate limited", 429))

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        with pytest.raises(PostizRateLimitError):
            with patch("app.services.publishing.PostizClient", return_value=mock_client):
                await schedule_post(db=db, post=post, integration_id="i", provider="x", when=WHEN)

    # Status must still be approved (unchanged)
    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        assert post.status == PostStatus.approved.value
        assert post.postiz_post_id is None


@pytest.mark.asyncio
async def test_schedule_post_logs_action(test_client, db_session):
    from tests.conftest import _TestSessionLocal

    ws = await test_client.post("/api/workspaces", json={"name": "Log Pub WS"})
    workspace_id = ws.json()["id"]
    post_id = await _seed_post(workspace_id)

    mock_client = _mock_postiz_client("pz-log")

    async with _TestSessionLocal() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one()
        with patch("app.services.publishing.PostizClient", return_value=mock_client):
            await schedule_post(db=db, post=post, integration_id="i", provider="x", when=WHEN)

    result = await db_session.execute(
        select(ActionLog).where(
            ActionLog.workspace_id == workspace_id,
            ActionLog.action == "schedule_post",
        )
    )
    log = result.scalar_one_or_none()
    assert log is not None
    assert log.payload["postiz_post_id"] == "pz-log"
    assert log.payload["integration_id"] == "i"
