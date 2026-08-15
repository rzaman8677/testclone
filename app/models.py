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


class WorkExperience(BaseModel):
    company: str
    title: str
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    current: bool = False
    description: str = ""


class EducationEntry(BaseModel):
    school: str
    degree: str = ""
    field_of_study: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    gpa: str = ""


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
    school_year: str = ""
    current_student: bool | None = None
    returning_to_school_after_internship: bool | None = None

    linkedin_url: str = ""
    github_url: str = ""
    portfolio_url: str = ""

    over_18: bool | None = None
    authorized_to_work_us: bool | None = None
    sponsorship_required: bool | None = None
    willing_to_relocate: bool | None = None
    available_full_internship: bool | None = None

    earliest_start_date: str = ""
    latest_end_date: str = ""
    preferred_locations: list[str] = Field(default_factory=list)

    # These structured histories are optional but strongly recommended for
    # Workday. Workday can parse a resume into repeated Experience/Education
    # sections; verified structured entries let the agent repair empty or
    # obviously incomplete parsed rows without inventing information.
    work_experience: list[WorkExperience] = Field(default_factory=list)
    education_history: list[EducationEntry] = Field(default_factory=list)

    how_heard_about_us: str = ""
    previous_employee: bool | None = None

    # Legal/privacy checkboxes are only automated when the user has explicitly
    # configured a verified preference. Leaving them null forces review.
    accept_terms_and_conditions: bool | None = None
    privacy_consent: bool | None = None
    data_processing_consent: bool | None = None
    marketing_consent: bool | None = None

    # Exact or partial question text -> verified answer. Useful for recurring
    # questions whose answers are not naturally represented by a profile field.
    answer_overrides: dict[str, str | bool] = Field(default_factory=dict)

    # "review" is safest. Set to "decline" only if you want the agent to pick
    # a visible Prefer not to answer / Decline to self-identify option.
    eeo_default: str = "review"

    target_titles: list[str] = Field(default_factory=list)
    target_keywords: list[str] = Field(default_factory=list)
    excluded_keywords: list[str] = Field(default_factory=list)
