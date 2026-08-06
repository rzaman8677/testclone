from __future__ import annotations

import os
from pathlib import Path
import yaml

from app.models import Profile, SourceConfig

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DB_PATH = Path(os.getenv("JOB_AGENT_DB", ROOT / "jobs.db"))
AUTO_SUBMIT = os.getenv("AUTO_SUBMIT", "false").lower() == "true"
MIN_AUTO_APPLY_SCORE = float(os.getenv("MIN_AUTO_APPLY_SCORE", "80"))
MIN_REVIEW_SCORE = float(os.getenv("MIN_REVIEW_SCORE", "65"))


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
