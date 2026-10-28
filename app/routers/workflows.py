from __future__ import annotations

import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_user, owned, verify_optional_owner
from ..services import ai
from .core import _hash


router = APIRouter(prefix="/api/v1", tags=["workflows"])


def validate_document(db, document_id, job_id, kind, auth):
    if document_id is None:
        return
    document = owned(db, models.DocumentVersion, document_id, auth)
    if document.kind != kind or document.job_id != job_id:
        raise HTTPException(422, "Attach a document of the correct kind and target job.")
    for snapshot in document.evidence_snapshot:
        evidence = db.query(models.EvidenceChunk).filter_by(id=snapshot["evidence_id"], user_uid=auth.uid).first()
        source = db.query(models.PortfolioSource).filter_by(id=evidence.source_id, user_uid=auth.uid).first() if evidence else None
        if not evidence or not source or source.status != "ready" or evidence.review_status != "approved" or _hash(evidence.approved_statement + evidence.content_hash) != snapshot["hash"]:
            raise HTTPException(409, "This document uses changed or removed evidence. Review and save a new version.")


@router.post("/applications", response_model=schemas.ApplicationRead, status_code=201)
def create_application(payload: schemas.ApplicationCreate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.resume_document_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.cover_letter_document_id, auth)
    validate_document(db, payload.resume_document_id, payload.job_id, "resume", auth)
    validate_document(db, payload.cover_letter_document_id, payload.job_id, "cover_letter", auth)
    item = models.Application(user_uid=auth.uid, **payload.model_dump())
    db.add(item)
    db.flush()
    db.add(models.ApplicationEvent(application_id=item.id, user_uid=auth.uid, event_type="created", to_stage=item.stage))
    db.commit()
    db.refresh(item)
    return item


@router.get("/applications", response_model=list[schemas.ApplicationRead])
def list_applications(
    stage: str | None = Query(default=None, pattern="^(saved|applied|interview|offer|closed)$"),
    search: str = Query(default="", max_length=120),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    query = db.query(models.Application).filter(models.Application.user_uid == auth.uid)
    if stage:
        query = query.filter(models.Application.stage == stage)
    if search:
        pattern = f"%{search}%"
        query = query.filter((models.Application.company.ilike(pattern)) | (models.Application.role.ilike(pattern)))
    return query.order_by(models.Application.updated_at.desc()).offset(offset).limit(limit).all()


@router.patch("/applications/{application_id}", response_model=schemas.ApplicationRead)
def update_application(application_id: int, payload: schemas.ApplicationUpdate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.Application, application_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.resume_document_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.cover_letter_document_id, auth)
    previous_stage = item.stage
    changes = payload.model_dump(exclude_unset=True)
    if any(value is None and key not in {"deadline", "resume_document_id", "cover_letter_document_id"} for key, value in changes.items()):
        raise HTTPException(422, "Only optional dates and document links can be cleared.")
    validate_document(db, changes.get("resume_document_id", item.resume_document_id), item.job_id, "resume", auth)
    validate_document(db, changes.get("cover_letter_document_id", item.cover_letter_document_id), item.job_id, "cover_letter", auth)
    for key, value in changes.items():
        setattr(item, key, value)
    event_type = "stage_changed" if item.stage != previous_stage else "updated"
    db.add(models.ApplicationEvent(application_id=item.id, user_uid=auth.uid, event_type=event_type, from_stage=previous_stage, to_stage=item.stage, details={"fields": sorted(changes)}))
    db.commit()
    db.refresh(item)
    return item


@router.get("/applications/{application_id}/events")
def application_events(application_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    owned(db, models.Application, application_id, auth)
    return db.query(models.ApplicationEvent).filter(models.ApplicationEvent.application_id == application_id, models.ApplicationEvent.user_uid == auth.uid).order_by(models.ApplicationEvent.created_at.asc()).all()


@router.get("/applications/{application_id}/package", response_model=schemas.ApplicationPackageRead)
def application_package(
    application_id: int,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    application = owned(db, models.Application, application_id, auth)
    resume = owned(db, models.DocumentVersion, application.resume_document_id, auth) if application.resume_document_id else None
    cover_letter = owned(db, models.DocumentVersion, application.cover_letter_document_id, auth) if application.cover_letter_document_id else None
    validate_document(db, application.resume_document_id, application.job_id, "resume", auth)
    validate_document(db, application.cover_letter_document_id, application.job_id, "cover_letter", auth)
    checks = [
        schemas.PackageChecklistItem(key="job", label="Saved job context", ready=bool(application.job_id), detail="Links the application to a stable job snapshot."),
        schemas.PackageChecklistItem(key="source", label="Source link", ready=bool(application.source_url), detail="Keeps the original posting reachable."),
        schemas.PackageChecklistItem(key="resume", label="Approved resume", ready=bool(resume and resume.approved), detail="Attach an approved, job-specific resume version."),
        schemas.PackageChecklistItem(key="cover_letter", label="Approved cover letter", ready=bool(cover_letter and cover_letter.approved), detail="Attach an approved cover letter when the role benefits from one."),
        schemas.PackageChecklistItem(key="deadline", label="Application deadline", ready=bool(application.deadline), detail="Capture the deadline so the application can be prioritized."),
    ]
    ready_count = sum(item.ready for item in checks)
    return schemas.ApplicationPackageRead(
        application_id=application.id,
        readiness_score=round(100 * ready_count / len(checks), 1),
        ready_count=ready_count,
        total_count=len(checks),
        checklist=checks,
        resume=resume,
        cover_letter=cover_letter,
    )


@router.delete("/applications/{application_id}", status_code=204)
def delete_application(application_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.Application, application_id, auth)
    db.delete(item)
    db.commit()
    return Response(status_code=204)


@router.post("/interviews", response_model=schemas.InterviewRead, status_code=201)
def create_interview(payload: schemas.InterviewCreate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.document_id, auth)
    questions = ai.interview_questions(payload.resume_text, payload.jd_text, payload.interview_type)
    prep_brief = ai.interview_prep(payload.resume_text, payload.jd_text)
    item = models.InterviewSession(user_uid=auth.uid, job_id=payload.job_id, document_id=payload.document_id, jd_text=payload.jd_text, interview_type=payload.interview_type, questions=questions, answers=[], prep_brief=prep_brief)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.post("/interviews/{session_id}/answers", response_model=schemas.InterviewRead)
def answer_interview(session_id: int, payload: schemas.InterviewAnswer, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.InterviewSession, session_id, auth)
    if payload.question_index >= len(item.questions):
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="Question index is outside this session.")
    answers = list(item.answers or [])
    feedback = ai.score_answer(payload.answer, item.jd_text, item.questions[payload.question_index]["question"])
    answers = [entry for entry in answers if entry.get("question_index") != payload.question_index]
    answers.append({"question_index": payload.question_index, "answer": payload.answer, "feedback": feedback})
    item.answers = sorted(answers, key=lambda entry: entry["question_index"])
    if len(item.answers) == len(item.questions):
        item.status = "completed"
    db.commit()
    db.refresh(item)
    return item


@router.get("/interviews", response_model=list[schemas.InterviewRead])
def list_interviews(db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    return db.query(models.InterviewSession).filter(models.InterviewSession.user_uid == auth.uid).order_by(models.InterviewSession.updated_at.desc()).limit(50).all()


@router.post("/tasks", response_model=schemas.FollowUpTaskRead, status_code=201)
def create_task(
    payload: schemas.FollowUpTaskCreate,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    ensure_user(db, auth)
    owned(db, models.Application, payload.application_id, auth)
    item = models.FollowUpTask(user_uid=auth.uid, **payload.model_dump())
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/tasks", response_model=list[schemas.FollowUpTaskRead])
def list_tasks(
    include_completed: bool = True,
    application_id: int | None = None,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    query = db.query(models.FollowUpTask).filter(models.FollowUpTask.user_uid == auth.uid)
    if not include_completed:
        query = query.filter(models.FollowUpTask.completed_at.is_(None))
    if application_id is not None:
        owned(db, models.Application, application_id, auth)
        query = query.filter(models.FollowUpTask.application_id == application_id)
    return query.order_by(models.FollowUpTask.completed_at.asc(), models.FollowUpTask.due_at.asc()).limit(200).all()


@router.patch("/tasks/{task_id}", response_model=schemas.FollowUpTaskRead)
def update_task(
    task_id: int,
    payload: schemas.FollowUpTaskUpdate,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    item = owned(db, models.FollowUpTask, task_id, auth)
    changes = payload.model_dump(exclude_unset=True, exclude={"completed"})
    for key, value in changes.items():
        if value is None:
            raise HTTPException(422, f"{key} cannot be null.")
        setattr(item, key, value)
    if payload.completed is not None:
        item.completed_at = dt.datetime.now(dt.timezone.utc) if payload.completed else None
    db.commit()
    db.refresh(item)
    return item


@router.delete("/tasks/{task_id}", status_code=204)
def delete_task(
    task_id: int,
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    db.delete(owned(db, models.FollowUpTask, task_id, auth))
    db.commit()
    return Response(status_code=204)


@router.post("/outreach", response_model=schemas.OutreachRead, status_code=201)
def create_outreach(payload: schemas.OutreachRequest, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    verify_optional_owner(db, models.Contact, payload.contact_id, auth)
    contact = owned(db, models.Contact, payload.contact_id, auth) if payload.contact_id else None
    if contact and contact.job_id != payload.job_id:
        raise HTTPException(422, "Choose a contact linked to this target job.")
    variants = ai.outreach_variants(payload.resume_text, payload.jd_text, payload.recipient_name, payload.recipient_role, payload.company, payload.call_to_action, payload.tone)
    if contact and contact.hiring_signal and contact.signal_url and contact.signal_observed_at:
        variants["hiring_manager_note"] += f" I noticed this hiring update: {contact.hiring_signal}"
        variants["context_sources"] = [{"url": contact.signal_url, "observed_at": contact.signal_observed_at.isoformat()}]
    item = models.OutreachKit(user_uid=auth.uid, job_id=payload.job_id, contact_id=payload.contact_id, recipient_name=payload.recipient_name, recipient_role=payload.recipient_role, company=payload.company, tone=payload.tone, variants=variants)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.patch("/outreach/{kit_id}", response_model=schemas.OutreachRead)
def update_outreach(kit_id: int, payload: schemas.OutreachUpdate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    item = owned(db, models.OutreachKit, kit_id, auth)
    values = {"revision": payload.revision + 1}
    if payload.variants is not None:
        allowed = {"subjects", "recruiter_email", "hiring_manager_note", "referral_request", "linkedin_message", "follow_ups", "evidence", "context_sources"}
        if not set(payload.variants) <= allowed or len(str(payload.variants)) > 15_000:
            raise HTTPException(422, "Outreach draft is too large or contains unsupported fields.")
        values["variants"] = dict(item.variants, **payload.variants)
    if payload.status is not None:
        values["status"] = payload.status
    if not db.query(models.OutreachKit).filter_by(id=kit_id, user_uid=auth.uid, revision=payload.revision).update(values):
        raise HTTPException(409, "This draft changed in another tab. Reload before editing.")
    db.commit()
    db.refresh(item)
    return item


@router.get("/outreach", response_model=list[schemas.OutreachRead])
def list_outreach(db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    return db.query(models.OutreachKit).filter(models.OutreachKit.user_uid == auth.uid).order_by(models.OutreachKit.created_at.desc()).limit(50).all()


@router.delete("/outreach/{kit_id}", status_code=204)
def delete_outreach(kit_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    db.delete(owned(db, models.OutreachKit, kit_id, auth))
    db.commit()
    return Response(status_code=204)


@router.post("/searches", response_model=schemas.SearchRead, status_code=201)
def create_search(payload: schemas.SearchCreate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    results = ai.discover(payload.resume_text, payload.preferences)
    item = models.SavedSearch(user_uid=auth.uid, name=payload.name, preferences=payload.preferences.model_dump(), results=results)
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


@router.get("/searches", response_model=list[schemas.SearchRead])
def list_searches(db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    return db.query(models.SavedSearch).filter(models.SavedSearch.user_uid == auth.uid).order_by(models.SavedSearch.updated_at.desc()).limit(50).all()


@router.delete("/searches/{search_id}", status_code=204)
def delete_search(search_id: int, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    db.delete(owned(db, models.SavedSearch, search_id, auth))
    db.commit()
    return Response(status_code=204)


@router.get("/analytics/summary", response_model=schemas.AnalyticsSummary)
def analytics_summary(
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    company: str = Query(default="", max_length=120),
    role: str = Query(default="", max_length=120),
    db: Session = Depends(get_db),
    auth: schemas.AuthUser = Depends(get_current_user),
):
    application_query = db.query(models.Application).filter(models.Application.user_uid == auth.uid)
    analysis_query = db.query(models.AnalysisRecord).filter(models.AnalysisRecord.user_uid == auth.uid)
    if date_from:
        start = dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.timezone.utc)
        application_query = application_query.filter(models.Application.created_at >= start)
        analysis_query = analysis_query.filter(models.AnalysisRecord.created_at >= start)
    if date_to:
        end = dt.datetime.combine(date_to, dt.time.max, tzinfo=dt.timezone.utc)
        application_query = application_query.filter(models.Application.created_at <= end)
        analysis_query = analysis_query.filter(models.AnalysisRecord.created_at <= end)
    if company:
        application_query = application_query.filter(models.Application.company.ilike(f"%{company}%"))
        analysis_query = analysis_query.join(models.SavedJob).filter(models.SavedJob.user_uid == auth.uid, models.SavedJob.company.ilike(f"%{company}%"))
    if role:
        application_query = application_query.filter(models.Application.role.ilike(f"%{role}%"))
        if not company:
            analysis_query = analysis_query.join(models.SavedJob)
        analysis_query = analysis_query.filter(models.SavedJob.user_uid == auth.uid, models.SavedJob.title.ilike(f"%{role}%"))
    applications = application_query.all()
    analyses = analysis_query.order_by(models.AnalysisRecord.created_at.asc()).all()
    stages = Counter(item.stage for item in applications)
    gap_counter = Counter(gap.get("keyword") for item in analyses for gap in (item.gap_plan or []) if gap.get("keyword"))
    milestones = {}
    for event in db.query(models.ApplicationEvent).filter_by(user_uid=auth.uid).all():
        milestones.setdefault(event.application_id, set()).add(event.to_stage)
    interviewed = sum(bool((milestones.get(item.id, set()) | {item.stage}) & {"interview", "offer"}) for item in applications)
    applied = sum(bool((milestones.get(item.id, set()) | {item.stage}) & {"applied", "interview", "offer"}) for item in applications)
    average = round(sum(item.score for item in analyses) / len(analyses), 1) if analyses else None
    return schemas.AnalyticsSummary(
        applications_by_stage={stage: stages.get(stage, 0) for stage in ("saved", "applied", "interview", "offer", "closed")},
        average_match_score=average,
        score_trend=[{"date": item.created_at.date().isoformat(), "score": item.score, "analysis_id": item.id} for item in analyses[-30:]],
        recurring_gaps=[{"keyword": keyword, "count": count} for keyword, count in gap_counter.most_common(10)],
        interview_conversion_rate=round(100 * interviewed / applied, 1) if applied else None,
        sample_size=len(analyses),
    )
