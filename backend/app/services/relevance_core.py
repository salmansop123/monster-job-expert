from __future__ import annotations

from app.ai.relevance_match import ai_query_match_score
from app.relevance_lexical import lexical_relevance_score
from app.schemas.job import JobRecord, SearchRequest


def combined_relevance(criteria: SearchRequest, jr: JobRecord) -> float:
    lex = lexical_relevance_score(
        criteria,
        jr.title,
        jr.company,
        jr.location_display,
        jr.description_text,
    )
    ai_n = ai_query_match_score(criteria, jr)
    if ai_n is None:
        return lex
    return round(0.52 * lex + 0.48 * float(ai_n), 1)
