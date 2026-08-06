# 2027 Internship Application Agent

Personal internship discovery and application-assistance MVP.

## What it does

- Discovers jobs from supported ATS feeds (Greenhouse and Ashby first)
- Normalizes and deduplicates postings
- Filters for internships and configurable 2027-target keywords
- Scores jobs against a structured personal profile
- Stores jobs and application state in SQLite
- Exposes a FastAPI API and lightweight dashboard
- Includes a Playwright-based form filler for common application fields
- Stops for review on unknown questions or CAPTCHAs
- Does **not** auto-submit by default

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp data/profile.example.yaml data/profile.yaml
uvicorn app.main:app --reload
```

Open http://127.0.0.1:8000.

## Configure sources

Edit `data/sources.yaml` and add public Greenhouse board tokens or Ashby board names.

## Safety defaults

`AUTO_SUBMIT=false` by default. The agent fills deterministic fields only and sends ambiguous questions to review. CAPTCHA bypassing is intentionally not implemented.

## Next adapters

- Lever
- Workday
- Jobright discovery provider, subject to its current site terms and access rules
- Resume variant generation
- LLM-backed job scoring / free-response answers using verified profile facts only
