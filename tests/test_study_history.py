from __future__ import annotations

from app.models import StudyResult
from app.orchestrator import PipelineResult


async def test_run_feasibility_study_creates_new_row_each_time(
    db_session, make_project, monkeypatch
):
    """A project's studies used to be a single row, overwritten in place on
    every rerun. Now each run must persist as its own, independent row."""
    import app.services.study as study_module

    async def fake_pipeline(study_id, feasibility_input, queue, glossary=None):
        return PipelineResult()

    monkeypatch.setattr(study_module, "run_feasibility_pipeline", fake_pipeline)

    project = make_project()

    first = await study_module.run_feasibility_study(db_session, project)
    second = await study_module.run_feasibility_study(db_session, project)

    assert first.id != second.id

    rows = db_session.query(StudyResult).filter_by(project_id=project.id).all()
    assert len(rows) == 2
    assert {r.id for r in rows} == {first.id, second.id}
    assert all(r.status == "completed" for r in rows)


def test_get_study_by_id_rejects_cross_project_id(db_session, make_project, client):
    """A study id from project A must not be readable through project B's URL
    — this is the IDOR the by-id endpoint has to guard against."""
    project_a = make_project("Project A")
    project_b = make_project("Project B")

    study_a = StudyResult(project_id=project_a.id, status="completed", verdict="proceed")
    db_session.add(study_a)
    db_session.commit()

    wrong_project_resp = client.get(f"/api/projects/{project_b.id}/studies/{study_a.id}")
    assert wrong_project_resp.status_code == 404

    right_project_resp = client.get(f"/api/projects/{project_a.id}/studies/{study_a.id}")
    assert right_project_resp.status_code == 200
    body = right_project_resp.json()
    assert body["id"] == study_a.id
    assert body["verdict"] == "proceed"
