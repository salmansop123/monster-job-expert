from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


engine = create_async_engine(settings.database_url, echo=False)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session


def _ensure_search_run_fingerprint_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("search_runs"):
        return
    cols = {c["name"] for c in insp.get_columns("search_runs")}
    if "fingerprint" not in cols:
        sync_conn.execute(text("ALTER TABLE search_runs ADD COLUMN fingerprint VARCHAR(128)"))
        sync_conn.execute(
            text("CREATE INDEX IF NOT EXISTS ix_search_runs_fingerprint ON search_runs (fingerprint)")
        )


def _ensure_jobs_relevance_score_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("jobs")}
    if "relevance_score" not in cols:
        sync_conn.execute(text("ALTER TABLE jobs ADD COLUMN relevance_score FLOAT"))


def _ensure_search_run_result_metadata_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("search_runs"):
        return
    cols = {c["name"] for c in insp.get_columns("search_runs")}
    if "result_metadata_json" not in cols:
        sync_conn.execute(text("ALTER TABLE search_runs ADD COLUMN result_metadata_json TEXT"))


def _ensure_feed_jobs_scraped_at_column(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("feed_jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("feed_jobs")}
    if "scraped_at" not in cols:
        sync_conn.execute(text("ALTER TABLE feed_jobs ADD COLUMN scraped_at DATETIME"))
    sync_conn.execute(
        text("CREATE INDEX IF NOT EXISTS ix_feed_jobs_scraped_at ON feed_jobs (scraped_at)")
    )


def _ensure_feed_jobs_detail_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("feed_jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("feed_jobs")}
    wanted = {
        "job_type": "TEXT",
        "industry": "TEXT",
        "company_size": "TEXT",
        "year_founded": "TEXT",
        "website": "TEXT",
        "about_company": "TEXT",
    }
    for col, typ in wanted.items():
        if col not in cols:
            sync_conn.execute(text(f"ALTER TABLE feed_jobs ADD COLUMN {col} {typ}"))


def _ensure_jobs_detail_columns(sync_conn) -> None:
    from sqlalchemy import inspect, text

    insp = inspect(sync_conn)
    if not insp.has_table("jobs"):
        return
    cols = {c["name"] for c in insp.get_columns("jobs")}
    wanted = {
        "job_type": "TEXT",
        "industry": "TEXT",
        "company_size": "TEXT",
        "year_founded": "TEXT",
        "website": "TEXT",
        "about_company": "TEXT",
    }
    for col, typ in wanted.items():
        if col not in cols:
            sync_conn.execute(text(f"ALTER TABLE jobs ADD COLUMN {col} {typ}"))


async def init_db() -> None:
    from app.db.models import Base  # noqa: F401 — registers FeedJob / QueryFeed mappers

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_search_run_fingerprint_column)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_jobs_relevance_score_column)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_search_run_result_metadata_column)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_feed_jobs_scraped_at_column)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_feed_jobs_detail_columns)
    async with engine.begin() as conn:
        await conn.run_sync(_ensure_jobs_detail_columns)
