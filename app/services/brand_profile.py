from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.brand_profile import BrandProfile
from app.schemas.brand_profile import BrandProfileUpsert
from app.services.action_log import log_action


def brand_profile_to_dict(bp: BrandProfile | None) -> dict:
    if bp is None:
        return {}
    return {
        "brand_name": bp.brand_name or "",
        "company_name": bp.company_name or "",
        "industry": bp.industry or "",
        "products": bp.products or [],
        "audience_segments": bp.audience_segments or [],
        "tone": bp.tone or "",
        "voice_guidelines": bp.voice_guidelines or "",
        "positioning": bp.positioning or "",
        "goals": bp.goals or [],
        "avoid": bp.avoid or [],
        "extra": bp.extra or {},
    }


async def upsert_brand_profile(
    db: AsyncSession, workspace_id: str, data: BrandProfileUpsert
) -> BrandProfile:
    result = await db.execute(
        select(BrandProfile).where(BrandProfile.workspace_id == workspace_id)
    )
    bp = result.scalar_one_or_none()

    if bp is None:
        bp = BrandProfile(workspace_id=workspace_id)
        db.add(bp)

    if data.company_name is not None:
        bp.company_name = data.company_name
    if data.brand_name is not None:
        bp.brand_name = data.brand_name
    if data.industry is not None:
        bp.industry = data.industry
    if data.products is not None:
        bp.products = [p.model_dump() for p in data.products]
    if data.audience_segments is not None:
        bp.audience_segments = [a.model_dump() for a in data.audience_segments]
    if data.tone is not None:
        bp.tone = data.tone
    if data.voice_guidelines is not None:
        bp.voice_guidelines = data.voice_guidelines
    if data.positioning is not None:
        bp.positioning = data.positioning
    if data.goals is not None:
        bp.goals = data.goals
    if data.avoid is not None:
        bp.avoid = data.avoid
    if data.extra is not None:
        bp.extra = data.extra
    if data.onboarding_status is not None:
        bp.onboarding_status = data.onboarding_status

    await db.flush()
    await log_action(
        db=db,
        workspace_id=workspace_id,
        actor="system",
        action="brand_profile.upserted",
        payload=data.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(bp)
    return bp


async def get_brand_profile(db: AsyncSession, workspace_id: str) -> BrandProfile | None:
    result = await db.execute(
        select(BrandProfile).where(BrandProfile.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()
