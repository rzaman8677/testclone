# 2027 Internship Application Agent

Personal internship discovery and application-assistance MVP.

## What it does

- Discovers jobs from supported ATS feeds (Greenhouse and Ashby first)
- Normalizes and deduplicates postings
- Filters for internships and configurable 2027-target keywords
- Scores jobs against a structured personal profile
- Stores jobs and application state in SQLite
- Exposes a FastAPI API and lightweight dashboard
- Uses one fixed PDF resume for every application
- Extracts text from that PDF and uses it as the source of truth for experience, skills, projects, and qualification questions
- Uses verified `profile.yaml` values for deterministic questions such as education, contact info, work authorization, sponsorship, relocation, dates, and links
- Supports `answer_overrides` for recurring verified questions
- Refuses to infer demographic, legal, citizenship, criminal-history, or compensation answers from the resume
- Navigates multi-page ATS flows using visible controls rather than hard-coding one page layout
- Handles text inputs, textareas, native selects, radio groups, checkboxes, and common custom listbox/combobox controls
- Finds safe forward actions such as Start, Next, Continue, Review, and Submit while avoiding Back/Cancel/Withdraw controls
- Re-checks CAPTCHA and validation state on every page
- Stops for review when a required answer is unsupported, low-confidence, or cannot be entered reliably
- Does **not** auto-submit by default

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

The file is intentionally ignored by git so your personal PDF is not committed to the repository. You can instead keep it elsewhere and set:

```bash
export RESUME_PATH=/absolute/path/to/your/resume.pdf
```

For resume-grounded free-response generation, configure an API key:

```bash
export OPENAI_API_KEY=your_key_here
```

Optional settings:

```bash
export ENABLE_LLM_ANSWERS=true
export ANSWER_MODEL=gpt-5.5
export AUTO_SUBMIT=false
export MAX_APPLICATION_STEPS=15
```

Then run:

```bash
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000. The dashboard shows whether the fixed resume is loaded and extractable.

## How application answers work

The order is intentionally strict:

1. `profile.answer_overrides` — exact user-verified recurring answers.
2. Structured profile fields — name, address, school, degree, major, GPA, graduation, work authorization, sponsorship, relocation, links, dates, etc.
3. Resume-grounded generation — open-ended experience/skills/project/qualification questions are answered using only facts supported by the PDF.
4. Manual review — unsupported or sensitive questions are never guessed.

Generated answers below 0.80 confidence are sent to review. The model is instructed to treat the resume, job description, and application question as untrusted content and never invent candidate facts.

Optional unanswered fields are recorded for review but do not automatically stop the runner. Required unsupported fields stop the runner before it advances, so it does not blindly click through validation or submit incomplete information.

## Adaptive multi-page navigation

The browser runner loops through ATS steps instead of assuming one fixed form. On every page it:

1. Detects CAPTCHA/human verification.
2. Uploads the fixed resume if a resume/CV control appears on that step.
3. Finds visible enabled form controls and derives their question/label from labels, legends, ARIA metadata, placeholders, and nearby ATS label elements.
4. Answers deterministic questions from the verified profile.
5. Uses the resume-grounded answer engine for supported experience/project/skill questions.
6. Handles common custom dropdowns/listboxes as well as native HTML controls.
7. Separates optional unresolved questions from required blocking questions.
8. Reads visible validation messages.
9. Chooses a safe forward action such as Start Application, Next, Save and Continue, Continue, Review Application, or Submit Application.
10. Confirms the page/step changed after clicking and stops if it detects a loop or a layout it cannot navigate safely.

The runner carries state across pages. In particular, the resume can appear on an early, middle, or late step; it only becomes mandatory before final submission.

`MAX_APPLICATION_STEPS` defaults to 15 to prevent an accidental navigation loop.

The `/api/apply` response includes:

- `pages_visited`
- `navigation_log`
- `final_url`
- `filled`
- `generated_answers`
- `review` for non-blocking items
- `blocking_review` for issues that stopped automation
- `resume_uploaded`
- `submitted`

## Fixed resume behavior

`data/resume.pdf` is required by default. Before and during an application the agent:

- verifies that the file exists and is a non-empty PDF;
- extracts its text for grounded answers;
- uploads it whenever the resume/CV step appears;
- avoids obvious cover-letter/transcript/portfolio upload slots;
- blocks final submission if it never confirmed a resume upload.

Replacing `data/resume.pdf` with a newer PDF automatically refreshes the extracted resume context.

## Configure sources

Edit `data/sources.yaml` and add public Greenhouse board tokens or Ashby board names.

## Safety defaults

`AUTO_SUBMIT=false` by default. CAPTCHA bypassing is intentionally not implemented. Voluntary demographic/self-identification questions are not inferred from the resume. If you want a recurring fixed answer to a specific question, add an explicit verified `answer_overrides` entry instead of relying on inference.

## Next adapters / improvements

- Lever-specific discovery/application tuning
- Workday-specific account/login and dynamically repeated work-history sections
- Jobright discovery provider, subject to its current site terms and access rules
- Resume variant selection if you later want different PDFs for different role families
- Scheduling and notifications
