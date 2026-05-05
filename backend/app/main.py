import asyncio
import csv
import io
import json
import logging
from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response, StreamingResponse
from sqlalchemy import func, select
try:
    from sse_starlette.sse import EventSourceResponse
except ModuleNotFoundError:
    class EventSourceResponse(StreamingResponse):
        def __init__(self, content, status_code: int = 200):
            async def _sse_wrapper():
                async for event in content:
                    payload = event.get("data", "") if isinstance(event, dict) else str(event)
                    yield f"data: {payload}\n\n"

            super().__init__(_sse_wrapper(), status_code=status_code, media_type="text/event-stream")

from app.config import settings
from app.db.models import JobStored, SearchRun
from app.db.session import AsyncSessionLocal, init_db
from app.schemas.job import SearchCreateResponse, SearchRequest
from app.scraper.chrome_launcher import (
    detect_os,
    find_chrome_binary,
    is_cdp_running,
    launch_chrome,
)
from app.scraper.monster import (
    DEBUG_DIR,
    discover_detail_selectors,
    load_selector_history,
    scrape_job_detail_safe,
    scraper_health,
    test_selector_on_url,
)
from app.services.ingestion_runner import scrape_progress
from app.services.search_service import (
    create_search,
    enrich_job_on_demand,
    execute_search_background,
    get_job,
    get_search_status,
    list_jobs,
)

logger = logging.getLogger("monster.api")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)s %(name)s %(message)s",
    )
    await init_db()
    logger.info("Scraping is manual-only. No background tasks run here.")
    logger.info("Detected OS: %s — Chrome binary: %s", detect_os(), find_chrome_binary())
    try:
        chrome_result = await launch_chrome(
            cdp_url=settings.chrome_cdp_url,
            user_data_dir=settings.chrome_user_data_dir,
        )
        logger.info("Chrome auto-launch at startup: %s", chrome_result)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Chrome did not auto-launch (%s). Use Launch Chrome in the dashboard or start Chrome with CDP manually.",
            exc,
        )
    yield


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
async def post_search(
    body: SearchRequest,
    background_tasks: BackgroundTasks,
    force_refresh: bool = True,
) -> SearchCreateResponse:
    search_id = await create_search(body)
    background_tasks.add_task(execute_search_background, search_id, body, force_refresh)
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
        "browser_mode": "cdp" if settings.use_cdp_chrome else "disabled",
    }


@app.get("/api/scraper/chrome-status")
async def chrome_status():
    import httpx

    connected = await is_cdp_running(settings.chrome_cdp_url)
    binary = find_chrome_binary()
    browser_info: dict[str, str] = {}
    if connected:
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{settings.chrome_cdp_url}/json/version", timeout=2.0)
                browser_info = resp.json()
        except Exception:
            pass
    return {
        "connected": connected,
        "os": detect_os(),
        "binary": binary or "not found",
        "binary_found": binary or "not found",
        "browser": browser_info.get("Browser", ""),
        "cdp_url": settings.chrome_cdp_url,
        "hint": (
            f"{binary or 'google-chrome'} "
            f"--remote-debugging-port=9222 "
            f"--user-data-dir=/tmp/chrome-monster-profile"
        )
        if not connected
        else "",
    }


@app.post("/api/scraper/launch-chrome")
async def trigger_chrome_launch():
    result = await launch_chrome(
        cdp_url=settings.chrome_cdp_url,
        user_data_dir=settings.chrome_user_data_dir,
    )
    return result


@app.get("/api/scraper/progress")
async def scrape_progress_stream(request: Request):
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            yield {"data": json.dumps(scrape_progress)}
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/debug/snapshots")
async def list_debug_snapshots() -> list[str]:
    if not DEBUG_DIR.exists():
        return []
    return sorted([p.name for p in DEBUG_DIR.iterdir() if p.is_file()], reverse=True)


@app.get("/debug/snapshots/{filename}")
async def get_debug_snapshot_file(filename: str):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Invalid filename")
    fp = (DEBUG_DIR / filename).resolve()
    base = DEBUG_DIR.resolve()
    if not str(fp).startswith(str(base)):
        raise HTTPException(status_code=400, detail="Invalid path")
    if not fp.exists() or not fp.is_file():
        raise HTTPException(status_code=404, detail="Snapshot not found")
    return FileResponse(path=str(fp), filename=fp.name)


@app.get("/api/scraper/selector-history")
async def get_selector_history():
    return load_selector_history(limit=50)


@app.post("/api/scraper/test-selector")
async def post_test_selector(body: dict[str, str]):
    selector = (body.get("selector") or "").strip()
    url = (body.get("url") or "").strip()
    if not selector or not url:
        raise HTTPException(status_code=400, detail="selector and url are required")
    try:
        return await test_selector_on_url(selector, url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/scraper/discover-selectors")
async def post_discover_selectors(body: dict[str, str]):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    try:
        return await discover_detail_selectors(url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/company/fetch-website")
async def fetch_company_website(body: dict[str, str]):
    import httpx
    from bs4 import BeautifulSoup

    url = (body.get("url") or "").strip()
    if not url:
        return {"error": "No URL provided"}
    if not url.startswith("http"):
        url = "https://" + url
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    }
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style", "nav", "footer", "header", "iframe", "noscript"]):
            tag.decompose()
        meta_desc = ""
        meta = soup.find("meta", attrs={"name": "description"})
        if meta:
            meta_desc = (meta.get("content") or "").strip()
        if not meta_desc:
            og = soup.find("meta", attrs={"property": "og:description"})
            if og:
                meta_desc = (og.get("content") or "").strip()
        body_text = " ".join(soup.get_text(separator=" ", strip=True).split())[:1500]
        title = soup.title.string.strip() if soup.title and soup.title.string else ""
        useful_links: list[dict[str, str]] = []
        for a in soup.find_all("a", href=True):
            href = (a.get("href") or "").strip()
            text = (a.get_text(strip=True) or "").strip()
            tl = text.lower()
            if any(kw in tl for kw in ["about", "careers", "jobs", "team", "linkedin", "culture", "mission"]):
                if href.startswith("http"):
                    useful_links.append({"text": text, "href": href})
        return {
            "url": url,
            "title": title,
            "meta_description": meta_desc,
            "body_preview": body_text,
            "useful_links": useful_links[:6],
            "status": "ok",
        }
    except httpx.TimeoutException:
        return {"url": url, "status": "timeout", "error": "Website took too long to respond"}
    except httpx.HTTPStatusError as exc:
        return {"url": url, "status": "error", "error": f"HTTP {exc.response.status_code}"}
    except Exception as exc:  # noqa: BLE001
        return {"url": url, "status": "error", "error": str(exc)}


@app.post("/api/scraper/job-detail")
async def post_scrape_job_detail(body: dict[str, str]):
    url = (body.get("url") or "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    try:
        detail = await scrape_job_detail_safe(url)
        return {"status": "ok", "detail": detail}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/v1/jobs/{job_id}/enrich")
async def enrich_job(job_id: int, search_id: int | None = None):
    try:
        record = await enrich_job_on_demand(job_id, search_id=search_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not record:
        raise HTTPException(status_code=404, detail="Job not found")
    return record


@app.get("/api/search/{search_id}/export-csv")
async def export_jobs_csv(search_id: int):
    async with AsyncSessionLocal() as session:
        rows = (
            await session.execute(
                select(JobStored).where(JobStored.search_id == search_id).order_by(JobStored.id.asc())
            )
        ).scalars().all()

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=[
            "title",
            "company",
            "location",
            "job_type",
            "industry",
            "salary",
            "company_size",
            "year_founded",
            "website",
            "url",
        ],
    )
    writer.writeheader()
    for job in rows:
        writer.writerow(
            {
                "title": job.title or "",
                "company": job.company or "",
                "location": job.location_display or "",
                "job_type": job.job_type or "",
                "industry": job.industry or "",
                "salary": job.salary_text or "",
                "company_size": job.company_size or "",
                "year_founded": job.year_founded or "",
                "website": job.website or "",
                "url": job.job_url or "",
            }
        )
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=jobs-search-{search_id}.csv"},
    )


@app.get("/api/search/history")
async def search_history():
    async with AsyncSessionLocal() as session:
        runs = (
            await session.execute(select(SearchRun).order_by(SearchRun.created_at.desc()).limit(10))
        ).scalars().all()
        result = []
        for r in runs:
            count = await session.scalar(
                select(func.count()).select_from(JobStored).where(JobStored.search_id == r.id)
            )
            criteria = json.loads(r.criteria_json or "{}")
            result.append(
                {
                    "id": r.id,
                    "title": criteria.get("title", ""),
                    "location": criteria.get("location", ""),
                    "num_jobs": criteria.get("limit", 0),
                    "result_count": int(count or 0),
                    "created_at": r.created_at.isoformat() if r.created_at else "",
                }
            )
    return result
