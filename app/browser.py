from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright

from app.answers import AnswerDecision, answer_question
from app.config import AUTO_SUBMIT, MAX_APPLICATION_STEPS
from app.models import Profile
from app.navigation import (
    find_navigation_action,
    is_required,
    page_fingerprint,
    visible_validation_errors,
    wait_for_step_change,
)
from app.resume import ResumeError, load_resume_text, require_resume_pdf


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    blocking_review: list[str] = field(default_factory=list)
    generated_answers: list[dict] = field(default_factory=list)
    navigation_log: list[dict] = field(default_factory=list)
    pages_visited: int = 0
    final_url: str = ""
    captcha_detected: bool = False
    resume_uploaded: bool = False
    submitted: bool = False


async def _captcha_present(page: Page) -> bool:
    body = (await page.locator("body").inner_text()).lower()
    markers = ("captcha", "verify you are human", "i'm not a robot", "recaptcha", "hcaptcha")
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
                    let node = el.parentElement;
                    for (let depth = 0; node && depth < 3; depth++, node = node.parentElement) {
                        const candidate = node.querySelector('label, [data-automation-id*=label], [class*=label]');
                        if (candidate) {
                            const t = (candidate.innerText || candidate.textContent || '').trim();
                            if (t && t.length < 500) parts.push(t);
                        }
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
        if input_type == "radio":
            name = await control.get_attribute("name")
            if name:
                page = control.page
                return await page.locator(f'input[type="radio"][name={json.dumps(name)}]:checked').count() > 0
            return await control.is_checked()
        if input_type == "checkbox":
            return await control.is_checked()
        if tag == "select":
            value = (await control.input_value()).strip()
            return bool(value)
        return bool((await control.input_value()).strip())
    except Exception:
        return False


async def _upload_resume_on_step(page: Page, resume_path: Path) -> bool:
    uploads = page.locator('input[type="file"]')
    count = await uploads.count()
    uploaded = False
    for i in range(count):
        upload = uploads.nth(i)
        try:
            if not await upload.is_enabled():
                continue
        except Exception:
            continue
        question = (await _question_for(upload)).lower()
        accept = (await upload.get_attribute("accept") or "").lower()
        looks_like_resume = any(word in question for word in ("resume", "résumé", "cv", "curriculum vitae"))
        looks_like_other_document = any(
            word in question for word in ("cover letter", "transcript", "portfolio", "writing sample", "other document")
        )
        if looks_like_other_document and not looks_like_resume:
            continue
        if looks_like_resume or (count == 1 and (not accept or "pdf" in accept)):
            try:
                await upload.set_input_files(str(resume_path))
                uploaded = True
            except Exception:
                continue
    return uploaded


async def _record_answer(
    result: FillResult,
    question: str,
    decision: AnswerDecision,
) -> None:
    result.filled.append(question)
    result.generated_answers.append(
        {
            "question": question,
            "answer": decision.answer,
            "source": decision.source,
            "confidence": decision.confidence,
        }
    )


async def _handle_unanswered(
    result: FillResult,
    question: str,
    reason: str,
    required: bool,
) -> None:
    message = f"Needs answer: {question} — {reason}"
    if required:
        if message not in result.blocking_review:
            result.blocking_review.append(message)
    elif message not in result.review:
        result.review.append(message)


async def _fill_native_controls(
    page: Page,
    profile: Profile,
    resume_text: str,
    job_context: str,
    result: FillResult,
) -> None:
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

        required = await is_required(control)
        decision = await answer_question(
            question=question,
            profile=profile,
            resume_text=resume_text,
            job_context=job_context,
        )

        if decision.needs_review or decision.answer is None:
            await _handle_unanswered(result, question, decision.reason, required)
            continue

        if await _set_control_value(page, control, decision.answer):
            await _record_answer(result, question, decision)
        else:
            await _handle_unanswered(result, question, "Could not select/fill the verified answer.", required)


async def _fill_custom_comboboxes(
    page: Page,
    profile: Profile,
    resume_text: str,
    job_context: str,
    result: FillResult,
) -> None:
    combos = page.locator('[role="combobox"]')
    for i in range(await combos.count()):
        combo = combos.nth(i)
        try:
            if not await combo.is_visible() or not await combo.is_enabled():
                continue
            tag = await combo.evaluate("el => el.tagName.toLowerCase()")
            if tag in {"input", "select"} and await _has_value(combo):
                continue
        except Exception:
            continue

        question = await _question_for(combo)
        if not question:
            continue
        required = await is_required(combo)
        decision = await answer_question(question, profile, resume_text, job_context)
        if decision.needs_review or decision.answer is None:
            await _handle_unanswered(result, question, decision.reason, required)
            continue

        answer = str(decision.answer)
        try:
            await combo.click()
            await page.wait_for_timeout(150)
            option = page.get_by_role("option", name=answer, exact=True).first
            if await option.count() == 0:
                option = page.get_by_role("option", name=answer, exact=False).first
            if await option.count() == 0:
                option = page.get_by_text(answer, exact=True).first
            if await option.count() > 0 and await option.is_visible():
                await option.click()
                await _record_answer(result, question, decision)
            else:
                await _handle_unanswered(result, question, "Could not find a matching dropdown option.", required)
        except Exception:
            await _handle_unanswered(result, question, "Could not operate this custom dropdown.", required)


async def _fill_current_step(
    page: Page,
    profile: Profile,
    resume_path: Path,
    resume_text: str,
    job_context: str,
    result: FillResult,
) -> None:
    if await _upload_resume_on_step(page, resume_path):
        if not result.resume_uploaded:
            result.filled.append("resume.pdf")
        result.resume_uploaded = True

    await _fill_native_controls(page, profile, resume_text, job_context, result)
    await _fill_custom_comboboxes(page, profile, resume_text, job_context, result)


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
        result.blocking_review.append(str(exc))
        return result

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto(url, wait_until="domcontentloaded", timeout=60_000)

        seen_fingerprints: dict[str, int] = {}

        for step in range(1, MAX_APPLICATION_STEPS + 1):
            result.pages_visited = step
            result.final_url = page.url

            if await _captcha_present(page):
                result.captcha_detected = True
                result.blocking_review.append("CAPTCHA/human verification requires manual completion")
                break

            fingerprint = await page_fingerprint(page)
            seen_fingerprints[fingerprint] = seen_fingerprints.get(fingerprint, 0) + 1
            if seen_fingerprints[fingerprint] > 2:
                result.blocking_review.append("Application navigation loop detected; manual review required")
                break

            before_blocking = len(result.blocking_review)
            await _fill_current_step(page, profile, resume_path, resume_text, job_context, result)

            errors = await visible_validation_errors(page)
            if errors:
                for error in errors:
                    message = f"Validation: {error}"
                    if message not in result.review:
                        result.review.append(message)

            new_blocking = result.blocking_review[before_blocking:]
            if new_blocking:
                result.navigation_log.append(
                    {"step": step, "url": page.url, "action": "review", "reason": "required unanswered fields"}
                )
                break

            action = await find_navigation_action(page)
            if action is None or action.locator is None:
                result.blocking_review.append("Could not identify a safe Next/Continue/Review/Submit action on this layout")
                result.navigation_log.append(
                    {"step": step, "url": page.url, "action": "review", "reason": "no navigation action"}
                )
                break

            result.navigation_log.append(
                {"step": step, "url": page.url, "action": action.kind, "label": action.label}
            )

            if action.kind == "submit":
                if not result.resume_uploaded:
                    result.blocking_review.append("Reached final submission without confirming a resume PDF upload")
                    break
                if not AUTO_SUBMIT:
                    result.review.append("Reached final submission; AUTO_SUBMIT is false")
                    break

                before_submit = await page_fingerprint(page)
                await action.locator.click()
                await wait_for_step_change(page, before_submit, timeout_ms=8_000)
                submit_errors = await visible_validation_errors(page)
                if submit_errors:
                    for error in submit_errors:
                        result.blocking_review.append(f"Submit validation: {error}")
                    break
                result.submitted = True
                result.final_url = page.url
                break

            before_navigation = await page_fingerprint(page)
            try:
                await action.locator.click()
            except Exception as exc:
                result.blocking_review.append(f"Could not click {action.label!r}: {exc}")
                break

            changed = await wait_for_step_change(page, before_navigation)
            result.final_url = page.url
            if not changed:
                errors = await visible_validation_errors(page)
                if errors:
                    for error in errors:
                        result.blocking_review.append(f"Validation prevented navigation: {error}")
                else:
                    result.blocking_review.append(
                        f"Clicked {action.label!r}, but the application did not advance to a new step"
                    )
                break
        else:
            result.blocking_review.append(
                f"Stopped after {MAX_APPLICATION_STEPS} application steps to prevent an automation loop"
            )

        if not result.submitted:
            try:
                await page.screenshot(path="application-preview.png", full_page=True)
            except Exception:
                pass
        await browser.close()
    return result
