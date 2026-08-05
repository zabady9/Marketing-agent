"""Background task for consulting analysis generation."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.consulting_agent import gather_research, run_analysis
from app.agents.eval_agent import run_eval
from app.database import AsyncSessionLocal
from app.models.consulting_analysis import ConsultingAnalysis
from app.services import event_bus

logger = logging.getLogger(__name__)

MIN_CITATIONS = 4

DISCLAIMER = (
    "هذا التحليل مُولَّد بالذكاء الاصطناعي استناداً إلى مصادر عامة متاحة على الإنترنت. "
    "يُعدّ مسودة أولية تستلزم مراجعة متخصص قبل اتخاذ أي قرار استثماري أو استراتيجي."
)


async def run_consulting_analysis(
    analysis_id: str,
    workspace_id: str,
    analysis_type: str,
    brand_profile: dict,
    context: str | None,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> None:
    """Background task: research → structured report → persist."""
    async with session_factory() as db:
        try:
            await event_bus.emit(analysis_id, {
                "type": "research_start",
                "analysis_type": analysis_type,
            })

            citations = await gather_research(brand_profile, analysis_type, context)

            # Fallback was active when industry was empty — "general business" queries were used.
            # In that case bypass the citation floor and proceed with degraded output.
            using_fallback_industry = not brand_profile.get("industry")
            low_sources = len(citations) < MIN_CITATIONS

            await event_bus.emit(analysis_id, {
                "type": "research_done",
                "citation_count": len(citations),
                "low_sources": low_sources,
            })

            if low_sources and not using_fallback_industry:
                error_msg = (
                    f"Could not retrieve enough sources ({len(citations)}) — "
                    f"please try again in a moment."
                )
                result = await db.execute(
                    select(ConsultingAnalysis).where(ConsultingAnalysis.id == analysis_id)
                )
                analysis = result.scalar_one()
                analysis.status = "failed"
                analysis.error = error_msg
                await db.commit()
                await event_bus.emit(analysis_id, {"type": "error", "message": error_msg})
                return

            await event_bus.emit(analysis_id, {"type": "analysis_start"})

            output = await run_analysis(brand_profile, analysis_type, citations, context)
            output_dict = output.model_dump()

            citations_dicts = [c.model_dump() for c in citations]

            # All list sections empty despite having citations → LLM found sources irrelevant
            list_sections = [v for v in output_dict.values() if isinstance(v, list)]
            no_relevant_findings = (
                bool(list_sections)
                and all(len(s) == 0 for s in list_sections)
                and bool(citations)
            )

            eval_result = None
            try:
                eval_output = await run_eval(analysis_type, output_dict, citations_dicts)
                eval_result = eval_output.model_dump()
            except Exception as eval_exc:
                logger.warning("Eval failed for analysis %s: %s", analysis_id, eval_exc)

            results = {
                "analysis_type": analysis_type,
                "output": output_dict,
                "citations": citations_dicts,
                "disclaimer": DISCLAIMER,
                "low_sources": low_sources,
                "no_relevant_findings": no_relevant_findings,
                "eval": eval_result,
            }

            result = await db.execute(
                select(ConsultingAnalysis).where(ConsultingAnalysis.id == analysis_id)
            )
            analysis = result.scalar_one()
            analysis.results = results
            analysis.status = "ready"
            await db.commit()

            await event_bus.emit(analysis_id, {"type": "done", "analysis_id": analysis_id})

        except Exception as exc:
            logger.exception("Consulting analysis failed for %s", analysis_id)
            await event_bus.emit(analysis_id, {
                "type": "error",
                "message": "Analysis failed. Check server logs for details.",
            })
            async with session_factory() as err_db:
                result = await err_db.execute(
                    select(ConsultingAnalysis).where(ConsultingAnalysis.id == analysis_id)
                )
                analysis = result.scalar_one_or_none()
                if analysis:
                    analysis.status = "failed"
                    analysis.error = type(exc).__name__
                    await err_db.commit()
        finally:
            event_bus.close(analysis_id)
