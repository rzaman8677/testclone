from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

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
