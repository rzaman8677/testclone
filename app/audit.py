from __future__ import annotations

from dataclasses import dataclass, field

from playwright.async_api import Locator, Page

from app.navigation import is_required, visible_validation_errors


@dataclass
class AuditReport:
    ok: bool
    issues: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def _control_has_value(control: Locator) -> bool:
    try:
        tag = await control.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await control.get_attribute("type") or "").lower()
        if input_type == "radio":
            return bool(
                await control.evaluate(
                    """el => el.name
                        ? Array.from(document.querySelectorAll('input[type="radio"]')).some(r => r.name === el.name && r.checked)
                        : !!el.checked"""
                )
            )
        if input_type == "checkbox":
            return await control.is_checked()
        if input_type == "file":
            return bool(await control.evaluate("el => !!(el.files && el.files.length)"))
        if tag == "select":
            return bool((await control.input_value()).strip())
        return bool((await control.input_value()).strip())
    except Exception:
        return False


async def missing_required_controls(page: Page) -> list[str]:
    controls = page.locator(
        'input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select, [role="combobox"]'
    )
    missing: list[str] = []
    seen_radio_groups: set[str] = set()
    for i in range(await controls.count()):
        control = controls.nth(i)
        try:
            if not await control.is_visible() or not await control.is_enabled():
                continue
        except Exception:
            continue
        if not await is_required(control):
            continue
        input_type = (await control.get_attribute("type") or "").lower()
        if input_type == "radio":
            group = await control.get_attribute("name") or f"radio-{i}"
            if group in seen_radio_groups:
                continue
            seen_radio_groups.add(group)
        if await _control_has_value(control):
            continue
        try:
            label = (
                await control.get_attribute("aria-label")
                or await control.get_attribute("name")
                or await control.get_attribute("id")
                or f"field-{i}"
            )
        except Exception:
            label = f"field-{i}"
        missing.append(str(label)[:200])
    return list(dict.fromkeys(missing))


async def final_audit(
    page: Page,
    *,
    resume_uploaded: bool,
    blocking_review: list[str],
    duplicate_submitted: bool = False,
) -> AuditReport:
    issues: list[str] = []
    warnings: list[str] = []

    if duplicate_submitted:
        issues.append("This application was already recorded as submitted; duplicate submission is blocked.")
    if not resume_uploaded:
        issues.append("The required resume PDF has not been confirmed as uploaded.")
    if blocking_review:
        issues.extend(blocking_review)

    validation = await visible_validation_errors(page)
    issues.extend(f"Validation: {message}" for message in validation)

    missing = await missing_required_controls(page)
    if missing:
        issues.append("Required fields still appear empty: " + ", ".join(missing[:12]))

    return AuditReport(ok=not issues, issues=list(dict.fromkeys(issues)), warnings=warnings)


async def detect_confirmation(page: Page) -> tuple[bool, str]:
    try:
        body = (await page.locator("body").inner_text()).strip()
    except Exception:
        return False, ""
    normalized = " ".join(body.lower().split())
    markers = (
        "thank you for applying",
        "thank you for your application",
        "application submitted",
        "application has been submitted",
        "application received",
        "we have received your application",
        "successfully applied",
        "your application was submitted",
    )
    for marker in markers:
        if marker in normalized:
            excerpt_start = max(0, normalized.find(marker) - 120)
            excerpt_end = min(len(body), excerpt_start + 500)
            return True, body[excerpt_start:excerpt_end].strip()
    return False, ""


async def detect_closed_or_unavailable(page: Page) -> str | None:
    try:
        body = " ".join((await page.locator("body").inner_text()).lower().split())
    except Exception:
        return None
    markers = (
        "job is no longer available",
        "position is no longer available",
        "position has been filled",
        "job posting has expired",
        "job has expired",
        "this job is closed",
        "no longer accepting applications",
        "this position is closed",
    )
    for marker in markers:
        if marker in body:
            return marker
    return None
