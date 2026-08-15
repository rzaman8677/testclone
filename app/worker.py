from __future__ import annotations

import asyncio
import os

from app.browser import fill_application
from app.config import load_profile, load_sources
from app.db import init_db, list_jobs, upsert_job
from app.scoring import score_job
from app.sources import fetch_source

POLL_INTERVAL_SECONDS = max(300, int(os.getenv("POLL_INTERVAL_SECONDS", "1800")))
AUTO_RUN_READY = os.getenv("AUTO_RUN_READY", "false").lower() == "true"
MAX_APPLICATIONS_PER_CYCLE = max(1, int(os.getenv("MAX_APPLICATIONS_PER_CYCLE", "5")))


async def discover_once() -> dict:
    profile = load_profile()
    sources = load_sources()
    results = await asyncio.gather(
        *(fetch_source(source) for source in sources), return_exceptions=True
    )
    discovered = 0
    failures: list[str] = []
    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            failures.append(f"{source.company}: {result}")
            continue
        for job in result:
            upsert_job(score_job(job, profile))
            discovered += 1
    return {"discovered": discovered, "failures": failures}


async def apply_ready_once() -> list[dict]:
    if not AUTO_RUN_READY:
        return []
    profile = load_profile()
    ready = [job for job in list_jobs(limit=1000) if job.get("status") == "READY"]
    results: list[dict] = []
    for job in ready[:MAX_APPLICATIONS_PER_CYCLE]:
        result = await fill_application(
            job["apply_url"],
            profile,
            job_context=job.get("description", ""),
        )
        results.append(
            {
                "company": job.get("company"),
                "title": job.get("title"),
                "submitted": result.submitted,
                "blocking_review": result.blocking_review,
            }
        )
    return results


async def run_forever() -> None:
    init_db()
    while True:
        summary = await discover_once()
        applications = await apply_ready_once()
        print({"discovery": summary, "applications": applications}, flush=True)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


if __name__ == "__main__":
    asyncio.run(run_forever())
