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
    assert deterministic_answer("What school do you attend?", profile).answer == "Georgia Institute of Technology"
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


def test_sensitive_question_can_use_explicit_decline_policy():
    profile = Profile(eeo_default="decline")
    decision = asyncio.run(
        answer_question(
            "What is your race or ethnicity?",
            profile,
            "Resume text",
            answer_choices=["Asian", "White", "Prefer not to answer"],
        )
    )
    assert decision.answer == "Prefer not to answer"
    assert decision.source == "profile.eeo_default"


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


def test_verified_yes_no_answer_uses_exact_ats_choice():
    profile = Profile(authorized_to_work_us=True)
    decision = asyncio.run(
        answer_question(
            "Are you legally authorized to work in the United States?",
            profile,
            "Resume text",
            answer_choices=["Yes", "No", "Prefer not to answer"],
        )
    )
    assert decision.answer == "Yes"
    assert decision.needs_review is False


def test_verified_consent_only_uses_explicit_profile_setting():
    unset = deterministic_answer("I agree to the terms and conditions", Profile())
    assert unset is None

    configured = deterministic_answer(
        "I agree to the terms and conditions",
        Profile(accept_terms_and_conditions=True),
    )
    assert configured.answer == "Yes"
    assert configured.source == "profile.accept_terms_and_conditions"


def test_generic_employment_dates_are_not_confused_with_internship_availability():
    profile = Profile(earliest_start_date="May 2027", latest_end_date="August 2027")
    assert deterministic_answer("Employment start date", profile) is None
    assert deterministic_answer("Employment end date", profile) is None
    assert deterministic_answer("What is your earliest available start date?", profile).answer == "May 2027"
    assert deterministic_answer("What is your internship end date?", profile).answer == "August 2027"


def test_verified_value_that_does_not_match_available_choice_stops_for_review():
    profile = Profile(answer_overrides={"preferred office": "Seattle"})
    decision = asyncio.run(
        answer_question(
            "Preferred office",
            profile,
            "Resume text",
            answer_choices=["Austin", "New York"],
        )
    )
    assert decision.answer is None
    assert decision.needs_review is True
