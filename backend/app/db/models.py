from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class QueryFeed(Base):
    """Normalized query bucket (title + location) shared across searches and ingestion."""

    __tablename__ = "query_feeds"

    fingerprint: Mapped[str] = mapped_column(String(64), primary_key=True)
    title: Mapped[str] = mapped_column(Text, default="")
    location: Mapped[str] = mapped_column(Text, default="")
    last_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    ingest_status: Mapped[str] = mapped_column(String(32), default="pending")
    ingest_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_processing: Mapped[bool] = mapped_column(Boolean, default=False)
    """Next time a refresh is allowed (rate limit window). Empty feed bypasses."""
    next_scrape_allowed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    jobs: Mapped[list["FeedJob"]] = relationship(
        back_populates="feed", cascade="all, delete-orphan"
    )


class FeedJob(Base):
    __tablename__ = "feed_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(
        String(64), ForeignKey("query_feeds.fingerprint"), index=True
    )
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="monster")
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrichment_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    openai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    openai_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    openai_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_founded: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_company: Mapped[str | None] = mapped_column(Text, nullable=True)
    scraped_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    feed: Mapped["QueryFeed"] = relationship(back_populates="jobs")


class ScrapeLog(Base):
    """Debug trail for ingestion / Playwright."""

    __tablename__ = "scrape_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    event: Mapped[str] = mapped_column(String(64), default="info")
    message: Mapped[str] = mapped_column(Text, default="")
    jobs_count: Mapped[int | None] = mapped_column(Integer, nullable=True)


class SearchRun(Base):
    __tablename__ = "search_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    status: Mapped[str] = mapped_column(String(32), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    criteria_json: Mapped[str] = mapped_column(Text, default="{}")
    fingerprint: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    result_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    jobs: Mapped[list["JobStored"]] = relationship(back_populates="search_run")


class JobStored(Base):
    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    search_id: Mapped[int] = mapped_column(ForeignKey("search_runs.id"), index=True)

    title: Mapped[str | None] = mapped_column(Text, nullable=True)
    company: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_display: Mapped[str | None] = mapped_column(Text, nullable=True)
    salary_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    posted_at_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(64), default="monster")
    relevance_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    description_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    enrichment_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    openai_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    openai_prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    openai_completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    job_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    industry: Mapped[str | None] = mapped_column(Text, nullable=True)
    company_size: Mapped[str | None] = mapped_column(Text, nullable=True)
    year_founded: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(Text, nullable=True)
    about_company: Mapped[str | None] = mapped_column(Text, nullable=True)

    search_run: Mapped["SearchRun"] = relationship(back_populates="jobs")
