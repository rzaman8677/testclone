from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import parse_qs, urlparse

import httpx

from app.ats import ATSKind, canonical_application_url, detect_ats


@dataclass
class PreflightResult:
    ats: str
    live: bool | None = None
    external_id: str = ""
    required_questions: list[str] = field(default_factory=list)
    optional_questions: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    error: str = ""


def _greenhouse_identity(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    query = parse_qs(parsed.query)

    # Current hosted forms commonly use /{board}/jobs/{job_id}.
    if len(parts) >= 3 and parts[1].lower() == "jobs" and parts[2].isdigit():
        return parts[0], parts[2]

    # Older/embedded links may carry gh_jid in the query string.
    jid = (query.get("gh_jid") or [""])[0]
    if jid.isdigit() and parts:
        return parts[0], jid
    return None


def _lever_identity(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() not in {"jobs.lever.co", "jobs.eu.lever.co"}:
        return None
    parts = [part for part in parsed.path.split("/") if part]
    if len(parts) >= 2:
        return parts[0], parts[1]
    return None


def _ashby_board(url: str) -> str | None:
    parsed = urlparse(url)
    if (parsed.hostname or "").lower() != "jobs.ashbyhq.com":
        return None
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0] if parts else None


def _flatten_greenhouse_questions(payload: dict) -> tuple[list[str], list[str]]:
    required: list[str] = []
    optional: list[str] = []
    for bucket in ("questions", "location_questions", "compliance"):
        for question in payload.get(bucket) or []:
            label = str(question.get("label") or question.get("title") or "").strip()
            if not label:
                continue
            (required if question.get("required") else optional).append(label)

    demographics = payload.get("demographic_questions") or {}
    for question in demographics.get("questions") or []:
        label = str(question.get("label") or question.get("title") or "").strip()
        if not label:
            continue
        (required if question.get("required") else optional).append(label)
    return list(dict.fromkeys(required)), list(dict.fromkeys(optional))


async def _greenhouse_preflight(url: str, client: httpx.AsyncClient) -> PreflightResult:
    result = PreflightResult(ats=ATSKind.GREENHOUSE.value)
    identity = _greenhouse_identity(url)
    if not identity:
        result.notes.append("Could not derive Greenhouse board token/job id from this URL; browser validation will be used.")
        return result

    board, job_id = identity
    result.external_id = job_id
    endpoint = f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs/{job_id}"
    response = await client.get(endpoint, params={"questions": "true"})
    if response.status_code == 404:
        result.live = False
        result.notes.append("Greenhouse job was not found on the public board API.")
        return result
    response.raise_for_status()
    payload = response.json()
    result.live = True
    result.required_questions, result.optional_questions = _flatten_greenhouse_questions(payload)
    if payload.get("data_compliance"):
        result.notes.append("Greenhouse data-compliance/consent fields are configured for this posting.")
    return result


async def _lever_preflight(url: str, client: httpx.AsyncClient) -> PreflightResult:
    result = PreflightResult(ats=ATSKind.LEVER.value)
    identity = _lever_identity(url)
    if not identity:
        result.notes.append("Could not derive Lever site/posting id; browser validation will be used.")
        return result
    site, posting_id = identity
    result.external_id = posting_id
    api_host = "api.eu.lever.co" if (urlparse(url).hostname or "").lower() == "jobs.eu.lever.co" else "api.lever.co"
    response = await client.get(f"https://{api_host}/v0/postings/{site}/{posting_id}", params={"mode": "json"})
    if response.status_code == 404:
        result.live = False
        result.notes.append("Lever posting is no longer available from the public postings API.")
        return result
    response.raise_for_status()
    result.live = True
    result.notes.append("Lever public postings API does not expose custom application questions; browser inspection remains authoritative.")
    return result


async def _ashby_preflight(url: str, client: httpx.AsyncClient) -> PreflightResult:
    result = PreflightResult(ats=ATSKind.ASHBY.value)
    board = _ashby_board(url)
    if not board:
        result.notes.append("Could not derive Ashby job-board name; browser validation will be used.")
        return result

    response = await client.get(f"https://api.ashbyhq.com/posting-api/job-board/{board}")
    if response.status_code == 404:
        result.live = False
        result.notes.append("Ashby job board is no longer available.")
        return result
    response.raise_for_status()
    payload = response.json()
    canonical = canonical_application_url(url)
    matched = None
    for job in payload.get("jobs") or []:
        candidates = [job.get("applyUrl"), job.get("jobUrl")]
        for candidate in candidates:
            if not candidate:
                continue
            candidate_canonical = canonical_application_url(str(candidate))
            if candidate_canonical == canonical or candidate_canonical.rstrip("/") in canonical.rstrip("/") or canonical.rstrip("/") in candidate_canonical.rstrip("/"):
                matched = job
                break
        if matched:
            break

    if matched:
        result.live = True
        result.external_id = str(matched.get("id") or matched.get("jobUrl") or "")
    else:
        # Unlisted Ashby postings can still be reachable by direct URL, so a
        # miss in the public listed feed is not proof that the job is closed.
        result.live = None
        result.notes.append("Posting was not found in Ashby's public listed feed; direct-link browser validation is required.")
    result.notes.append("Ashby's public posting feed does not expose applicant form fields without employer credentials.")
    return result


async def preflight_application(url: str) -> PreflightResult:
    ats = detect_ats(url)
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        try:
            if ats == ATSKind.GREENHOUSE:
                return await _greenhouse_preflight(url, client)
            if ats == ATSKind.LEVER:
                return await _lever_preflight(url, client)
            if ats == ATSKind.ASHBY:
                return await _ashby_preflight(url, client)
        except (httpx.HTTPError, ValueError) as exc:
            return PreflightResult(ats=ats.value, error=f"Preflight unavailable: {exc}")
    return PreflightResult(ats=ats.value, notes=["No safe public preflight API is available; browser validation will be used."])
