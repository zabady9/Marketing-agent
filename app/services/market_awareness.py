"""Cache-first competitor market data lookup with Tavily fallback.

Flow per call:
1. Check market_data_cache for a fresh row (within TTL).
2. If fresh  → return cached value immediately (no network call).
3. If stale or missing → call Tavily, upsert result, return fresh data.
4. If Tavily fails → return stale cache row (flagged stale=True), or an
   unavailable signal if no cached row exists at all.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.market_data_cache import MarketDataCache, TTL_HOURS

logger = logging.getLogger(__name__)


def _is_stale(row: MarketDataCache) -> bool:
    ttl = timedelta(hours=row.ttl_hours)
    fetched = row.fetched_at
    if fetched.tzinfo is None:
        fetched = fetched.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) - fetched > ttl


async def _fetch_cache_row(
    workspace_id: str,
    competitor_name: str,
    metric_type: str,
    db: AsyncSession,
) -> MarketDataCache | None:
    result = await db.execute(
        sa.select(MarketDataCache).where(
            MarketDataCache.workspace_id == workspace_id,
            MarketDataCache.competitor_name == competitor_name,
            MarketDataCache.metric_type == metric_type,
        )
    )
    return result.scalar_one_or_none()


async def _search_tavily(
    competitor_name: str, metric_type: str, industry: str, tavily_api_key: str
) -> dict:
    from tavily import AsyncTavilyClient  # lazy import — not available until installed

    metric_label = metric_type.replace("_", " ")
    query = f"{competitor_name} {metric_label} {industry} 2025"

    client = AsyncTavilyClient(api_key=tavily_api_key)
    response = await client.search(query, max_results=5)
    results = response.get("results", [])

    if not results:
        return {"value": None, "source_url": None, "source_title": None}

    top = results[0]
    return {
        "value": {
            "summary": top.get("content", "")[:500],
            "raw_results": [
                {
                    "title": r.get("title"),
                    "url": r.get("url"),
                    "content": r.get("content", "")[:300],
                }
                for r in results
            ],
        },
        "source_url": top.get("url"),
        "source_title": top.get("title"),
    }


async def _upsert_cache_row(
    workspace_id: str,
    competitor_name: str,
    metric_type: str,
    data: dict,
    db: AsyncSession,
) -> None:
    ttl = TTL_HOURS.get(metric_type, 168)
    stmt = (
        pg_insert(MarketDataCache)
        .values(
            workspace_id=workspace_id,
            competitor_name=competitor_name,
            metric_type=metric_type,
            value=data["value"],
            source_url=data.get("source_url"),
            source_title=data.get("source_title"),
            ttl_hours=ttl,
        )
        .on_conflict_do_update(
            constraint="uq_market_data_cache",
            set_={
                "value": data["value"],
                "source_url": data.get("source_url"),
                "source_title": data.get("source_title"),
                "fetched_at": sa.text("now()"),
                "ttl_hours": ttl,
            },
        )
    )
    await db.execute(stmt)
    await db.commit()


async def get_market_data(
    workspace_id: str,
    competitor_name: str,
    metric_type: str,
    industry: str,
    tavily_api_key: str,
    db: AsyncSession,
) -> dict:
    """Return market data for a competitor metric, using the cache when fresh."""
    normalized = competitor_name.lower().strip()
    row = await _fetch_cache_row(workspace_id, normalized, metric_type, db)

    if row and not _is_stale(row):
        return {
            "value": row.value,
            "source_url": row.source_url,
            "source_title": row.source_title,
            "fetched_at": row.fetched_at.isoformat(),
            "cached": True,
            "stale": False,
        }

    try:
        data = await _search_tavily(normalized, metric_type, industry, tavily_api_key)
        if data["value"] is not None:
            await _upsert_cache_row(workspace_id, normalized, metric_type, data, db)
        return {
            "value": data["value"],
            "source_url": data.get("source_url"),
            "source_title": data.get("source_title"),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "cached": False,
            "stale": False,
        }
    except Exception as exc:
        logger.warning(
            "Tavily search failed for %s / %s: %s", competitor_name, metric_type, exc
        )
        if row:
            # Return stale cache rather than nothing
            return {
                "value": row.value,
                "source_url": row.source_url,
                "source_title": row.source_title,
                "fetched_at": row.fetched_at.isoformat(),
                "cached": True,
                "stale": True,
            }
        return {
            "value": None,
            "stale": True,
            "unavailable": True,
            "message": f"No data available for {competitor_name} / {metric_type}",
        }
