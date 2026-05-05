"""Optional AI match score 0–100 (one small call per job when enabled)."""

from __future__ import annotations

import json
import re

from openai import OpenAI

from app.config import settings
from app.schemas.job import JobRecord, SearchRequest

_SCORE_DIGITS = re.compile(r"\b(\d{1,3})\b")


def ai_query_match_score(criteria: SearchRequest, job: JobRecord) -> int | None:
    """Return 0–100 or None if disabled / error."""
    if not settings.enable_ai_relevance_scoring:
        return None
    if not settings.enable_openai or not settings.openai_api_key.strip():
        return None

    snippet = " ".join(
        filter(
            None,
            [
                job.title or "",
                job.company or "",
                job.location_display or "",
                (job.enrichment.summary if job.enrichment else "") or "",
                (job.description_text or "")[:2000],
            ],
        )
    )
    if not snippet.strip():
        return None

    client = OpenAI(api_key=settings.openai_api_key)
    try:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You rate how well a job posting matches a user's search. "
                        "Reply with JSON only: {\"score\": <integer 0-100>}."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Search job title: {criteria.title!r}\n"
                        f"Search location preference: {criteria.location!r}\n\n"
                        f"Job posting:\n{snippet}\n"
                    ),
                },
            ],
            response_format={"type": "json_object"},
            max_tokens=80,
        )
    except Exception:
        return None

    raw = completion.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        n = int(data.get("score", -1))
        if 0 <= n <= 100:
            return n
    except Exception:
        pass
    m = _SCORE_DIGITS.search(raw)
    if m:
        n = int(m.group(1))
        return max(0, min(100, n))
    return None
