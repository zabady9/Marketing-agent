"""Chat agent tools: subject knowledge search, web search (Tavily), market data lookup, and formal analysis."""
import json
import logging
from typing import Literal

from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import AsyncSessionLocal
from app.services.knowledge_search import search_knowledge

logger = logging.getLogger(__name__)

MetricType = Literal[
    "revenue", "funding", "headcount", "market_share",
    "growth_rate", "pricing", "product_launches", "news_sentiment",
]


def make_chat_tools(
    workspace_id: str,
    brand_profile: dict,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> tuple[list, dict, list[str]]:
    """Return (tools_list, tool_map, created_analysis_ids) for the agentic loop.

    created_analysis_ids accumulates IDs of ConsultingAnalysis rows created by
    run_formal_analysis during a turn, so the caller can backfill chat_message_id
    after the assistant ChatMessage commits.
    """
    created_analysis_ids: list[str] = []

    @tool
    async def web_search(query: str) -> str:
        """Search the web for real-time information: competitors, market data, industry news,
        pricing benchmarks, financial reports, social metrics, and any topic requiring current data.

        PROXY RESEARCH (CRITICAL): When direct business data — revenue, sales, internal figures —
        is not publicly available, do NOT say "data unavailable." Proactively search for PUBLIC
        PROXY INDICATORS that help estimate the competitor's scale and performance:
          - Public financial reports, investor presentations, annual reports
          - Website/app traffic rankings (Similarweb, SensorTower)
          - Social media follower counts and engagement rates
          - Product pricing and discount patterns (signals positioning and demand)
          - Job postings volume on LinkedIn/Indeed (signals growth rate)
          - News coverage, press releases, funding announcements
          - App store ratings count and review volume
          - Physical store/location counts (for retail or food businesses)
          - E-commerce listing counts and bestseller rankings

        Data labeling (STRICT): Always clearly label what each figure represents:
          ✓ "Reported revenue: $X (Source: [Annual Report 2024](url))"
          ✓ "Estimated scale: app ranked #23 in food delivery (Source: [SensorTower](url))"
          ✗ Never present an estimate or proxy as a confirmed figure.

        ALWAYS include the source URL for every cited data point using [Source Name](url) format.
        Use specific queries (e.g. "Competitor X annual revenue 2024 Saudi Arabia") not vague ones.
        """
        from app.config import settings

        if not settings.tavily_api_key:
            return "Web search unavailable: TAVILY_API_KEY is not configured."

        try:
            from tavily import AsyncTavilyClient
            client = AsyncTavilyClient(api_key=settings.tavily_api_key.get_secret_value())
            response = await client.search(query, max_results=6)
            results = response.get("results", [])
        except Exception as exc:
            logger.warning("Tavily search failed for %r: %s", query, exc)
            return f"Web search temporarily unavailable: {exc}"

        if not results:
            return "No web results found for that query."

        lines = [f"Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            title = r.get("title", "")
            content = r.get("content", "")[:300]
            url = r.get("url", "")
            lines.append(f"{i}. **{title}**\n   {content}\n   Source: {url}")
        return "\n\n".join(lines)

    @tool
    async def get_market_data(competitor_name: str, metric_type: MetricType) -> str:
        """Look up cached or live competitor data for a specific metric type.

        Uses a local cache first (TTL varies by metric) and calls the web when stale.
        Results include source_url, source_title, and fetched_at — ALWAYS cite these
        in your response using [source_title](source_url) format.

        If the result contains unavailable=True, do NOT stop there. Use web_search
        immediately to find proxy indicators for the missing metric instead.

        competitor_name: exact brand name as known in the market (e.g. "Competitor X").
        metric_type: one of revenue, funding, headcount, market_share, growth_rate,
                     pricing, product_launches, news_sentiment.
        """
        from app.config import settings
        from app.services.market_awareness import get_market_data as _get

        if not settings.tavily_api_key:
            return json.dumps({
                "value": None,
                "unavailable": True,
                "message": "Market data unavailable: TAVILY_API_KEY is not configured.",
            })

        industry = brand_profile.get("industry") or "general"

        async with session_factory() as db:
            result = await _get(
                workspace_id=workspace_id,
                competitor_name=competitor_name,
                metric_type=metric_type,
                industry=industry,
                tavily_api_key=settings.tavily_api_key.get_secret_value(),
                db=db,
            )
        return json.dumps(result, default=str)

    @tool
    async def search_subject_knowledge(query: str) -> str:
        """Search subject knowledge documents for specific information about the entity under analysis.

        Use this when you need more detail than what's already in context, e.g.,
        specific business line details, competitor notes, or areas of interest context.
        """
        async with session_factory() as db:
            chunks = await search_knowledge(query, workspace_id, db, k=3)
        if not chunks:
            return "No relevant knowledge found for that query."
        return "\n---\n".join(c.content for c in chunks)

    @tool
    async def run_formal_analysis(analysis_type: str, context: str = "") -> str:
        """Invoke the structured analysis engine to produce a formal report.

        Produces an evidence-backed structured report grounded in web research.
        Call this when the user's request requires a formal structured analysis report.

        analysis_type: The framework to use. Must be one of:
          - "swot": SWOT analysis (strengths, weaknesses, opportunities, threats)
          - "pestel": PESTEL macro-environment analysis
          - "feasibility": Go/no-go feasibility study for a specific decision
          - "market_research": External market landscape, size, and key segments
          - "subject_analysis": Deep analysis of the subject's positioning and competitive structure
        context: Specific question or focus area to ground the analysis (optional but recommended).

        Returns a JSON-formatted structured report. Format its sections into your synthesis —
        do not return the raw JSON to the user.
        """
        from sqlalchemy import select

        from app.agents.consulting_agent import gather_research, run_analysis as _run_analysis
        from app.models.consulting_analysis import ConsultingAnalysis

        _TYPE_MAP = {
            "swot": "swot",
            "pestel": "pestel",
            "feasibility": "feasibility",
            "market_research": "market_research",
            "subject_analysis": "brand_analysis",
        }

        consulting_type = _TYPE_MAP.get(analysis_type)
        if not consulting_type:
            valid = ", ".join(sorted(_TYPE_MAP.keys()))
            return f"Invalid analysis_type '{analysis_type}'. Must be one of: {valid}"

        # Persist a record so the report is retrievable via GET /reports/{id}.
        # analysis_id is tracked in created_analysis_ids so the caller can
        # backfill chat_message_id once the assistant ChatMessage commits.
        async with session_factory() as db:
            record = ConsultingAnalysis(
                workspace_id=workspace_id,
                analysis_type=consulting_type,
                status="generating",
            )
            db.add(record)
            await db.commit()
            await db.refresh(record)
            analysis_id = record.id
        created_analysis_ids.append(analysis_id)

        try:
            citations = await gather_research(brand_profile, consulting_type, context or None)
            output = await _run_analysis(brand_profile, consulting_type, citations, context or None)
            output_dict = output.model_dump()
            citations_dicts = [c.model_dump() for c in citations]

            async with session_factory() as db:
                result = await db.execute(
                    select(ConsultingAnalysis).where(ConsultingAnalysis.id == analysis_id)
                )
                saved = result.scalar_one()
                saved.status = "ready"
                saved.results = {
                    "analysis_type": consulting_type,
                    "output": output_dict,
                    "citations": citations_dicts,
                }
                await db.commit()

            return json.dumps(output_dict, indent=2, ensure_ascii=False)
        except Exception as exc:
            logger.warning("run_formal_analysis failed for type %s: %s", analysis_type, exc)
            try:
                async with session_factory() as db:
                    result = await db.execute(
                        select(ConsultingAnalysis).where(ConsultingAnalysis.id == analysis_id)
                    )
                    saved = result.scalar_one_or_none()
                    if saved:
                        saved.status = "failed"
                        saved.error = str(exc)
                        await db.commit()
            except Exception:
                pass
            return f"Analysis engine temporarily unavailable: {exc}"

    tools = [
        web_search,
        get_market_data,
        search_subject_knowledge,
        run_formal_analysis,
    ]
    tool_map = {t.name: t for t in tools}
    return tools, tool_map, created_analysis_ids
