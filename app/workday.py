from __future__ import annotations

import re
from typing import Iterable

from playwright.async_api import Locator, Page

from app.models import EducationEntry, Profile, WorkExperience


async def detect_manual_gate(page: Page) -> str | None:
    """Return a reason when a human login/MFA/email-verification step is visible."""
    try:
        password = page.locator('input[type="password"]')
        for i in range(await password.count()):
            if await password.nth(i).is_visible():
                return "Candidate account sign-in requires human completion"
    except Exception:
        pass

    try:
        body = " ".join((await page.locator("body").inner_text()).lower().split())
    except Exception:
        body = ""

    verification_markers = (
        "verification code",
        "one-time passcode",
        "one time passcode",
        "enter the code we sent",
        "check your email for a code",
        "verify your email",
        "multi-factor authentication",
        "multifactor authentication",
        "two-factor authentication",
    )
    if any(marker in body for marker in verification_markers):
        return "Email/MFA verification requires human completion"
    return None


async def prepare_workday_step(page: Page) -> list[str]:
    """Handle safe Workday choices that keep the configured resume authoritative."""
    actions: list[str] = []
    # Signed-in Candidate Home can offer reuse of the previous application or a
    # new resume. Always prefer the current configured PDF so stale experience
    # is not silently reused.
    labels = (
        "Upload a New Resume or CV",
        "Upload a new Resume or CV",
        "Upload New Resume or CV",
        "Upload a New Resume",
    )
    for label in labels:
        option = page.get_by_text(label, exact=False).first
        try:
            if await option.count() and await option.is_visible():
                await option.click()
                actions.append("selected current resume instead of prior Workday application")
                await page.wait_for_timeout(250)
                break
        except Exception:
            continue
    return actions


async def _visible_labeled(page_or_scope: Locator | Page, pattern: str) -> list[Locator]:
    result: list[Locator] = []
    locator = page_or_scope.get_by_label(re.compile(pattern, re.IGNORECASE))
    for i in range(await locator.count()):
        item = locator.nth(i)
        try:
            if await item.is_visible() and await item.is_enabled():
                result.append(item)
        except Exception:
            continue
    return result


async def _safe_fill(control: Locator, value: str) -> bool:
    if not value:
        return False
    try:
        if (await control.input_value()).strip():
            return False
        await control.fill(value)
        return True
    except Exception:
        return False


async def _row_scope(control: Locator) -> Locator | None:
    selectors = (
        "xpath=ancestor::fieldset[1]",
        "xpath=ancestor::*[@role='group'][1]",
        "xpath=ancestor::*[@data-automation-id][1]",
    )
    for selector in selectors:
        try:
            scope = control.locator(selector)
            if await scope.count():
                return scope.first
        except Exception:
            continue
    return None


async def _fill_first_in_scope(scope: Locator, pattern: str, value: str) -> bool:
    controls = await _visible_labeled(scope, pattern)
    if not controls:
        return False
    return await _safe_fill(controls[0], value)


async def _set_current(scope: Locator, current: bool) -> bool:
    boxes = scope.get_by_label(re.compile(r"current|currently work|currently employed", re.IGNORECASE))
    for i in range(await boxes.count()):
        box = boxes.nth(i)
        try:
            if not await box.is_visible() or not await box.is_enabled():
                continue
            if current:
                await box.check()
            else:
                await box.uncheck()
            return True
        except Exception:
            continue
    return False


async def _repair_work_rows(page: Page, entries: list[WorkExperience]) -> list[str]:
    if not entries:
        return []
    company_controls = await _visible_labeled(page, r"company|employer|organization")
    if not company_controls:
        return []

    actions: list[str] = []
    for index, company_control in enumerate(company_controls[: len(entries)]):
        entry = entries[index]
        scope = await _row_scope(company_control)
        if scope is None:
            continue
        changed = await _safe_fill(company_control, entry.company)
        changed |= await _fill_first_in_scope(scope, r"job title|position title|role title|title", entry.title)
        changed |= await _fill_first_in_scope(scope, r"location", entry.location)
        changed |= await _fill_first_in_scope(scope, r"start date|from date", entry.start_date)
        if not entry.current:
            changed |= await _fill_first_in_scope(scope, r"end date|to date", entry.end_date)
        await _set_current(scope, entry.current)
        changed |= await _fill_first_in_scope(scope, r"description|responsibilities", entry.description)
        if changed:
            actions.append(f"repaired Workday work-experience row {index + 1}")
    return actions


async def _repair_education_rows(page: Page, entries: list[EducationEntry]) -> list[str]:
    if not entries:
        return []
    school_controls = await _visible_labeled(page, r"school|university|institution")
    if not school_controls:
        return []

    actions: list[str] = []
    for index, school_control in enumerate(school_controls[: len(entries)]):
        entry = entries[index]
        scope = await _row_scope(school_control)
        if scope is None:
            continue
        changed = await _safe_fill(school_control, entry.school)
        changed |= await _fill_first_in_scope(scope, r"degree", entry.degree)
        changed |= await _fill_first_in_scope(scope, r"field of study|major|discipline", entry.field_of_study)
        changed |= await _fill_first_in_scope(scope, r"location", entry.location)
        changed |= await _fill_first_in_scope(scope, r"start date|from date", entry.start_date)
        changed |= await _fill_first_in_scope(scope, r"end date|graduation|to date", entry.end_date)
        changed |= await _fill_first_in_scope(scope, r"gpa|grade point average", entry.gpa)
        if changed:
            actions.append(f"repaired Workday education row {index + 1}")
    return actions


async def _section_text_for_button(button: Locator) -> str:
    for selector in (
        "xpath=ancestor::section[1]",
        "xpath=ancestor::*[@role='group'][1]",
        "xpath=ancestor::*[@data-automation-id][1]",
        "xpath=ancestor::div[1]",
    ):
        try:
            scope = button.locator(selector)
            if await scope.count():
                text = " ".join((await scope.first.inner_text()).lower().split())
                if text:
                    return text[:2000]
        except Exception:
            continue
    return ""


async def _add_missing_rows(page: Page, needed: int, current: int, section_words: Iterable[str]) -> int:
    if current >= needed:
        return current
    buttons = page.get_by_role("button", name=re.compile(r"^add(?: another)?(?: experience| education)?$", re.IGNORECASE))
    attempts = 0
    while current < needed and attempts < needed:
        chosen: Locator | None = None
        for i in range(await buttons.count()):
            button = buttons.nth(i)
            try:
                if not await button.is_visible() or not await button.is_enabled():
                    continue
            except Exception:
                continue
            context = await _section_text_for_button(button)
            if any(word in context for word in section_words):
                chosen = button
                break
        if chosen is None:
            break
        try:
            await chosen.click()
            await page.wait_for_timeout(250)
            current += 1
            attempts += 1
            buttons = page.get_by_role("button", name=re.compile(r"^add(?: another)?(?: experience| education)?$", re.IGNORECASE))
        except Exception:
            break
    return current


async def repair_workday_structured_sections(page: Page, profile: Profile) -> list[str]:
    """Best-effort repair of Workday's repeated parsed Experience/Education rows.

    This only uses explicit structured profile entries. It never invents a row
    from an open-ended LLM answer. If Workday's layout cannot be identified
    safely, the generic required-field audit will stop for manual review.
    """
    actions: list[str] = []
    if profile.work_experience:
        companies = await _visible_labeled(page, r"company|employer|organization")
        await _add_missing_rows(page, len(profile.work_experience), len(companies), ("work experience", "experience"))
        actions.extend(await _repair_work_rows(page, profile.work_experience))

    if profile.education_history:
        schools = await _visible_labeled(page, r"school|university|institution")
        await _add_missing_rows(page, len(profile.education_history), len(schools), ("education", "school"))
        actions.extend(await _repair_education_rows(page, profile.education_history))
    return actions
