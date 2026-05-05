from __future__ import annotations

import asyncio
import logging

from app.config import settings
from app.schemas.job import SearchRequest
from app.scraper.monster.engine import scrape_listing_jobs
from app.sources.types import FetchOutcome

_logger = logging.getLogger("monster.ingest")


def _backoff_seconds() -> list[int]:
    raw = settings.monster_retry_backoff_seconds or "5,15"
    parts: list[int] = []
    for x in raw.split(","):
        xs = x.strip()
        if xs.isdigit():
            parts.append(int(xs))
    if not parts:
        return [5, 15]
    return parts


class MonsterJobSource:
    name = "monster"

    async def fetch_jobs_with_retries(self, criteria: SearchRequest) -> FetchOutcome:
        if not settings.enable_monster_playwright:
            return FetchOutcome(
                jobs=[],
                status="failed",
                message="Monster Playwright disabled on server (ENABLE_MONSTER_PLAYWRIGHT=false).",
            )

        retries = max(0, int(settings.monster_scrape_retries))
        delays = _backoff_seconds()
        attempts = max(1, retries + 1)

        last_block_message: str | None = None

        for attempt in range(attempts):
            _logger.info(
                "Monster listing attempt %s/%s title=%r",
                attempt + 1,
                attempts,
                criteria.title,
            )
            try:
                listing = await scrape_listing_jobs(criteria)
            except Exception as exc:
                last_block_message = str(exc)
                _logger.warning("Monster listing exception: %s", exc)
                if attempt < attempts - 1:
                    wait_s = delays[attempt] if attempt < len(delays) else delays[-1]
                    await asyncio.sleep(wait_s)
                continue

            rows = listing.rows

            if rows and not listing.blocked_or_restricted:
                return FetchOutcome(jobs=list(rows), status="success")

            if rows and listing.blocked_or_restricted:
                _logger.warning("Monster restriction after partial SERP rows (n=%s).", len(rows))
                return FetchOutcome(
                    jobs=list(rows),
                    status="partial_success",
                    message="Monster showed a restriction banner after partial SERP extraction.",
                )

            if listing.blocked_or_restricted:
                last_block_message = "Monster blocked or restricted this session."
                _logger.warning("Monster blocked SERP (attempt %s).", attempt + 1)
                if attempt < attempts - 1:
                    wait_s = delays[attempt] if attempt < len(delays) else delays[-1]
                    await asyncio.sleep(wait_s)
                continue

            # Empty listing, no block markers (legitimate empty search)
            return FetchOutcome(
                jobs=[],
                status="success",
                message="No Monster.com listings matched this query.",
            )

        return FetchOutcome(
            jobs=[],
            status="blocked",
            message=last_block_message or "Monster blocked automated access.",
        )


async def combine_with_secondary_if_configured(primary: FetchOutcome, _criteria: SearchRequest) -> FetchOutcome:
    """Hook for optional API sources later — Monster-only today."""
    return primary
