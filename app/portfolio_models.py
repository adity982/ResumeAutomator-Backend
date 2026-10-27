from __future__ import annotations

import datetime as dt

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Integer, JSON, String, Text, UniqueConstraint

from .database import Base


def utcnow():
    return dt.datetime.now(dt.timezone.utc)


class PortfolioSource(Base):
    __tablename__ = "portfolio_sources"
    __table_args__ = (UniqueConstraint("user_uid", "repository", "commit_sha", name="uq_source_snapshot"),)
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    repository = Column(String(240), nullable=False)
    commit_sha = Column(String(64), nullable=False)
    source_url = Column(String(2048), nullable=False)
    description = Column(Text, default="", nullable=False)
    is_fork = Column(Boolean, default=False, nullable=False)
    is_private = Column(Boolean, default=False, nullable=False)
    status = Column(String(32), default="preview", nullable=False)
    contribution = Column(Text, default="", nullable=False)
    relationship = Column(String(32), default="unconfirmed", nullable=False)
    files = Column(JSON, default=list, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class EvidenceChunk(Base):
    __tablename__ = "evidence_chunks"
    __table_args__ = (Index("ix_chunk_owner_source", "user_uid", "source_id"),)
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("portfolio_sources.id", ondelete="CASCADE"), nullable=False)
    path = Column(String(500), nullable=False)
    start_line = Column(Integer, nullable=False)
    end_line = Column(Integer, nullable=False)
    content = Column(Text, nullable=False)
    content_hash = Column(String(64), nullable=False)
    source_url = Column(String(2048), nullable=False)
    kind = Column(String(32), nullable=False)
    review_status = Column(String(32), default="observed", nullable=False)
    approved_statement = Column(Text, default="", nullable=False)
    embedding = Column(Vector(384).with_variant(JSON(), "sqlite"), nullable=True)
    embedding_version = Column(String(240), default="none", nullable=False)
    parser_version = Column(String(32), default="sections-v1", nullable=False)


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    source_id = Column(Integer, ForeignKey("portfolio_sources.id", ondelete="CASCADE"), nullable=False)
    status = Column(String(32), default="queued", nullable=False)
    paths = Column(JSON, default=list, nullable=False)
    attempts = Column(Integer, default=0, nullable=False)
    error = Column(String(500), default="", nullable=False)
    lease_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class RetrievalRun(Base):
    __tablename__ = "retrieval_runs"
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="CASCADE"), nullable=False)
    result = Column(JSON, default=dict, nullable=False)
    input_fingerprint = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class WorkspaceDraft(Base):
    __tablename__ = "workspace_drafts"
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), primary_key=True)
    revision = Column(Integer, default=1, nullable=False)
    data = Column(JSON, default=dict, nullable=False)
    updated_at = Column(DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False)


class Contact(Base):
    __tablename__ = "contacts"
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(240), nullable=False)
    role = Column(String(240), default="", nullable=False)
    company = Column(String(240), default="", nullable=False)
    linkedin_url = Column(String(2048), default="", nullable=False)
    relationship = Column(String(240), default="", nullable=False)
    hiring_signal = Column(Text, default="", nullable=False)
    signal_url = Column(String(2048), default="", nullable=False)
    signal_observed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(32), default="saved", nullable=False)
    follow_up_at = Column(DateTime(timezone=True), nullable=True)
    stop_follow_up = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class PilotFeedback(Base):
    __tablename__ = "pilot_feedback"
    id = Column(Integer, primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, index=True)
    job_id = Column(Integer, ForeignKey("saved_jobs.id", ondelete="SET NULL"), nullable=True)
    task = Column(String(120), nullable=False)
    rating = Column(Integer, nullable=False)
    comment = Column(Text, default="", nullable=False)
    completed_without_help = Column(Boolean, nullable=False)
    created_at = Column(DateTime(timezone=True), default=utcnow, nullable=False)


class UsageWindow(Base):
    __tablename__ = "usage_windows"
    key = Column(String(64), primary_key=True)
    count = Column(Integer, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)


class GitHubConnection(Base):
    __tablename__ = "github_connections"
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), primary_key=True)
    login = Column(String(100), nullable=False)
    token_ciphertext = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)


class GitHubAuthorization(Base):
    __tablename__ = "github_authorizations"
    state_hash = Column(String(64), primary_key=True)
    user_uid = Column(String(128), ForeignKey("users.uid", ondelete="CASCADE"), nullable=False, unique=True)
    verifier_ciphertext = Column(Text, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
