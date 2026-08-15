from __future__ import annotations

import os
from pathlib import Path
import yaml

from app.models import Profile, SourceConfig

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("JOB_AGENT_DB", ROOT / "jobs.db"))
RESUME_PATH = Path(os.getenv("RESUME_PATH", DATA_DIR / "resume.pdf")).expanduser()
BROWSER_STATE_DIR = Path(os.getenv("BROWSER_STATE_DIR", DATA_DIR / "browser_state")).expanduser()
ARTIFACT_DIR = Path(os.getenv("APPLICATION_ARTIFACT_DIR", DATA_DIR / "application_artifacts")).expanduser()
AUTO_SUBMIT = os.getenv("AUTO_SUBMIT", "false").lower() == "true"
AUTO_RESUME_APPLICATIONS = os.getenv("AUTO_RESUME_APPLICATIONS", "true").lower() == "true"
MIN_AUTO_APPLY_SCORE = float(os.getenv("MIN_AUTO_APPLY_SCORE", "80"))
MIN_REVIEW_SCORE = float(os.getenv("MIN_REVIEW_SCORE", "65"))
ENABLE_LLM_ANSWERS = os.getenv("ENABLE_LLM_ANSWERS", "true").lower() == "true"
ANSWER_MODEL = os.getenv("ANSWER_MODEL", "gpt-5")
MAX_APPLICATION_STEPS = max(1, int(os.getenv("MAX_APPLICATION_STEPS", "20")))
MANUAL_HANDOFF_SECONDS = max(0, int(os.getenv("MANUAL_HANDOFF_SECONDS", "0")))


def _read_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def load_profile() -> Profile:
    path = DATA_DIR / "profile.yaml"
    if not path.exists():
        path = DATA_DIR / "profile.example.yaml"
    return Profile.model_validate(_read_yaml(path))


def load_sources() -> list[SourceConfig]:
    raw = _read_yaml(DATA_DIR / "sources.yaml")
    return [SourceConfig.model_validate(item) for item in raw.get("sources", []) if item.get("enabled", True)]
