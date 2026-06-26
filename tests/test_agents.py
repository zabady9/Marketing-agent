from unittest.mock import AsyncMock, MagicMock

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

# Bypass validation to create a 6-idea instance for retry testing
SIX_IDEAS = StrategyOutput.model_construct(
    ideas=[
        ContentIdea(day=i + 1, theme=f"Theme {i+1}", format="post", angle=f"Angle {i+1}")
        for i in range(6)
    ]
)


def _mock_chain(*return_values):
    """Return a MagicMock whose .ainvoke is an AsyncMock cycling through return_values."""
    chain = MagicMock()
    chain.ainvoke = AsyncMock(side_effect=list(return_values))
    return chain


# ──────────────────────────────────────────────
# Strategy Agent
# ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_strategy_happy_path():
    from app.agents.strategy_agent import StrategyAgent

    agent = StrategyAgent()
    agent._chain = _mock_chain(SEVEN_IDEAS)

    result = await agent.generate(BRAND, goal="launch product")
    assert isinstance(result, StrategyOutput)
    assert len(result.ideas) == 7
    agent._chain.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_strategy_off_by_one_retries_and_succeeds():
    from app.agents.strategy_agent import StrategyAgent

    agent = StrategyAgent()
    # First call returns 6 ideas (triggers retry), second returns 7
    agent._chain = _mock_chain(SIX_IDEAS, SEVEN_IDEAS)

    result = await agent.generate(BRAND)
    assert len(result.ideas) == 7
    assert agent._chain.ainvoke.await_count == 2


# ──────────────────────────────────────────────
# Content Agent
# ──────────────────────────────────────────────

CONTENT_OUTPUT = ContentOutput(
    content="Check out our new product! #innovation",
    hashtags=["#innovation", "#launch"],
    suggested_time="09:00",
)


@pytest.mark.asyncio
async def test_content_happy_path():
    from app.agents.content_agent import ContentAgent

    agent = ContentAgent()
    agent._chain = _mock_chain(CONTENT_OUTPUT)

    idea = SEVEN_IDEAS.ideas[0]
    result = await agent.write(idea, BRAND)
    assert isinstance(result, ContentOutput)
    assert result.content == CONTENT_OUTPUT.content
    agent._chain.ainvoke.assert_awaited_once()


@pytest.mark.asyncio
async def test_content_with_revision_hint():
    from app.agents.content_agent import ContentAgent

    agent = ContentAgent()
    agent._chain = _mock_chain(CONTENT_OUTPUT)

    idea = SEVEN_IDEAS.ideas[0]
    await agent.write(idea, BRAND, revision_hint="make it more casual")

    # Inspect the messages passed to ainvoke
    call_messages = agent._chain.ainvoke.call_args[0][0]
    human_texts = [m.content for m in call_messages if hasattr(m, "content")]
    assert any("casual" in t for t in human_texts)


# ──────────────────────────────────────────────
# Critic Agent
# ──────────────────────────────────────────────

APPROVED = CriticOutput(approved=True, issues=[])
REJECTED = CriticOutput(
    approved=False, issues=["tone mismatch"], fixed_body="Better post body"
)


@pytest.mark.asyncio
async def test_critic_approved():
    from app.agents.critic_agent import CriticAgent

    agent = CriticAgent()
    agent._chain = _mock_chain(APPROVED)

    result = await agent.review(CONTENT_OUTPUT, BRAND)
    assert result.approved is True
    assert result.fixed_body is None


@pytest.mark.asyncio
async def test_critic_rejected_with_fix():
    from app.agents.critic_agent import CriticAgent

    agent = CriticAgent()
    agent._chain = _mock_chain(REJECTED)

    result = await agent.review(CONTENT_OUTPUT, BRAND)
    assert result.approved is False
    assert result.fixed_body == "Better post body"
    assert "tone mismatch" in result.issues
