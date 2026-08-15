from __future__ import annotations

from collections.abc import Awaitable, Callable

from playwright.async_api import Locator, Page


async def retry_async(
    operation: Callable[[], Awaitable[None]],
    *,
    attempts: int = 3,
    delay_ms: int = 500,
) -> Exception | None:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            await operation()
            return None
        except Exception as exc:  # Browser/network errors vary by ATS.
            last_error = exc
            if attempt + 1 < attempts:
                # Callers use Playwright pages, so avoid pulling in asyncio just
                # for a short backoff.
                pass
    return last_error


async def goto_with_retry(
    page: Page,
    url: str,
    *,
    attempts: int = 3,
    timeout_ms: int = 60_000,
) -> Exception | None:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return None
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await page.wait_for_timeout(600 * (attempt + 1))
    return last_error


async def click_with_retry(
    page: Page,
    locator: Locator,
    *,
    attempts: int = 2,
) -> Exception | None:
    last_error: Exception | None = None
    for attempt in range(max(1, attempts)):
        try:
            await locator.click()
            return None
        except Exception as exc:
            last_error = exc
            if attempt + 1 < attempts:
                await page.wait_for_timeout(400 * (attempt + 1))
    return last_error
