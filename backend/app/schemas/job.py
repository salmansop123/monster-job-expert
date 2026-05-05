from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")
    title: str = Field(..., min_length=1, max_length=200)
    location: str = Field(default="remote", max_length=200)
    limit: int = Field(default=0, ge=0, le=50)


class JobNumbersFacts(BaseModel):
    location: str | None = None
    job_type: str | None = None
    industry: str | None = None
    company_size: str | None = None
    year_founded: str | None = None
    website: str | None = None


class JobEnrichment(BaseModel):
    summary: str = ""
    description: str = ""
    numbers_facts: JobNumbersFacts = Field(default_factory=JobNumbersFacts)
    about_company: str = ""
    confidence_notes: str | None = None


class JobRecord(BaseModel):
    id: int | None = None
    search_id: int | None = None
    title: str | None = None
    company: str | None = None
    location_display: str | None = None
    salary_text: str | None = None
    posted_at_text: str | None = None
    job_url: str | None = None
    source: str = "monster"
    relevance_score: float | None = None
    description_text: str | None = None
    job_type: str | None = None
    industry: str | None = None
    company_size: str | None = None
    year_founded: str | None = None
    website: str | None = None
    about_company: str | None = None
    enrichment: JobEnrichment | None = None
    openai_model: str | None = None
    openai_prompt_tokens: int | None = None
    openai_completion_tokens: int | None = None


class IngestMetadata(BaseModel):
    """How this search run was satisfied (feed cache vs ingestion)."""

    response_status: str
    ingest_status: str | None = None
    feed_last_updated: datetime | None = None
    scraped_at: datetime | None = None
    message: str | None = None


class SearchStatusResponse(BaseModel):
    search_id: int
    status: Literal["queued", "running", "completed", "failed"]
    error_message: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None
    criteria: SearchRequest | None = None
    ingest: IngestMetadata | None = None


class SearchCreateResponse(BaseModel):
    search_id: int
    status: Literal["queued", "running", "completed", "failed"]


class JobListResponse(BaseModel):
    items: list[JobRecord]
    total: int
    offset: int
    limit: int
