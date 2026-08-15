# 2027 Internship Application Agent

Personal internship discovery and application-assistance agent built around verified candidate data, one fixed PDF resume, ATS-specific public interfaces where available, and conservative Playwright automation where applicant-facing APIs are not available.

## Current capabilities

- Discovers published jobs from Greenhouse, Ashby, and Lever public posting interfaces.
- Normalizes, deduplicates, filters, and scores 2027 internship postings.
- Stores discovered jobs plus a persistent application audit/checkpoint history in SQLite.
- Detects Greenhouse, Lever, Ashby, Workday, and unknown/generic application URLs.
- Uses ATS-specific preflight checks instead of assuming every platform exposes the same API.
- Navigates multi-page applications with Start / Next / Continue / Save and Continue / Review / Submit flows.
- Handles text fields, textareas, native selects, radio groups, checkboxes, common ARIA combobox/listbox controls, and dynamic resume upload buttons.
- Uses one fixed PDF resume for every application and blocks final submission if the resume was never confirmed as attached.
- Extracts resume text and uses it as the only source of candidate experience, skill, project, employer, and achievement facts for generated answers.
- Uses structured `profile.yaml` values for deterministic facts such as identity, contact information, education, graduation, work authorization, sponsorship, relocation, links, internship availability, and verified recurring answers.
- Supports explicit Workday work-experience and education rows so parsed resume sections can be repaired without guessing.
- Persists browser login/session state per ATS/employer so Candidate Home-style sessions can be reused.
- Detects password/login gates, email verification, MFA, and CAPTCHA and hands them to a human instead of bypassing them.
- Checkpoints every application step and resumes incomplete applications from their saved URL/session when safe.
- Blocks duplicate submissions and treats an unconfirmed post-Submit state as `UNKNOWN_AFTER_SUBMIT` so it will not blindly click Submit a second time.
- Runs a final audit before submission: required fields, visible validation errors, verified resume upload, existing blockers, and duplicate state.
- Requires a recognizable success/thank-you page before recording an application as submitted.
- Saves per-application preview screenshots outside Git when a run stops before submission.
- Provides a periodic worker for discovery and, when explicitly enabled, processing READY applications.
- Keeps final submission disabled by default.

## Why the ATS logic differs by platform

The agent intentionally does not use one universal strategy:

### Greenhouse

The public Job Board API can expose a published job and its job-specific application question definitions, including required/optional questions and compliance/demographic buckets. The agent uses that public interface for preflight/liveness/question metadata, then uses the applicant-facing browser form for actual completion. Applicant code does not use Greenhouse's employer-authenticated application submission API.

### Lever

Lever's public Postings API is useful for discovery and confirming that a posting is still public, but it does not expose custom application questions. The browser form therefore remains authoritative for questions and completion. Both US and EU Lever posting endpoints are supported for discovery/preflight.

### Ashby

Ashby's public posting feed exposes published jobs and applicant URLs. Application-form schema/submission APIs are employer-authenticated, so the personal agent uses the public feed for discovery/liveness context and the browser for applicant form completion.

### Workday

Workday application flows are employer-configurable and can contain contact information, resume parsing, repeated work experience/education, application questions, voluntary disclosures, terms, and final review. Candidate Home can also require login and reuse prior application data. The agent therefore:

- keeps a persistent per-employer browser session;
- detects login/MFA/email-verification gates for human handoff;
- prefers the configured current PDF when Workday offers reuse-vs-new-resume choices;
- supports verified structured `work_experience` and `education_history` rows to repair missing parsed fields;
- refuses to map ambiguous bare fields such as an employment `Start Date` to internship availability;
- relies on browser validation rather than undocumented internal Workday APIs.

Workday discovery is deliberately not implemented through undocumented internal endpoints. Employers can configure/index career sites differently, so use direct company career URLs or another permitted discovery source for Workday-hosted jobs.

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp data/profile.example.yaml data/profile.yaml
```

Put your current resume at:

```text
data/resume.pdf
```

The PDF, your populated profile, browser auth state, and application screenshots are ignored by Git.

You can store the resume elsewhere:

```bash
export RESUME_PATH=/absolute/path/to/resume.pdf
```

For resume-grounded free-response answers:

```bash
export OPENAI_API_KEY=your_key_here
```

The default answer model is `gpt-5`; override it if your account uses another supported model:

```bash
export ANSWER_MODEL=gpt-5
```

Run the dashboard/API:

```bash
uvicorn app.main:app --reload
```

Open `http://127.0.0.1:8000`.

## Important configuration

```bash
export AUTO_SUBMIT=false
export AUTO_RESUME_APPLICATIONS=true
export ENABLE_LLM_ANSWERS=true
export MAX_APPLICATION_STEPS=20
export MANUAL_HANDOFF_SECONDS=0
```

- `AUTO_SUBMIT=false` is the safe default. The runner can reach the final review/submit step without clicking Submit.
- `AUTO_RESUME_APPLICATIONS=true` restores safe checkpoints and browser state when possible.
- `MANUAL_HANDOFF_SECONDS=0` means login/MFA/CAPTCHA immediately becomes `NEEDS_REVIEW`. Set a positive value to keep the local headful browser open for that many seconds while you complete the human-only step.

## Verified profile data

Start from `data/profile.example.yaml`. Fill deterministic facts explicitly rather than asking an LLM to infer them.

For Workday, populate `work_experience` and `education_history` when possible. These rows are the verified source used to repair repeated structured sections after resume parsing.

Legal/privacy choices such as terms, privacy consent, and data-processing consent default to `null`; the agent will not agree for you unless you explicitly configure a verified value.

For voluntary demographic/self-identification questions:

- `eeo_default: review` stops for review.
- `eeo_default: decline` chooses an actual visible “Prefer not to answer” / “Decline” option when the ATS provides one.

It never fabricates a demographic answer.

## Answer priority and grounding

The order is strict:

1. `profile.answer_overrides` — user-verified recurring answers.
2. Structured profile fields — identity, education, authorization, links, dates, consent preferences, etc.
3. Resume-grounded generation — experience/skills/projects/qualification/free-response questions.
4. Manual review — unsupported, ambiguous, sensitive, or low-confidence questions.

The job description can make wording relevant to the role, but it is never evidence that the candidate has a skill or experience. Candidate experience facts may come only from the resume/verified profile.

Generated resume answers below `0.80` confidence are not filled automatically. When a control has fixed choices, the generated answer must match an actual visible ATS choice.

The Responses API call uses `store=False` so resume-grounded answer responses are not intentionally stored by the application through the Responses API.

## Resume behavior

`data/resume.pdf` is required by default. The runner:

- checks that it exists and is a non-empty PDF;
- extracts text for grounded answers;
- uploads the same PDF whenever a resume/CV field appears;
- supports both visible/hidden file inputs and dynamic file-chooser buttons;
- avoids obvious cover-letter/transcript/portfolio slots;
- blocks final submission if no resume upload was ever confirmed.

Replacing the PDF automatically refreshes extracted text.

## Sessions and credentials

Browser state lives under:

```text
data/browser_state/
```

This directory is ignored by Git because stored cookies/local/IndexedDB/session state can contain authenticated session material. Treat it like credentials. Do not commit or share it.

## Application memory and duplicate protection

SQLite contains an `applications` table with:

- stable ATS/application identity;
- original/canonical/current URL;
- status and current step;
- pages visited;
- resume upload state;
- generated answers;
- navigation log;
- review/blocking items;
- preflight results;
- confirmation text;
- timestamps.

Important statuses include:

- `IN_PROGRESS`
- `NEEDS_REVIEW`
- `READY_TO_SUBMIT`
- `SUBMITTED`
- `CLOSED`
- `UNKNOWN_AFTER_SUBMIT`

`UNKNOWN_AFTER_SUBMIT` is intentionally conservative: if the agent clicked Submit but could not prove success, future runs stop instead of risking a duplicate application.

## Final submission audit

Before a real Submit click, the runner verifies:

- the fixed resume was attached;
- no blocking review items remain;
- visible required fields appear complete;
- the page has no visible validation errors;
- the application is not already recorded as submitted.

After clicking Submit, it only records success after detecting a recognizable application-received/success page.

## Human handoff

The runner does not bypass:

- CAPTCHA/hCaptcha/reCAPTCHA;
- password/login gates;
- MFA/2FA;
- email verification codes;
- unsupported required questions.

It checkpoints before/around those states so the flow can be resumed after the human-only action.

## Public discovery sources

Configure `data/sources.yaml` with:

- `greenhouse`
- `ashby`
- `lever`
- `lever_eu`

The agent intentionally prefers documented public posting feeds over scraping when available.

## Periodic worker

Run:

```bash
python -m app.worker
```

Defaults:

```bash
export POLL_INTERVAL_SECONDS=1800
export AUTO_RUN_READY=false
export MAX_APPLICATIONS_PER_CYCLE=5
```

`AUTO_RUN_READY=false` means scheduled discovery can run without automatically opening applications. To process READY jobs automatically, explicitly enable it. Final submission is still independently controlled by `AUTO_SUBMIT`.

## API endpoints

- `GET /api/health`
- `GET /api/resume/status`
- `POST /api/discover`
- `GET /api/jobs`
- `GET /api/applications`
- `POST /api/apply`

`/api/apply` returns ATS/preflight information, generated answers, review/blocking items, page/navigation history, resume state, confirmation text, checkpoint-resume state, and submission state.

## Safety / limitations

No browser agent can guarantee every employer's customized application works forever. ATS tenants can add custom widgets, change labels, require third-party assessments, enforce authentication, or alter layouts. The design goal is therefore: automate aggressively when facts and controls are unambiguous, but stop before guessing or risking a duplicate submission.

`AUTO_SUBMIT` should remain off until live browser testing has been completed against representative Greenhouse, Lever, Ashby, and Workday flows using your real local profile/resume.

Jobright/other aggregator discovery is separate from this ATS application layer and should only be added through a permitted interface or a scraper that complies with the site's current access rules; CAPTCHA/anti-bot bypass is intentionally out of scope.
