import uuid

from sqlalchemy import Enum, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.enums import OnboardingStatus


class BrandProfile(Base):
    __tablename__ = "brand_profiles"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    workspace_id: Mapped[str] = mapped_column(
        String, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_name: Mapped[str | None] = mapped_column(String, nullable=True)
    brand_name: Mapped[str | None] = mapped_column(String, nullable=True)
    industry: Mapped[str | None] = mapped_column(String, nullable=True)
    products: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    audience_segments: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    tone: Mapped[str | None] = mapped_column(String, nullable=True)
    voice_guidelines: Mapped[str | None] = mapped_column(Text, nullable=True)
    positioning: Mapped[str | None] = mapped_column(Text, nullable=True)
    goals: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    avoid: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    onboarding_status: Mapped[str] = mapped_column(
        Enum(OnboardingStatus, native_enum=False),
        nullable=False,
        server_default=OnboardingStatus.in_progress.value,
    )
    created_at: Mapped[str] = mapped_column(server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
