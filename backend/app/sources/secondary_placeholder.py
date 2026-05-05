"""Optional non-Monster sources can be plugged in later (same FetchOutcome surface)."""

from __future__ import annotations

from app.schemas.job import SearchRequest
from app.sources.types import FetchOutcome


class SecondaryPlaceholderSource:
    """Returns empty outcomes until you wire Remotive/other APIs."""

    name = "placeholder"

    async def fetch_jobs(self, criteria: SearchRequest) -> FetchOutcome:  # noqa: ARG002
        return FetchOutcome(jobs=[], status="failed", message="No secondary sources configured.")
