import uuid

from sqlalchemy import Enum, String, func
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import expression

from app.database import Base
from app.models.enums import AutonomyLevel


class Workspace(Base):
    __tablename__ = "workspaces"

    id: Mapped[str] = mapped_column(
        String, primary_key=True, default=lambda: str(uuid.uuid4())
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    autonomy_level: Mapped[str] = mapped_column(
        Enum(AutonomyLevel, native_enum=False),
        nullable=False,
        server_default=expression.literal(AutonomyLevel.supervised.value),
    )
    created_at: Mapped[str] = mapped_column(server_default=func.now())
    updated_at: Mapped[str] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
