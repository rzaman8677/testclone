from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from playwright.async_api import Locator, Page, async_playwright

from app.answers import AnswerDecision, answer_question
from app.ats import ATSKind, application_key as make_application_key, detect_ats
from app.audit import detect_closed_or_unavailable, detect_confirmation, final_audit
from app.config import (
    ARTIFACT_DIR,
    AUTO_RESUME_APPLICATIONS,
    AUTO_SUBMIT,
    MANUAL_HANDOFF_SECONDS,
    MAX_APPLICATION_STEPS,
)
from app.db import begin_application, checkpoint_application, get_application
from app.models import Profile
from app.navigation import (
    find_navigation_action,
    is_required,
    page_fingerprint,
    visible_validation_errors,
    wait_for_step_change,
)
from app.preflight import preflight_application
from app.resume import ResumeError, load_resume_text, require_resume_pdf
from app.session import new_context, save_context
from app.workday import detect_manual_gate, prepare_workday_step, repair_workday_structured_sections


@dataclass
class FillResult:
    filled: list[str] = field(default_factory=list)
    review: list[str] = field(default_factory=list)
    blocking_review: list[str] = field(default_factory=list)
    generated_answers: list[dict] = field(default_factory=list)
    navigation_log: list[dict] = field(default_factory=list)
    preflight: dict = field(default_factory=dict)
    pages_visited: int = 0
    final_url: str = ""
    ats: str = ""
    application_key: str = ""
    confirmation_text: str = ""
    captcha_detected: bool = False
    resume_uploaded: bool = False
    submitted: bool = False
    resumed_from_checkpoint: bool = False
    session_saved: bool = False


async def _captcha_present(page: Page) -> bool:
    try:
        body = (await page.locator("body").inner_text()).lower()
    except Exception:
        return False
    markers = ("captcha", "verify you are human", "i'm not a robot", "recaptcha", "hcaptcha")
    return any(marker in body for marker in markers)


async def _question_for(control: Locator) -> str:
    try:
        return (
            await control.evaluate(
                r"""el => {
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
                    const labelledBy = (el.getAttribute('aria-labelledby') || '').split(/\s+/).filter(Boolean);
                    for (const id of labelledBy) {
                        const node = document.getElementById(id);
                        if (node) {
                            const t = (node.innerText || node.textContent || '').trim();
                            if (t) parts.push(t);
                        }
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
    if value in {"yes", "true", "1", "y", "agree", "i agree"}:
        return True
    if value in {"no", "false", "0", "n", "disagree", "i disagree"}:
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
                    if target == label.lower() or target == value.lower() or (target and target in label.lower()):
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
                if target == label or target == value or (target and target in label):
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
            "month",
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


async def _native_choices(page: Page, control: Locator) -> list[str]:
    choices: list[str] = []
    try:
        tag = await control.evaluate("el => el.tagName.toLowerCase()")
        input_type = (await control.get_attribute("type") or "").lower()
        if tag == "select":
            options = control.locator("option")
            for i in range(await options.count()):
                option = options.nth(i)
                if await option.is_disabled():
                    continue
                label = (await option.inner_text()).strip()
                value = (await option.get_attribute("value") or "").strip()
                if label and (value or label.lower() not in {"select", "select one", "choose", "choose one", "--"}):
                    choices.append(label)
        elif input_type == "radio":
            name = await control.get_attribute("name")
            group = page.locator('input[type="radio"]')
            if name:
                group = page.locator(f'input[type="radio"][name={json.dumps(name)}]')
            for i in range(await group.count()):
                option = group.nth(i)
                label = (await _radio_label(option)).strip()
                value = (await option.get_attribute("value") or "").strip()
                choice = label or value
                if choice:
                    choices.append(choice)
    except Exception:
        return []
    return list(dict.fromkeys(choices))


async def _visible_role_options(page: Page) -> list[str]:
    choices: list[str] = []
    options = page.get_by_role("option")
    for i in range(min(await options.count(), 100)):
        option = options.nth(i)
        try:
            if not await option.is_visible():
                continue
            text = (await option.inner_text()).strip()
        except Exception:
            continue
        if text:
            choices.append(text)
    return list(dict.fromkeys(choices))


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

    if uploaded:
        return True

    # Some ATS widgets create the file input only after an Upload button is
    # clicked. Playwright's file-chooser API handles that without relying on a
    # brittle hidden-input selector.
    buttons = page.get_by_role(
        "button",
        name=re.compile(r"(upload|attach).*(resume|résumé|cv)|(resume|résumé|cv).*(upload|attach)", re.IGNORECASE),
    )
    for i in range(min(await buttons.count(), 5)):
        button = buttons.nth(i)
        try:
            if not await button.is_visible() or not await button.is_enabled():
                continue
            async with page.expect_file_chooser(timeout=3_000) as chooser_info:
                await button.click()
            chooser = await chooser_info.value
            await chooser.set_files(str(resume_path))
            return True
        except Exception:
            continue
    return False


async def _record_answer(result: FillResult, question: str, decision: AnswerDecision) -> None:
    result.filled.append(question)
    result.generated_answers.append(
        {
            "question": question,
            "answer": decision.answer,
            "source": decision.source,
            "confidence": decision.confidence,
        }
    )


async def _handle_unanswered(result: FillResult, question: str, reason: str, required: bool) -> None:
    message = f"Needs answer: {question} — {reason}"
    target = result.blocking_review if required else result.review
    if message not in target:
        target.append(message)


def _ambiguous_workday_history_field(question: str) -> bool:
    q = " ".join(question.lower().split())
    patterns = (
        "company",
        "employer",
        "job title",
        "position title",
        "start date",
        "end date",
    )
    return any(q == pattern or q.endswith("| " + pattern) or q.startswith(pattern + " |") for pattern in patterns)


async def _fill_native_controls(
    page: Page,
    profile: Profile,
    resume_text: str,
    job_context: str,
    result: FillResult,
    ats_kind: ATSKind,
) -> None:
    controls = page.locator(
        'input:not([type="hidden"]):not([type="file"]):not([type="submit"]):not([type="button"]):not([role="combobox"]), '
        'textarea, select:not([role="combobox"])'
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
        if ats_kind == ATSKind.WORKDAY and _ambiguous_workday_history_field(question):
            await _handle_unanswered(
                result,
                question,
                "Workday history field could not be mapped safely to a verified structured experience row.",
                required,
            )
            continue

        choices = await _native_choices(page, control)
        decision = await answer_question(
            question=question,
            profile=profile,
            resume_text=resume_text,
            job_context=job_context,
            answer_choices=choices,
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
    combos = page.locator('[role="combobox"], button[aria-haspopup="listbox"], input[aria-autocomplete="list"]')
    for i in range(await combos.count()):
        combo = combos.nth(i)
        try:
            if not await combo.is_visible() or not await combo.is_enabled() or await _has_value(combo):
                continue
        except Exception:
            continue

        question = await _question_for(combo)
        if not question:
            continue
        required = await is_required(combo)

        try:
            tag = await combo.evaluate("el => el.tagName.toLowerCase()")
            await combo.click()
            await page.wait_for_timeout(200)
            choices = await _visible_role_options(page)
            decision = await answer_question(
                question,
                profile,
                resume_text,
                job_context,
                answer_choices=choices,
            ) if choices else await answer_question(question, profile, resume_text, job_context)

            if decision.needs_review or decision.answer is None:
                await page.keyboard.press("Escape")
                await _handle_unanswered(result, question, decision.reason, required)
                continue

            answer = str(decision.answer)
            if not choices and tag == "input":
                await combo.fill(answer)
                await page.wait_for_timeout(400)
                choices = await _visible_role_options(page)

            option = page.get_by_role("option", name=answer, exact=True).first
            if await option.count() == 0:
                option = page.get_by_role("option", name=answer, exact=False).first
            if await option.count() == 0:
                option = page.get_by_text(answer, exact=True).first

            if await option.count() > 0 and await option.is_visible():
                await option.click()
                await _record_answer(result, question, decision)
            elif tag == "input" and not choices:
                await combo.press("Enter")
                if await _has_value(combo):
                    await _record_answer(result, question, decision)
                else:
                    await _handle_unanswered(result, question, "Could not confirm the typeahead selection.", required)
            else:
                await page.keyboard.press("Escape")
                await _handle_unanswered(result, question, "Could not find a matching dropdown option.", required)
        except Exception:
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            await _handle_unanswered(result, question, "Could not operate this custom dropdown.", required)


async def _fill_current_step(
    page: Page,
    profile: Profile,
    resume_path: Path,
    resume_text: str,
    job_context: str,
    result: FillResult,
    ats_kind: ATSKind,
) -> None:
    if ats_kind == ATSKind.WORKDAY:
        workday_actions = await repair_workday_structured_sections(page, profile)
        for detail in workday_actions:
            result.navigation_log.append({"step": result.pages_visited, "url": page.url, "action": "workday_repair", "detail": detail})

    if await _upload_resume_on_step(page, resume_path):
        if not result.resume_uploaded:
            result.filled.append("resume.pdf")
        result.resume_uploaded = True

    await _fill_native_controls(page, profile, resume_text, job_context, result, ats_kind)
    await _fill_custom_comboboxes(page, profile, resume_text, job_context, result)


async def _wait_for_human_if_configured(page: Page, reason: str, *, captcha: bool = False) -> bool:
    if MANUAL_HANDOFF_SECONDS <= 0:
        return False
    elapsed = 0
    while elapsed < MANUAL_HANDOFF_SECONDS:
        await page.wait_for_timeout(1_000)
        elapsed += 1
        still_blocked = await _captcha_present(page) if captcha else bool(await detect_manual_gate(page))
        if not still_blocked:
            return True
    return False


def _checkpoint_status(result: FillResult) -> str:
    if result.submitted:
        return "SUBMITTED"
    if result.confirmation_text:
        return "SUBMITTED"
    if result.blocking_review:
        if any("no longer" in item.lower() or "closed" in item.lower() for item in result.blocking_review):
            return "CLOSED"
        return "NEEDS_REVIEW"
    if any("AUTO_SUBMIT is false" in item for item in result.review):
        return "READY_TO_SUBMIT"
    return "IN_PROGRESS"


def _save_checkpoint(original_url: str, result: FillResult, step: int, fingerprint: str = "") -> None:
    checkpoint_application(
        original_url,
        current_url=result.final_url or original_url,
        status=_checkpoint_status(result),
        step_index=step,
        pages_visited=result.pages_visited,
        resume_uploaded=result.resume_uploaded,
        submitted=result.submitted,
        confirmation_text=result.confirmation_text,
        last_fingerprint=fingerprint,
        navigation_log=result.navigation_log,
        generated_answers=result.generated_answers,
        review=result.review,
        blocking_review=result.blocking_review,
    )


async def fill_application(url: str, profile: Profile, job_context: str = "") -> FillResult:
    result = FillResult()
    result.ats = detect_ats(url).value
    result.application_key = make_application_key(url)

    try:
        resume_path = require_resume_pdf()
        resume_text = load_resume_text()
    except ResumeError as exc:
        result.blocking_review.append(str(exc))
        return result

    preflight = await preflight_application(url)
    result.preflight = asdict(preflight)
    if preflight.live is False:
        result.blocking_review.append("Posting is no longer live according to the ATS public posting interface")
        begin_application(url, result.preflight)
        _save_checkpoint(url, result, 0)
        return result

    existing = get_application(url)
    if existing and (existing.get("submitted") or existing.get("status") == "SUBMITTED"):
        result.blocking_review.append("This job is already recorded as submitted; duplicate application blocked")
        result.submitted = True
        result.final_url = existing.get("current_url") or url
        result.confirmation_text = existing.get("confirmation_text") or ""
        return result
    if existing and existing.get("status") == "UNKNOWN_AFTER_SUBMIT":
        result.blocking_review.append("A previous run clicked Submit without a confirmed success page; verify manually before retrying")
        result.final_url = existing.get("current_url") or url
        return result

    record = begin_application(url, result.preflight)
    start_url = url
    step_offset = 0
    if AUTO_RESUME_APPLICATIONS and record.get("status") in {"IN_PROGRESS", "NEEDS_REVIEW", "READY_TO_SUBMIT"}:
        saved_url = str(record.get("current_url") or "")
        if saved_url.startswith(("https://", "http://")) and saved_url != url:
            start_url = saved_url
            result.resumed_from_checkpoint = True
        step_offset = int(record.get("step_index") or 0)
        result.resume_uploaded = bool(record.get("resume_uploaded"))
        result.navigation_log = list(record.get("navigation_log") or [])
        result.generated_answers = list(record.get("generated_answers") or [])
        result.review = list(record.get("review") or [])

    ats_kind = detect_ats(url)
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    screenshot_path = ARTIFACT_DIR / f"{result.application_key.replace(':', '-')}-preview.png"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await new_context(browser, url)
        page = await context.new_page()
        seen_fingerprints: dict[str, int] = {}
        last_step = step_offset

        try:
            await page.goto(start_url, wait_until="domcontentloaded", timeout=60_000)

            for run_step in range(1, MAX_APPLICATION_STEPS + 1):
                step = step_offset + run_step
                last_step = step
                result.pages_visited = max(result.pages_visited, step)
                result.final_url = page.url

                confirmed, confirmation_text = await detect_confirmation(page)
                if confirmed:
                    result.submitted = True
                    result.confirmation_text = confirmation_text
                    break

                closed_reason = await detect_closed_or_unavailable(page)
                if closed_reason:
                    result.blocking_review.append(f"Application page reports the role is unavailable: {closed_reason}")
                    break

                gate = await detect_manual_gate(page)
                if gate:
                    result.navigation_log.append({"step": step, "url": page.url, "action": "human_handoff", "reason": gate})
                    if not await _wait_for_human_if_configured(page, gate):
                        result.blocking_review.append(gate)
                        break

                if await _captcha_present(page):
                    result.captcha_detected = True
                    result.navigation_log.append({"step": step, "url": page.url, "action": "human_handoff", "reason": "captcha"})
                    if not await _wait_for_human_if_configured(page, "captcha", captcha=True):
                        result.blocking_review.append("CAPTCHA/human verification requires manual completion")
                        break
                    result.captcha_detected = False

                if ats_kind == ATSKind.WORKDAY:
                    for detail in await prepare_workday_step(page):
                        result.navigation_log.append({"step": step, "url": page.url, "action": "workday_prepare", "detail": detail})

                fingerprint = await page_fingerprint(page)
                seen_fingerprints[fingerprint] = seen_fingerprints.get(fingerprint, 0) + 1
                if seen_fingerprints[fingerprint] > 2:
                    result.blocking_review.append("Application navigation loop detected; manual review required")
                    break

                before_blocking = len(result.blocking_review)
                await _fill_current_step(page, profile, resume_path, resume_text, job_context, result, ats_kind)

                errors = await visible_validation_errors(page)
                for error in errors:
                    message = f"Validation: {error}"
                    if message not in result.review:
                        result.review.append(message)

                await save_context(context, page, url)
                result.session_saved = True
                result.final_url = page.url
                _save_checkpoint(url, result, step, fingerprint)

                if result.blocking_review[before_blocking:]:
                    result.navigation_log.append({"step": step, "url": page.url, "action": "review", "reason": "required unanswered fields"})
                    break

                action = await find_navigation_action(page)
                if action is None or action.locator is None:
                    confirmed, confirmation_text = await detect_confirmation(page)
                    if confirmed:
                        result.submitted = True
                        result.confirmation_text = confirmation_text
                        break
                    result.blocking_review.append("Could not identify a safe Next/Continue/Review/Submit action on this layout")
                    result.navigation_log.append({"step": step, "url": page.url, "action": "review", "reason": "no navigation action"})
                    break

                result.navigation_log.append({"step": step, "url": page.url, "action": action.kind, "label": action.label})

                if action.kind == "submit":
                    audit = await final_audit(
                        page,
                        resume_uploaded=result.resume_uploaded,
                        blocking_review=result.blocking_review,
                    )
                    if not audit.ok:
                        for issue in audit.issues:
                            if issue not in result.blocking_review:
                                result.blocking_review.append(issue)
                        break

                    if not AUTO_SUBMIT:
                        result.review.append("Reached final submission; AUTO_SUBMIT is false")
                        break

                    before_submit = await page_fingerprint(page)
                    await action.locator.click()
                    await wait_for_step_change(page, before_submit, timeout_ms=10_000)
                    submit_errors = await visible_validation_errors(page)
                    if submit_errors:
                        for error in submit_errors:
                            result.blocking_review.append(f"Submit validation: {error}")
                        break

                    confirmed, confirmation_text = await detect_confirmation(page)
                    result.final_url = page.url
                    if confirmed:
                        result.submitted = True
                        result.confirmation_text = confirmation_text
                    else:
                        result.blocking_review.append(
                            "Submit was clicked but no reliable confirmation page was detected; verify manually before any retry"
                        )
                        checkpoint_application(
                            url,
                            current_url=page.url,
                            status="UNKNOWN_AFTER_SUBMIT",
                            step_index=step,
                            pages_visited=result.pages_visited,
                            resume_uploaded=result.resume_uploaded,
                            submitted=False,
                            navigation_log=result.navigation_log,
                            generated_answers=result.generated_answers,
                            review=result.review,
                            blocking_review=result.blocking_review,
                        )
                    break

                before_navigation = await page_fingerprint(page)
                try:
                    await action.locator.click()
                except Exception as exc:
                    result.blocking_review.append(f"Could not click {action.label!r}: {exc}")
                    break

                changed = await wait_for_step_change(page, before_navigation)
                result.final_url = page.url
                await save_context(context, page, url)
                result.session_saved = True
                _save_checkpoint(url, result, step, before_navigation)
                if not changed:
                    errors = await visible_validation_errors(page)
                    if errors:
                        for error in errors:
                            result.blocking_review.append(f"Validation prevented navigation: {error}")
                    else:
                        result.blocking_review.append(f"Clicked {action.label!r}, but the application did not advance to a new step")
                    break
            else:
                result.blocking_review.append(
                    f"Stopped after {MAX_APPLICATION_STEPS} application steps to prevent an automation loop"
                )

        except Exception as exc:
            result.blocking_review.append(f"Browser/application failure: {exc}")
        finally:
            result.final_url = page.url or result.final_url or start_url
            try:
                await save_context(context, page, url)
                result.session_saved = True
            except Exception:
                pass
            if not result.submitted:
                try:
                    await page.screenshot(path=str(screenshot_path), full_page=True)
                except Exception:
                    pass
            _save_checkpoint(url, result, last_step)
            await browser.close()

    return result
