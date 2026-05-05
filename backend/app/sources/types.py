from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FetchOutcome:
    jobs: list[dict[str, str | None]]
    """Monster listing rows (+ optional partial detail fields)."""

    status: str
    """success | partial_success | blocked | failed"""

    message: str | None = None
