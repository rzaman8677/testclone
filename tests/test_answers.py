import asyncio

from app.answers import answer_question, deterministic_answer
from app.models import Profile


def test_common_profile_questions_use_verified_values():
    profile = Profile(
        first_name="Raiyan",
        university="Georgia Institute of Technology",
        graduation="May 2028",
        authorized_to_work_us=True,
        sponsorship_required=False,
        willing_to_relocate=True,
    )

    assert deterministic_answer("First name", profile).answer == "Raiyan"
    assert deterministic_answer("University", profile).answer == "Georgia Institute of Technology"
    assert deterministic_answer("Expected graduation date", profile).answer == "May 2028"
    assert deterministic_answer("Are you legally authorized to work in the United States?", profile).answer == "Yes"
    assert deterministic_answer("Will you require sponsorship in the future?", profile).answer == "No"


def test_sensitive_question_is_not_inferred_from_resume():
    profile = Profile(authorized_to_work_us=True)
    decision = asyncio.run(
        answer_question(
            "Please provide your citizenship status.",
            profile,
            "Software engineering resume text",
        )
    )
    assert decision.needs_review is True
    assert decision.answer is None


def test_verified_override_wins_for_recurring_question():
    profile = Profile(answer_overrides={"previously employed by Acme": False})
    decision = asyncio.run(
        answer_question(
            "Have you previously been employed by Acme Corporation?",
            profile,
            "Resume text",
        )
    )
    assert decision.answer == "No"
    assert decision.source == "profile_override"
