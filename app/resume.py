from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pypdf import PdfReader

from app.config import RESUME_PATH


class ResumeError(RuntimeError):
    pass


def require_resume_pdf(path: Path | None = None) -> Path:
    resume = (path or RESUME_PATH).expanduser().resolve()
    if not resume.exists():
        raise ResumeError(
            f"Required resume PDF was not found at {resume}. "
            "Place your resume there or set RESUME_PATH."
        )
    if not resume.is_file() or resume.suffix.lower() != ".pdf":
        raise ResumeError(f"Resume must be a PDF file: {resume}")
    if resume.stat().st_size == 0:
        raise ResumeError(f"Resume PDF is empty: {resume}")
    return resume


@lru_cache(maxsize=8)
def _extract_pdf_text(path_str: str, modified_ns: int) -> str:
    del modified_ns  # Included in the cache key so replacing the PDF refreshes text.
    reader = PdfReader(path_str)
    text = "\n".join((page.extract_text() or "").strip() for page in reader.pages).strip()
    if not text:
        raise ResumeError(
            "The resume PDF contains no extractable text. Use a text-based PDF rather than an image-only scan."
        )
    return text


def load_resume_text(path: Path | None = None) -> str:
    resume = require_resume_pdf(path)
    return _extract_pdf_text(str(resume), resume.stat().st_mtime_ns)
