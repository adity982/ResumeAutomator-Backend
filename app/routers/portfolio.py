from __future__ import annotations

import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import models, portfolio_schemas as schemas
from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_user, owned, verify_optional_owner
from ..schemas import AuthUser
from ..services import embeddings, github_import, github_connection, retrieval
from ..services.ai import tokens, TECH_SKILLS
from ..services.provenance import invalidate_source

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


def source_read(source):
    return {"id": source.id, "repository": source.repository, "commit_sha": source.commit_sha, "source_url": source.source_url, "description": source.description, "is_fork": source.is_fork, "is_private": source.is_private, "status": source.status, "relationship": source.relationship, "contribution": source.contribution, "created_at": source.created_at, "files": [{"path": f["path"], "bytes": f["bytes"], "excerpt": f["content"][:400]} for f in source.files]}


@router.post("/sources/preview", status_code=201)
def preview_source(payload: schemas.SourcePreview, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    if db.query(models.PortfolioSource).filter_by(user_uid=auth.uid).count() >= 20:
        raise HTTPException(409, "Keep up to 20 source snapshots. Remove an older source before importing another.")
    try:
        result = github_import.connected_preview(payload.url, github_connection.access_token(db, auth.uid)) if payload.use_connected_github else github_import.public_preview(payload.url)
    except HTTPException:
        raise
    except Exception as exc:
        # Never return provider payloads or credentials in a client error.
        if isinstance(exc, github_import.ImportFailure):
            raise HTTPException(400, str(exc)) from exc
        raise HTTPException(502, "GitHub import is unavailable. Retry shortly.") from exc
    existing = db.query(models.PortfolioSource).filter_by(user_uid=auth.uid, repository=result["repository"], commit_sha=result["commit_sha"]).first()
    if existing:
        return source_read(existing)
    source = models.PortfolioSource(user_uid=auth.uid, **result)
    db.add(source)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        source = db.query(models.PortfolioSource).filter_by(user_uid=auth.uid, repository=result["repository"], commit_sha=result["commit_sha"]).one()
    db.refresh(source)
    return source_read(source)


@router.get("/sources")
def list_sources(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    return [source_read(s) for s in db.query(models.PortfolioSource).filter_by(user_uid=auth.uid).order_by(models.PortfolioSource.created_at.desc()).all()]


@router.post("/sources/{source_id}/import", status_code=202)
def import_source(source_id: int, payload: schemas.SourceImport, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    source = owned(db, models.PortfolioSource, source_id, auth)
    paths = list(dict.fromkeys(payload.paths))
    if not set(paths) <= {f["path"] for f in source.files}:
        raise HTTPException(422, "Select only files from this source preview.")
    running = db.query(models.IngestionJob).filter(models.IngestionJob.source_id == source_id, models.IngestionJob.user_uid == auth.uid, models.IngestionJob.status.in_(["queued", "running"])).first()
    if running:
        return running
    source.relationship, source.contribution, source.status = payload.relationship, payload.contribution, "queued"
    invalidate_source(db, source_id, auth.uid)
    item = models.IngestionJob(user_uid=auth.uid, source_id=source_id, paths=paths)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/imports")
def list_imports(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    return db.query(models.IngestionJob).filter_by(user_uid=auth.uid).order_by(models.IngestionJob.created_at.desc()).limit(50).all()


@router.post("/imports/{import_id}/cancel")
def cancel_import(import_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    item = owned(db, models.IngestionJob, import_id, auth)
    if item.status in {"queued", "running"}:
        item.status = "cancelled"
        owned(db, models.PortfolioSource, item.source_id, auth).status = "cancelled"
        db.commit()
    return {"status": item.status}


@router.delete("/sources/{source_id}", status_code=204)
def delete_source(source_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    source = owned(db, models.PortfolioSource, source_id, auth)
    invalidate_source(db, source_id, auth.uid)
    db.delete(source)
    db.commit()
    return Response(status_code=204)


@router.get("/sources/{source_id}/evidence")
def source_evidence(source_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    owned(db, models.PortfolioSource, source_id, auth)
    return [{c.name: getattr(row, c.name) for c in models.EvidenceChunk.__table__.columns if c.name not in {"embedding", "user_uid"}} for row in db.query(models.EvidenceChunk).filter_by(user_uid=auth.uid, source_id=source_id).order_by(models.EvidenceChunk.path, models.EvidenceChunk.start_line).all()]


@router.patch("/project-evidence/{evidence_id}")
def review_evidence(evidence_id: int, payload: schemas.EvidenceReview, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    evidence = owned(db, models.EvidenceChunk, evidence_id, auth)
    source = owned(db, models.PortfolioSource, evidence.source_id, auth)
    if source.status != "ready":
        raise HTTPException(409, "Wait until import completes before reviewing evidence.")
    if payload.status == "approved" and len(payload.statement.strip()) < 20:
        raise HTTPException(422, "Describe your own contribution in at least 20 characters before approving.")
    if payload.status == "approved":
        unsupported = (set(tokens(payload.statement)) & TECH_SKILLS) - set(tokens(evidence.content))
        if unsupported:
            raise HTTPException(422, "These technologies do not appear in this excerpt: " + ", ".join(sorted(unsupported)))
        if not set(re.findall(r"\b\d+(?:\.\d+)?%?", payload.statement)) <= set(re.findall(r"\b\d+(?:\.\d+)?%?", evidence.content)):
            raise HTTPException(422, "Numeric claims must appear in the cited source. Use a statement without unsupported metrics.")
    invalidate_source(db, source.id, auth.uid)
    evidence.review_status = payload.status
    evidence.approved_statement = payload.statement.strip() if payload.status == "approved" else ""
    evidence.embedding = embeddings.embed([evidence.content + "\n" + evidence.approved_statement])[0]
    evidence.embedding_version = embeddings.version()
    db.commit()
    return {"id": evidence.id, "review_status": evidence.review_status, "statement": evidence.approved_statement}


@router.post("/jobs/{job_id}/projects")
def recommend_projects(job_id: int, payload: schemas.RecommendRequest, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    job = owned(db, models.SavedJob, job_id, auth)
    if payload.mode == "dense" and embeddings.version() == "none":
        raise HTTPException(409, "Semantic embeddings are disabled. Use lexical mode or configure FastEmbed.")
    result = retrieval.recommend(db, auth.uid, job, payload.max_projects, payload.mode)
    run = models.RetrievalRun(user_uid=auth.uid, job_id=job_id, result=result, input_fingerprint=result["input_fingerprint"])
    db.add(run)
    db.commit()
    db.refresh(run)
    return dict(result, run_id=run.id)


@router.get("/jobs/{job_id}/projects")
def project_history(job_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    owned(db, models.SavedJob, job_id, auth)
    return [{"id": r.id, "created_at": r.created_at, "result": r.result} for r in db.query(models.RetrievalRun).filter_by(user_uid=auth.uid, job_id=job_id).order_by(models.RetrievalRun.id.desc()).limit(10).all()]


@router.get("/workspace")
def get_workspace(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    draft = db.get(models.WorkspaceDraft, auth.uid)
    return {"revision": draft.revision if draft else 0, "data": draft.data if draft else schemas.WorkspaceData().model_dump()}


@router.put("/workspace")
def save_workspace(payload: schemas.WorkspaceSave, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.data.selected_job_id, auth)
    for evidence_id in payload.data.evidence_ids:
        owned(db, models.EvidenceChunk, evidence_id, auth)
    draft = db.get(models.WorkspaceDraft, auth.uid)
    if draft:
        updated = db.query(models.WorkspaceDraft).filter_by(user_uid=auth.uid, revision=payload.revision).update({"data": payload.data.model_dump(), "revision": payload.revision + 1})
        if not updated:
            raise HTTPException(409, "This workspace changed in another tab. Reload before saving.")
    elif payload.revision == 0:
        db.add(models.WorkspaceDraft(user_uid=auth.uid, data=payload.data.model_dump()))
    else:
        raise HTTPException(409, "Workspace revision is no longer available. Reload before saving.")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(409, "This workspace changed in another tab. Reload before saving.") from exc
    return {"revision": payload.revision + 1, "data": payload.data.model_dump()}


@router.delete("/workspace", status_code=204)
def clear_workspace(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    db.query(models.WorkspaceDraft).filter_by(user_uid=auth.uid).delete()
    db.commit()
    return Response(status_code=204)


@router.post("/contacts", status_code=201)
def create_contact(payload: schemas.ContactCreate, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    item = models.Contact(user_uid=auth.uid, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/contacts")
def list_contacts(job_id: int | None = None, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    query = db.query(models.Contact).filter_by(user_uid=auth.uid)
    if job_id is not None:
        owned(db, models.SavedJob, job_id, auth)
        query = query.filter_by(job_id=job_id)
    return query.order_by(models.Contact.id.desc()).limit(200).all()


@router.patch("/contacts/{contact_id}")
def update_contact(contact_id: int, payload: schemas.ContactUpdate, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    item = owned(db, models.Contact, contact_id, auth)
    for key, value in payload.model_dump(exclude_unset=True).items():
        if value is None and key != "follow_up_at":
            raise HTTPException(422, f"{key} cannot be null.")
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/contacts/{contact_id}", status_code=204)
def delete_contact(contact_id: int, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    db.delete(owned(db, models.Contact, contact_id, auth))
    db.commit()
    return Response(status_code=204)


@router.post("/pilot/feedback", status_code=201)
def feedback(payload: schemas.FeedbackCreate, db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    item = models.PilotFeedback(user_uid=auth.uid, **payload.model_dump())
    db.add(item)
    db.commit()
    return {"saved": True}


@router.get("/pilot/summary")
def pilot_summary(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    rows = db.query(models.PilotFeedback).filter_by(user_uid=auth.uid).all()
    return {"responses": len(rows), "average_rating": round(sum(r.rating for r in rows) / len(rows), 2) if rows else None, "completed_without_help": sum(r.completed_without_help for r in rows), "limitations": "Your own feedback only. No hiring-outcome attribution is inferred."}


@router.get("/account/export")
def export_account(db: Session = Depends(get_db), auth: AuthUser = Depends(get_current_user)):
    tables = [models.SavedJob, models.DocumentVersion, models.AnalysisRecord, models.Application, models.ApplicationEvent, models.InterviewSession, models.OutreachKit, models.SavedSearch, models.CareerEvidence, models.FollowUpTask, models.PortfolioSource, models.EvidenceChunk, models.IngestionJob, models.RetrievalRun, models.Contact, models.PilotFeedback, models.WorkspaceDraft]
    result = {}
    for table in tables:
        rows = db.query(table).filter_by(user_uid=auth.uid).all()
        result[table.__tablename__] = [{c.name: getattr(row, c.name).tolist() if hasattr(getattr(row, c.name), "tolist") else getattr(row, c.name) for c in table.__table__.columns if c.name != "embedding"} for row in rows]
    return result


@router.get("/capabilities")
def capabilities():
    return {"embedding_provider": embeddings.settings.embedding_provider, "embedding_version": embeddings.version(), "private_github": github_connection.configured(), "linkedin_automation": False, "generation": "extractive-reviewed-statements", "source_limit": 20}
