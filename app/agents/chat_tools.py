"""Chat agent tools: brand knowledge search, web search (Tavily), draft post creation,
plan generation, and competitor market data lookup."""
import asyncio
import json
import logging
import uuid
from typing import Literal

from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import AsyncSessionLocal
from app.models.enums import PlanStatus, PostStatus
from app.models.content_plan import ContentPlan
from app.models.post import Post
from app.services.chat import get_or_create_chat_draft_plan
from app.services.event_bus import create as bus_create
from app.services.knowledge_search import search_knowledge

logger = logging.getLogger(__name__)

# Strong reference to prevent asyncio GC of fire-and-forget tasks.
_background_tasks: set[asyncio.Task] = set()

MetricType = Literal["followers", "engagement_rate", "pricing", "campaign", "recent_posts"]


def make_chat_tools(
    workspace_id: str,
    brand_profile: dict,
    session_factory: async_sessionmaker = AsyncSessionLocal,
) -> tuple[list, dict]:
    """Return (tools_list, tool_map) for the agentic loop.

    tool_map is {tool_name: tool_callable} used to dispatch tool calls.
    """

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
        metric_type: one of followers, engagement_rate, pricing, campaign, recent_posts.
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
    async def search_brand_knowledge(query: str) -> str:
        """Search brand knowledge documents for specific brand information.

        Use this when you need more detail than what's already in context, e.g.,
        specific product specs, pricing language, or exact messaging guidelines.
        """
        async with session_factory() as db:
            chunks = await search_knowledge(query, workspace_id, db, k=3)
        if not chunks:
            return "No relevant knowledge found for that query."
        return "\n---\n".join(c.content for c in chunks)

    @tool
    async def create_draft_post(
        content: str,
        hashtags: list[str],
        suggested_time: str,
        theme: str,
    ) -> dict:
        """Draft a social media post and save it to the workspace draft queue.

        The user can then review and submit it for approval from the UI.
        Returns the post_id and a content preview.
        """
        async with session_factory() as db:
            plan = await get_or_create_chat_draft_plan(db, workspace_id)
            post = Post(
                id=str(uuid.uuid4()),
                plan_id=plan.id,
                workspace_id=workspace_id,
                day=0,
                theme=theme,
                format="post",
                angle="Chat draft",
                content=content,
                hashtags=hashtags,
                suggested_time=suggested_time,
                status=PostStatus.draft.value,
            )
            db.add(post)
            await db.commit()
            await db.refresh(post)
        preview = content[:100] + ("…" if len(content) > 100 else "")
        return {"post_id": post.id, "preview": preview}

    @tool
    async def trigger_plan_generation(goal: str) -> str:
        """Start a full 7-day content plan generation in the background.

        Returns the plan_id so the user can track it in the Plans section.
        """
        from app.services.generation import run_generation

        plan_id = str(uuid.uuid4())
        async with session_factory() as db:
            plan = ContentPlan(
                id=plan_id,
                workspace_id=workspace_id,
                goal=goal,
                status=PlanStatus.generating.value,
            )
            db.add(plan)
            await db.commit()

        bus_create(plan_id)
        task = asyncio.create_task(
            run_generation(plan_id, workspace_id, brand_profile, goal, session_factory)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

        return f"Plan generation started. Plan ID: {plan_id}"

    tools = [
        web_search,
        get_market_data,
        search_brand_knowledge,
        create_draft_post,
        trigger_plan_generation,
    ]
    tool_map = {t.name: t for t in tools}
    return tools, tool_map
