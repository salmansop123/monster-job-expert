from pathlib import Path

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_REPO_ROOT = _BACKEND_ROOT.parent
_ENV_FILES = [p for p in (_BACKEND_ROOT / ".env", _REPO_ROOT / ".env") if p.is_file()]
_SETTINGS_KWARGS: dict[str, object] = {"env_file_encoding": "utf-8", "extra": "ignore"}
if _ENV_FILES:
    _SETTINGS_KWARGS["env_file"] = _ENV_FILES


class Settings(BaseSettings):
    model_config = SettingsConfigDict(**_SETTINGS_KWARGS)

    database_url: str = "sqlite+aiosqlite:///./monster_jobs.db"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    max_jobs_per_search: int = 25
    max_description_chars: int = 24_000
    request_delay_ms: int = 800
    """Legacy base delay; scrape min/max derive from this when unset."""
    scrape_delay_min_ms: int | None = Field(default=None)
    scrape_delay_max_ms: int | None = Field(default=None)
    playwright_headless: bool = True
    playwright_slow_mo_ms: int = 0
    playwright_visual_scroll_debug: bool = False
    """If set and the file exists, Playwright loads this storage state (cookies/session)."""
    playwright_storage_state_path: str = ""
    """If True, persist storage state to `playwright_storage_state_path` after each browser session."""
    playwright_save_storage_state: bool = False
    """Deprecated legacy search-run copy cache; feed cache supersedes."""
    search_cache_ttl_seconds: int = 0
    """If False, searches fail fast (Monster.com is the only data source)."""
    enable_monster_playwright: bool = True

    query_feed_cache_ttl_seconds: int = 1800
    """TTL for considering feed data 'fresh' (30 minutes default)."""
    ingest_rate_limit_seconds: int = 1800
    """Minimum seconds between scrapes for the same query (after first successful load)."""
    ingestion_schedule_seconds: int = 2700
    """Background ticker interval (45 min) to refresh known query feeds."""
    ingest_max_pages: int = 2
    ingest_max_jobs: int = 15
    ingest_human_delay_min_s: float = 2.0
    ingest_human_delay_max_s: float = 5.0
    post_nav_wait_ms: int = 2000
    monster_scrape_retries: int = 2
    """Retries after the first attempt (total tries = 1 + retries)."""
    monster_retry_backoff_seconds: str = "5,15"
    """Comma-separated backoff delays before retry 1, retry 2, ..."""
    playwright_user_data_dir: str = ""
    """If set, use persistent Chromium profile (cookies/session) at this path."""

    enable_openai: bool = True
    """If true, batch ingestion calls OpenAI for each job; keep false to avoid request bursts."""
    enable_openai_on_ingest: bool = False
    enable_html_fallback_ai: bool = False
    """If true, one extra tiny OpenAI call per job blends into relevance_score (~slower/costlier)."""
    enable_ai_relevance_scoring: bool = False

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @model_validator(mode="after")
    def _default_scrape_delays(self) -> "Settings":
        base = max(50, self.request_delay_ms)
        lo = (
            max(80, int(base * 0.55))
            if self.scrape_delay_min_ms is None
            else int(self.scrape_delay_min_ms)
        )
        hi = (
            max(lo + 80, int(base * 1.55))
            if self.scrape_delay_max_ms is None
            else int(self.scrape_delay_max_ms)
        )
        if hi < lo:
            lo, hi = hi, lo
        object.__setattr__(self, "scrape_delay_min_ms", int(lo))
        object.__setattr__(self, "scrape_delay_max_ms", int(hi))
        return self


settings = Settings()
