# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

Vancouver job posting analyzer — scrapes LinkedIn public guest endpoints, extracts skills with spaCy, and displays hiring trends in a React dashboard. Deployed on Railway (backend) and Vercel (frontend).

## Commands

### Backend (uv)

```bash
cd backend
uv sync                                    # install deps from pyproject.toml
uv run python -m spacy download en_core_web_sm
cp .env.example .env                       # fill in DATABASE_URL + CORS_ORIGIN
uv run uvicorn app.main:app --reload       # dev server → :8000
```

### Frontend

```bash
cd frontend
npm install
npm run dev      # Vite dev server → :5173
npm run build    # tsc + vite build
npm run lint
```

### Full stack (Docker)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

## Architecture

**Backend** (`backend/app/`)

- `main.py` — FastAPI app. Reads `CORS_ORIGIN` from env. Creates DB tables on startup via `lifespan`.
- `database.py` — Async SQLAlchemy engine (`asyncpg`). `get_db()` yields an `AsyncSession`.
- `models.py` — `JobPosting` ORM model. `skills` is a Postgres `ARRAY(String)`.
- `schemas.py` — Pydantic v2 schemas. `SkillTrendsResponse` and `RoleTrendsResponse` are separate types.
- `routes/jobs.py` — CRUD for `GET/POST /jobs`. Supports `?location=` filter.
- `routes/trends.py` — Two endpoints under `/trends`:
  - `GET /trends/skills` — `func.unnest(skills)` + `GROUP BY` to count skill frequency.
  - `GET /trends/roles` — `GROUP BY title` to count most common job titles.
- `services/nlp.py` — spaCy PhraseMatcher against a curated `_SKILLS_VOCAB` list. Model loaded once at import. `extract_skills(text)` returns sorted lowercase list. Truncates input at 50k chars.
- `routes/scrape.py` — `POST /scrape` endpoint. Fetches listing cards, concurrently fetches descriptions (semaphore=3, 0.8s delay), runs NLP, then bulk-upserts via `pg_insert(...).on_conflict_do_nothing(index_elements=["source_url"])`.

**Scraper** (`backend/scraper/linkedin.py`)

- Hits `linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search?keywords=…&location=Vancouver%2C+BC&start=…`
- Parses HTML fragments with BeautifulSoup (`lxml` parser).
- `scrape(keywords, max_pages)` returns list of dicts: `title`, `company`, `location`, `source_url`. `raw_description` and `skills` are empty — filled by the NLP pipeline.
- Built-in 429 back-off (5 s retry) and a 1.5 s delay between pages.

**Frontend** (`frontend/src/`)

- Vite proxy: `/api/*` → `localhost:8000` (no CORS issues in dev).
- `api/client.ts` — Axios instance, `baseURL: "/api"`.
- `api/jobs.ts` — All API types and typed fetchers for jobs, skill trends, role trends, and scrape.
- `components/SkillsChart.tsx` — Horizontal `BarChart` (Recharts) for `/trends/skills`.
- `components/RolesChart.tsx` — Horizontal `BarChart` for `/trends/roles`.
- `components/JobTable.tsx` — Job list with inline skill tags.
- `App.tsx` — Full dashboard: header with keywords input + Scrape button, two-column chart grid, job table. Calls `loadData()` after a successful scrape.

## Key conventions

- All DB access is async. Never use sync SQLAlchemy calls.
- `source_url` has a `UNIQUE` constraint — use it to deduplicate on ingest.
- Skills must be normalised to lowercase before storing so `unnest` aggregation in `/trends/skills` groups correctly.
- Python deps are managed with `uv` via `pyproject.toml` — do not add a `requirements.txt`.
