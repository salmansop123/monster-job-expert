from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

from playwright.async_api import Page

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
SELECTOR_LOG_FILE = DEBUG_DIR / "selector_log.jsonl"

DETAIL_SELECTORS: dict[str, list[str]] = {
    "location": [
        "[data-testid='jobDetailLocation']",
        ".job-detail-location",
        "[class*='location']",
        "span[itemprop='addressLocality']",
    ],
    "job_type": [
        "[data-testid='jobDetailJobType']",
        ".job-type",
        "[class*='jobType']",
        "[class*='job-type']",
    ],
    "industry": [
        "[data-testid='jobDetailIndustry']",
        "[class*='industry']",
        ".industry",
    ],
    "salary": [
        "[data-testid='jobDetailSalary']",
        "[class*='salary']",
        ".salary",
    ],
    "company_size": [
        "[data-testid='companySize']",
        "[class*='companySize']",
        "[class*='company-size']",
    ],
    "year_founded": [
        "[data-testid='yearFounded']",
        "[class*='yearFounded']",
        "[class*='year-founded']",
    ],
    "website": [
        "[data-testid='companyWebsite']",
        "a[class*='website']",
        "a[class*='companyWebsite']",
    ],
    "description": [
        "[data-testid='jobDetailDescription']",
        ".job-description",
        "[class*='jobDescription']",
        "#JobDescription",
        "[class*='description-content']",
    ],
    "company_about": [
        "[data-testid='companyAbout']",
        "[class*='companyAbout']",
        "[class*='about-company']",
    ],
}


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


async def extract_with_fallback(page: Page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if not el:
                continue
            text = await el.inner_text()
            if text and text.strip():
                return text.strip()
        except Exception:
            continue
    return ""


async def _extract_href_with_fallback(page: Page, selectors: list[str]) -> str:
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if not el:
                continue
            href = await el.get_attribute("href")
            if href and href.strip():
                return href.strip()
        except Exception:
            continue
    return ""


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
    if not settings.playwright_visual_scroll_debug:
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


def _append_selector_history(
    *,
    query: str,
    selector: str | None,
    cards_found: int,
    blocked: bool,
) -> None:
    payload = {
        "ts": datetime.utcnow().isoformat(),
        "query": query,
        "selector": selector or "",
        "cards_found": int(cards_found),
        "blocked": bool(blocked),
    }
    try:
        with SELECTOR_LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=True) + "\n")
    except Exception as exc:
        logger.warning("Failed writing selector history: %s", exc)


def load_selector_history(limit: int = 50) -> list[dict[str, object]]:
    if not SELECTOR_LOG_FILE.exists():
        return []
    out: list[dict[str, object]] = []
    try:
        with SELECTOR_LOG_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(json.loads(line))
                except Exception:
                    continue
    except Exception:
        return []
    return out[-limit:]


async def _scrape_listing_jobs_once(
    criteria: SearchRequest,
) -> tuple[ListingScrapeResult, str | None]:
    """
    Monster SERP scrape — limited pages/jobs when using default ingest-oriented settings,
    randomized pacing, graceful degradation on failures.
    """
    url = build_search_url(criteria)
    logger.info("Browser mode: %s", "CDP" if settings.use_cdp_chrome else "disabled")
    requested = max(1, int(criteria.limit))
    cap = min(requested, settings.max_jobs_per_search)
    max_pages = max(1, min(8, settings.ingest_max_pages))
    results: list[dict[str, str | None]] = []
    blocked_hit = False
    selector_used: str | None = None

    async with monster_browser_context() as (_browser, _context, page):
        try:
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

                try:
                    await page.wait_for_selector(
                        "div[data-testid='JobCard'], div.job-card, [class*='JobCard']",
                        timeout=8000,
                    )
                except Exception:
                    await asyncio.sleep(5)
                await light_human_gesture(page)

                if await _page_looks_blocked(page):
                    return ListingScrapeResult([], True), None

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
            except Exception:
                return ListingScrapeResult([], False), selector_used
        except Exception:
            return ListingScrapeResult([], False), selector_used

    return ListingScrapeResult(results[:cap], blocked_hit), selector_used


async def scrape_listing_jobs(criteria: SearchRequest) -> ListingScrapeResult:
    try:
        res, selector_used = await _scrape_listing_jobs_once(criteria)
        scraper_health.last_run_at = datetime.utcnow().isoformat()
        scraper_health.last_query = f"{criteria.title} | {criteria.location}"
        scraper_health.cards_found = len(res.rows)
        scraper_health.selector_used = selector_used or ""
        scraper_health.blocked = bool(res.blocked_or_restricted)
        scraper_health.error = "blocked_or_empty" if (res.blocked_or_restricted and not res.rows) else ""
        _append_selector_history(
            query=scraper_health.last_query,
            selector=selector_used,
            cards_found=len(res.rows),
            blocked=bool(res.blocked_or_restricted),
        )
        return res
    except Exception as exc:  # noqa: BLE001
        scraper_health.last_run_at = datetime.utcnow().isoformat()
        scraper_health.last_query = f"{criteria.title} | {criteria.location}"
        scraper_health.cards_found = 0
        scraper_health.selector_used = ""
        scraper_health.blocked = False
        scraper_health.error = str(exc)[:500]
        _append_selector_history(
            query=scraper_health.last_query,
            selector=None,
            cards_found=0,
            blocked=False,
        )
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
        cards = cards[:cap]
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
    mapped: dict[str, str] = {}
    if not job_url:
        return {"title": None, "description_text": None}

    async with monster_browser_context() as (_browser, _context, page):
        try:
            page.set_default_timeout(45_000)
            await page.goto(job_url, wait_until="domcontentloaded", timeout=30_000)
            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass
            try:
                await page.wait_for_selector(
                    ", ".join(DETAIL_SELECTORS["description"]),
                    timeout=10_000,
                )
            except Exception:
                await save_debug_snapshot(page, job_url, "detail_no_description")
                logger.warning("Description not found on detail page: %s", job_url)
            await asyncio.sleep(2)
            try:
                await page.wait_for_timeout(int(settings.post_nav_wait_ms))
            except Exception:
                pass
            await random_human_delay_seconds()

            if await _page_looks_blocked(page):
                return {"title": None, "description_text": None}

            title = await _first_inner_text(page, page, sel.DETAIL_TITLE_SELECTORS)
            facts = await page.evaluate(
                """
                () => {
                    const result = {};
                    document.querySelectorAll('dl').forEach((dl) => {
                        const dts = dl.querySelectorAll('dt');
                        const dds = dl.querySelectorAll('dd');
                        dts.forEach((dt, i) => {
                            const label = (dt.innerText || '').trim().toLowerCase();
                            const value = (dds[i]?.innerText || '').trim();
                            if (label && value) result[label] = value;
                        });
                    });
                    return result;
                }
                """
            )

            def get_fact(d: dict[str, str], *keys: str) -> str:
                for k in keys:
                    for dk, dv in d.items():
                        if dk.lower().strip() == k.lower() and dv and dv.strip() and dv.strip() != "—":
                            return dv.strip()
                return ""

            mapped = {
                "location": await extract_with_fallback(page, DETAIL_SELECTORS["location"]),
                "job_type": await extract_with_fallback(page, DETAIL_SELECTORS["job_type"]) or get_fact(facts, "job type", "jobtype"),
                "industry": await extract_with_fallback(page, DETAIL_SELECTORS["industry"]) or get_fact(facts, "industry"),
                "salary": await extract_with_fallback(page, DETAIL_SELECTORS["salary"]) or get_fact(facts, "salary", "salary range"),
                "company_size": await extract_with_fallback(page, DETAIL_SELECTORS["company_size"]) or get_fact(facts, "company size"),
                "year_founded": await extract_with_fallback(page, DETAIL_SELECTORS["year_founded"]) or get_fact(facts, "year founded"),
                "website": await _extract_href_with_fallback(page, DETAIL_SELECTORS["website"]) or get_fact(facts, "website"),
                "about_company": await extract_with_fallback(page, DETAIL_SELECTORS["company_about"]),
                "description": await extract_with_fallback(page, DETAIL_SELECTORS["description"]),
            }
            for field_name, value in mapped.items():
                if value:
                    logger.info("Extracted %s from detail: %s", field_name, value[:80])
                else:
                    logger.warning("Could not extract %s from %s", field_name, job_url)
            description = (mapped["description"] or "")[: settings.max_description_chars]
        except Exception:
            pass

    return {
        "title": title,
        "description_text": description,
        "location": mapped.get("location"),
        "job_type": mapped.get("job_type"),
        "industry": mapped.get("industry"),
        "salary": mapped.get("salary"),
        "company_size": mapped.get("company_size"),
        "year_founded": mapped.get("year_founded"),
        "website": mapped.get("website"),
        "about_company": mapped.get("about_company"),
    }


def map_detail_to_job(raw: dict[str, str]) -> dict[str, str]:
    return {
        "location": raw.get("location", ""),
        "job_type": raw.get("job_type", ""),
        "industry": raw.get("industry", ""),
        "salary": raw.get("salary", ""),
        "company_size": raw.get("company_size", ""),
        "year_founded": raw.get("year_founded", ""),
        "website": raw.get("website", ""),
        "description": raw.get("description", ""),
        "about_company": raw.get("company_about", ""),
    }


async def test_selector_on_url(selector: str, url: str) -> dict[str, object]:
    selector = (selector or "").strip()
    if not selector:
        raise ValueError("selector is required")
    if not (url or "").strip():
        raise ValueError("url is required")
    if not url.startswith("https://www.monster.com/jobs"):
        raise ValueError("url must start with https://www.monster.com/jobs")
    async with monster_browser_context() as (_browser, _context, page):
        page.set_default_timeout(45_000)
        await page.goto(url, wait_until="domcontentloaded")
        try:
            await page.wait_for_selector(
                "div[data-testid='JobCard'], div.job-card, [class*='JobCard']",
                timeout=8000,
            )
        except Exception:
            await asyncio.sleep(5)
        await page.wait_for_timeout(4000)
        matched = len(await page.query_selector_all(selector))
        html_f, _ = await save_debug_snapshot(page, query=f"test|{selector}|{url}", reason="selector_test")
        page_title = await page.title()
        return {"matched": matched, "page_title": page_title, "snapshot_saved": html_f}


async def discover_detail_selectors(url: str) -> dict[str, object]:
    if not (url or "").startswith("https://www.monster.com/job"):
        raise ValueError("url must be a Monster job detail URL")
    async with monster_browser_context() as (_browser, _context, page):
        page.set_default_timeout(45_000)
        await page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        await page.wait_for_timeout(4000)
        elements = await page.evaluate(
            """
            () => {
                const out = [];
                document.querySelectorAll('[data-testid]').forEach((el) => {
                    const text = (el.innerText || '').trim();
                    if (text && text.length < 500) {
                        out.push({
                            selector: `[data-testid="${el.getAttribute('data-testid')}"]`,
                            text: text.slice(0, 200),
                            tag: (el.tagName || '').toLowerCase(),
                        });
                    }
                });
                const keywords = [
                    'location', 'industry', 'company', 'size',
                    'founded', 'website', 'description', 'about',
                    'jobtype', 'job-type', 'salary', 'benefit'
                ];
                document.querySelectorAll('*').forEach((el) => {
                    const cls = (el.className || '').toString().toLowerCase();
                    const id = (el.id || '').toLowerCase();
                    const text = (el.innerText || '').trim();
                    if (!text || text.length > 500 || text.length < 2) return;
                    keywords.forEach((kw) => {
                        if (cls.includes(kw) || id.includes(kw)) {
                            const firstClass = ((el.className || '').toString().split(' ')[0] || '').trim();
                            out.push({
                                selector: el.id ? `#${el.id}` : (firstClass ? `.${firstClass}` : el.tagName.toLowerCase()),
                                text: text.slice(0, 200),
                                tag: (el.tagName || '').toLowerCase(),
                                matched_keyword: kw,
                            });
                        }
                    });
                });
                return out;
            }
            """
        )
        title = await page.title()
        return {"url": url, "page_title": title, "elements_found": len(elements), "elements": elements}
