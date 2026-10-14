"""
Tests for Mode A markdown export (app.services.export.build_report_markdown)
and the GET .../studies/{id}/export endpoint. Every block type must render —
there is no section allow-list that could silently drop content.
"""

from __future__ import annotations

from app.models import StudyResult
from app.schemas.blocks import parse_block
from app.services.export import build_report_markdown

ALL_BLOCKS = [
    {"type": "answer", "headline": "Yes, in a niche", "body": "Because...", "confidence": "medium"},
    {"type": "text", "kind": "reasoning", "markdown": "Reasoning text"},
    {"type": "stats", "items": [{"label": "Break-even", "value": "8", "unit": "months", "basis": "calculated"}]},
    {"type": "chart", "chart_type": "bar", "categories": ["2025", "2026"],
     "series": [{"name": "Revenue", "data": [10, 20]}], "x_label": "Year"},
    {"type": "table", "columns": ["Name", "Price"], "rows": [["A|B", "5"]], "caption": "Prices"},
    {"type": "comparison", "options": ["Us", "Them"], "criteria": ["Price"], "scores": [[8], [5]],
     "verdict": "We win on price"},
    {"type": "board", "cells": [{"title": "Strengths", "items": [{"label": "Fresh beans"}]}]},
    {"type": "matrix", "x_axis": "Price", "y_axis": "Quality", "points": [{"label": "Us", "x": 7, "y": 9}]},
    {"type": "diagram", "mermaid": "flowchart TD\n  A --> B", "fallback": "- A\n  - B"},
    {"type": "timeline", "phases": [{"label": "Launch", "start": "Q1", "end": "Q2", "items": ["Pilot"]}]},
    {"type": "list", "style": "numbered", "items": [{"label": "Hire a roaster", "detail": "first"}]},
]


def _study(**overrides) -> StudyResult:
    blocks = [parse_block(b).model_dump() for b in ALL_BLOCKS]
    blocks[0]["citations"] = [{"url": "https://ex.com/a", "title": "Source A", "snippet": ""}]
    defaults = dict(
        status="completed",
        title="Test Analysis",
        goal="Can I compete?",
        report={
            "title": "Test Analysis",
            "answer": {"headline": "Yes", "body": "In a niche.", "confidence": "medium"},
            "findings": ["Finding one"],
            "recommendations": ["Do this"],
            "steps": [{"id": "s1", "title": "Step one", "summary": "Summary one", "status": "completed",
                       "blocks": blocks}],
            "sources": [{"url": "https://ex.com/a", "title": "Source A", "snippet": ""}],
        },
    )
    defaults.update(overrides)
    return StudyResult(**defaults)


class TestBuildReportMarkdown:
    def test_renders_answer_findings_steps_and_sources(self):
        markdown = build_report_markdown([_study()])

        assert markdown.startswith("# Test Analysis")
        assert "*Question: Can I compete?*" in markdown
        assert markdown.index("## Answer") < markdown.index("## Key findings") < markdown.index("## Step one")
        assert "1. [Source A](https://ex.com/a)" in markdown

    def test_every_block_type_renders_its_content(self):
        markdown = build_report_markdown([_study()])

        for expected in (
            "Yes, in a niche", "Reasoning text", "**Break-even**: 8 months", "| 2025 | 10.0 |",
            "A\\|B", "We win on price", "**Strengths**", "| Us | 7.0 | 9.0 |",
            "```mermaid", "**Launch** (Q1 – Q2)", "1. **Hire a roaster**: first",
        ):
            assert expected in markdown, expected
        assert "*Sources: Source A*" in markdown

    def test_multiple_studies_get_separate_headings(self):
        markdown = build_report_markdown([_study(title="One"), _study(title="Two")])

        assert "# One" in markdown
        assert "# Two" in markdown

    def test_falls_back_when_no_title(self):
        markdown = build_report_markdown([_study(title=None, report={"steps": []})])

        assert markdown.startswith("# Analysis")


class TestExportStudyEndpoint:
    def test_export_returns_markdown(self, client, db_session, make_project):
        project = make_project()
        study = _study(project_id=project.id)
        db_session.add(study)
        db_session.commit()

        resp = client.get(f"/api/projects/{project.id}/studies/{study.id}/export")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "# Test Analysis" in resp.text

    def test_404_for_unknown_study(self, client, make_project):
        project = make_project()
        resp = client.get(f"/api/projects/{project.id}/studies/nonexistent/export")
        assert resp.status_code == 404
