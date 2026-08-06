from app.models import Job, JobStatus, Profile
from app.scoring import score_job


def make_job(title: str, description: str = "") -> Job:
    return Job(
        source="test",
        company="Example",
        title=title,
        description=description,
        job_url="https://example.com/job",
        apply_url="https://example.com/apply",
        ats="test",
        external_id="1",
    )


def test_relevant_2027_internship_scores_high():
    profile = Profile(
        target_titles=["software engineer"],
        target_keywords=["python", "distributed systems", "aws"],
        excluded_keywords=["senior"],
    )
    job = make_job(
        "Software Engineer Intern 2027",
        "Build distributed systems in Python on AWS.",
    )
    scored = score_job(job, profile)
    assert scored.score >= 80
    assert scored.status == JobStatus.READY


def test_senior_role_is_rejected():
    profile = Profile(
        target_titles=["software engineer"],
        target_keywords=["python"],
        excluded_keywords=["senior"],
    )
    job = make_job("Senior Software Engineer", "Python backend systems")
    scored = score_job(job, profile)
    assert scored.status == JobStatus.REJECTED
