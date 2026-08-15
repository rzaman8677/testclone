from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


class ATSKind(StrEnum):
    WORKDAY = "workday"
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    GENERIC = "generic"


@dataclass(frozen=True)
class ATSPolicy:
    kind: ATSKind
    persistent_session: bool
    supports_public_preflight: bool
    browser_questions_required: bool
    notes: str


POLICIES: dict[ATSKind, ATSPolicy] = {
    ATSKind.WORKDAY: ATSPolicy(
        kind=ATSKind.WORKDAY,
        persistent_session=True,
        supports_public_preflight=False,
        browser_questions_required=True,
        notes="Candidate Home may be required; application sections are tenant-configurable.",
    ),
    ATSKind.GREENHOUSE: ATSPolicy(
        kind=ATSKind.GREENHOUSE,
        persistent_session=False,
        supports_public_preflight=True,
        browser_questions_required=False,
        notes="Published job questions can often be inspected through the public Job Board API.",
    ),
    ATSKind.LEVER: ATSPolicy(
        kind=ATSKind.LEVER,
        persistent_session=False,
        supports_public_preflight=True,
        browser_questions_required=True,
        notes="Public postings API exposes jobs but not custom application questions.",
    ),
    ATSKind.ASHBY: ATSPolicy(
        kind=ATSKind.ASHBY,
        persistent_session=False,
        supports_public_preflight=True,
        browser_questions_required=True,
        notes="Public posting feed exposes jobs/apply URLs; application-form schema needs employer API credentials.",
    ),
    ATSKind.GENERIC: ATSPolicy(
        kind=ATSKind.GENERIC,
        persistent_session=True,
        supports_public_preflight=False,
        browser_questions_required=True,
        notes="Unknown layout; use conservative browser automation and manual handoff.",
    ),
}


TRACKING_QUERY_KEYS = {
    "gh_jid",
    "gh_src",
    "source",
    "sourceid",
    "lever-source",
    "lever-via",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
}


def detect_ats(url: str) -> ATSKind:
    parsed = urlparse(url)
    host = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.lower()

    if "myworkdayjobs.com" in host or "workdayjobs.com" in host:
        return ATSKind.WORKDAY
    if "greenhouse.io" in host or "greenhouse.com" in host:
        return ATSKind.GREENHOUSE
    if host in {"jobs.lever.co", "jobs.eu.lever.co"} or host.endswith(".lever.co"):
        return ATSKind.LEVER
    if host == "jobs.ashbyhq.com" or host.endswith(".ashbyhq.com"):
        return ATSKind.ASHBY
    if "/greenhouse/" in path:
        return ATSKind.GREENHOUSE
    return ATSKind.GENERIC


def policy_for_url(url: str) -> ATSPolicy:
    return POLICIES[detect_ats(url)]


def canonical_application_url(url: str) -> str:
    parsed = urlparse(url)
    cleaned_query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key.lower() not in TRACKING_QUERY_KEYS and not key.lower().startswith("utm_")
    ]
    path = re.sub(r"/+", "/", parsed.path).rstrip("/") or "/"
    return urlunparse(
        (
            parsed.scheme.lower() or "https",
            parsed.netloc.lower(),
            path,
            "",
            urlencode(cleaned_query, doseq=True),
            "",
        )
    )


def application_key(url: str) -> str:
    ats = detect_ats(url).value
    canonical = canonical_application_url(url)
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    return f"{ats}:{digest}"


def session_scope(url: str) -> str:
    parsed = urlparse(url)
    host = (parsed.hostname or "unknown").lower()
    segments = [segment for segment in parsed.path.split("/") if segment]

    # Workday tenants often share the same host pattern while the first path
    # component identifies a separate employer/career-site tenant.
    if detect_ats(url) == ATSKind.WORKDAY and segments:
        raw = f"{host}-{segments[0]}"
    else:
        raw = host

    safe = re.sub(r"[^a-z0-9._-]+", "-", raw).strip("-") or "unknown"
    return safe[:120]
