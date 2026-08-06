from __future__ import annotations

import re
from dataclasses import dataclass

from playwright.async_api import Locator, Page


NEXT_LABELS = (
    "save and continue",
    "continue",
    "next step",
    "next",
    "review application",
    "review",
    "proceed",
)
START_LABELS = (
    "start application",
    "begin application",
    "apply now",
    "apply",
)
SUBMIT_LABELS = (
    "submit application",
    "submit my application",
    "submit",
)
BLOCKED_LABELS = (
    "back",
    "previous",
    "cancel",
    "withdraw",
    "delete",
    "sign out",
)


@dataclass
class NavigationAction:
    kind: str
    label: str
    locator: Locator | None = None


def normalize_label(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def classify_action_label(text: str) -> str | None:
    label = normalize_label(text)
    if not label or any(blocked == label or label.startswith(blocked + " ") for blocked in BLOCKED_LABELS):
        return None
    if any(token == label or token in label for token in SUBMIT_LABELS):
        return "submit"
    if any(token == label or token in label for token in NEXT_LABELS):
        return "next"
    if any(token == label or token in label for token in START_LABELS):
        return "start"
    return None


def action_priority(kind: str, label: str) -> tuple[int, int]:
    normalized = normalize_label(label)
    base = {"next": 0, "start": 1, "submit": 2}.get(kind, 9)
    preferred = 0
    if normalized in NEXT_LABELS or normalized in START_LABELS or normalized in SUBMIT_LABELS:
        preferred = -1
    return base, preferred


async def _visible_text(locator: Locator) -> str:
    try:
        return normalize_label(await locator.inner_text())
    except Exception:
        try:
            return normalize_label(await locator.get_attribute("aria-label") or "")
        except Exception:
            return ""


async def find_navigation_action(page: Page) -> NavigationAction | None:
    candidates: list[NavigationAction] = []
    locators = page.locator(
        'button, input[type="submit"], input[type="button"], a[role="button"], [role="button"]'
    )
    for i in range(await locators.count()):
        locator = locators.nth(i)
        try:
            if not await locator.is_visible() or not await locator.is_enabled():
                continue
        except Exception:
            continue

        label = await _visible_text(locator)
        if not label:
            label = normalize_label(await locator.get_attribute("value") or "")
        kind = classify_action_label(label)
        if kind:
            candidates.append(NavigationAction(kind=kind, label=label, locator=locator))

    if not candidates:
        return None
    candidates.sort(key=lambda action: action_priority(action.kind, action.label))
    return candidates[0]


async def page_fingerprint(page: Page) -> str:
    try:
        title = await page.title()
    except Exception:
        title = ""
    try:
        heading = await page.locator("h1, h2, [role=heading]").first.inner_text()
    except Exception:
        heading = ""
    try:
        controls = await page.locator("input, textarea, select, [role=combobox]").count()
    except Exception:
        controls = 0
    return f"{page.url}|{normalize_label(title)}|{normalize_label(heading)}|{controls}"


async def visible_validation_errors(page: Page) -> list[str]:
    selectors = (
        '[role="alert"]',
        '[aria-live="assertive"]',
        '[aria-invalid="true"]',
        '.error',
        '.errors',
        '.field-error',
        '.validation-error',
    )
    messages: list[str] = []
    seen: set[str] = set()
    for selector in selectors:
        nodes = page.locator(selector)
        for i in range(min(await nodes.count(), 30)):
            node = nodes.nth(i)
            try:
                if not await node.is_visible():
                    continue
                text = normalize_label(await node.inner_text())
            except Exception:
                continue
            if text and text not in seen:
                seen.add(text)
                messages.append(text[:400])
    return messages


async def is_required(control: Locator) -> bool:
    try:
        required = await control.get_attribute("required")
        aria_required = normalize_label(await control.get_attribute("aria-required") or "")
        if required is not None or aria_required == "true":
            return True
        question = normalize_label(
            await control.evaluate(
                """el => {
                    const parts=[];
                    if (el.labels) for (const label of el.labels) parts.push(label.innerText || label.textContent || '');
                    const fieldset=el.closest('fieldset');
                    const legend=fieldset && fieldset.querySelector('legend');
                    if (legend) parts.push(legend.innerText || legend.textContent || '');
                    return parts.join(' ');
                }"""
            )
        )
        return "required" in question or "*" in question
    except Exception:
        return False


async def wait_for_step_change(page: Page, before: str, timeout_ms: int = 10_000) -> bool:
    elapsed = 0
    while elapsed < timeout_ms:
        await page.wait_for_timeout(400)
        elapsed += 400
        if await page_fingerprint(page) != before:
            return True
    return False
