"""Session context retriever for the meeting agent.

Retrieves and structures the most recent conversation turns relevant to the
current message. Prevents the agent from re-explaining established context
(e.g., re-stating the analysis subject or re-running completed analyses).

Uses recency-weighted selection (not semantic search) for speed: we pull the
k most recent assistant messages so the agent has a clear picture of what was
already covered without a vector search on every turn.
"""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat import ChatMessage, MessageRole

logger = logging.getLogger(__name__)


async def retrieve_context(
    session_id: str,
    db: AsyncSession,
    k: int = 5,
) -> str:
    """Return a compact context block from recent assistant turns in the session.

    Parameters
    ----------
    session_id:
        The active chat session identifier.
    db:
        An open AsyncSession (caller owns the lifecycle).
    k:
        Number of most-recent assistant messages to include (default 5).

    Returns
    -------
    A markdown-formatted context block ready to prepend to retrieved_context,
    or an empty string when no prior messages exist.
    """
    try:
        result = await db.execute(
            select(ChatMessage)
            .where(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.assistant,
            )
            .order_by(ChatMessage.created_at.desc())
            .limit(k)
        )
        messages = list(result.scalars().all())
    except Exception as exc:
        logger.warning("context_retriever: DB query failed (non-fatal): %s", exc)
        return ""

    if not messages:
        return ""

    # Reverse so the oldest comes first (chronological order)
    messages = list(reversed(messages))

    parts = ["## Prior Conversation Context\n"]
    for msg in messages:
        meta = msg.metadata_ or {}
        agent_label = meta.get("agent_name") or msg.agent_id or "Assistant"
        is_synthesis = meta.get("synthesis", False)
        label = f"**{agent_label}** (synthesis)" if is_synthesis else f"**{agent_label}**"
        # Truncate long messages to keep the context block compact
        content = (msg.content or "").strip()
        if len(content) > 600:
            content = content[:580] + "… [truncated]"
        parts.append(f"{label}:\n{content}\n")

    return "\n".join(parts)
