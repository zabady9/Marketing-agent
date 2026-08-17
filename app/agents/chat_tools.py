"""Chat agent tools: subject knowledge search, web search (Tavily), market data lookup,
safe arithmetic calculator, and formal analysis engine."""
import ast
import json
import logging
import math
from datetime import datetime, timezone
from typing import Literal

from langchain_core.tools import tool
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import AsyncSessionLocal
from app.services.knowledge_search import search_knowledge
from app.services.source_registry import SourceRegistry

logger = logging.getLogger(__name__)

MetricType = Literal[
    "revenue", "funding", "headcount", "market_share",
    "growth_rate", "pricing", "product_launches", "news_sentiment",
]

# How old a Tavily result's published_date must be (in days) to be flagged stale.
_STALE_THRESHOLD_DAYS = 180


def _parse_published_date(raw: str | None) -> datetime | None:
    if not raw:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _is_stale(published_date: datetime | None) -> bool:
    if published_date is None:
        return False
    age_days = (datetime.now(timezone.utc) - published_date).days
    return age_days > _STALE_THRESHOLD_DAYS


# ── Safe calculator ────────────────────────────────────────────────────────────

_ALLOWED_NAMES = {
    "abs": abs, "round": round, "min": min, "max": max,
    "log": math.log, "log10": math.log10, "log2": math.log2,
    "sqrt": math.sqrt, "pow": pow, "int": int, "float": float,
}

_ALLOWED_NODE_TYPES = (
    ast.Expression, ast.BinOp, ast.UnaryOp, ast.Call,
    ast.Constant, ast.Name, ast.Load,
    ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow, ast.FloorDiv,
    ast.UAdd, ast.USub,
)


def _safe_eval(expression: str) -> float:
    """Evaluate *expression* using only safe numeric operations.

    Raises ValueError if the expression contains disallowed constructs.
    """
    try:
        tree = ast.parse(expression.strip(), mode="eval")
    except SyntaxError as exc:
        raise ValueError(f"Invalid expression syntax: {exc}") from exc

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODE_TYPES):
            raise ValueError(
                f"Disallowed operation in expression: {type(node).__name__}"
            )
        if isinstance(node, ast.Name) and node.id not in _ALLOWED_NAMES:
            raise ValueError(f"Disallowed name in expression: {node.id!r}")

    result = eval(  # noqa: S307 — AST-validated safe subset only
        compile(tree, "<calculator>", "eval"),
        {"__builtins__": {}},
        _ALLOWED_NAMES,
    )
    if not isinstance(result, (int, float)):
        raise ValueError("Expression did not evaluate to a number.")
    return float(result)


# ── Tool factory ───────────────────────────────────────────────────────────────

def make_chat_tools(
    workspace_id: str,
    brand_profile: dict,
    session_factory: async_sessionmaker = AsyncSessionLocal,
    source_registry: SourceRegistry | None = None,
) -> tuple[list, dict, list[str], SourceRegistry]:
    """Return (tools_list, tool_map, created_analysis_ids, source_registry).

    source_registry is created here if not supplied by the caller; it accumulates
    citation bindings across all tool calls in a single request turn.

    created_analysis_ids accumulates IDs of ConsultingAnalysis rows created by
    run_formal_analysis during a turn, so the caller can backfill chat_message_id
    after the assistant ChatMessage commits.
    """
    if source_registry is None:
        source_registry = SourceRegistry()
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

        CITATION DISCIPLINE (STRICT):
          - Every result is automatically assigned a citation ID like [S1], [S2], etc.
          - Reference these IDs in your response — never paraphrase without citing the ID.
          - Label each figure: verified data, reported figure, estimate, or proxy indicator.
          - Results older than 6 months are flagged as potentially outdated.

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
        for r in results:
            title = r.get("title", "Untitled")
            content = (r.get("content") or "")[:300]
            url = r.get("url", "")
            published_raw = r.get("published_date") or r.get("published") or None
            pub_dt = _parse_published_date(published_raw)
            stale = _is_stale(pub_dt)
            fetched_at = pub_dt.strftime("%Y-%m-%d") if pub_dt else datetime.now(timezone.utc).strftime("%Y-%m-%d")

            if url:
                source_id = source_registry.register(
                    url=url,
                    title=title,
                    fetched_at=fetched_at,
                    snippet=content,
                    stale=stale,
                )
                stale_note = " ⚠ *possibly outdated*" if stale else ""
                lines.append(
                    f"**[{source_id}] {title}**{stale_note}\n   {content}\n   Source: {url}"
                )
            else:
                lines.append(f"**{title}**\n   {content}")

        return "\n\n".join(lines)

    @tool
    async def get_market_data(competitor_name: str, metric_type: MetricType) -> str:
        """Look up cached or live competitor data for a specific metric type.

        Uses a local cache first (TTL varies by metric) and calls the web when stale.
        Results include source_url, source_title, and fetched_at.

        Reference the automatically assigned citation ID (e.g. [S3]) in your response
        rather than repeating the full URL inline. Label the figure as: verified data,
        reported figure, estimate, or proxy indicator.

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

        # Register the source if we have a URL
        source_url = result.get("source_url") or ""
        source_title = result.get("source_title") or competitor_name
        fetched_at = str(result.get("fetched_at") or datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        if source_url:
            source_id = source_registry.register(
                url=source_url,
                title=source_title,
                fetched_at=fetched_at[:10],
                snippet=f"{metric_type} data for {competitor_name}",
                stale=result.get("stale", False),
            )
            result["citation_id"] = source_id

        return json.dumps(result, default=str)

    @tool
    async def search_subject_knowledge(query: str) -> str:
        """Search subject knowledge documents for specific information about the entity under analysis.

        Retrieved chunks are assigned citation IDs (e.g. [K1], [K2]) automatically.
        Reference these IDs when citing internal documents in your response.

        Use this when you need more detail than what's already in context, e.g.,
        specific business line details, competitor notes, or areas of interest context.
        """
        async with session_factory() as db:
            chunks = await search_knowledge(query, workspace_id, db, k=3)
        if not chunks:
            return "No relevant knowledge found for that query."

        parts = []
        for chunk in chunks:
            # Internal documents: use a K-prefix so they're visually distinct from web sources
            meta = chunk.metadata_ or {}
            url = meta.get("source_url") or f"knowledge://{chunk.id}"
            title = meta.get("filename") or meta.get("title") or "Internal document"
            source_id = source_registry.register(
                url=url,
                title=title,
                fetched_at=meta.get("indexed_at", "internal"),
                snippet=chunk.content[:200],
            )
            parts.append(f"[{source_id}] {chunk.content}")

        return "\n---\n".join(parts)

    @tool
    def calculate(expression: str) -> str:
        """Evaluate a mathematical expression safely.

        Use for ALL derived arithmetic: growth rates, CAGR, ratios, percentages,
        TAM/SAM/SOM calculations, market share, year-over-year changes.

        The LLM must NOT compute these inline — always call this tool for any math
        so the result is verified and traceable.

        Supported: +, -, *, /, //, %, ** (power), and functions:
          abs, round, min, max, log, log10, log2, sqrt, pow, int, float

        Examples:
          calculate("(450 - 320) / 320 * 100")   → growth rate %
          calculate("sqrt(1500 / 200) - 1")       → CAGR approximation
          calculate("round(12.5 / 87.3 * 100, 2)")  → market share %

        Returns JSON: {"result": <number>, "expression": <original>}
        """
        try:
            result = _safe_eval(expression)
            return json.dumps({"result": result, "expression": expression})
        except (ValueError, ZeroDivisionError) as exc:
            return json.dumps({"error": str(exc), "expression": expression})

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

            # Register citations from consulting research into the shared registry
            for c in citations:
                if c.url:
                    source_registry.register(
                        url=c.url,
                        title=c.title,
                        fetched_at=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
                        snippet=c.snippet,
                    )

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
        calculate,
        run_formal_analysis,
    ]
    tool_map = {t.name: t for t in tools}
    return tools, tool_map, created_analysis_ids, source_registry
