import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.intent_agent import classify_intent
from app.database import get_db
from app.models.consulting_analysis import ConsultingAnalysis
from app.schemas.consulting import ConsultRequest, ConsultingAnalysisResponse
from app.services import event_bus
from app.services.brand_profile import brand_profile_to_dict, get_brand_profile
from app.services.consulting import run_consulting_analysis
from app.services.workspace import get_workspace

logger = logging.getLogger(__name__)

router = APIRouter(tags=["consult"])

# market_comparison, competitive_analysis, trend_check are chat-only intents —
# they require the live web_search / get_market_data tools in the chat agent,
# not the structured batch analysis pipeline here.
_NON_ACTIONABLE_TYPES = {
    "general", "out_of_scope",
    "market_comparison", "competitive_analysis", "trend_check",
}


@router.post(
    "/{workspace_id}/consult",
    response_model=ConsultingAnalysisResponse,
    status_code=202,
)
async def consult(
    workspace_id: str,
    data: ConsultRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    ws = await get_workspace(db, workspace_id)
    if not ws:
        raise HTTPException(status_code=404, detail="Workspace not found")

    bp = await get_brand_profile(db, workspace_id)
    if not bp:
        raise HTTPException(
            status_code=422,
            detail="Brand profile not set — call PUT /brand-profile first",
        )

    brand_dict = brand_profile_to_dict(bp)

    try:
        classification = await classify_intent(data.question, brand_dict)
    except Exception:
        logger.exception("Intent classification failed for workspace %s", workspace_id)
        raise HTTPException(
            status_code=503,
            detail="Classification service unavailable — please try again in a moment.",
        )

    if classification.analysis_type in _NON_ACTIONABLE_TYPES:
        raise HTTPException(
            status_code=422,
            detail={
                "classification": classification.analysis_type,
                "message": (
                    classification.suggestion
                    or "Please clarify what type of analysis you need."
                ),
            },
        )

    analysis = ConsultingAnalysis(
        workspace_id=workspace_id,
        analysis_type=classification.analysis_type,
        status="generating",
    )
    db.add(analysis)
    await db.commit()
    await db.refresh(analysis)

    event_bus.create(analysis.id)

    background_tasks.add_task(
        run_consulting_analysis,
        analysis_id=analysis.id,
        workspace_id=workspace_id,
        analysis_type=classification.analysis_type,
        brand_profile=brand_dict,
        context=data.question,
    )

    return ConsultingAnalysisResponse(
        id=analysis.id,
        workspace_id=workspace_id,
        analysis_type=analysis.analysis_type,
        status=analysis.status,
        results=None,
        error=None,
        created_at=str(analysis.created_at),
        classified_as=classification.analysis_type,
    )
