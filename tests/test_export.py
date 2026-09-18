"""
Tests for Mode A markdown export (app.services.export.build_study_markdown)
and its router endpoint — deterministic, no LLM involved, so fully testable
without mocking. Mode B (synthesize_chat_export) makes a real LLM call and
is exercised at the unit level only via its markdown-transcript assembly,
not end-to-end here.
"""

from __future__ import annotations

from app.models import StudyResult
from app.services.export import build_study_markdown


def _study(**overrides) -> StudyResult:
    defaults = dict(
        status="completed",
        verdict="proceed",
        confidence_score=0.8,
        title="Test Study",
        sections={
            "executive_summary": {
                "data": {"verdict": "proceed", "executive_summary": {"text": "Looks good."}}
            },
            "financial_feasibility": {
                "data": {
                    "break_even_months": {"value": 8, "calculation_trace": {"fn": "x"}},
                    "npv": {"value": 1000, "citations": ["should be stripped"]},
                }
            },
        },
    )
    defaults.update(overrides)
    return StudyResult(**defaults)


class TestBuildStudyMarkdown:
    def test_renders_sections_in_toc_order_with_heading(self):
        markdown = build_study_markdown([_study()])

        assert markdown.startswith("# Test Study")
        exec_idx = markdown.index("## Executive Summary")
        fin_idx = markdown.index("## Financial Feasibility")
        assert exec_idx < fin_idx

    def test_strips_verbose_keys(self):
        markdown = build_study_markdown([_study()])

        assert "calculation_trace" not in markdown
        assert "should be stripped" not in markdown

    def test_skips_missing_sections(self):
        markdown = build_study_markdown([_study(sections={"executive_summary": {"data": {"verdict": "proceed"}}})])

        assert "## Executive Summary" in markdown
        assert "## Financial Feasibility" not in markdown

    def test_multiple_studies_get_separate_headings(self):
        markdown = build_study_markdown([_study(title="Study One"), _study(title="Study Two")])

        assert "# Study One" in markdown
        assert "# Study Two" in markdown

    def test_falls_back_to_id_when_no_title(self, db_session, make_project):
        project = make_project()
        study = _study(title=None, project_id=project.id)
        db_session.add(study)
        db_session.commit()

        markdown = build_study_markdown([study])

        assert f"# Study {study.id[:8]}" in markdown


class TestExportStudyEndpoint(object):
    def test_export_returns_markdown(self, client, db_session, make_project):
        project = make_project()
        study = _study(project_id=project.id)
        db_session.add(study)
        db_session.commit()

        resp = client.get(f"/api/projects/{project.id}/studies/{study.id}/export")

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/markdown")
        assert "# Test Study" in resp.text

    def test_404_for_unknown_study(self, client, make_project):
        project = make_project()
        resp = client.get(f"/api/projects/{project.id}/studies/nonexistent/export")
        assert resp.status_code == 404
