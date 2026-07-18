from __future__ import annotations

import hashlib
import uuid

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Query, Response, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_user, owned, verify_optional_owner
from ..services import ai
from ..services.documents import InvalidDocument, create_docx, create_pdf, parse_pdf, safe_filename
from ..services.scraper import UnsafeURL, normalize_url, scrape_job


router = APIRouter(prefix="/api/v1", tags=["core"])


def _hash(value: str) -> str:
    return hashlib.sha256(" ".join(value.split()).lower().encode()).hexdigest()


@router.post("/resumes/parse")
async def parse_resume(
    file: UploadFile = File(...),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    if file.content_type not in {"application/pdf", "application/x-pdf", "application/octet-stream"}:
        raise HTTPException(status_code=415, detail="Only PDF uploads are supported.")
    content = await file.read()
    try:
        parsed = parse_pdf(content)
    except InvalidDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    finally:
        await file.close()
    return {"status": "success", "extracted_data": parsed}


@router.post("/jobs/scrape", response_model=schemas.ScrapeResult)
async def scrape(request: schemas.ScrapeRequest, auth: schemas.AuthUser = Depends(get_current_user)):
    try:
        result, cached = await scrape_job(str(request.url))
    except (UnsafeURL, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return schemas.ScrapeResult(**result, cached=cached)


@router.post("/jobs", response_model=schemas.JobRead, status_code=201)
def create_job(
    payload: schemas.JobCreate,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    ensure_user(db, auth)
    normalized = normalize_url(payload.source_url) if payload.source_url else ""
    content_hash = _hash(payload.description)
    version = (
        db.query(func.max(models.SavedJob.version))
        .filter(models.SavedJob.user_uid == auth.uid, models.SavedJob.content_hash == content_hash)
        .scalar()
        or 0
    ) + 1
    item = models.SavedJob(
        user_uid=auth.uid,
        normalized_url=normalized,
        content_hash=content_hash,
        version=version,
        **payload.model_dump(),
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/jobs", response_model=list[schemas.JobRead])
def list_jobs(
    archived: bool = False,
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    query = db.query(models.SavedJob).filter(models.SavedJob.user_uid == auth.uid, models.SavedJob.archived == archived)
    if search:
        pattern = f"%{search}%"
        query = query.filter((models.SavedJob.title.ilike(pattern)) | (models.SavedJob.company.ilike(pattern)))
    return query.order_by(models.SavedJob.updated_at.desc()).offset(offset).limit(limit).all()


@router.patch("/jobs/{job_id}", response_model=schemas.JobRead)
def update_job(
    job_id: int,
    payload: schemas.JobUpdate,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    item = owned(db, models.SavedJob, job_id, auth)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(item, key, value)
    db.commit()
    db.refresh(item)
    return item


@router.post("/jobs/{job_id}/refresh", response_model=schemas.JobRead, status_code=201)
async def refresh_job(
    job_id: int,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    previous = owned(db, models.SavedJob, job_id, auth)
    if not previous.source_url:
        raise HTTPException(status_code=400, detail="This job does not have a source URL.")
    try:
        result, _ = await scrape_job(previous.source_url)
    except (UnsafeURL, httpx.HTTPError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    item = models.SavedJob(
        user_uid=auth.uid,
        title=result["title"],
        company=previous.company,
        location=previous.location,
        source_url=result["source_url"],
        normalized_url=normalize_url(result["source_url"]),
        description=result["description"],
        extraction_method="scrape",
        content_hash=_hash(result["description"]),
        version=previous.version + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.delete("/jobs/{job_id}", status_code=204)
def delete_job(job_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.SavedJob, job_id, auth)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/documents", response_model=schemas.DocumentRead, status_code=201)
def create_document(
    payload: schemas.DocumentCreate,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    logical_id = payload.logical_id or str(uuid.uuid4())
    version = (
        db.query(func.max(models.DocumentVersion.version))
        .filter(models.DocumentVersion.user_uid == auth.uid, models.DocumentVersion.logical_id == logical_id)
        .scalar()
        or 0
    ) + 1
    item = models.DocumentVersion(user_uid=auth.uid, logical_id=logical_id, version=version, **payload.model_dump(exclude={"logical_id"}))
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/documents", response_model=list[schemas.DocumentRead])
def list_documents(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    return (
        db.query(models.DocumentVersion)
        .filter(models.DocumentVersion.user_uid == auth.uid)
        .order_by(models.DocumentVersion.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(document_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.DocumentVersion, document_id, auth)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/documents/export")
def export_document(payload: schemas.ExportRequest, auth: schemas.AuthUser = Depends(get_current_user)):
    try:
        content = create_pdf(payload.text, payload.template, payload.doc_type) if payload.format == "pdf" else create_docx(payload.text, payload.template, payload.doc_type)
    except InvalidDocument as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    extension = payload.format
    media_type = "application/pdf" if extension == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    filename = f"{safe_filename(payload.filename_hint)}.{extension}"
    return Response(content=content, media_type=media_type, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/analysis", response_model=schemas.AnalysisResult)
def analyze_match(
    payload: schemas.AnalysisRequest,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.document_id, auth)
    result = ai.analyze(payload.resume_text, payload.jd_text)
    record = models.AnalysisRecord(
        user_uid=auth.uid,
        job_id=payload.job_id,
        document_id=payload.document_id,
        score=result.score,
        dimensions=[item.model_dump() for item in result.dimensions],
        gap_plan=[item.model_dump() for item in result.gap_plan],
        methodology_version=result.methodology_version,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return result.model_copy(update={"id": record.id})


@router.post("/analysis/batch", response_model=list[schemas.BatchAnalysisItem])
def batch_analysis(payload: schemas.BatchAnalysisRequest, auth: schemas.AuthUser = Depends(get_current_user)):
    return [schemas.BatchAnalysisItem(label=target.label, analysis=ai.analyze(payload.resume_text, target.jd_text)) for target in payload.targets]


@router.post("/ai/tailor", response_model=schemas.TailorResult)
def tailor_resume(payload: schemas.TailorRequest, auth: schemas.AuthUser = Depends(get_current_user)):
    return ai.tailor(payload.resume_text, payload.jd_text, payload.confirmed_facts)


@router.post("/ai/cover-letter", response_model=schemas.GeneratedText)
def generate_cover_letter(payload: schemas.CoverLetterRequest, auth: schemas.AuthUser = Depends(get_current_user)):
    return schemas.GeneratedText(text=ai.cover_letter(payload.resume_text, payload.jd_text, payload.company, payload.role))


@router.delete("/account", status_code=204)
def delete_account(db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    user = db.get(models.User, auth.uid)
    if user is not None:
        db.delete(user)
        db.commit()
    return Response(status_code=204)
