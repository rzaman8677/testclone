from app.navigation import action_priority, classify_action_label, normalize_label


def test_classifies_common_multi_page_actions():
    assert classify_action_label("Save and Continue") == "next"
    assert classify_action_label("Next") == "next"
    assert classify_action_label("Review Application") == "next"
    assert classify_action_label("Start Application") == "start"
    assert classify_action_label("Submit Application") == "submit"


def test_does_not_treat_back_or_cancel_as_forward_navigation():
    assert classify_action_label("Back") is None
    assert classify_action_label("Previous") is None
    assert classify_action_label("Cancel Application") is None


def test_prefers_forward_navigation_before_submit_when_both_are_present():
    assert action_priority("next", "Continue") < action_priority("submit", "Submit Application")


def test_normalizes_button_text():
    assert normalize_label("  Save   and\nContinue ") == "save and continue"
