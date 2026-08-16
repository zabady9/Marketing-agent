"""SQLAlchemy model for the market data cache (competitor metrics with per-metric TTLs)."""
from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.database import Base

# TTL in hours per metric type — slower-changing data gets longer TTL.
TTL_HOURS: dict[str, int] = {
    "revenue":         720,  # 30 days — annual/quarterly figures change rarely
    "funding":         720,  # 30 days — funding rounds are infrequent
    "headcount":       168,  # 7 days
    "market_share":    168,  # 7 days
    "growth_rate":     168,  # 7 days
    "pricing":         168,  # 7 days
    "product_launches":  48,  # 2 days
    "news_sentiment":    24,  # 1 day — news is time-sensitive
}

METRIC_TYPES: tuple[str, ...] = tuple(TTL_HOURS.keys())


class MarketDataCache(Base):
    __tablename__ = "market_data_cache"

    id: Mapped[str] = mapped_column(primary_key=True, default=lambda: str(uuid4()))
    workspace_id: Mapped[str] = mapped_column(
        sa.ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    # Stored normalised (lowercase, stripped) — see market_awareness.py
    competitor_name: Mapped[str]
    # One of METRIC_TYPES
    metric_type: Mapped[str]
    value: Mapped[dict] = mapped_column(postgresql.JSONB)
    source_url: Mapped[str | None]
    source_title: Mapped[str | None]
    fetched_at: Mapped[datetime] = mapped_column(server_default=func.now())
    ttl_hours: Mapped[int] = mapped_column(default=168)

    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "competitor_name", "metric_type",
            name="uq_market_data_cache",
        ),
    )
