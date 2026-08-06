from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field, HttpUrl


class JobStatus(StrEnum):
    NEW = "NEW"
    REJECTED = "REJECTED"
    QUALIFIED = "QUALIFIED"
    READY = "READY"
    APPLYING = "APPLYING"
    APPLIED = "APPLIED"
    NEEDS_REVIEW = "NEEDS_REVIEW"
    FAILED = "FAILED"


class Job(BaseModel):
    source: str
    company: str
    title: str
    location: str = ""
    description: str = ""
    job_url: str
    apply_url: str
    ats: str
    external_id: str
    posted_at: datetime | None = None
    score: float = 0
    status: JobStatus = JobStatus.NEW
    reasons: list[str] = Field(default_factory=list)


class SourceConfig(BaseModel):
    type: str
    company: str
    token: str
    enabled: bool = True


class Profile(BaseModel):
    first_name: str = ""
    last_name: str = ""
    email: str = ""
    phone: str = ""
    university: str = ""
    degree: str = ""
    major: str = "Computer Science"
    graduation: str = ""
    gpa: str = ""
    authorized_to_work_us: bool | None = None
    sponsorship_required: bool | None = None
    willing_to_relocate: bool | None = None
    target_titles: list[str] = Field(default_factory=list)
    target_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
