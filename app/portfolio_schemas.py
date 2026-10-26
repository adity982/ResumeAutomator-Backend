from __future__ import annotations

import datetime as dt
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator


class SourcePreview(BaseModel):
    url: str = Field(max_length=500)


class SourceImport(BaseModel):
    paths: list[str] = Field(min_length=1, max_length=16)
    relationship: Literal["personal", "team", "fork", "contribution"]
    contribution: str = Field(min_length=20, max_length=2000)


class EvidenceReview(BaseModel):
    status: Literal["approved", "observed", "rejected"]
    statement: str = Field(default="", max_length=1000)


class RecommendRequest(BaseModel):
    max_projects: int = Field(default=2, ge=1, le=3)
    mode: Literal["lexical", "dense", "hybrid"] = "hybrid"


class WorkspaceData(BaseModel):
    resume_text: str = Field(default="", max_length=50_000)
    jd_text: str = Field(default="", max_length=50_000)
    selected_job_id: int | None = None
    tailored_text: str = Field(default="", max_length=50_000)
    cover_letter: str = Field(default="", max_length=50_000)
    evidence_ids: list[int] = Field(default_factory=list, max_length=100)
    resume_logical_id: str | None = Field(default=None, max_length=36)
    cover_logical_id: str | None = Field(default=None, max_length=36)
    target_title: str = Field(default="Target role", max_length=240)
    target_company: str = Field(default="", max_length=240)
    target_url: str = Field(default="", max_length=2048)


class WorkspaceSave(BaseModel):
    revision: int = Field(ge=0)
    data: WorkspaceData


class ContactCreate(BaseModel):
    job_id: int | None = None
    name: str = Field(min_length=1, max_length=240)
    role: str = Field(default="", max_length=240)
    company: str = Field(default="", max_length=240)
    linkedin_url: str = Field(default="", max_length=2048)
    relationship: str = Field(default="", max_length=240)
    hiring_signal: str = Field(default="", max_length=2000)
    signal_url: str = Field(default="", max_length=2048)
    signal_observed_at: dt.datetime | None = None
    status: Literal["saved", "contacted", "replied", "closed"] = "saved"
    follow_up_at: dt.datetime | None = None
    stop_follow_up: bool = False

    @field_validator("linkedin_url", "signal_url")
    @classmethod
    def safe_link(cls, value, info):
        if not value:
            return value
        parsed = urlsplit(value)
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError("Use an HTTPS source link without credentials.")
        if info.field_name == "linkedin_url" and parsed.hostname.lower() not in {"linkedin.com", "www.linkedin.com"}:
            raise ValueError("Use a linkedin.com profile link.")
        return value


class ContactUpdate(BaseModel):
    status: Literal["saved", "contacted", "replied", "closed"] | None = None
    follow_up_at: dt.datetime | None = None
    stop_follow_up: bool | None = None


class FeedbackCreate(BaseModel):
    job_id: int | None = None
    task: Literal["import", "choose_projects", "prepare_application", "outreach"]
    rating: int = Field(ge=1, le=5)
    comment: str = Field(default="", max_length=2000)
    completed_without_help: bool
