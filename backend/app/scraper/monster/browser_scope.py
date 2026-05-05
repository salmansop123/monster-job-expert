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
    """Run manually once to capture cookies after any human interaction/CAPTCHA."""
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False, slow_mo=120)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.monster.com", wait_until="domcontentloaded")
        input("Solve any challenge in browser, then press Enter...")
        cookies = await context.cookies()
        COOKIE_FILE.write_text(json.dumps(cookies), encoding="utf-8")
        await browser.close()


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


@asynccontextmanager
async def monster_browser_context(playwright: Playwright, *, headless_override: bool | None = None):
    """Prefer persistent Chromium profile when `playwright_user_data_dir` is set."""
    ud_raw = (settings.playwright_user_data_dir or "").strip()
    storage_raw = (settings.playwright_storage_state_path or "").strip()
    ud_path = Path(ud_raw).resolve() if ud_raw else None
    browser: Browser | None = None
    ctx: Any = None

    base_opts = {
        "viewport": {"width": 1280, "height": 900},
        "user_agent": _DEFAULT_UA,
    }

    try:
        if ud_path:
            ud_path.mkdir(parents=True, exist_ok=True)
            ctx = await playwright.chromium.launch_persistent_context(
                user_data_dir=str(ud_path),
                headless=settings.playwright_headless if headless_override is None else headless_override,
                slow_mo=settings.playwright_slow_mo_ms,
                **base_opts,
            )
            await load_session_cookies(ctx)
        else:
            browser = await playwright.chromium.launch(
                headless=settings.playwright_headless if headless_override is None else headless_override,
                slow_mo=settings.playwright_slow_mo_ms,
            )
            ctx_opts = dict(base_opts)
            sto = Path(storage_raw) if storage_raw else None
            if sto and sto.is_file():
                ctx_opts["storage_state"] = str(sto.resolve())
            ctx = await browser.new_context(**ctx_opts)
            await load_session_cookies(ctx)

        yield ctx

    finally:
        if ctx is not None:
            try:
                if (
                    ud_path
                    and settings.playwright_save_storage_state
                    and settings.playwright_storage_state_path
                ):
                    out = Path(settings.playwright_storage_state_path)
                    out.parent.mkdir(parents=True, exist_ok=True)
                    await ctx.storage_state(path=str(out.resolve()))
                await ctx.close()
            except Exception:
                pass
        if browser:
            try:
                await browser.close()
            except Exception:
                pass
