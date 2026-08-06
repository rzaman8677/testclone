from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from playwright.async_api import Page, async_playwright

from app.config import AUTO_SUBMIT
from app.models import Profile


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    captcha_detected: bool = False
    submitted: bool = False


FIELD_ALIASES = {
    "first name": "first_name",
    "firstname": "first_name",
    "last name": "last_name",
    "lastname": "last_name",
    "email": "email",
    "email address": "email",
    "phone": "phone",
    "phone number": "phone",
    "university": "university",
    "school": "university",
    "college": "university",
    "degree": "degree",
    "major": "major",
    "gpa": "gpa",
}


async def _captcha_present(page: Page) -> bool:
    body = (await page.locator("body").inner_text()).lower()
    markers = ("captcha", "verify you are human", "i'm not a robot", "recaptcha")
    return any(marker in body for marker in markers)


async def _fill_by_label(page: Page, label: str, value: str) -> bool:
    if not value:
        return False
    try:
        locator = page.get_by_label(label, exact=False).first
        if await locator.count() == 0:
            return False
        await locator.fill(value)
        return True
    except Exception:
        return False


async def fill_application(url: str, profile: Profile, resume_path: str | None = None) -> FillResult:
    result = FillResult()
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        if await _captcha_present(page):
            result.captcha_detected = True
            result.review.append("CAPTCHA/human verification requires manual completion")
            await browser.close()
            return result

        for label, attr in FIELD_ALIASES.items():
            value = getattr(profile, attr, "")
            if value and await _fill_by_label(page, label, str(value)):
                result.filled.append(label)

        if resume_path and Path(resume_path).exists():
            try:
                file_inputs = page.locator('input[type="file"]')
                if await file_inputs.count() > 0:
                    await file_inputs.first.set_input_files(resume_path)
                    result.filled.append("resume")
            except Exception:
                result.review.append("Could not attach resume automatically")

        textareas = page.locator("textarea")
        for i in range(await textareas.count()):
            textarea = textareas.nth(i)
            if not (await textarea.input_value()).strip():
                label = await textarea.get_attribute("aria-label") or await textarea.get_attribute("name") or f"textarea[{i}]"
                result.review.append(f"Needs answer: {label}")

        if AUTO_SUBMIT and not result.review and not result.captcha_detected:
            submit = page.get_by_role("button", name="Submit", exact=False).first
            if await submit.count() > 0:
                await submit.click()
                result.submitted = True
        else:
            result.review.append("Submission intentionally paused; AUTO_SUBMIT is false")

        if not result.submitted:
            await page.screenshot(path="application-preview.png", full_page=True)
        await browser.close()
    return result
