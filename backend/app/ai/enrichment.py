import json
from typing import Any

from openai import OpenAI

from app.config import settings
from app.schemas.job import JobEnrichment, JobRecord


ENRICHMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "summary": {"type": "string"},
        "description": {"type": "string"},
        "numbers_facts": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "location": {"type": ["string", "null"]},
                "job_type": {"type": ["string", "null"]},
                "industry": {"type": ["string", "null"]},
                "company_size": {"type": ["string", "null"]},
                "year_founded": {"type": ["string", "null"]},
                "website": {"type": ["string", "null"]},
            },
            "required": [
                "location",
                "job_type",
                "industry",
                "company_size",
                "year_founded",
                "website",
            ],
        },
        "about_company": {"type": "string"},
        "confidence_notes": {"type": ["string", "null"]},
    },
    "required": [
        "summary",
        "description",
        "numbers_facts",
        "about_company",
        "confidence_notes",
    ],
}


def _client() -> OpenAI:
    return OpenAI(api_key=settings.openai_api_key or None)


def enrich_job_record(job: JobRecord) -> tuple[JobEnrichment, dict[str, int | None]]:
    empty_usage = {"prompt_tokens": None, "completion_tokens": None}

    if not settings.enable_openai or not settings.openai_api_key.strip():
        return JobEnrichment(summary="AI enrichment disabled; set OPENAI_API_KEY."), empty_usage

    payload = _build_prompt(job)

    client = _client()
    completion = None
    try:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You extract structured Monster job data from plain job posting text. "
                        "Output JSON only with keys: summary, description, numbers_facts, "
                        "about_company, confidence_notes. "
                        "numbers_facts must include: location, job_type, industry, company_size, "
                        "year_founded, website. Use null for unknown values. "
                        "Do not invent facts."
                    ),
                },
                {"role": "user", "content": payload},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "job_enrichment",
                    "schema": ENRICHMENT_SCHEMA,
                    "strict": True,
                },
            },
        )
    except Exception:
        completion = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        'Return ONLY valid JSON matching: {"summary":"","description":"",'
                        '"numbers_facts":{"location":null,"job_type":null,"industry":null,'
                        '"company_size":null,"year_founded":null,"website":null},'
                        '"about_company":"","confidence_notes":null}'
                    ),
                },
                {"role": "user", "content": payload},
            ],
            response_format={"type": "json_object"},
        )

    raw = completion.choices[0].message.content or "{}"
    try:
        data = json.loads(raw)
        enrichment = JobEnrichment.model_validate(data)
    except Exception:
        enrichment = JobEnrichment(
            summary=raw[:2000],
            confidence_notes="Model returned non-JSON; stored raw excerpt in summary.",
        )

    usage = completion.usage if completion else None
    return enrichment, {
        "prompt_tokens": usage.prompt_tokens if usage else None,
        "completion_tokens": usage.completion_tokens if usage else None,
    }


def _build_prompt(job: JobRecord) -> str:
    parts = [
        "Extract these sections if present:",
        "- Job summary",
        "- Description",
        "- Numbers & Facts (Location, Job Type, Industry, Company Size, Year Founded, Website)",
        "- About Company",
        f"\nKnown title (may repeat): {job.title or ''}",
        f"Known company: {job.company or ''}",
        f"Known location: {job.location_display or ''}",
        "\n=== FULL DESCRIPTION ===\n",
        (job.description_text or "")[: settings.max_description_chars],
    ]
    return "\n".join(parts)
