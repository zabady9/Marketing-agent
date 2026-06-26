from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.schemas import (
    ContentIdea,
    ContentOutput,
    CriticOutput,
    StrategyOutput,
)

BRAND = {"name": "Acme", "audience": "SMBs", "tone": "professional", "language": "en"}

SEVEN_IDEAS = StrategyOutput(
    ideas=[
        ContentIdea(day=i + 1, theme=f"Theme {i+1}", format="post", angle=f"Angle {i+1}")
        for i in range(7)
    ]
)

CONTENT = ContentOutput(
    content="Great post content", hashtags=["#test"], suggested_time="09:00"
)

APPROVED = CriticOutput(approved=True, issues=[])


def _make_mock_agents():
    strategy = MagicMock()
    strategy.generate = AsyncMock(return_value=SEVEN_IDEAS)

    content = MagicMock()
    content.write = AsyncMock(return_value=CONTENT)

    critic = MagicMock()
    critic.review = AsyncMock(return_value=APPROVED)

    return strategy, content, critic


@pytest.mark.asyncio
async def test_graph_produces_seven_posts():
    strategy, content, critic = _make_mock_agents()

    with (
        patch("app.agents.graph._strategy_agent", strategy),
        patch("app.agents.graph._content_agent", content),
        patch("app.agents.graph._critic_agent", critic),
    ):
        from app.agents.graph import generation_graph

        initial_state = {
            "brand_profile": BRAND,
            "goal": "launch product",
            "ideas": [],
            "current_idx": 0,
            "revision_count": 0,
            "current_content": None,
            "finished_posts": [],
            "action_logs": [],
            "workspace_id": "ws-test",
            "plan_id": "plan-test",
        }

        result = await generation_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-thread-1"}},
        )

    assert len(result["finished_posts"]) == 7
    # 1 strategy log + 7 content + 7 critic
    assert len(result["action_logs"]) == 15
    # strategy called once, content and critic called 7 times each
    assert strategy.generate.await_count == 1
    assert content.write.await_count == 7
    assert critic.review.await_count == 7


@pytest.mark.asyncio
async def test_graph_revision_loop():
    """Critic rejects idea #1 once → revision → approved → 7 total posts."""
    strategy, content, critic = _make_mock_agents()

    rejected = CriticOutput(
        approved=False, issues=["tone"], fixed_body="Fixed content"
    )
    # idea 0: reject then approve; ideas 1-6: approve immediately
    critic.review = AsyncMock(side_effect=[rejected, APPROVED] + [APPROVED] * 6)

    with (
        patch("app.agents.graph._strategy_agent", strategy),
        patch("app.agents.graph._content_agent", content),
        patch("app.agents.graph._critic_agent", critic),
    ):
        from app.agents.graph import generation_graph

        initial_state = {
            "brand_profile": BRAND,
            "goal": None,
            "ideas": [],
            "current_idx": 0,
            "revision_count": 0,
            "current_content": None,
            "finished_posts": [],
            "action_logs": [],
            "workspace_id": "ws-test",
            "plan_id": "plan-test-2",
        }

        result = await generation_graph.ainvoke(
            initial_state,
            config={"configurable": {"thread_id": "test-thread-2"}},
        )

    assert len(result["finished_posts"]) == 7
    # content called 8 times: 7 normal + 1 revision for idea 0
    assert content.write.await_count == 8
    # critic called 8 times: reject + approve for idea 0, then 6 more approvals
    assert critic.review.await_count == 8
