from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class AuthUser(BaseModel):
    uid: str
    email: str


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    fields: dict[str, str] | None = None


class ErrorEnvelope(BaseModel):
    error: ErrorDetail


class JobCreate(BaseModel):
    title: str = Field(min_length=1, max_length=240)
    company: str = Field(default="", max_length=240)
    location: str = Field(default="", max_length=240)
    source_url: str = Field(default="", max_length=2048)
    description: str = Field(min_length=30, max_length=50_000)
    extraction_method: Literal["manual", "scrape"] = "manual"


class JobUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=240)
    company: str | None = Field(default=None, max_length=240)
    location: str | None = Field(default=None, max_length=240)
    archived: bool | None = None


class JobRead(ORMModel):
    id: int
    title: str
    company: str
    location: str
    source_url: str
    description: str
    extraction_method: str
    content_hash: str
    version: int
    archived: bool
    created_at: dt.datetime
    updated_at: dt.datetime


class ScrapeRequest(BaseModel):
    url: HttpUrl


class ScrapeResult(BaseModel):
    title: str
    description: str
    source_url: str
    cached: bool = False


class DocumentCreate(BaseModel):
    logical_id: str | None = Field(default=None, max_length=36)
    job_id: int | None = None
    kind: Literal["resume", "cover_letter"] = "resume"
    title: str = Field(min_length=1, max_length=240)
    original_text: str = Field(default="", max_length=50_000)
    content: str = Field(min_length=1, max_length=50_000)
    template: Literal["standard", "modern", "executive", "minimalist", "creative"] = "standard"
    approved: bool = False
    evidence_snapshot: list[int] = Field(default_factory=list, max_length=100)


class DocumentRead(ORMModel):
    id: int
    logical_id: str
    job_id: int | None
    kind: str
    title: str
    original_text: str
    content: str
    template: str
    version: int
    approved: bool
    content_hash: str
    evidence_snapshot: list[dict[str, Any]]
    created_at: dt.datetime


class ExportRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    template: Literal["standard", "modern", "executive", "minimalist", "creative"] = "standard"
    doc_type: Literal["resume", "cover_letter"] = "resume"
    format: Literal["pdf", "docx"] = "pdf"
    filename_hint: str = Field(default="document", max_length=120)


class Dimension(BaseModel):
    key: str
    label: str
    score: float = Field(ge=0, le=100)
    definition: str
    evidence: list[str] = Field(default_factory=list, max_length=10)
    confidence: float | None = Field(default=None, ge=0, le=1)


class GapAction(BaseModel):
    keyword: str
    importance: Literal["high", "medium", "low"]
    action: Literal["add", "clarify", "learn", "leave_unchanged"]
    jd_evidence: str
    resume_evidence: str | None = None
    suggestion: str
    confidence: float | None = Field(default=None, ge=0, le=1)


class AnalysisRequest(BaseModel):
    resume_text: str = Field(min_length=30, max_length=50_000)
    jd_text: str = Field(min_length=30, max_length=50_000)
    job_id: int | None = None
    document_id: int | None = None


class AnalysisResult(BaseModel):
    id: int | None = None
    score: float = Field(ge=0, le=100)
    verdict: str
    dimensions: list[Dimension]
    gap_plan: list[GapAction]
    methodology_version: str
    input_fingerprint: str
    methodology: dict[str, Any]


class AnalysisHistoryRead(ORMModel):
    id: int
    job_id: int | None
    document_id: int | None
    score: float
    dimensions: list[dict[str, Any]]
    gap_plan: list[dict[str, Any]]
    methodology_version: str
    input_fingerprint: str
    methodology: dict[str, Any]
    created_at: dt.datetime


class BatchTarget(BaseModel):
    label: str = Field(min_length=1, max_length=120)
    jd_text: str = Field(min_length=30, max_length=50_000)


class BatchAnalysisRequest(BaseModel):
    resume_text: str = Field(min_length=30, max_length=50_000)
    targets: list[BatchTarget] = Field(min_length=1, max_length=5)


class BatchAnalysisItem(BaseModel):
    label: str
    analysis: AnalysisResult


class TailorRequest(AnalysisRequest):
    confirmed_facts: list[str] = Field(default_factory=list, max_length=100)
    evidence_ids: list[int] = Field(default_factory=list, max_length=20)


class TailorResult(BaseModel):
    original: str
    tailored: str
    added_phrases: list[str]
    warnings: list[str]
    citations: list[dict[str, Any]] = Field(default_factory=list)


class CoverLetterRequest(AnalysisRequest):
    company: str = Field(default="", max_length=240)
    role: str = Field(default="", max_length=240)


class GeneratedText(BaseModel):
    text: str


ApplicationStage = Literal["saved", "applied", "interview", "offer", "closed"]
ApplicationOutcome = Literal["", "rejected", "withdrawn", "expired", "accepted"]


class ApplicationCreate(BaseModel):
    job_id: int | None = None
    company: str = Field(min_length=1, max_length=240)
    role: str = Field(min_length=1, max_length=240)
    source_url: str = Field(default="", max_length=2048)
    stage: ApplicationStage = "saved"
    deadline: dt.datetime | None = None
    notes: str = Field(default="", max_length=10_000)
    resume_document_id: int | None = None
    cover_letter_document_id: int | None = None
    outcome: ApplicationOutcome = ""


class ApplicationUpdate(BaseModel):
    company: str | None = Field(default=None, min_length=1, max_length=240)
    role: str | None = Field(default=None, min_length=1, max_length=240)
    source_url: str | None = Field(default=None, max_length=2048)
    stage: ApplicationStage | None = None
    deadline: dt.datetime | None = None
    notes: str | None = Field(default=None, max_length=10_000)
    resume_document_id: int | None = None
    cover_letter_document_id: int | None = None
    outcome: ApplicationOutcome | None = None


class ApplicationRead(ORMModel):
    id: int
    job_id: int | None
    company: str
    role: str
    source_url: str
    stage: str
    deadline: dt.datetime | None
    notes: str
    resume_document_id: int | None
    cover_letter_document_id: int | None
    created_at: dt.datetime
    updated_at: dt.datetime
    outcome: str


class InterviewCreate(BaseModel):
    job_id: int | None = None
    document_id: int | None = None
    resume_text: str = Field(min_length=30, max_length=50_000)
    jd_text: str = Field(min_length=30, max_length=50_000)
    interview_type: Literal["behavioral", "technical", "mixed"] = "mixed"


class InterviewAnswer(BaseModel):
    question_index: int = Field(ge=0, le=20)
    answer: str = Field(min_length=10, max_length=10_000)


class InterviewRead(ORMModel):
    id: int
    job_id: int | None
    document_id: int | None
    interview_type: str
    questions: list[dict[str, Any]]
    answers: list[dict[str, Any]]
    prep_brief: dict[str, Any]
    status: str
    created_at: dt.datetime
    updated_at: dt.datetime


class OutreachRequest(BaseModel):
    job_id: int | None = None
    resume_text: str = Field(min_length=30, max_length=50_000)
    jd_text: str = Field(min_length=30, max_length=50_000)
    recipient_name: str = Field(default="", max_length=240)
    recipient_role: str = Field(default="Recruiter", max_length=240)
    company: str = Field(default="", max_length=240)
    tone: Literal["professional", "warm", "concise"] = "professional"
    call_to_action: str = Field(default="a brief 10-minute conversation", max_length=240)
    contact_id: int | None = None


class OutreachRead(ORMModel):
    id: int
    job_id: int | None
    recipient_name: str
    recipient_role: str
    company: str
    tone: str
    variants: dict[str, Any]
    created_at: dt.datetime
    contact_id: int | None
    status: str
    revision: int
    updated_at: dt.datetime


class OutreachUpdate(BaseModel):
    revision: int = Field(ge=1)
    variants: dict[str, Any] | None = None
    status: Literal["draft", "sent", "replied", "closed"] | None = None


class SearchPreferences(BaseModel):
    desired_titles: list[str] = Field(default_factory=list, max_length=20)
    excluded_titles: list[str] = Field(default_factory=list, max_length=20)
    skills: list[str] = Field(default_factory=list, max_length=50)
    seniority: Literal["intern", "entry", "mid", "senior", "lead", "any"] = "any"
    locations: list[str] = Field(default_factory=list, max_length=20)
    work_modes: list[Literal["remote", "hybrid", "onsite"]] = Field(default_factory=lambda: ["remote"])
    minimum_salary: int | None = Field(default=None, ge=0, le=10_000_000)


class SearchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=240)
    resume_text: str = Field(min_length=30, max_length=50_000)
    preferences: SearchPreferences


class SearchRead(ORMModel):
    id: int
    name: str
    preferences: dict[str, Any]
    results: list[dict[str, Any]]
    created_at: dt.datetime
    updated_at: dt.datetime


EvidenceCategory = Literal["achievement", "skill", "project", "education", "certification", "story"]


class CareerEvidenceCreate(BaseModel):
    category: EvidenceCategory
    title: str = Field(min_length=1, max_length=240)
    statement: str = Field(min_length=10, max_length=10_000)
    source: str = Field(default="", max_length=500)
    verified: bool = False
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("tags")
    @classmethod
    def normalize_tags(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(item.strip().lower() for item in value if item.strip()))


class CareerEvidenceUpdate(BaseModel):
    category: EvidenceCategory | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    statement: str | None = Field(default=None, min_length=10, max_length=10_000)
    source: str | None = Field(default=None, max_length=500)
    verified: bool | None = None
    tags: list[str] | None = Field(default=None, max_length=20)


class CareerEvidenceRead(ORMModel):
    id: int
    category: str
    title: str
    statement: str
    source: str
    verified: bool
    tags: list[str]
    created_at: dt.datetime
    updated_at: dt.datetime


TaskType = Literal["follow_up", "interview", "deadline", "networking", "thank_you", "custom"]


class FollowUpTaskCreate(BaseModel):
    application_id: int
    task_type: TaskType = "follow_up"
    title: str = Field(min_length=1, max_length=240)
    due_at: dt.datetime
    notes: str = Field(default="", max_length=5_000)


class FollowUpTaskUpdate(BaseModel):
    task_type: TaskType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=240)
    due_at: dt.datetime | None = None
    notes: str | None = Field(default=None, max_length=5_000)
    completed: bool | None = None


class FollowUpTaskRead(ORMModel):
    id: int
    application_id: int
    task_type: str
    title: str
    due_at: dt.datetime
    notes: str
    completed_at: dt.datetime | None
    created_at: dt.datetime
    updated_at: dt.datetime


class PackageChecklistItem(BaseModel):
    key: str
    label: str
    ready: bool
    detail: str


class ApplicationPackageRead(BaseModel):
    application_id: int
    readiness_score: float = Field(ge=0, le=100)
    ready_count: int
    total_count: int
    checklist: list[PackageChecklistItem]
    resume: DocumentRead | None = None
    cover_letter: DocumentRead | None = None


class AnalyticsSummary(BaseModel):
    applications_by_stage: dict[str, int]
    average_match_score: float | None
    score_trend: list[dict[str, Any]]
    recurring_gaps: list[dict[str, Any]]
    interview_conversion_rate: float | None
    sample_size: int
