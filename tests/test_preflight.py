from app.preflight import (
    _ashby_board,
    _flatten_greenhouse_questions,
    _greenhouse_identity,
    _lever_identity,
)


def test_greenhouse_identity_from_hosted_job_url():
    assert _greenhouse_identity(
        "https://job-boards.greenhouse.io/acme/jobs/123456?gh_src=abc"
    ) == ("acme", "123456")


def test_lever_identity_from_apply_url():
    assert _lever_identity("https://jobs.lever.co/acme/posting-id/apply") == (
        "acme",
        "posting-id",
    )


def test_ashby_board_from_apply_url():
    assert _ashby_board("https://jobs.ashbyhq.com/acme/job-id/application") == "acme"


def test_greenhouse_question_buckets_keep_required_distinction():
    payload = {
        "questions": [
            {"label": "Portfolio", "required": False},
            {"label": "Work authorization", "required": True},
        ],
        "compliance": [{"label": "Compliance question", "required": True}],
        "demographic_questions": {
            "questions": [{"label": "Voluntary demographic", "required": False}]
        },
    }
    required, optional = _flatten_greenhouse_questions(payload)
    assert "Work authorization" in required
    assert "Compliance question" in required
    assert "Portfolio" in optional
    assert "Voluntary demographic" in optional
