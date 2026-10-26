from __future__ import annotations

import datetime as dt

from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from .database import Base


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    __tablename__ = "users"

    uid = Column(String(128), primary_key=True)
    email = Column(String(320), unique=True, index=True, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class SavedJob(Base):
    __tablename__ = "saved_jobs"
    __table_args__ = (
        UniqueConstraint("user_uid", "content_hash", "version", name="uq_job_snapshot"),
        Index("ix_saved_jobs_user_updated", "user_uid", "updated_at"),
    )

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String(240), nullable=False)
    company = Column(String(240), default="", nullable=False)
    location = Column(String(240), default="", nullable=False)
    source_url = Column(String(2048), default="", nullable=False)
    normalized_url = Column(String(2048), default="", nullable=False, index=True)
    description = Column(Text, nullable=False)
    extraction_method = Column(String(32), default="manual", nullable=False)
    content_hash = Column(String(64), nullable=False, index=True)
    version = Column(Integer, default=1, nullable=False)
    archived = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class DocumentVersion(Base):
    __tablename__ = "document_versions"
    __table_args__ = (
        UniqueConstraint("user_uid", "logical_id", "version", name="uq_document_version"),
        Index("ix_documents_user_created", "user_uid", "created_at"),
    )

    id = Column(Integer, primary_key=True)
    logical_id = Column(String(36), nullable=False, index=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    kind = Column(String(32), nullable=False)
    title = Column(String(240), nullable=False)
    original_text = Column(Text, default="", nullable=False)
    content = Column(Text, nullable=False)
    template = Column(String(32), default="standard", nullable=False)
    version = Column(Integer, default=1, nullable=False)
    approved = Column(Boolean, default=False, nullable=False)
    content_hash = Column(String(64), default="", nullable=False)
    evidence_snapshot = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class Application(Base):
    __tablename__ = "applications"
    __table_args__ = (Index("ix_applications_user_stage", "user_uid", "stage"),)

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    company = Column(String(240), nullable=False)
    role = Column(String(240), nullable=False)
    source_url = Column(String(2048), default="", nullable=False)
    stage = Column(String(32), default="saved", nullable=False)
    deadline = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, default="", nullable=False)
    outcome = Column(String(32), default="", nullable=False)
    resume_document_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    cover_letter_document_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class ApplicationEvent(Base):
    __tablename__ = "application_events"

    id = Column(Integer, primary_key=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False, index=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    event_type = Column(String(64), nullable=False)
    from_stage = Column(String(32), default="", nullable=False)
    to_stage = Column(String(32), default="", nullable=False)
    details = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class AnalysisRecord(Base):
    __tablename__ = "analysis_records"
    __table_args__ = (Index("ix_analysis_user_created", "user_uid", "created_at"),)

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    document_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    score = Column(Float, nullable=False)
    dimensions = Column(JSON, default=list, nullable=False)
    gap_plan = Column(JSON, default=list, nullable=False)
    methodology_version = Column(String(32), default="heuristic-v1", nullable=False)
    input_fingerprint = Column(String(64), default="", nullable=False, index=True)
    methodology = Column(JSON, default=dict, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class InterviewSession(Base):
    __tablename__ = "interview_sessions"

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    document_id = Column(Integer, ForeignKey("document_versions.id", ondelete="SET NULL"), nullable=True)
    interview_type = Column(String(32), default="mixed", nullable=False)
    questions = Column(JSON, default=list, nullable=False)
    answers = Column(JSON, default=list, nullable=False)
    prep_brief = Column(JSON, default=dict, nullable=False)
    status = Column(String(32), default="active", nullable=False)
    jd_text = Column(Text, default="", nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class OutreachKit(Base):
    __tablename__ = "outreach_kits"

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    recipient_name = Column(String(240), default="", nullable=False)
    recipient_role = Column(String(240), default="Recruiter", nullable=False)
    company = Column(String(240), default="", nullable=False)
    tone = Column(String(32), default="professional", nullable=False)
    variants = Column(JSON, default=dict, nullable=False)
    contact_id = Column(Integer, ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(32), default="draft", nullable=False)
    revision = Column(Integer, default=1, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class SavedSearch(Base):
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(240), nullable=False)
    preferences = Column(JSON, default=dict, nullable=False)
    results = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class CareerEvidence(Base):
    __tablename__ = "career_evidence"
    __table_args__ = (Index("ix_evidence_user_updated", "user_uid", "updated_at"),)

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    category = Column(String(32), nullable=False)
    title = Column(String(240), nullable=False)
    statement = Column(Text, nullable=False)
    source = Column(String(500), default="", nullable=False)
    verified = Column(Boolean, default=False, nullable=False)
    tags = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class FollowUpTask(Base):
    __tablename__ = "follow_up_tasks"
    __table_args__ = (
        Index("ix_follow_up_user_due", "user_uid", "due_at"),
        Index("ix_follow_up_application", "application_id"),
    )

    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    application_id = Column(Integer, ForeignKey("applications.id", ondelete="CASCADE"), nullable=False)
    task_type = Column(String(32), default="follow_up", nullable=False)
    title = Column(String(240), nullable=False)
    due_at = Column(DateTime(timezone=True), nullable=False)
    notes = Column(Text, default="", nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


# Register separately maintained portfolio tables with the same migration metadata.
from .portfolio_models import Contact, EvidenceChunk, IngestionJob, PortfolioSource, RetrievalRun, PilotFeedback, WorkspaceDraft  # noqa: E402,F401
