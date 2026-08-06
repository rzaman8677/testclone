from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright

from app.answers import AnswerDecision, answer_question
from app.config import AUTO_SUBMIT
from app.models import Profile
from app.resume import ResumeError, load_resume_text, require_resume_pdf


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    generated_answers: list[dict] = field(default_factory=list)
    captcha_detected: bool = False
    resume_uploaded: bool = False
    submitted: bool = False


async def _captcha_present(page: Page) -> bool:
    body = (await page.locator("body").inner_text()).lower()
    markers = ("captcha", "verify you are human", "i'm not a robot", "recaptcha")
    return any(marker in body for marker in markers)


async def _question_for(control: Locator) -> str:
    try:
        return (
            await control.evaluate(
                """el => {
                    const parts = [];
                    if (el.labels) {
                        for (const label of el.labels) {
                            const t = (label.innerText || label.textContent || '').trim();
                            if (t) parts.push(t);
                        }
                    }
                    const fieldset = el.closest('fieldset');
                    if (fieldset) {
                        const legend = fieldset.querySelector('legend');
                        if (legend && legend.innerText.trim()) parts.unshift(legend.innerText.trim());
                    }
                    for (const key of ['aria-label', 'placeholder', 'name', 'id']) {
                        const v = el.getAttribute(key);
                        if (v) parts.push(v);
                    }
                    return [...new Set(parts)].join(' | ');
                }"""
            )
        ).strip()
    except Exception:
        return ""


async def _radio_label(radio: Locator) -> str:
    try:
        return (
            await radio.evaluate(
                """el => el.labels ? Array.from(el.labels).map(x => (x.innerText || x.textContent || '').trim()).join(' ') : ''"""
            )
        ).strip()
    except Exception:
        return ""


def _truthy(answer: str | bool) -> bool | None:
    if isinstance(answer, bool):
        return answer
    value = str(answer).strip().lower()
    if value in {"yes", "true", "1", "y"}:
        return True
    if value in {"no", "false", "0", "n"}:
        return False
    return None


async def _set_control_value(page: Page, control: Locator, answer: str | bool) -> bool:
    try:
        tag = await control.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await control.get_attribute("type") or "").lower()
        text = "Yes" if answer is True else "No" if answer is False else str(answer)

        if tag == "select":
            try:
                await control.select_option(label=text)
                return True
            except Exception:
                options = await control.locator("option").all()
                target = text.strip().lower()
                for option in options:
                    label = (await option.inner_text()).strip()
                    value = (await option.get_attribute("value") or "").strip()
                    if target == label.lower() or target == value.lower() or target in label.lower():
                        await control.select_option(value=value)
                        return True
                return False

        if input_type == "radio":
            name = await control.get_attribute("name")
            group = page.locator('input[type="radio"]')
            if name:
                group = page.locator(f'input[type="radio"][name={json.dumps(name)}]')
            target = text.strip().lower()
            for i in range(await group.count()):
                option = group.nth(i)
                label = (await _radio_label(option)).lower()
                value = (await option.get_attribute("value") or "").lower()
                if target == label or target == value or target in label:
                    await option.check()
                    return True
            return False

        if input_type == "checkbox":
            truth = _truthy(answer)
            if truth is None:
                return False
            if truth:
                await control.check()
            else:
                await control.uncheck()
            return True

        if tag == "textarea" or input_type in {
            "",
            "text",
            "email",
            "tel",
            "url",
            "number",
            "search",
            "date",
        }:
            await control.fill(text)
            return True
    except Exception:
        return False
    return False


async def _has_value(control: Locator) -> bool:
    try:
        tag = await control.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await control.get_attribute("type") or "").lower()
        if input_type in {"radio", "checkbox"}:
            return await control.is_checked()
        if tag == "select":
            value = (await control.input_value()).strip()
            return bool(value)
        return bool((await control.input_value()).strip())
    except Exception:
        return False


async def _upload_resume(page: Page, resume_path: Path) -> bool:
    uploads = page.locator('input[type="file"]')
    count = await uploads.count()
    uploaded = False
    for i in range(count):
        upload = uploads.nth(i)
        question = (await _question_for(upload)).lower()
        accept = (await upload.get_attribute("accept") or "").lower()
        # Avoid putting the resume into a separate cover-letter/transcript slot.
        looks_like_resume = any(word in question for word in ("resume", "résumé", "cv"))
        if looks_like_resume or (count == 1 and (not accept or "pdf" in accept)):
            try:
                await upload.set_input_files(str(resume_path))
                uploaded = True
            except Exception:
                continue
    return uploaded


async def fill_application(
    url: str,
    profile: Profile,
    job_context: str = "",
) -> FillResult:
    result = FillResult()

    try:
        resume_path = require_resume_pdf()
        resume_text = load_resume_text()
    except ResumeError as exc:
        result.review.append(str(exc))
        return result

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

        result.resume_uploaded = await _upload_resume(page, resume_path)
        if result.resume_uploaded:
            result.filled.append("resume.pdf")
        else:
            result.review.append("Required resume PDF could not be attached on this application page")

        controls = page.locator(
            'input:not([type="hidden"]):not([type="file"]):not([type="submit"]):not([type="button"]), textarea, select'
        )
        processed_radio_groups: set[str] = set()

        for i in range(await controls.count()):
            control = controls.nth(i)
            try:
                if not await control.is_visible() or not await control.is_enabled():
                    continue
            except Exception:
                continue

            input_type = (await control.get_attribute("type") or "").lower()
            if input_type == "radio":
                group_name = await control.get_attribute("name") or f"radio-{i}"
                if group_name in processed_radio_groups:
                    continue
                processed_radio_groups.add(group_name)

            if await _has_value(control):
                continue

            question = await _question_for(control)
            if not question:
                continue

            decision: AnswerDecision = await answer_question(
                question=question,
                profile=profile,
                resume_text=resume_text,
                job_context=job_context,
            )

            if decision.needs_review or decision.answer is None:
                result.review.append(f"Needs answer: {question} — {decision.reason}")
                continue

            if await _set_control_value(page, control, decision.answer):
                result.filled.append(question)
                result.generated_answers.append(
                    {
                        "question": question,
                        "answer": decision.answer,
                        "source": decision.source,
                        "confidence": decision.confidence,
                    }
                )
            else:
                result.review.append(f"Could not select/fill answer for: {question}")

        if AUTO_SUBMIT and result.resume_uploaded and not result.review and not result.captcha_detected:
            submit = page.get_by_role("button", name="Submit", exact=False).first
            if await submit.count() > 0:
                await submit.click()
                result.submitted = True
            else:
                result.review.append("Could not find the final Submit button")
        elif not AUTO_SUBMIT:
            result.review.append("Submission intentionally paused; AUTO_SUBMIT is false")

        if not result.submitted:
            await page.screenshot(path="application-preview.png", full_page=True)
        await browser.close()
    return result
