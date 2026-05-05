from __future__ import annotations

import asyncio
import hashlib
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Page, async_playwright

from app.config import settings
from app.schemas.job import SearchRequest
from app.scraper import selectors as sel
from app.scraper.monster.browser_scope import (
    light_human_gesture,
    monster_browser_context,
    random_human_delay_seconds,
)
from app.scraper.monster.urls import build_search_url

logger = logging.getLogger("monster.scraper")
DEBUG_DIR = Path("debug_snapshots")
DEBUG_DIR.mkdir(exist_ok=True)


class MonsterBlockedError(RuntimeError):
    """Raised when Monster anti-bot / restricted page is detected."""

    def __init__(self, message: str, partial_results: list | None = None) -> None:
        super().__init__(message)
        self.partial_results = partial_results or []


@dataclass
class ListingScrapeResult:
    rows: list[dict[str, str | None]]
    blocked_or_restricted: bool


@dataclass
class ScraperHealth:
    last_run_at: str = ""
    last_query: str = ""
    cards_found: int = 0
    selector_used: str = ""
    blocked: bool = False
    error: str = ""


scraper_health = ScraperHealth()


@dataclass
class SelectorMatch:
    cards: list[Any]
    selector: str | None


def _looks_like_job_url(href: str) -> bool:
    if not href:
        return False
    lower = href.lower()
    if "monster.com" not in lower and not lower.startswith("/"):
        return False
    bad = (
        "/jobs/search",
        "/profile",
        "/login",
        "/employer",
        "/promo",
        "/salary",
        "/career-advice",
    )
    if any(b in lower for b in bad):
        return False
    good = ("/job-openings/", "/jobs/job", "/jobview", "/job/", "job-opening", "jobid=")
    return any(g in lower for g in good)


def _abs_url(base: str, href: str | None) -> str | None:
    if not href:
        return None
    return urljoin(base, href)


async def _legacy_scrape_pause() -> None:
    lo = settings.scrape_delay_min_ms / 1000
    hi = settings.scrape_delay_max_ms / 1000
    if hi < lo:
        lo, hi = hi, lo
    await asyncio.sleep(random.uniform(lo, hi))


async def _first_inner_text(page: Page, scope, candidates: list[str]) -> str | None:
    for css in candidates:
        try:
            el = await scope.query_selector(css)
            if el:
                text = (await el.inner_text()).strip()
                if text:
                    return text
        except Exception:
            continue
    return None


async def _first_href(page: Page, scope, candidates: list[str]) -> str | None:
    for css in candidates:
        try:
            el = await scope.query_selector(css)
            if el:
                href = await el.get_attribute("href")
                if href:
                    return href
        except Exception:
            continue
    return None


async def _collect_cards(page: Page) -> SelectorMatch:
    for css in sel.LISTING_JOB_CARD_SELECTORS:
        try:
            cards = await page.query_selector_all(css)
            if len(cards) >= 1:
                logger.info("Matched %s job cards with selector: %s", len(cards), css)
                return SelectorMatch(cards=cards, selector=css)
        except Exception:
            continue
    return SelectorMatch(cards=[], selector=None)


async def _page_looks_blocked(page: Page) -> bool:
    try:
        if page.is_closed():
            return False
        body = await page.inner_text("body")
    except Exception:
        return False
    lower = body.lower()
    blocked_markers = (
        "access is temporarily restricted",
        "we detected unusual activity",
        "automated (bot) activity",
    )
    return any(marker in lower for marker in blocked_markers)


async def _visual_debug_scroll(page: Page) -> None:
    if settings.playwright_headless or not settings.playwright_visual_scroll_debug:
        return

    async def _wheel(dx: float, dy: float) -> bool:
        if page.is_closed():
            return False
        try:
            await page.mouse.wheel(dx, dy)
        except Exception:
            return False
        return True

    for _ in range(8):
        if not await _wheel(0, 1200):
            return
        await asyncio.sleep(0.8)
    if not await _wheel(0, -10_000):
        return
    await asyncio.sleep(1.0)


async def save_debug_snapshot(page: Page, query: str, reason: str) -> tuple[str, str]:
    slug = hashlib.md5(query.encode()).hexdigest()[:8]
    ts = int(time.time())
    html_path = DEBUG_DIR / f"{ts}_{slug}__{reason}.html"
    img_path = DEBUG_DIR / f"{ts}_{slug}__{reason}.png"
    html_path.write_text(await page.content(), encoding="utf-8")
    await page.screenshot(path=str(img_path), full_page=True)
    return str(html_path), str(img_path)


async def _scrape_listing_jobs_once(
    criteria: SearchRequest,
    *,
    headless_override: bool | None = None,
) -> tuple[ListingScrapeResult, str | None]:
    """
    Monster SERP scrape — limited pages/jobs when using default ingest-oriented settings,
    randomized pacing, graceful degradation on failures.
    """
    url = build_search_url(criteria)
    cap = min(criteria.limit, settings.max_jobs_per_search, settings.ingest_max_jobs)
    max_pages = max(1, min(8, settings.ingest_max_pages))
    results: list[dict[str, str | None]] = []
    blocked_hit = False
    selector_used: str | None = None

    async with async_playwright() as p:
        async with monster_browser_context(p, headless_override=headless_override) as context:
            try:
                page = await context.new_page()
            except Exception:
                return ListingScrapeResult([], False), None
            page.set_default_timeout(45_000)

            try:
                try:
                    await page.goto(url, wait_until="domcontentloaded")
                except Exception:
                    await random_human_delay_seconds()
                    try:
                        await page.goto(url, wait_until="domcontentloaded")
                    except Exception:
                        return ListingScrapeResult([], False), None

                await random_human_delay_seconds()
                try:
                    await page.wait_for_timeout(int(settings.post_nav_wait_ms))
                except Exception:
                    pass
                await light_human_gesture(page)

                if await _page_looks_blocked(page):
                    return ListingScrapeResult([], True)

                for sel_try in [
                    "main",
                    "[data-testid='JobSearch']",
                    "body",
                ]:
                    try:
                        await page.wait_for_selector(sel_try, timeout=10_000)
                        break
                    except Exception:
                        continue

                await _legacy_scrape_pause()
                await random_human_delay_seconds()

                await _visual_debug_scroll(page)

                seen_urls: set[str] = set()
                page_num = 0
                while len(results) < cap and page_num < max_pages:
                    page_num += 1
                    try:
                        matched = await _extract_from_current_page(page, results, seen_urls, cap)
                        if matched and not selector_used:
                            selector_used = matched
                    except Exception:
                        pass

                    await light_human_gesture(page)
                    await random_human_delay_seconds()

                    if len(results) >= cap:
                        break

                    if page_num >= max_pages:
                        break

                    try:
                        next_btn = await page.query_selector(
                            "a[aria-label='Next'], button[aria-label='Next'], a.pagination-next, li.next a"
                        )
                        if next_btn:
                            await next_btn.click()
                            await page.wait_for_load_state("domcontentloaded")
                            try:
                                await page.wait_for_timeout(int(settings.post_nav_wait_ms))
                            except Exception:
                                pass
                            if await _page_looks_blocked(page):
                                blocked_hit = True
                                break
                            await random_human_delay_seconds()
                        else:
                            break
                    except Exception:
                        break

                if not results:
                    html_f, img_f = await save_debug_snapshot(
                        page,
                        query=f"{criteria.title}|{criteria.location}",
                        reason="zero_results",
                    )
                    logger.warning("Zero jobs extracted. See %s and %s", img_f, html_f)

            finally:
                try:
                    await page.close()
                except Exception:
                    pass

    return ListingScrapeResult(results[:cap], blocked_hit), selector_used


async def scrape_listing_jobs(criteria: SearchRequest) -> ListingScrapeResult:
    try:
        res, selector_used = await _scrape_listing_jobs_once(criteria, headless_override=None)
        # Headed fallback for local diagnosis when headless extraction is empty.
        if not res.rows and settings.playwright_headless:
            logger.warning("Headless returned zero jobs — retrying headed fallback")
            res2, selector2 = await _scrape_listing_jobs_once(criteria, headless_override=False)
            if res2.rows:
                res = res2
                selector_used = selector2
        scraper_health.last_run_at = datetime.utcnow().isoformat()
        scraper_health.last_query = f"{criteria.title} | {criteria.location}"
        scraper_health.cards_found = len(res.rows)
        scraper_health.selector_used = selector_used or ""
        scraper_health.blocked = bool(res.blocked_or_restricted)
        scraper_health.error = "blocked_or_empty" if (res.blocked_or_restricted and not res.rows) else ""
        return res
    except Exception as exc:  # noqa: BLE001
        scraper_health.last_run_at = datetime.utcnow().isoformat()
        scraper_health.last_query = f"{criteria.title} | {criteria.location}"
        scraper_health.cards_found = 0
        scraper_health.selector_used = ""
        scraper_health.blocked = False
        scraper_health.error = str(exc)[:500]
        raise


async def _extract_from_current_page(
    page: Page,
    results: list[dict[str, str | None]],
    seen_urls: set[str],
    cap: int,
) -> str | None:
    base = page.url
    cards_match = await _collect_cards(page)
    cards = cards_match.cards

    if cards:
        for card in cards:
            if len(results) >= cap:
                break
            try:
                link = await _first_href(page, card, sel.LISTING_LINK_SELECTORS)
                full = _abs_url(base, link)
                if not full or not _looks_like_job_url(full):
                    continue
                norm = full.split("?")[0].rstrip("/")
                if norm in seen_urls:
                    continue
                seen_urls.add(norm)

                title = await _first_inner_text(page, card, sel.LISTING_TITLE_SELECTORS)
                company = await _first_inner_text(page, card, sel.LISTING_COMPANY_SELECTORS)
                location = await _first_inner_text(page, card, sel.LISTING_LOCATION_SELECTORS)
                salary = await _first_inner_text(page, card, sel.LISTING_SALARY_SELECTORS)
                posted = await _first_inner_text(page, card, sel.LISTING_POSTED_SELECTORS)

                results.append(
                    {
                        "title": title or None,
                        "company": company or None,
                        "location_display": location or None,
                        "salary_text": salary or None,
                        "posted_at_text": posted or None,
                        "job_url": full,
                    }
                )
            except Exception:
                continue

    if len(results) >= cap:
        return cards_match.selector

    try:
        anchors = await page.query_selector_all("a[href]")
    except Exception:
        return cards_match.selector

    for a in anchors:
        if len(results) >= cap:
            break
        try:
            href = await a.get_attribute("href")
            full = _abs_url(base, href)
            if not full or not _looks_like_job_url(full):
                continue
            norm = full.split("?")[0].rstrip("/")
            if norm in seen_urls:
                continue
            seen_urls.add(norm)
            title = (await a.inner_text()).strip() or None
            results.append(
                {
                    "title": title,
                    "company": None,
                    "location_display": None,
                    "salary_text": None,
                    "posted_at_text": None,
                    "job_url": full,
                }
            )
        except Exception:
            continue
    return cards_match.selector


async def scrape_job_detail(job_url: str) -> dict[str, str | None]:
    return await scrape_job_detail_safe(job_url)


async def scrape_job_detail_safe(job_url: str) -> dict[str, str | None]:
    title: str | None = None
    description: str | None = None

    if not job_url:
        return {"title": None, "description_text": None}

    async with async_playwright() as p:
        async with monster_browser_context(p) as context:
            page = None
            try:
                try:
                    page = await context.new_page()
                    page.set_default_timeout(45_000)
                    await page.goto(job_url, wait_until="domcontentloaded")
                    try:
                        await page.wait_for_timeout(int(settings.post_nav_wait_ms))
                    except Exception:
                        pass
                    await random_human_delay_seconds()

                    if await _page_looks_blocked(page):
                        return {"title": None, "description_text": None}

                    for css in sel.DETAIL_TITLE_SELECTORS:
                        try:
                            el = await page.query_selector(css)
                            if el:
                                t = (await el.inner_text()).strip()
                                if t and len(t) < 500:
                                    title = t
                                    break
                        except Exception:
                            continue

                    for css in sel.DETAIL_CONTAINER_SELECTORS:
                        try:
                            el = await page.query_selector(css)
                            if el:
                                text = (await el.inner_text()).strip()
                                if text and len(text) > 80:
                                    description = text[: settings.max_description_chars]
                                    break
                        except Exception:
                            continue

                    if not description:
                        try:
                            body = await page.query_selector("body")
                            if body:
                                description = (
                                    await body.inner_text()
                                ).strip()[: settings.max_description_chars]
                        except Exception:
                            description = None
                except Exception:
                    pass
            finally:
                if page:
                    try:
                        await page.close()
                    except Exception:
                        pass

    return {"title": title, "description_text": description}
