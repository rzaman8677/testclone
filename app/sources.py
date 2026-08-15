from __future__ import annotations

from datetime import datetime
import html
import re

import httpx

from app.models import Job, SourceConfig


def _strip_html(value: str) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


async def fetch_greenhouse(source: SourceConfig) -> list[Job]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{source.token}/jobs?content=true"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        location = (item.get("location") or {}).get("name", "")
        jobs.append(
            Job(
                source="greenhouse",
                company=source.company,
                title=item.get("title", ""),
                location=location,
                description=_strip_html(item.get("content", "")),
                job_url=item.get("absolute_url", ""),
                apply_url=item.get("absolute_url", ""),
                ats="greenhouse",
                external_id=str(item.get("id")),
                posted_at=None,
            )
        )
    return jobs


async def fetch_ashby(source: SourceConfig) -> list[Job]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{source.token}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url)
        response.raise_for_status()
        payload = response.json()

    jobs: list[Job] = []
    for item in payload.get("jobs", []):
        published = item.get("publishedAt")
        posted_at = None
        if published:
            try:
                posted_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
            except ValueError:
                posted_at = None
        jobs.append(
            Job(
                source="ashby",
                company=source.company,
                title=item.get("title", ""),
                location=item.get("location", "") or "",
                description=_strip_html(item.get("descriptionHtml") or item.get("descriptionPlain") or ""),
                job_url=item.get("jobUrl", ""),
                apply_url=item.get("applyUrl") or item.get("jobUrl", ""),
                ats="ashby",
                external_id=str(item.get("id") or item.get("jobUrl")),
                posted_at=posted_at,
            )
        )
    return jobs


async def fetch_lever(source: SourceConfig, *, eu: bool = False) -> list[Job]:
    api_host = "api.eu.lever.co" if eu else "api.lever.co"
    url = f"https://{api_host}/v0/postings/{source.token}"
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.get(url, params={"mode": "json"})
        response.raise_for_status()
        payload = response.json()

    jobs: list[Job] = []
    for item in payload if isinstance(payload, list) else []:
        categories = item.get("categories") or {}
        jobs.append(
            Job(
                source="lever",
                company=source.company,
                title=item.get("text", ""),
                location=categories.get("location", "") or "",
                description=_strip_html(
                    item.get("descriptionPlain")
                    or item.get("description")
                    or item.get("openingPlain")
                    or ""
                ),
                job_url=item.get("hostedUrl", ""),
                apply_url=item.get("applyUrl") or item.get("hostedUrl", ""),
                ats="lever",
                external_id=str(item.get("id") or item.get("hostedUrl")),
                posted_at=None,
            )
        )
    return jobs


async def fetch_source(source: SourceConfig) -> list[Job]:
    kind = source.type.lower().replace("-", "_")
    if kind == "greenhouse":
        return await fetch_greenhouse(source)
    if kind == "ashby":
        return await fetch_ashby(source)
    if kind == "lever":
        return await fetch_lever(source, eu=False)
    if kind in {"lever_eu", "levereu"}:
        return await fetch_lever(source, eu=True)
    raise ValueError(f"Unsupported source type: {source.type}")
