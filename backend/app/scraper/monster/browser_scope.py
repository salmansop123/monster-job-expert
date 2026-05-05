from __future__ import annotations

import json
import random
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, Playwright, async_playwright

from app.config import settings


_DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
COOKIE_FILE = Path("monster_session.json")


async def random_human_delay_seconds() -> None:
    import asyncio

    lo = float(settings.ingest_human_delay_min_s)
    hi = float(settings.ingest_human_delay_max_s)
    if hi < lo:
        lo, hi = hi, lo
    await asyncio.sleep(random.uniform(lo, hi))


async def light_human_gesture(page) -> None:
    """Cheap movement + scroll; best-effort (page may close)."""
    try:
        if page.is_closed():
            return
        vp = page.viewport_size or {"width": 1280, "height": 900}
        w, h = int(vp["width"]), int(vp["height"])
        await page.mouse.move(random.randint(40, max(41, w - 60)), random.randint(40, max(41, h - 60)))
        await page.mouse.wheel(0, random.randint(120, 400))
    except Exception:
        pass


async def bootstrap_session() -> None:
    """Deprecated when using real Chrome via CDP."""
    return None


async def load_session_cookies(context) -> bool:
    if not COOKIE_FILE.exists():
        return False
    try:
        cookies = json.loads(COOKIE_FILE.read_text(encoding="utf-8"))
        if cookies:
            await context.add_cookies(cookies)
            return True
    except Exception:
        return False
    return False


async def get_browser(playwright: Playwright) -> Browser:
    """
    ONLY connects to real Chrome via CDP.
    Never launches a new browser — doing so causes immediate IP block.
    """
    if not settings.use_cdp_chrome:
        raise RuntimeError(
            "USE_CDP_CHROME must be set to true in .env. "
            "The scraper does not launch its own browser. "
            "See README for Chrome CDP setup instructions."
        )
    try:
        browser = await playwright.chromium.connect_over_cdp(settings.chrome_cdp_url)
        return browser
    except Exception as e:
        raise RuntimeError(
            f"Could not connect to Chrome at {settings.chrome_cdp_url}. "
            f"Make sure Chrome is running with: "
            f"google-chrome --remote-debugging-port=9222 "
            f"--user-data-dir=/tmp/chrome-monster-profile"
        ) from e


@asynccontextmanager
async def monster_browser_context():
    async with async_playwright() as playwright:
        browser = await get_browser(playwright)
        try:
            contexts = browser.contexts
            context = contexts[0] if contexts else await browser.new_context(
                user_agent=_DEFAULT_UA,
                viewport={"width": 1366, "height": 768},
            )

            page = await context.new_page()
            try:
                yield browser, context, page
            finally:
                await page.close()
        except Exception:
            raise
