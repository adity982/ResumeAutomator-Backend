"""Small, explainable actions that reduce repeated application work."""
from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_
from sqlalchemy.orm import Session

from .. import models
from ..auth import get_current_user
from ..database import get_db
from ..deps import owned
from ..schemas import AuthUser
from .core import _hash

router = APIRouter(prefix="/api/v1", tags=["productivity"])


def evidence_status(db, uid, documents):
    ids = {s["evidence_id"] for document in documents for s in document.evidence_snapshot}
    rows = db.query(models.EvidenceChunk, models.PortfolioSource).join(models.PortfolioSource, models.PortfolioSource.id == models.EvidenceChunk.source_id).filter(models.EvidenceChunk.user_uid == uid, models.PortfolioSource.user_uid == uid, models.EvidenceChunk.id.in_(ids)).all() if ids else []
    hashes = {e.id: _hash(e.approved_statement + e.content_hash) for e, source in rows if source.status == "ready" and e.review_status == "approved"}
    return {document.id: all(hashes.get(s["evidence_id"]) == s["hash"] for s in document.evidence_snapshot) for document in documents}


@router.post("/jobs/{job_id}/resume-base/{document_id}")
def reuse_resume(job_id: int, document_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    job = owned(db, models.SavedJob, job_id, auth)
    document = owned(db, models.DocumentVersion, document_id, auth)
    if document.kind != "resume":
        raise HTTPException(422, "Choose a resume, not a cover letter, as your starting version.")
    if not evidence_status(db, auth.uid, [document])[document.id]:
        raise HTTPException(409, "This resume uses changed or removed project evidence. Review its sources before reusing it.")
    return {"job_id": job.id, "source_document_id": document.id, "source_title": document.title, "source_version": document.version, "content": document.content, "evidence_ids": [s["evidence_id"] for s in document.evidence_snapshot], "approved": False, "logical_id": None, "warnings": ["Copied as a new draft. Check company names, dates and relevance for this target. Approval does not carry over.", "Existing project citations were checked against their current source snapshots; other statements remain your responsibility."]}


@router.get("/work-queue")
def work_queue(limit: int = Query(default=8, ge=1, le=30), db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    now = dt.datetime.now(dt.timezone.utc)
    horizon = now + dt.timedelta(days=7)
    items = []
    def add(key, kind, title, detail, href, rank, due=None):
        items.append({"key": key, "kind": kind, "title": title, "detail": detail, "href": href, "due_at": due, "overdue": bool(due and due.replace(tzinfo=dt.timezone.utc) < now), "rank": rank})

    active = db.query(models.Application).outerjoin(models.SavedJob, models.Application.job_id == models.SavedJob.id).filter(models.Application.user_uid == auth.uid, models.Application.stage != "closed", or_(models.Application.job_id.is_(None), (models.SavedJob.user_uid == auth.uid) & (models.SavedJob.archived.is_(False))))
    deadlines = active.filter(models.Application.stage == "saved", models.Application.deadline <= horizon).order_by(models.Application.deadline).limit(100).all()
    for application in deadlines:
        add(f"deadline-{application.id}", "deadline", f"Check deadline: {application.role}", f"{application.company} · Confirm the posting is still open before applying.", f"#/jobs/{application.job_id}/tracking" if application.job_id else "#/activity", 0, application.deadline)

    tasks = db.query(models.FollowUpTask, models.Application).join(models.Application, models.Application.id == models.FollowUpTask.application_id).outerjoin(models.SavedJob, models.Application.job_id == models.SavedJob.id).filter(models.FollowUpTask.user_uid == auth.uid, models.Application.user_uid == auth.uid, models.Application.stage != "closed", models.FollowUpTask.completed_at.is_(None), models.FollowUpTask.due_at <= horizon, or_(models.Application.job_id.is_(None), (models.SavedJob.user_uid == auth.uid) & (models.SavedJob.archived.is_(False)))).order_by(models.FollowUpTask.due_at).limit(100).all()
    for task, application in tasks:
        add(f"task-{task.id}", "follow_up", task.title, f"{application.company} · {application.role}. Review the situation before contacting anyone.", f"#/jobs/{application.job_id}/tracking" if application.job_id else "#/activity", 1, task.due_at)

    applications = active.order_by(models.Application.updated_at.desc()).limit(100).all()
    document_ids = {a.resume_document_id for a in applications if a.resume_document_id}
    documents = db.query(models.DocumentVersion).filter(models.DocumentVersion.user_uid == auth.uid, models.DocumentVersion.id.in_(document_ids)).all() if document_ids else []
    current = evidence_status(db, auth.uid, documents)
    by_id = {d.id: d for d in documents}
    for application in applications:
        document = by_id.get(application.resume_document_id)
        if document and not current.get(document.id, False):
            add(f"evidence-{application.id}", "evidence", f"Review changed evidence: {application.role}", f"{application.company} · The attached version refers to changed or unavailable project evidence. Your saved document is preserved.", f"#/jobs/{application.job_id}/documents" if application.job_id else "#/activity", 2)
        elif application.stage == "saved" and (not document or not document.approved):
            add(f"resume-{application.id}", "resume", f"Prepare a reviewed resume: {application.role}", f"{application.company} · No approved resume is attached to this application.", f"#/jobs/{application.job_id}/prepare" if application.job_id else "#/activity", 3)

    imports = db.query(models.IngestionJob, models.PortfolioSource).join(models.PortfolioSource, models.PortfolioSource.id == models.IngestionJob.source_id).filter(models.IngestionJob.user_uid == auth.uid, models.PortfolioSource.user_uid == auth.uid, models.IngestionJob.status == "failed", models.PortfolioSource.status == "failed").order_by(models.IngestionJob.updated_at.desc()).limit(20).all()
    seen_sources = set()
    for ingestion, source in imports:
        if source.id not in seen_sources:
            add(f"import-{source.id}", "import", f"Review failed import: {source.repository}", "Open My evidence to inspect the failure and retry selected files.", "#/evidence", 4)
            seen_sources.add(source.id)
    items.sort(key=lambda item: (item["rank"], item["due_at"].replace(tzinfo=dt.timezone.utc) if item["due_at"] else horizon, item["key"]))
    for item in items:
        item.pop("rank")
    return {"items": items[:limit], "has_more": len(items) > limit, "generated_at": now, "scope": "Deadlines and follow-ups within seven days (including overdue); up to 100 per category, evidence/package checks on the 100 most recently updated active applications, and 20 recent failed imports. Closed and archived work is excluded. This is a checklist, not a hiring prediction."}
