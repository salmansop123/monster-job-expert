import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from app.config import settings
from app.db.session import init_db
from app.schemas.job import SearchCreateResponse, SearchRequest
from app.scraper.monster import DEBUG_DIR, scraper_health
from app.services.ingestion_runner import scheduled_refresh_all_feeds
from app.services.search_service import (
    create_search,
    enrich_job_on_demand,
    execute_search_background,
    get_job,
    get_search_status,
    list_jobs,
)

logger = logging.getLogger("monster.api")
_tick_task: asyncio.Task | None = None


async def _scheduled_ingestion_loop() -> None:
    interval = max(60, settings.ingestion_schedule_seconds)
    while True:
        try:
            await asyncio.sleep(interval)
            await scheduled_refresh_all_feeds()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.warning("Scheduled ingestion tick failed: %s", exc)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _tick_task
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    await init_db()
    if settings.ingestion_schedule_seconds > 0:
        _tick_task = asyncio.create_task(_scheduled_ingestion_loop())
        logger.info(
            "Started background ingestion ticker (every %ss)",
            settings.ingestion_schedule_seconds,
        )
    else:
        logger.info("Background ingestion ticker disabled (ingestion_schedule_seconds=0).")
    try:
        yield
    finally:
        if _tick_task is not None:
            _tick_task.cancel()
            try:
                await _tick_task
            except asyncio.CancelledError:
                pass
            _tick_task = None


app = FastAPI(title="Monster Job Expert", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
async def root() -> dict[str, str]:
    """Avoid 404 when opening the API base URL in a browser; UI runs on Vite (e.g. :5173)."""
    return {
        "service": "Monster Job Expert API",
        "docs": "/docs",
        "health": "/health",
        "search": "POST /api/v1/search",
        "ui": "Run the frontend (npm run dev) and open http://localhost:5173",
    }


@app.get("/favicon.ico")
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/v1/search", response_model=SearchCreateResponse)
async def post_search(body: SearchRequest, background_tasks: BackgroundTasks) -> SearchCreateResponse:
    search_id = await create_search(body)
    background_tasks.add_task(execute_search_background, search_id, body)
    return SearchCreateResponse(search_id=search_id, status="running")


@app.get("/api/v1/search/{search_id}")
async def search_status(search_id: int):
    row = await get_search_status(search_id)
    if not row:
        raise HTTPException(status_code=404, detail="Search not found")
    return row


@app.get("/api/v1/search/{search_id}/jobs")
async def search_jobs(
    search_id: int,
    offset: int = 0,
    limit: int = 50,
    sort: str = "relevance",
):
    data = await list_jobs(search_id, offset=offset, limit=limit, sort=sort)
    if data is None:
        raise HTTPException(status_code=404, detail="Search not found")
    return data


@app.get("/api/v1/jobs/{job_id}")
async def job_detail(job_id: int, search_id: int | None = None):
    record = await get_job(job_id, search_id=search_id)
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record


@app.get("/api/scraper/health")
async def get_scraper_health() -> dict[str, object]:
    return {
        "last_run_at": scraper_health.last_run_at,
        "last_query": scraper_health.last_query,
        "cards_found": scraper_health.cards_found,
        "selector_used": scraper_health.selector_used,
        "blocked": scraper_health.blocked,
        "error": scraper_health.error,
    }


@app.get("/debug/snapshots")
async def list_debug_snapshots() -> list[str]:
    if not DEBUG_DIR.exists():
        return []
    return sorted([p.name for p in DEBUG_DIR.iterdir() if p.is_file()], reverse=True)


@app.post("/api/v1/jobs/{job_id}/enrich")
async def enrich_job(job_id: int, search_id: int | None = None):
    try:
        record = await enrich_job_on_demand(job_id, search_id=search_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record
