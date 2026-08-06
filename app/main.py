from __future__ import annotations

import asyncio
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.browser import fill_application
from app.config import load_profile, load_sources
from app.db import init_db, list_jobs, upsert_job
from app.resume import ResumeError, load_resume_text, require_resume_pdf
from app.scoring import score_job
from app.sources import fetch_source

app = FastAPI(title="2027 Internship Agent", version="0.2.0")


class ApplyRequest(BaseModel):
    url: str
    job_context: str = ""


@app.on_event("startup")
def startup() -> None:
    init_db()


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/resume/status")
def resume_status() -> dict:
    try:
        path = require_resume_pdf()
        text = load_resume_text()
        return {
            "ready": True,
            "filename": path.name,
            "extractable_characters": len(text),
        }
    except ResumeError as exc:
        return {"ready": False, "error": str(exc)}


@app.post("/api/discover")
async def discover() -> dict:
    profile = load_profile()
    sources = load_sources()
    results = await asyncio.gather(
        *(fetch_source(source) for source in sources), return_exceptions=True
    )

    discovered = 0
    failures: list[str] = []
    for source, result in zip(sources, results):
        if isinstance(result, Exception):
            failures.append(f"{source.company}: {result}")
            continue
        for job in result:
            upsert_job(score_job(job, profile))
            discovered += 1

    return {"discovered": discovered, "source_failures": failures}


@app.get("/api/jobs")
def jobs(limit: int = 200) -> list[dict]:
    return list_jobs(limit=min(max(limit, 1), 1000))


@app.post("/api/apply")
async def apply(req: ApplyRequest) -> dict:
    if not req.url.startswith(("https://", "http://")):
        raise HTTPException(status_code=400, detail="Invalid application URL")
    result = await fill_application(req.url, load_profile(), req.job_context)
    return {
        "filled": result.filled,
        "review": result.review,
        "generated_answers": result.generated_answers,
        "captcha_detected": result.captcha_detected,
        "resume_uploaded": result.resume_uploaded,
        "submitted": result.submitted,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard() -> str:
    return """
<!doctype html>
<html>
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>2027 Internship Agent</title>
  <style>
    body{font-family:Inter,system-ui,sans-serif;max-width:1100px;margin:40px auto;padding:0 20px;background:#0b0d10;color:#f4f7fb}
    button{padding:10px 16px;border:0;border-radius:9px;cursor:pointer}
    .card{border:1px solid #262b33;border-radius:14px;padding:16px;margin:12px 0;background:#12161c}
    .meta{opacity:.72;font-size:14px}.score{font-weight:800}.reason{font-size:13px;opacity:.8}
    a{color:#9cc2ff}.toolbar{display:flex;gap:10px;align-items:center;margin-bottom:24px;flex-wrap:wrap}
    .ok{color:#89e5a7}.bad{color:#ff9b9b}
  </style>
</head>
<body>
  <h1>2027 Internship Agent</h1>
  <div class="toolbar">
    <button onclick="discover()">Discover jobs</button>
    <span id="status"></span>
    <span id="resume"></span>
  </div>
  <div id="jobs"></div>
<script>
async function loadResume(){
  const r=await fetch('/api/resume/status').then(r=>r.json());
  const el=document.getElementById('resume');
  el.className=r.ready?'ok':'bad';
  el.textContent=r.ready?`Resume ready: ${r.filename}`:`Resume missing: ${r.error}`;
}
async function load(){
  const jobs=await fetch('/api/jobs').then(r=>r.json());
  document.getElementById('jobs').innerHTML=jobs.map(j=>`<div class="card">
    <div><span class="score">${j.score}</span> — <strong>${j.company}</strong> · ${j.title}</div>
    <div class="meta">${j.location||''} · ${j.ats} · ${j.status}</div>
    <div class="reason">${(j.reasons||[]).join(' · ')}</div>
    <a target="_blank" href="${j.apply_url}">Open application</a>
  </div>`).join('') || '<p>No jobs yet. Configure sources, then run discovery.</p>';
}
async function discover(){
  const s=document.getElementById('status'); s.textContent='Discovering…';
  const r=await fetch('/api/discover',{method:'POST'}).then(r=>r.json());
  s.textContent=`Found ${r.discovered} jobs`;
  await load();
}
loadResume(); load();
</script>
</body>
</html>
"""
