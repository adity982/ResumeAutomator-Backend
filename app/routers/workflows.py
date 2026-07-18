from __future__ import annotations

import datetime as dt
from collections import Counter

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db
from ..deps import ensure_user, owned, verify_optional_owner
from ..services import ai


router = APIRouter(prefix="/api/v1", tags=["workflows"])


@router.post("/applications", response_model=schemas.ApplicationRead, status_code=201)
def create_application(payload: schemas.ApplicationCreate, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.resume_document_id, auth)
    verify_optional_owner(db, models.DocumentVersion, payload.cover_letter_document_id, auth)
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
    item = models.InterviewSession(user_uid=auth.uid, job_id=payload.job_id, document_id=payload.document_id, interview_type=payload.interview_type, questions=questions, answers=[])
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
    feedback = ai.score_answer(payload.answer)
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


@router.post("/outreach", response_model=schemas.OutreachRead, status_code=201)
def create_outreach(payload: schemas.OutreachRequest, db: Session = Depends(get_db), auth: schemas.AuthUser = Depends(get_current_user)):
    ensure_user(db, auth)
    verify_optional_owner(db, models.SavedJob, payload.job_id, auth)
    variants = ai.outreach_variants(payload.resume_text, payload.jd_text, payload.recipient_name, payload.recipient_role, payload.company, payload.call_to_action)
    item = models.OutreachKit(user_uid=auth.uid, job_id=payload.job_id, recipient_name=payload.recipient_name, recipient_role=payload.recipient_role, company=payload.company, tone=payload.tone, variants=variants)
    db.add(item)
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
    if role:
        application_query = application_query.filter(models.Application.role.ilike(f"%{role}%"))
    applications = application_query.all()
    analyses = analysis_query.order_by(models.AnalysisRecord.created_at.asc()).all()
    stages = Counter(item.stage for item in applications)
    gap_counter = Counter(gap.get("keyword") for item in analyses for gap in (item.gap_plan or []) if gap.get("keyword"))
    interviewed = sum(item.stage in {"interview", "offer", "closed"} for item in applications)
    applied = sum(item.stage != "saved" for item in applications)
    average = round(sum(item.score for item in analyses) / len(analyses), 1) if analyses else None
    return schemas.AnalyticsSummary(
        applications_by_stage={stage: stages.get(stage, 0) for stage in ("saved", "applied", "interview", "offer", "closed")},
        average_match_score=average,
        score_trend=[{"date": item.created_at.date().isoformat(), "score": item.score, "analysis_id": item.id} for item in analyses[-30:]],
        recurring_gaps=[{"keyword": keyword, "count": count} for keyword, count in gap_counter.most_common(10)],
        interview_conversion_rate=round(100 * interviewed / applied, 1) if applied else None,
        sample_size=len(analyses),
    )
