"""Lexical relevance 0–100 from search criteria vs job text (no extra API calls)."""

from __future__ import annotations

import re

from app.schemas.job import SearchRequest

_WORD = re.compile(r"[a-z0-9+#.]+", re.I)


def _tokens(s: str) -> set[str]:
    return {w.lower() for w in _WORD.findall(s or "") if len(w) > 1}


def lexical_relevance_score(
    criteria: SearchRequest,
    title: str | None,
    company: str | None,
    location_display: str | None,
    description: str | None,
) -> float:
    """Weighted overlap: title tokens matter most, then location, then body."""
    qt = _tokens(criteria.title)
    ql = _tokens(criteria.location)
    for discard in ("remote", "hybrid"):
        qt.discard(discard)
        ql.discard(discard)

    if not qt and not ql:
        return 55.0

    blob = " ".join(
        filter(None, [(title or ""), (company or ""), (location_display or ""), (description or "")[:6000]])
    ).lower()

    score = 0.0
    max_parts = 0.0

    for tok in qt:
        max_parts += 2.0
        tl = (title or "").lower()
        if tok in tl:
            score += 2.0
        elif tok in blob:
            score += 1.0

    for tok in ql:
        max_parts += 1.2
        ll = (location_display or "").lower()
        if tok in ll or tok in blob:
            score += 1.2

    if max_parts <= 0:
        return 50.0
    return round(min(100.0, 100.0 * score / max_parts), 1)
