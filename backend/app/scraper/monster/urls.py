from urllib.parse import quote_plus, urlencode

from app.schemas.job import SearchRequest


BASE_SEARCH = "https://www.monster.com/jobs/search"


def build_search_url(criteria: SearchRequest) -> str:
    """Build Monster primary search URL from title + location/remote."""

    params: dict[str, str] = {
        "q": criteria.title.strip(),
        "where": _location_query(criteria),
    }

    qs = urlencode(params, quote_via=lambda s, *_a, **_k: quote_plus(s, safe="/"))
    return f"{BASE_SEARCH}?{qs}"


def _location_query(criteria: SearchRequest) -> str:
    loc = criteria.location.strip()
    if not loc:
        return "Remote"
    return loc


def augment_title_for_setting(criteria: SearchRequest) -> SearchRequest:
    """Compatibility helper; no-op for current simplified workflow."""
    return criteria
