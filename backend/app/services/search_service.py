from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta

from sqlalchemy import func, select, update

from app.ai.enrichment import enrich_job_record
from app.config import settings
from app.db.models import JobStored, SearchRun
from app.db.session import AsyncSessionLocal
from app.schemas.job import JobEnrichment, JobListResponse, JobRecord, SearchRequest, SearchStatusResponse
from app.scraper.monster import augment_title_for_setting
from app.services.feed_keys import query_feed_fingerprint
from app.services.ingestion_runner import (
    build_result_metadata,
    copy_feed_to_search_run,
    ensure_query_feed_row,
    ingest_feed,
    invalidate_feed,
)
from app.services.relevance_core import combined_relevance


def criteria_fingerprint(criteria: SearchRequest) -> str:
    effective = augment_title_for_setting(criteria)
    blob = json.dumps(
        effective.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    )
    return hashlib.sha256(blob.encode()).hexdigest()


async def _count_jobs_for_feed(session, fingerprint: str) -> int:
    from app.db.models import FeedJob

    q = await session.scalar(
        select(func.count()).select_from(FeedJob).where(FeedJob.fingerprint == fingerprint)
    )
    return int(q or 0)


async def execute_search_background(
    search_id: int,
    criteria: SearchRequest,
    force_refresh: bool = True,
) -> None:
    """Resolve jobs from SQLite feed cache. Live Playwright ingestion runs in ingestion_runner only."""
    crit = augment_title_for_setting(criteria)
    fp_feed = query_feed_fingerprint(crit.title, crit.location)

    async with AsyncSessionLocal() as session:
        await session.execute(
            update(SearchRun)
            .where(SearchRun.id == search_id)
            .values(status="running", fingerprint=criteria_fingerprint(crit), updated_at=datetime.utcnow())
        )
        await session.commit()

    completion_message: str | None = None
    meta_json: str | None = None

    try:
        if not settings.enable_monster_playwright:
            raise RuntimeError(
                "Monster.com scraping is disabled (ENABLE_MONSTER_PLAYWRIGHT=false). "
                "Enable Playwright in .env to populate the shared job feed."
            )

        await ensure_query_feed_row(crit.title, crit.location)

        ttl = timedelta(seconds=settings.query_feed_cache_ttl_seconds)
        now = datetime.utcnow()

        async with AsyncSessionLocal() as session:
            from app.db.models import QueryFeed

            feed = await session.get(QueryFeed, fp_feed)
            nj = await _count_jobs_for_feed(session, fp_feed)

        fresh = (
            nj > 0
            and feed
            and feed.last_updated_at
            and (now - feed.last_updated_at) <= ttl
        )

        ingest_status_snap = getattr(feed, "ingest_status", None) if feed else None

        if force_refresh:
            await invalidate_feed(crit.title, crit.location)
            await ingest_feed(
                fp_feed,
                crit.title,
                crit.location,
                force=True,
                enrich_with_openai=settings.enable_openai_on_ingest,
                requested_limit=crit.limit,
            )
            await copy_feed_to_search_run(search_id, fp_feed, crit)
            flt_hit = datetime.utcnow()
            meta_json = build_result_metadata(
                response_status="live_ingestion",
                ingest_status=ingest_status_snap,
                feed_last_updated=flt_hit,
                scraped_at=flt_hit,
                message="Fresh scrape completed for this search.",
            )
        elif nj > 0 and fresh:
            await copy_feed_to_search_run(search_id, fp_feed, crit)
            flt_hit = feed.last_updated_at if feed else None
            meta_json = build_result_metadata(
                response_status="cache_hit",
                ingest_status=ingest_status_snap,
                feed_last_updated=flt_hit,
                scraped_at=None,
                message=(
                    f"Fresh feed snapshot (TTL {settings.query_feed_cache_ttl_seconds}s). Listing scrape skipped."
                ),
            )

        elif nj > 0 and not fresh:
            await copy_feed_to_search_run(search_id, fp_feed, crit)
            flt_dt = feed.last_updated_at if feed else None
            meta_json = build_result_metadata(
                response_status="stale_served_manual_refresh_required",
                ingest_status=ingest_status_snap,
                feed_last_updated=flt_dt,
                scraped_at=None,
                message=(
                    "Returned cached feed snapshot; no background refresh is scheduled."
                ),
            )
            completion_message = "Results are slightly older than the cache TTL — run a search to refresh."

        else:
            # Empty feed snapshot — ingestion populates Monster feed (serialized per query).
            await ingest_feed(
                fp_feed,
                crit.title,
                crit.location,
                force=False,
                enrich_with_openai=settings.enable_openai_on_ingest,
                requested_limit=crit.limit,
            )

            async with AsyncSessionLocal() as session:
                feed_live = await session.get(QueryFeed, fp_feed)
                nj_live = await _count_jobs_for_feed(session, fp_feed)

            ist = getattr(feed_live, "ingest_status", None) if feed_live else None
            fld = feed_live.last_updated_at if feed_live else None

            if nj_live > 0:
                await copy_feed_to_search_run(search_id, fp_feed, crit)
                meta_json = build_result_metadata(
                    response_status="live_ingestion",
                    ingest_status=ist,
                    feed_last_updated=fld,
                    scraped_at=fld,
                    message="Feed populated via Monster ingestion pipeline.",
                )
            elif feed_live and feed_live.ingest_status in {"blocked", "failed"}:
                completion_message = (
                    feed_live.ingest_message
                    or f"Monster source returned status={feed_live.ingest_status}"
                )
                meta_json = build_result_metadata(
                    response_status="blocked",
                    ingest_status=feed_live.ingest_status,
                    feed_last_updated=fld,
                    scraped_at=None,
                    message=completion_message[:2000],
                )
            else:
                completion_message = "No Monster.com listings matched this feed query."
                meta_json = build_result_metadata(
                    response_status="empty",
                    ingest_status=ist or "success",
                    feed_last_updated=fld,
                    scraped_at=None,
                    message=completion_message,
                )

        async with AsyncSessionLocal() as session:
            await session.execute(
                update(SearchRun)
                .where(SearchRun.id == search_id)
                .values(
                    status="completed",
                    error_message=completion_message,
                    result_metadata_json=meta_json,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()

    except Exception as exc:  # noqa: BLE001
        async with AsyncSessionLocal() as session:
            md = build_result_metadata(
                response_status="failed",
                ingest_status="failed",
                feed_last_updated=None,
                scraped_at=None,
                message=str(exc)[:2000],
            )
            await session.execute(
                update(SearchRun)
                .where(SearchRun.id == search_id)
                .values(
                    status="failed",
                    error_message=str(exc),
                    result_metadata_json=md,
                    updated_at=datetime.utcnow(),
                )
            )
            await session.commit()


def _parse_maybe_iso(value: object) -> datetime | None:
    if value is None or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


async def create_search(criteria: SearchRequest) -> int:
    fp = criteria_fingerprint(criteria)
    async with AsyncSessionLocal() as session:
        run = SearchRun(
            status="queued",
            criteria_json=criteria.model_dump_json(),
            fingerprint=fp,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        session.add(run)
        await session.flush()
        sid = run.id
        await session.commit()
        return sid


async def get_search_status(search_id: int) -> SearchStatusResponse | None:
    from app.schemas.job import IngestMetadata

    async with AsyncSessionLocal() as session:
        result = await session.execute(select(SearchRun).where(SearchRun.id == search_id))
        row = result.scalar_one_or_none()
        if not row:
            return None
        crit = SearchRequest.model_validate_json(row.criteria_json)
        ingest_payload: dict | None = None
        if row.result_metadata_json:
            try:
                ingest_payload = json.loads(row.result_metadata_json)
            except Exception:
                ingest_payload = None

        ingest: IngestMetadata | None = None
        if ingest_payload:
            fl_raw = ingest_payload.get("feed_last_updated")
            fl_dt = _parse_maybe_iso(fl_raw)
            ingest = IngestMetadata(
                response_status=ingest_payload.get("response_status", "") or "",
                ingest_status=ingest_payload.get("ingest_status"),
                feed_last_updated=fl_dt,
                scraped_at=_parse_maybe_iso(ingest_payload.get("scraped_at")),
                message=ingest_payload.get("message"),
            )

        return SearchStatusResponse(
            search_id=row.id,
            status=row.status,  # type: ignore[arg-type]
            error_message=row.error_message,
            created_at=row.created_at,
            updated_at=row.updated_at,
            criteria=crit,
            ingest=ingest,
        )


async def list_jobs(
    search_id: int,
    offset: int = 0,
    limit: int = 50,
    sort: str = "relevance",
) -> JobListResponse | None:
    async with AsyncSessionLocal() as session:
        exists = await session.execute(select(SearchRun.id).where(SearchRun.id == search_id))
        if exists.scalar_one_or_none() is None:
            return None

        base_filter = JobStored.search_id == search_id

        total = await session.scalar(
            select(func.count()).select_from(JobStored).where(base_filter)
        )
        total = int(total or 0)

        stmt = select(JobStored).where(base_filter)
        if sort.strip().lower() == "id":
            stmt = stmt.order_by(JobStored.id.asc())
        else:
            stmt = stmt.order_by(
                func.coalesce(JobStored.relevance_score, -1.0).desc(),
                JobStored.id.asc(),
            )
        result = await session.execute(stmt.offset(offset).limit(limit))
        rows = result.scalars().all()

    items = [job_row_to_record(r) for r in rows]
    return JobListResponse(items=items, total=total, offset=offset, limit=limit)


async def get_job(job_id: int, search_id: int | None = None) -> JobRecord | None:
    async with AsyncSessionLocal() as session:
        stmt = select(JobStored).where(JobStored.id == job_id)
        if search_id is not None:
            stmt = stmt.where(JobStored.search_id == search_id)
        result = await session.execute(stmt)
        row = result.scalar_one_or_none()
    if not row:
        return None
    return job_row_to_record(row)


def job_row_to_record(r: JobStored) -> JobRecord:
    enrichment = None
    if r.enrichment_json:
        try:
            enrichment = JobEnrichment.model_validate(json.loads(r.enrichment_json))
        except Exception:
            enrichment = None
    return JobRecord(
        id=r.id,
        search_id=r.search_id,
        title=r.title,
        company=r.company,
        location_display=r.location_display,
        salary_text=r.salary_text,
        posted_at_text=r.posted_at_text,
        job_url=r.job_url,
        source=r.source,
        relevance_score=r.relevance_score,
        description_text=r.description_text,
        job_type=r.job_type,
        industry=r.industry,
        company_size=r.company_size,
        year_founded=r.year_founded,
        website=r.website,
        about_company=r.about_company,
        enrichment=enrichment,
        openai_model=r.openai_model,
        openai_prompt_tokens=r.openai_prompt_tokens,
        openai_completion_tokens=r.openai_completion_tokens,
    )


async def enrich_job_on_demand(job_id: int, search_id: int | None = None) -> JobRecord | None:
    """Run OpenAI enrichment once for a specific stored job."""
    if not settings.enable_openai or not settings.openai_api_key.strip():
        raise RuntimeError("OpenAI enrichment is disabled (ENABLE_OPENAI=false or missing OPENAI_API_KEY).")

    async with AsyncSessionLocal() as session:
        stmt = select(JobStored).where(JobStored.id == job_id)
        if search_id is not None:
            stmt = stmt.where(JobStored.search_id == search_id)
        row = (await session.execute(stmt)).scalar_one_or_none()
        if not row:
            return None

        if not (row.description_text or "").strip():
            raise RuntimeError("This job has no description text to enrich.")

        # If already enriched by OpenAI, return as-is to avoid extra requests.
        if row.enrichment_json and row.openai_model:
            return job_row_to_record(row)

        base = job_row_to_record(row)
        result, meta = await asyncio.to_thread(enrich_job_record, base)
        row.enrichment_json = result.model_dump_json()
        row.openai_model = settings.openai_model
        row.openai_prompt_tokens = meta.get("prompt_tokens")
        row.openai_completion_tokens = meta.get("completion_tokens")

        # Re-score once enrichment is available.
        srow = (
            await session.execute(select(SearchRun).where(SearchRun.id == row.search_id))
        ).scalar_one_or_none()
        if srow:
            try:
                crit = SearchRequest.model_validate_json(srow.criteria_json)
                enriched_record = job_row_to_record(row)
                row.relevance_score = combined_relevance(crit, enriched_record)
            except Exception:
                pass

        await session.commit()
        await session.refresh(row)
        return job_row_to_record(row)
