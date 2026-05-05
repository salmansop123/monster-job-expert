# Monster Job Expert

Full-stack app: **Playwright** scrapes Monster.com listings and job pages; **OpenAI** extracts structured fields like summary, description, Numbers & Facts (location, job type, industry, company size, year founded, website), and About Company. The UI uses a simple search form (job title, location/remote, latest-job count) and a dashboard.

## Prerequisites

- **Python 3.11+**
- **Node.js 20+** and **npm** (for the Vite frontend)
- **OpenAI API key** — copy [`.env.example`](.env.example) to `.env` and set `OPENAI_API_KEY` (and optionally `OPENAI_MODEL`)

## Compliance

Automated scraping may conflict with Monster’s terms of service. Use for learning or with permission. Defaults use conservative delays between page loads.

## Run the project

### Option A — one script (backend + UI)

From the **repo root** (after venv + deps are set up — see below):

```bash
./scripts/start-dev.sh
```

Run from the **repo root**. **Ctrl+C** stops both processes.

If port **8000** is busy: `PORT=8001 ./scripts/start-dev.sh` and set `VITE_API_PROXY=http://127.0.0.1:8001` in `frontend/.env.local`, then restart the UI.

### Option B — two terminals

**Backend**

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
cp ../.env.example ../.env   # add OPENAI_API_KEY
python run_dev.py
```

API: **http://127.0.0.1:8000/docs** — `run_dev.py` checks that the port is free first.

**Frontend**

```bash
cd frontend
npm install
npm run dev
```

UI: **http://localhost:5173** (proxies `/api` to the API on port 8000 by default).

## API

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Health check |
| POST | `/api/v1/search` | Start search (`SearchRequest`: `title`, `location`, `limit`) |
| GET | `/api/v1/search/{id}` | Poll status |
| GET | `/api/v1/search/{id}/jobs` | List jobs |
| GET | `/api/v1/jobs/{job_id}` | Single job |

## Tuning scrapers

Monster’s DOM changes. Update [`backend/app/scraper/selectors.py`](backend/app/scraper/selectors.py). Optional HTML fixtures: `backend/tests/fixtures/`.

## Monster-only + feed cache / ingestion

- **Playwright scraping never runs inline on the `/search` HTTP handler.** The worker resolves each search against a **shared SQLite feed** keyed by normalized `title` + `location`, then clones rows onto the search’s dashboard.
- **`QUERY_FEED_CACHE_TTL_SECONDS`** (default 1800): if cached rows exist and are fresh → copy only (instant). If stale → copy immediately and schedule a refresh in the background (rate-limited by `INGEST_RATE_LIMIT_SECONDS` when rows already exist).
- **First-ever query**: the async search task runs `MonsterJobSource.fetch_jobs_with_retries()` (Listing → detail scrape → enrichment) inside `app/services/ingestion_runner.py`, then stores `feed_jobs` + `query_feeds` rows.
- **`INGESTION_SCHEDULE_SECONDS`**: asyncio loop re-runs ingestion for each known fingerprint (skipped when inside the rate-limit window unless the snapshot is empty). Set `0` to disable scheduled refresh entirely.
- **Logging**: ingestion + scrape checkpoints write `scrape_logs`; Python loggers emit `monster.ingest` lines.
- **Optional secondary feeds**: stub + hook in [`backend/app/sources/secondary_placeholder.py`](backend/app/sources/secondary_placeholder.py) / `combine_with_secondary_if_configured`.
- **`PLAYWRIGHT_USER_DATA_DIR`**: Chromium persistent profile directory for cookies/session.
- **`ENABLE_AI_RELEVANCE_SCORING=false|true`** — optional extra OpenAI call per job blended into `relevance_score`.
- **Jobs API**: `GET .../jobs?sort=relevance|id`.

If Monster blocks ingestion, stale cached rows remain for the TTL path; cold queries surface `blocked` status on the poll payload via `SearchStatusResponse.ingest`.

This project does **not** integrate “stealth” / anti-detection browser patches.

## Layout

- `backend/` — FastAPI, SQLite, scraper, OpenAI enrichment  
- `frontend/` — React + Vite + Tailwind  
- `scripts/start-dev.sh` — starts API + UI locally  

*(Container / CI setup can be added later under DevOps.)*
