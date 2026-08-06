from __future__ import annotations

from app.config import MIN_AUTO_APPLY_SCORE, MIN_REVIEW_SCORE
from app.models import Job, JobStatus, Profile


def score_job(job: Job, profile: Profile) -> Job:
    text = f"{job.title} {job.description} {job.location}".lower()
    title = job.title.lower()
    score = 0.0
    reasons: list[str] = []

    if "intern" in title or "internship" in text:
        score += 35
        reasons.append("internship role")
    else:
        score -= 30

    if "2027" in text:
        score += 15
        reasons.append("mentions 2027")

    title_matches = [x for x in profile.target_titles if x.lower() in title]
    if title_matches:
        score += min(25, 12 + 4 * len(title_matches))
        reasons.append(f"target title match: {', '.join(title_matches[:3])}")

    keyword_matches = [x for x in profile.target_keywords if x.lower() in text]
    if keyword_matches:
        score += min(25, 4 * len(keyword_matches))
        reasons.append(f"skill match: {', '.join(keyword_matches[:5])}")

    excluded = [x for x in profile.excluded_keywords if x.lower() in text]
    if excluded:
        score -= 60
        reasons.append(f"excluded: {', '.join(excluded[:3])}")

    job.score = max(0, min(100, round(score, 1)))
    job.reasons = reasons

    if job.score >= MIN_AUTO_APPLY_SCORE:
        job.status = JobStatus.READY
    elif job.score >= MIN_REVIEW_SCORE:
        job.status = JobStatus.QUALIFIED
    else:
        job.status = JobStatus.REJECTED
    return job
