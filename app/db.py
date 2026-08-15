from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from app.ats import application_key, canonical_application_url, detect_ats
from app.config import DB_PATH
from app.models import Job


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT NOT NULL,
  company TEXT NOT NULL,
  title TEXT NOT NULL,
  location TEXT NOT NULL DEFAULT '',
  description TEXT NOT NULL DEFAULT '',
  job_url TEXT NOT NULL,
  apply_url TEXT NOT NULL,
  ats TEXT NOT NULL,
  external_id TEXT NOT NULL,
  posted_at TEXT,
  score REAL NOT NULL DEFAULT 0,
  status TEXT NOT NULL,
  reasons TEXT NOT NULL DEFAULT '[]',
  first_seen TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(ats, external_id)
);

CREATE TABLE IF NOT EXISTS applications (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  application_key TEXT NOT NULL UNIQUE,
  ats TEXT NOT NULL,
  apply_url TEXT NOT NULL,
  canonical_url TEXT NOT NULL,
  current_url TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'IN_PROGRESS',
  step_index INTEGER NOT NULL DEFAULT 0,
  pages_visited INTEGER NOT NULL DEFAULT 0,
  resume_uploaded INTEGER NOT NULL DEFAULT 0,
  submitted INTEGER NOT NULL DEFAULT 0,
  confirmation_text TEXT NOT NULL DEFAULT '',
  last_fingerprint TEXT NOT NULL DEFAULT '',
  navigation_log TEXT NOT NULL DEFAULT '[]',
  generated_answers TEXT NOT NULL DEFAULT '[]',
  review TEXT NOT NULL DEFAULT '[]',
  blocking_review TEXT NOT NULL DEFAULT '[]',
  preflight TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_applications_status ON applications(status, updated_at);
"""


@contextmanager
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def upsert_job(job: Job) -> None:
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO jobs (
              source, company, title, location, description, job_url, apply_url,
              ats, external_id, posted_at, score, status, reasons, first_seen, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ats, external_id) DO UPDATE SET
              company=excluded.company,
              title=excluded.title,
              location=excluded.location,
              description=excluded.description,
              job_url=excluded.job_url,
              apply_url=excluded.apply_url,
              posted_at=excluded.posted_at,
              score=excluded.score,
              status=CASE WHEN jobs.status='APPLIED' THEN jobs.status ELSE excluded.status END,
              reasons=excluded.reasons,
              updated_at=excluded.updated_at
            """,
            (
                job.source, job.company, job.title, job.location, job.description,
                job.job_url, job.apply_url, job.ats, job.external_id,
                job.posted_at.isoformat() if job.posted_at else None,
                job.score, job.status.value, json.dumps(job.reasons), now, now,
            ),
        )


def list_jobs(limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs ORDER BY score DESC, first_seen DESC LIMIT ?", (limit,)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["reasons"] = json.loads(item["reasons"] or "[]")
        result.append(item)
    return result


def update_status(ats: str, external_id: str, status: str) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status=?, updated_at=? WHERE ats=? AND external_id=?",
            (status, datetime.now(timezone.utc).isoformat(), ats, external_id),
        )


def _decode_application(row: sqlite3.Row | None) -> dict | None:
    if row is None:
        return None
    item = dict(row)
    for field, default in (
        ("navigation_log", []),
        ("generated_answers", []),
        ("review", []),
        ("blocking_review", []),
        ("preflight", {}),
    ):
        try:
            item[field] = json.loads(item.get(field) or json.dumps(default))
        except (TypeError, json.JSONDecodeError):
            item[field] = default
    item["resume_uploaded"] = bool(item.get("resume_uploaded"))
    item["submitted"] = bool(item.get("submitted"))
    return item


def get_application(url: str) -> dict | None:
    key = application_key(url)
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM applications WHERE application_key=?", (key,)
        ).fetchone()
    return _decode_application(row)


def begin_application(url: str, preflight: dict | None = None) -> dict:
    key = application_key(url)
    now = datetime.now(timezone.utc).isoformat()
    canonical = canonical_application_url(url)
    ats = detect_ats(url).value
    with connect() as conn:
        conn.execute(
            """
            INSERT INTO applications (
              application_key, ats, apply_url, canonical_url, current_url,
              status, preflight, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'IN_PROGRESS', ?, ?, ?)
            ON CONFLICT(application_key) DO UPDATE SET
              preflight=excluded.preflight,
              updated_at=excluded.updated_at
            """,
            (key, ats, url, canonical, url, json.dumps(preflight or {}), now, now),
        )
        row = conn.execute(
            "SELECT * FROM applications WHERE application_key=?", (key,)
        ).fetchone()
    decoded = _decode_application(row)
    assert decoded is not None
    return decoded


def checkpoint_application(
    url: str,
    *,
    current_url: str,
    status: str,
    step_index: int,
    pages_visited: int,
    resume_uploaded: bool,
    submitted: bool,
    confirmation_text: str = "",
    last_fingerprint: str = "",
    navigation_log: list[dict] | None = None,
    generated_answers: list[dict] | None = None,
    review: list[str] | None = None,
    blocking_review: list[str] | None = None,
) -> None:
    key = application_key(url)
    now = datetime.now(timezone.utc).isoformat()
    with connect() as conn:
        conn.execute(
            """
            UPDATE applications SET
              current_url=?, status=?, step_index=?, pages_visited=?,
              resume_uploaded=?, submitted=?, confirmation_text=?,
              last_fingerprint=?, navigation_log=?, generated_answers=?,
              review=?, blocking_review=?, updated_at=?
            WHERE application_key=?
            """,
            (
                current_url,
                status,
                step_index,
                pages_visited,
                int(resume_uploaded),
                int(submitted),
                confirmation_text,
                last_fingerprint,
                json.dumps(navigation_log or []),
                json.dumps(generated_answers or []),
                json.dumps(review or []),
                json.dumps(blocking_review or []),
                now,
                key,
            ),
        )


def list_applications(limit: int = 200) -> list[dict]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM applications ORDER BY updated_at DESC LIMIT ?", (limit,)
        ).fetchall()
    return [_decode_application(row) for row in rows if row is not None]
