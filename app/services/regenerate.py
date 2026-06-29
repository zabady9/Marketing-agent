from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.graph import _content_agent, _critic_agent
from app.agents.schemas import ContentIdea, ContentOutput
from app.database import AsyncSessionLocal
from app.models.enums import PostStatus
from app.models.post import Post
from app.services.action_log import log_action
from app.services.brand_profile import brand_profile_to_dict, get_brand_profile
from app.services.post_status import transition


async def regenerate_post(
    post_id: str,
    note: str | None = None,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> None:
    """Background task: rewrite a single post's content via ContentAgent + CriticAgent."""
    async with session_factory() as db:
        result = await db.execute(select(Post).where(Post.id == post_id))
        post = result.scalar_one_or_none()
        if not post:
            return

        bp = await get_brand_profile(db, post.workspace_id)
        brand_profile = brand_profile_to_dict(bp)

        idea = ContentIdea(
            day=post.day,
            theme=post.theme,
            format=post.format,
            angle=post.angle,
        )

        content_output: ContentOutput = await _content_agent.write(
            idea, brand_profile, revision_hint=note
        )
        critic_output = await _critic_agent.review(content_output, brand_profile)

        # Apply critic's fix when rejected; otherwise use generated content.
        final_content = (
            critic_output.fixed_body
            if not critic_output.approved and critic_output.fixed_body
            else content_output.content
        )

        post.content = final_content
        post.hashtags = content_output.hashtags
        post.suggested_time = content_output.suggested_time

        # Regenerating approved content resets it for re-review.
        if PostStatus(post.status) == PostStatus.approved:
            transition(post, PostStatus.pending_approval)

        await log_action(
            db,
            post.workspace_id,
            "api",
            "regenerate_post",
            {
                "post_id": post_id,
                "note": note,
                "critic_approved": critic_output.approved,
            },
        )
        await db.commit()
