from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
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
        "[data-testid='jobDescription']",
        "[data-automation='jobDescription']",
        "section[class*='description']",
        ".job-description",
        "[class*='jobDescription']",
        "[class*='JobDescription']",
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


async def extract_longest_inner_text(page: Page, selectors: list[str]) -> str:
    """Prefer the longest non-empty match (Monster often has multiple partial nodes)."""
    best = ""
    for selector in selectors:
        try:
            elements = await page.query_selector_all(selector)
            for el in elements:
                text = (await el.inner_text()).strip()
                if len(text) > len(best):
                    best = text
        except Exception:
            continue
    return best


_BAD_WEBSITE_SNIPPETS = (
    "onetrust",
    "privacyportal",
    "cookie",
    "consent.",
    "trustarc",
    "privacy-choice",
    "doubleclick",
    "googleadservices",
    "googlesyndication",
    "facebook.com",
    "twitter.com",
    "t.co/",
    "instagram.com",
    "youtube.com",
    "tiktok.com",
    "addthis.com",
    "linkedin.com/sharing",
    "monster.com",
    "indeed.com",
    "glassdoor.com",
    "apps.apple.com",
    "itunes.apple.com",
    "play.google.com",
    "appstore",
    "mailto:",
    "tel:",
)


def _is_plausible_company_website(href: str | None) -> bool:
    if not href:
        return False
    h = href.strip().lower()
    if not h.startswith(("http://", "https://")):
        return False
    return not any(b in h for b in _BAD_WEBSITE_SNIPPETS)


def _normalize_website_href(raw: str) -> str:
    s = raw.strip()
    if not s:
        return ""
    lower = s.lower()
    if lower.startswith(("http://", "https://")):
        return s
    if lower.startswith("//"):
        return "https:" + s
    if " " in s:
        return s
    return "https://" + s.lstrip("/")


def _sanitize_website_field(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return ""
    norm = _normalize_website_href(str(raw).strip())
    if norm and _is_plausible_company_website(norm):
        return norm
    return ""


def _clean_job_description_text(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # Drop boilerplate header lines Monster injects outside the JD body.
    drop_patterns = (
        r"(?mi)^skip to content\s*$",
        r"(?mi)^sign up\s*$",
        r"(?mi)^log in\s*$",
        r"(?mi)^find jobs\s*$",
        r"(?mi)^salary tools\s*$",
        r"(?mi)^career advice\s*$",
        r"(?mi)^free resume templates\s*$",
        r"(?mi)^employers\s*/\s*post job\s*$",
        r"(?mi)^back to results\s*$",
    )
    for pat in drop_patterns:
        t = re.sub(pat, "", t)
    t = re.sub(r"[ \t]+\n", "\n", t)
    return re.sub(r"\n{3,}", "\n\n", t).strip()


def _pick_longer_description(*candidates: str) -> str:
    best = ""
    for c in candidates:
        s = _clean_job_description_text(c)
        if len(s) > len(best):
            best = s
    return best


def _get_fact_fuzzy(facts: dict[str, str], *needles: str) -> str:
    """Match dl labels when Monster uses wording like \"Type of Hire\" instead of \"Job Type\"."""
    n = [x.lower().strip() for x in needles if x.strip()]
    if not n:
        return ""
    for dk, dv in facts.items():
        dkl = dk.lower().replace(" ", "")
        if not dv or not str(dv).strip() or str(dv).strip() == "—":
            continue
        if all(nd.replace(" ", "") in dkl for nd in n):
            return str(dv).strip()
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

    # Keep this intentionally gentle in CDP mode to avoid aggressive visible scrolling.
    for _ in range(2):
        if not await _wheel(0, 300):
            return
        await asyncio.sleep(1.2)
    if not await _wheel(0, -250):
        return
    await asyncio.sleep(0.8)


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
                description_snippet = await _first_inner_text(
                    page,
                    card,
                    [
                        "[data-testid='job-snippet']",
                        "[class*='snippet']",
                        "[class*='description']",
                        "p",
                    ],
                )

                results.append(
                    {
                        "title": title or None,
                        "company": company or None,
                        "location_display": location or None,
                        "salary_text": salary or None,
                        "posted_at_text": posted or None,
                        "description_text": description_snippet or None,
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
                    "description_text": None,
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

            desc_selectors = DETAIL_SELECTORS["description"]

            mapped = {
                "location": await extract_with_fallback(page, DETAIL_SELECTORS["location"]),
                "job_type": (
                    await extract_with_fallback(page, DETAIL_SELECTORS["job_type"])
                    or get_fact(facts, "job type", "jobtype")
                    or _get_fact_fuzzy(facts, "type", "hire")
                    or _get_fact_fuzzy(facts, "employment")
                ),
                "industry": await extract_with_fallback(page, DETAIL_SELECTORS["industry"]) or get_fact(facts, "industry"),
                "salary": await extract_with_fallback(page, DETAIL_SELECTORS["salary"]) or get_fact(
                    facts,
                    "salary",
                    "salary range",
                ),
                "company_size": await extract_with_fallback(page, DETAIL_SELECTORS["company_size"]) or get_fact(
                    facts,
                    "company size",
                ),
                "year_founded": await extract_with_fallback(page, DETAIL_SELECTORS["year_founded"]) or get_fact(
                    facts,
                    "year founded",
                ),
                "website": _sanitize_website_field(
                    await _extract_href_with_fallback(page, DETAIL_SELECTORS["website"]) or get_fact(facts, "website")
                ),
                "about_company": await extract_with_fallback(page, DETAIL_SELECTORS["company_about"]),
                "description": await extract_longest_inner_text(page, desc_selectors),
            }
            fallback_structured = await page.evaluate(
                """
                () => {
                    const out = {
                        job_type: "",
                        industry: "",
                        salary: "",
                        company_size: "",
                        year_founded: "",
                        website: "",
                        description: "",
                    };
                    const bodyText = (document.body?.innerText || "").replace(/\\s+/g, " ");
                    const pick = (regex) => {
                        const m = bodyText.match(regex);
                        return m && m[1] ? String(m[1]).trim() : "";
                    };
                    const pullAfterLabel = (label) => {
                        const re = new RegExp(
                            label + "\\\\s*[:\\\\-]?\\\\s*(.*?)\\\\s*(?=(?:Location|Job\\\\s*Type|Type\\\\s*of\\\\s*Hire|Industry|Salary|Company\\\\s*Size|Year\\\\s*Founded|Website|About\\\\s*Company|Description|Responsibilities|Requirements)\\\\b|$)",
                            "i"
                        );
                        const m = bodyText.match(re);
                        return m && m[1] ? String(m[1]).trim() : "";
                    };
                    out.job_type =
                        pullAfterLabel("Type of Hire") ||
                        pullAfterLabel("Job Type") ||
                        pick(/Type of Hire\\s*[:-]+\\s*([^\\n|]+)/i) ||
                        pick(/Job Type\\s*[:-]+\\s*([^\\n|]+)/i);
                    out.industry =
                        pullAfterLabel("Industry") ||
                        pick(/Industry\\s*[:-]+\\s*([^\\n|]+)/i) ||
                        pick(/Industry\\s+([^\\n|]+)/i) ||
                        (bodyText.match(/Other\\s*\\/\\s*Not\\s*Classified/i) ? "Other/Not Classified" : "");
                    out.salary =
                        pullAfterLabel("Salary") ||
                        pick(/Salary\\s*[:-]+\\s*([^\\n|]+)/i) ||
                        (() => {
                            const range = bodyText.match(
                                /(\\$[0-9,]+(?:\\.[0-9]+)?\\s*(?:–|-|to)\\s*\\$[0-9,]+(?:\\.[0-9]+)?(?:\\s*(?:per\\s*year|\\/\\s*year|year|yr))?)/i
                            );
                            if (range && range[1]) return String(range[1]).trim();
                            const single = bodyText.match(
                                /(\\$[0-9,]+(?:\\.[0-9]+)?(?:\\s*(?:per\\s*year|\\/\\s*year|year|yr))?)/i
                            );
                            if (single && single[1]) return String(single[1]).trim();
                            return "";
                        })();
                    out.company_size =
                        pullAfterLabel("Company Size") ||
                        pick(/Company Size\\s*[:-]+\\s*([^\\n|]+)/i);
                    out.year_founded =
                        pullAfterLabel("Year Founded") ||
                        pick(/Year Founded\\s*[:-]+\\s*([^\\n|]+)/i);

                    const badHost = (u) => {
                        try {
                            const h = new URL(u).hostname.toLowerCase();
                            return /onetrust|privacy|cookie|consent|trustarc|privacyportal|doubleclick|googleadservices|googlesyndication|facebook|twitter\\.com|t\\.co|instagram|youtube|tiktok|monster\\.com|indeed\\.com|glassdoor|apps\\.apple\\.com|itunes\\.apple\\.com|play\\.google\\.com|appstore/i.test(h);
                        } catch {
                            return true;
                        }
                    };
                    const anchors = Array.from(document.querySelectorAll('a[href^="http"]')).map((a) => ({
                        href: a.href,
                        t: (a.innerText || "").trim(),
                    }));
                    const clean = anchors.filter((x) => !badHost(x.href) && !/monster\\.com/i.test(x.href));
                    const labeled = clean.find((x) => /^(website|www\\.)/i.test(x.t) || /visit\\s+(our\\s+)?(website|company)/i.test(x.t) || /company\\s+site/i.test(x.t));
                    out.website = (labeled || clean[0] || {}).href || "";
                    if (!out.website) {
                        const bodyUrl = bodyText.match(/https?:\\/\\/[^\\s)]+/i);
                        out.website = bodyUrl && bodyUrl[0] ? String(bodyUrl[0]).trim() : "";
                    }

                    const descSels = [
                        "[data-testid='jobDetailDescription']",
                        "[data-testid='jobDescription']",
                        "[data-automation='jobDescription']",
                        "section[class*='description']",
                        "[class*='jobDescription']",
                        "article",
                        "main",
                    ];
                    let bestD = "";
                    descSels.forEach((s) => {
                        document.querySelectorAll(s).forEach((el) => {
                            const t = (el.innerText || "").trim();
                            if (t.length > bestD.length) bestD = t;
                        });
                    });

                    const heading = Array.from(document.querySelectorAll("h1,h2,h3,h4,strong,span,div,p"))
                        .find((el) => /^description\\s*$/i.test((el.textContent || "").trim()));
                    if (heading) {
                        const container = heading.closest("section,article,main,div") || heading.parentElement;
                        if (container) {
                            let text = (container.textContent || "").replace(/\\s+/g, " ").trim();
                            text = text.replace(/^Description\\s*/i, "").trim();
                            if (text.length > bestD.length) bestD = text;
                        }
                    }
                    out.description = bestD;
                    return out;
                }
                """
            )
            if not mapped.get("job_type"):
                mapped["job_type"] = (fallback_structured.get("job_type") or "").strip()
            if not mapped.get("industry"):
                mapped["industry"] = (fallback_structured.get("industry") or "").strip()
            if not mapped.get("salary"):
                mapped["salary"] = (fallback_structured.get("salary") or "").strip()
            if not mapped.get("company_size"):
                mapped["company_size"] = (fallback_structured.get("company_size") or "").strip()
            if not mapped.get("year_founded"):
                mapped["year_founded"] = (fallback_structured.get("year_founded") or "").strip()

            fb_desc = (fallback_structured.get("description") or "").strip()
            if not mapped.get("description"):
                for fallback_selector in sel.DETAIL_CONTAINER_SELECTORS + ["article", "[role='main']", "body"]:
                    try:
                        fallback_text = await extract_longest_inner_text(page, [fallback_selector])
                    except Exception:
                        fallback_text = ""
                    cleaned = (fallback_text or "").strip()
                    if len(cleaned) >= 120:
                        mapped["description"] = cleaned
                        logger.info("Fallback description extracted via selector: %s", fallback_selector)
                        break

            merged = _pick_longer_description((mapped.get("description") or ""), fb_desc)
            noisy_markers = ["Skip to content", "Find Jobs", "Salary Tools", "Career Advice", "Resume Builder"]
            if any(m in merged for m in noisy_markers) and len(fb_desc) > len(merged) * 0.5:
                merged = _pick_longer_description(merged, fb_desc)
            mapped["description"] = merged

            merged_site = mapped.get("website") or ""
            if not merged_site.strip():
                merged_site = _sanitize_website_field((fallback_structured.get("website") or "").strip())
            else:
                merged_site = _sanitize_website_field(merged_site)
            mapped["website"] = merged_site
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
