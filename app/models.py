from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pydantic import BaseModel, Field


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
    middle_name: str = ""
    last_name: str = ""
    preferred_name: str = ""
    email: str = ""
    phone: str = ""

    address_line1: str = ""
    address_line2: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "United States"

    university: str = ""
    degree: str = ""
    major: str = "Computer Science"
    graduation: str = ""
    gpa: str = ""
    current_student: bool | None = None

    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""

    over_18: bool | None = None
    authorized_to_work_us: bool | None = None
    sponsorship_required: bool | None = None
    willing_to_relocate: bool | None = None

    earliest_start_date: str = ""
    latest_end_date: str = ""
    preferred_locations: list[str] = Field(default_factory=list)

    # Exact or partial question text -> verified answer. Useful for recurring
    # questions whose answers are not naturally represented by a profile field.
    answer_overrides: dict[str, str | bool] = Field(default_factory=dict)

    # Keep voluntary demographic/self-identification questions out of the
    # resume-answering path. "review" is the safest default.
    eeo_default: str = "review"

    target_titles: list[str] = Field(default_factory=list)
    target_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
