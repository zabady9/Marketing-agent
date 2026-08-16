from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analysis_subject import AnalysisSubject
from app.schemas.analysis_subject import AnalysisSubjectUpsert
from app.services.action_log import log_action


def analysis_subject_to_dict(subject: AnalysisSubject | None) -> dict:
    if subject is None:
        return {}
    return {
        "subject_name": subject.subject_name or "",
        "legal_name": subject.legal_name or "",
        "subject_type": subject.subject_type or "",
        "industry": subject.industry or "",
        "business_lines": subject.business_lines or [],
        "tracked_competitors": subject.tracked_competitors or [],
        "subject_description": subject.subject_description or "",
        "areas_of_interest": subject.areas_of_interest or [],
        "extra": subject.extra or {},
    }


async def upsert_analysis_subject(
    db: AsyncSession, workspace_id: str, data: AnalysisSubjectUpsert
) -> AnalysisSubject:
    result = await db.execute(
        select(AnalysisSubject).where(AnalysisSubject.workspace_id == workspace_id)
    )
    subject = result.scalar_one_or_none()

    if subject is None:
        subject = AnalysisSubject(workspace_id=workspace_id)
        db.add(subject)

    if data.subject_name is not None:
        subject.subject_name = data.subject_name
    if data.legal_name is not None:
        subject.legal_name = data.legal_name
    if data.subject_type is not None:
        subject.subject_type = data.subject_type
    if data.industry is not None:
        subject.industry = data.industry
    if data.business_lines is not None:
        subject.business_lines = [b.model_dump() for b in data.business_lines]
    if data.tracked_competitors is not None:
        subject.tracked_competitors = [c.model_dump() for c in data.tracked_competitors]
    if data.subject_description is not None:
        subject.subject_description = data.subject_description
    if data.areas_of_interest is not None:
        subject.areas_of_interest = data.areas_of_interest
    if data.setup_status is not None:
        subject.setup_status = data.setup_status
    if data.extra is not None:
        subject.extra = data.extra

    await db.flush()
    await log_action(
        db=db,
        workspace_id=workspace_id,
        actor="system",
        action="analysis_subject.upserted",
        payload=data.model_dump(exclude_none=True),
    )
    await db.commit()
    await db.refresh(subject)
    return subject


async def get_analysis_subject(db: AsyncSession, workspace_id: str) -> AnalysisSubject | None:
    result = await db.execute(
        select(AnalysisSubject).where(AnalysisSubject.workspace_id == workspace_id)
    )
    return result.scalar_one_or_none()
