from app.ats import ATSKind, application_key, canonical_application_url, detect_ats, session_scope


def test_detects_main_ats_hosts():
    assert detect_ats("https://acme.wd5.myworkdayjobs.com/en-US/jobs/job/123") == ATSKind.WORKDAY
    assert detect_ats("https://job-boards.greenhouse.io/acme/jobs/123456") == ATSKind.GREENHOUSE
    assert detect_ats("https://jobs.lever.co/acme/abc-def/apply") == ATSKind.LEVER
    assert detect_ats("https://jobs.ashbyhq.com/acme/abc-def/application") == ATSKind.ASHBY


def test_tracking_parameters_do_not_change_application_identity():
    base = "https://job-boards.greenhouse.io/acme/jobs/123456"
    tracked = base + "?gh_src=abc&utm_source=linkedin"
    assert canonical_application_url(base) == canonical_application_url(tracked)
    assert application_key(base) == application_key(tracked)


def test_workday_session_scope_is_tenant_scoped():
    one = session_scope("https://acme.wd5.myworkdayjobs.com/en-US/jobs/job/123")
    two = session_scope("https://other.wd5.myworkdayjobs.com/en-US/jobs/job/456")
    assert one != two
