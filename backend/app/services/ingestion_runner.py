from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select

from app.ai.enrichment import enrich_job_record
from app.config import settings
from app.db.models import FeedJob, JobStored, QueryFeed, ScrapeLog
from app.db.session import AsyncSessionLocal
from app.schemas.job import JobEnrichment, JobRecord, SearchRequest
from app.scraper.monster import augment_title_for_setting
from app.scraper.monster.engine import scrape_job_detail_safe
from app.services.feed_keys import query_feed_fingerprint
from app.services.relevance_core import combined_relevance
from app.sources.monster_source import MonsterJobSource, combine_with_secondary_if_configured

_logger = logging.getLogger("monster.ingest")

monster_source = MonsterJobSource()
_feed_locks: dict[str, asyncio.Lock] = {}


def feed_ingest_lock(fp: str) -> asyncio.Lock:
    if fp not in _feed_locks:
        _feed_locks[fp] = asyncio.Lock()
    return _feed_locks[fp]


async def scrape_log_write(
    fingerprint: str, event: str, message: str, jobs_count: int | None = None
) -> None:
    try:
        async with AsyncSessionLocal() as session:
            session.add(
                ScrapeLog(
                    fingerprint=fingerprint,
                    event=event,
                    message=message[:4000],
                    jobs_count=jobs_count,
                )
            )
            await session.commit()
    except Exception as exc:
        _logger.warning("scrape_log_write failed: %s", exc)


async def ensure_query_feed_row(title: str, location: str) -> str:
    fp = query_feed_fingerprint(title, location)
    async with AsyncSessionLocal() as session:
        row = await session.get(QueryFeed, fp)
        if row is None:
            session.add(
                QueryFeed(
                    fingerprint=fp,
                    title=title.strip(),
                    location=(location or "").strip(),
                    ingest_status="pending",
                )
            )
        else:
            row.title = title.strip()
            row.location = (location or "").strip()
        await session.commit()
    return fp


def _criteria_for_feed_row(title: str, location: str) -> SearchRequest:
    crit = SearchRequest(
        title=title.strip(),
        location=(location or "").strip(),
        limit=min(settings.ingest_max_jobs, settings.max_jobs_per_search),
    )
    return augment_title_for_setting(crit)


async def _count_feed_jobs(session, fingerprint: str) -> int:
    q = await session.scalar(
        select(func.count()).select_from(FeedJob).where(FeedJob.fingerprint == fingerprint)
    )
    return int(q or 0)


async def persist_listing_into_feed_jobs(
    fingerprint: str,
    outcome,
    ingest_criteria: SearchRequest,
    *,
    use_openai: bool,
) -> None:
    """Build rows in-memory, then replace feed_jobs in one transaction."""
    staged: list[FeedJob] = []

    for idx, row in enumerate(outcome.jobs):
        jr = JobRecord(
            title=row.get("title"),
            company=row.get("company"),
            location_display=row.get("location_display"),
            salary_text=row.get("salary_text"),
            posted_at_text=row.get("posted_at_text"),
            job_url=row.get("job_url"),
            description_text=row.get("description_text"),
        )
        detail: dict[str, str | None] = {}
        if jr.job_url:
            detail = await scrape_job_detail_safe(jr.job_url)
        if detail.get("description_text"):
            jr.description_text = detail["description_text"]
        if detail.get("title") and not jr.title:
            jr.title = detail["title"]

        enrichment = None
        prompt_tok = completion_tok = None
        model_name = None
        if (
            use_openai
            and settings.enable_openai
            and settings.openai_api_key.strip()
            and jr.description_text
        ):
            try:
                enrichment_result, meta = await asyncio.to_thread(enrich_job_record, jr)
                enrichment = enrichment_result
                prompt_tok = meta.get("prompt_tokens")
                completion_tok = meta.get("completion_tokens")
                model_name = settings.openai_model
            except Exception as exc:  # noqa: BLE001
                enrichment = JobEnrichment(
                    summary="OpenAI enrichment failed for this posting.",
                    confidence_notes=str(exc)[:500],
                )

        jr.enrichment = enrichment
        rel = combined_relevance(ingest_criteria, jr)

        staged.append(
            FeedJob(
                fingerprint=fingerprint,
                sort_order=idx,
                title=jr.title,
                company=jr.company,
                location_display=jr.location_display,
                salary_text=jr.salary_text,
                posted_at_text=jr.posted_at_text,
                job_url=jr.job_url,
                source="monster",
                relevance_score=rel,
                description_text=jr.description_text,
                enrichment_json=enrichment.model_dump_json() if enrichment else None,
                openai_model=model_name,
                openai_prompt_tokens=prompt_tok,
                openai_completion_tokens=completion_tok,
            )
        )

    async with AsyncSessionLocal() as session:
        await session.execute(delete(FeedJob).where(FeedJob.fingerprint == fingerprint))
        session.add_all(staged)
        await session.commit()


async def ingest_feed(
    fingerprint: str,
    title: str,
    location: str,
    *,
    force: bool = False,
    enrich_with_openai: bool = False,
) -> None:
    """Acquires feed lock — rate-limited when cached rows exist and window active."""
    lock = feed_ingest_lock(fingerprint)

    async with lock:
        now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            feed = await session.get(QueryFeed, fingerprint)
            if feed is None:
                session.add(
                    QueryFeed(
                        fingerprint=fingerprint,
                        title=title.strip(),
                        location=(location or "").strip(),
                        ingest_status="pending",
                    )
                )
                await session.commit()
                feed = await session.get(QueryFeed, fingerprint)

            nj = await _count_feed_jobs(session, fingerprint)
            rate_limited = bool(
                feed
                and feed.next_scrape_allowed_at
                and now < feed.next_scrape_allowed_at
                and nj > 0
                and not force
            )
            if rate_limited:
                await scrape_log_write(
                    fingerprint,
                    "rate_skip",
                    "Skipped scrape: within ingest_rate_limit window with existing rows.",
                    jobs_count=nj,
                )
                return

            feed.is_processing = True  # type: ignore[union-attr]
            await session.commit()

        _logger.info("ingest_feed start fp=%s jobs_before=%s", fingerprint, nj)
        await scrape_log_write(fingerprint, "ingest_start", "Ingestion started", jobs_count=nj)

        crit = _criteria_for_feed_row(title, location)
        outcome = None
        try:
            outcome = await monster_source.fetch_jobs_with_retries(crit)
            outcome = await combine_with_secondary_if_configured(outcome, crit)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("ingest_feed fetch failed: %s", exc)
            await scrape_log_write(fingerprint, "error", str(exc)[:2000], jobs_count=None)
            outcome = None

        now2 = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            feed = await session.get(QueryFeed, fingerprint)
            assert feed is not None

            if outcome is None:
                feed.ingest_status = "failed"
                feed.ingest_message = "Unexpected ingestion error."
                feed.is_processing = False
                await session.commit()
                await scrape_log_write(fingerprint, "failed", "Unexpected ingestion error", jobs_count=0)
                return

            await scrape_log_write(
                fingerprint,
                "fetch_done",
                outcome.message or outcome.status,
                jobs_count=len(outcome.jobs),
            )

            if outcome.jobs:
                try:
                    await persist_listing_into_feed_jobs(
                        fingerprint,
                        outcome,
                        crit,
                        use_openai=enrich_with_openai,
                    )
                except Exception as exc:  # noqa: BLE001
                    _logger.exception("persist_listing failed: %s", exc)
                    feed.ingest_status = "partial_success"
                    feed.ingest_message = f"Fetched listings but storing rows failed: {exc}"[:2000]
                    feed.is_processing = False
                    await session.commit()
                    await scrape_log_write(fingerprint, "error", feed.ingest_message or "", jobs_count=None)
                    return

                feed.ingest_status = outcome.status if outcome.status in {"success", "partial_success"} else "success"
                feed.ingest_message = outcome.message
                feed.last_updated_at = now2
                feed.next_scrape_allowed_at = now2 + timedelta(seconds=settings.ingest_rate_limit_seconds)
                feed.is_processing = False
                await session.commit()
                _logger.info("ingest_feed done fp=%s rows=%s", fingerprint, len(outcome.jobs))
                return

            if outcome.status in {"blocked", "failed"}:
                feed.ingest_status = outcome.status
                feed.ingest_message = outcome.message
                feed.is_processing = False
                await session.commit()
                await scrape_log_write(
                    fingerprint,
                    "blocked" if outcome.status == "blocked" else "failed",
                    outcome.message or outcome.status,
                    jobs_count=0,
                )
                return

            await session.execute(delete(FeedJob).where(FeedJob.fingerprint == fingerprint))
            feed.ingest_status = "success"
            feed.ingest_message = outcome.message
            feed.last_updated_at = now2
            feed.next_scrape_allowed_at = now2 + timedelta(seconds=settings.ingest_rate_limit_seconds)
            feed.is_processing = False
            await session.commit()


async def scheduled_refresh_all_feeds() -> None:
    """Scheduler entrypoint — refresh every known query subject to rate limits inside ingest_feed."""
    try:
        async with AsyncSessionLocal() as session:
            rows = (await session.execute(select(QueryFeed.fingerprint, QueryFeed.title, QueryFeed.location))).all()
    except Exception as exc:
        _logger.warning("scheduled_refresh_all_feeds load failed: %s", exc)
        return

    for fp, title, location in rows:
        try:
            await ingest_feed(fp, title, location, force=False, enrich_with_openai=False)
        except Exception as exc:
            _logger.warning("scheduled refresh failed fp=%s: %s", fp, exc)


def schedule_background_ingest(fingerprint: str, title: str, location: str) -> None:
    async def runner() -> None:
        try:
            await ingest_feed(
                fingerprint,
                title,
                location,
                force=False,
                enrich_with_openai=False,
            )
        except Exception as exc:
            _logger.warning("background ingest failed: %s", exc)

    asyncio.create_task(runner())


async def copy_feed_to_search_run(search_id: int, fingerprint: str, criteria: SearchRequest) -> int:
    """Returns number of jobs copied."""
    async with AsyncSessionLocal() as session:
        stmt = (
            select(FeedJob)
            .where(FeedJob.fingerprint == fingerprint)
            .order_by(FeedJob.sort_order.asc(), FeedJob.id.asc())
        )
        rows = (await session.execute(stmt)).scalars().all()

        cap = min(criteria.limit, len(rows))
        n = 0
        for fj in rows[:cap]:
            enrichment = None
            if fj.enrichment_json:
                try:
                    enrichment = JobEnrichment.model_validate_json(fj.enrichment_json)
                except Exception:
                    enrichment = None
            jr = JobRecord(
                title=fj.title,
                company=fj.company,
                location_display=fj.location_display,
                salary_text=fj.salary_text,
                posted_at_text=fj.posted_at_text,
                job_url=fj.job_url,
                description_text=fj.description_text,
                enrichment=enrichment,
            )
            rel = combined_relevance(criteria, jr)
            session.add(
                JobStored(
                    search_id=search_id,
                    title=fj.title,
                    company=fj.company,
                    location_display=fj.location_display,
                    salary_text=fj.salary_text,
                    posted_at_text=fj.posted_at_text,
                    job_url=fj.job_url,
                    source=fj.source or "monster",
                    relevance_score=rel,
                    description_text=fj.description_text,
                    enrichment_json=fj.enrichment_json,
                    openai_model=fj.openai_model,
                    openai_prompt_tokens=fj.openai_prompt_tokens,
                    openai_completion_tokens=fj.openai_completion_tokens,
                )
            )
            n += 1
        await session.commit()
        return n


def build_result_metadata(
    *,
    response_status: str,
    ingest_status: str | None,
    feed_last_updated: datetime | None,
    message: str | None,
) -> str:
    payload = {
        "response_status": response_status,
        "ingest_status": ingest_status,
        "feed_last_updated": feed_last_updated.isoformat() if feed_last_updated else None,
        "message": message,
    }
    return json.dumps(payload)
