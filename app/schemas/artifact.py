from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SlideContent(BaseModel):
    """One slide's content — the deterministic pptx driver maps this onto
    Presenton's slide-layout JSON schema; it never lets the LLM touch that
    schema directly."""

    heading: str
    bullets: list[str] = Field(..., min_length=1, max_length=8)
    notes: str | None = None


class PresentationOutline(BaseModel):
    """A small, constrained presentation spec the chat agent fills in via
    generate_presentation_tool — deliberately narrow (heading + bullets per
    slide) rather than an open-ended layout DSL, mirroring app.schemas.chart's
    ChartSpec: every field here maps 1:1 to something the deterministic pptx
    driver can hand to Presenton without further interpretation."""

    title: str
    slides: list[SlideContent] = Field(..., min_length=1, max_length=30)


class DocumentSection(BaseModel):
    heading: str
    body: str


class DocumentOutline(BaseModel):
    """Mirrors PresentationOutline for Word/PDF documents — rendered to
    Markdown by the deterministic docx/pdf drivers."""

    title: str
    sections: list[DocumentSection] = Field(..., min_length=1, max_length=50)


class ArtifactSummary(BaseModel):
    """The shape persisted onto ChatMessage.artifact_data and returned to the
    frontend — never the raw file bytes. Mirrors app.schemas.chart.ChartSpec's
    role as the thing the frontend renders directly."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    format: Literal["docx", "pptx", "pdf"]
    title: str
    filename: str
    size_bytes: int
