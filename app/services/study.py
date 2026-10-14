"""Reading and admin-managing analysis runs (StudyResult rows). Running an
analysis lives in app.analysis.engine."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.models import Project, StudyResult
from app.schemas.admin import StudyResultAdminCreate, StudyResultAdminUpdate


def list_study_results(db: Session, project: Project) -> list[StudyResult]:
    return (
        db.query(StudyResult)
        .filter(StudyResult.project_id == project.id, StudyResult.deleted_at.is_(None))
        .order_by(StudyResult.created_at.desc())
        .all()
    )


# ── Admin ──────────────────────────────────────────────────────────────────


def list_study_results_admin(
    db: Session,
    *,
    limit: int,
    offset: int,
    include_deleted: bool,
    project_id: str | None = None,
    status: str | None = None,
) -> tuple[list[StudyResult], int]:
    query = db.query(StudyResult)
    if not include_deleted:
        query = query.filter(StudyResult.deleted_at.is_(None))
    if project_id is not None:
        query = query.filter(StudyResult.project_id == project_id)
    if status is not None:
        query = query.filter(StudyResult.status == status)
    total = query.count()
    items = query.order_by(StudyResult.created_at.desc()).offset(offset).limit(limit).all()
    return items, total


def get_study_result_admin(db: Session, study_id: str) -> StudyResult | None:
    return db.query(StudyResult).filter_by(id=study_id).one_or_none()


def create_study_result_admin(db: Session, payload: StudyResultAdminCreate) -> StudyResult:
    study = StudyResult(**payload.model_dump())
    db.add(study)
    db.commit()
    db.refresh(study)
    return study


def update_study_result(
    db: Session, study: StudyResult, patch: StudyResultAdminUpdate
) -> StudyResult:
    data = patch.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(study, field, value)
    db.commit()
    db.refresh(study)
    return study


def soft_delete_study_result(db: Session, study: StudyResult) -> StudyResult:
    study.deleted_at = datetime.utcnow()
    db.commit()
    db.refresh(study)
    return study


def restore_study_result(db: Session, study: StudyResult) -> StudyResult:
    study.deleted_at = None
    db.commit()
    db.refresh(study)
    return study
