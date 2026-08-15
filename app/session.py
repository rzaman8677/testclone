from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import Browser, BrowserContext, Page

from app.ats import session_scope
from app.config import BROWSER_STATE_DIR


def _ensure_state_dir() -> Path:
    BROWSER_STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        BROWSER_STATE_DIR.chmod(0o700)
    except OSError:
        pass
    return BROWSER_STATE_DIR


def state_paths(url: str) -> tuple[Path, Path]:
    root = _ensure_state_dir()
    scope = session_scope(url)
    return root / f"{scope}.json", root / f"{scope}.session.json"


async def new_context(browser: Browser, url: str) -> BrowserContext:
    storage_path, session_path = state_paths(url)
    kwargs: dict = {}
    if storage_path.exists() and storage_path.stat().st_size > 0:
        kwargs["storage_state"] = str(storage_path)

    context = await browser.new_context(**kwargs)

    # Playwright storage_state covers cookies/localStorage/IndexedDB. Some apps
    # also keep short-lived state in sessionStorage, which Playwright does not
    # persist automatically, so restore our best-effort copy before navigation.
    if session_path.exists():
        try:
            payload = json.loads(session_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
        host = (urlparse(url).hostname or "").lower()
        values = payload.get(host, {}) if isinstance(payload, dict) else {}
        if isinstance(values, dict) and values:
            script = """({host, values}) => {
                if (window.location.hostname.toLowerCase() !== host) return;
                for (const [key, value] of Object.entries(values)) {
                    try { window.sessionStorage.setItem(key, value); } catch (_) {}
                }
            }"""
            await context.add_init_script(script=f"({script})({json.dumps({'host': host, 'values': values})})")
    return context


async def save_context(context: BrowserContext, page: Page, url: str) -> None:
    storage_path, session_path = state_paths(url)
    try:
        await context.storage_state(path=str(storage_path))
        try:
            storage_path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        pass

    try:
        host = (urlparse(page.url).hostname or urlparse(url).hostname or "").lower()
        values = await page.evaluate(
            "() => Object.fromEntries(Array.from({length: sessionStorage.length}, (_, i) => { const k = sessionStorage.key(i); return [k, sessionStorage.getItem(k)]; }))"
        )
        existing: dict = {}
        if session_path.exists():
            try:
                existing = json.loads(session_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
        if not isinstance(existing, dict):
            existing = {}
        existing[host] = values if isinstance(values, dict) else {}
        session_path.write_text(json.dumps(existing), encoding="utf-8")
        try:
            session_path.chmod(0o600)
        except OSError:
            pass
    except Exception:
        pass


def clear_session(url: str) -> None:
    for path in state_paths(url):
        try:
            path.unlink(missing_ok=True)
        except OSError:
            pass
