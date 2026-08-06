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
- Stops for review when an answer is unsupported, low-confidence, or blocked by CAPTCHA
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

## Fixed resume behavior

`data/resume.pdf` is required by default. Before opening an application the agent:

- verifies that the file exists and is a non-empty PDF;
- extracts its text for grounded answers;
- finds the resume/CV file-upload control;
- uploads the same PDF automatically;
- blocks submission if it could not attach the resume.

Replacing `data/resume.pdf` with a newer PDF automatically refreshes the extracted resume context.

## Configure sources

Edit `data/sources.yaml` and add public Greenhouse board tokens or Ashby board names.

## Safety defaults

`AUTO_SUBMIT=false` by default. CAPTCHA bypassing is intentionally not implemented. Voluntary demographic/self-identification questions are not inferred from the resume.

## Next adapters

- Lever
- Workday
- Jobright discovery provider, subject to its current site terms and access rules
- Multi-page ATS navigation
- Resume variant selection if you later want different PDFs for different role families
- Scheduling and notifications
