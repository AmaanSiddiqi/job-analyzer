# Vancouver Job Analyzer

Scrapes Vancouver tech job postings from LinkedIn's public guest endpoints, extracts skills with a spaCy NLP pipeline, and visualizes hiring trends in a React dashboard. The backend auto-scrapes 8 keyword sets every 6 hours.

**Live:** backend on Railway · frontend on Vercel

## Stack

| Layer     | Tech                                                          |
|-----------|---------------------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy (async), asyncpg             |
| Database  | PostgreSQL 16                                                 |
| Scraping  | LinkedIn public guest API, httpx, BeautifulSoup, APScheduler |
| NLP       | spaCy `en_core_web_sm` + PhraseMatcher (100+ skills vocab)   |
| Frontend  | React 18, TypeScript, Tailwind CSS, Recharts                 |
| Deploy    | Railway (backend + DB), Vercel (frontend)                    |

## Features

- **Auto-scrape** — APScheduler runs 8 keyword queries every 6 hours, fetches full job descriptions, extracts skills, and upserts to Postgres (deduped on `source_url`)
- **NLP skill extraction** — spaCy PhraseMatcher against a curated 100+ skill vocabulary; case-insensitive, multi-word aware (e.g. "machine learning", "spring boot")
- **Skill trends over time** — weekly posting counts per skill over the last 8 weeks (`/trends/skills/history`)
- **Dashboard** — stats cards, skill demand line chart, top-skills bar chart, top-roles bar chart, searchable job table
- **Rate-limit handling** — exponential backoff on 429s, semaphored concurrent description fetches

## Local dev

### With Docker (recommended)

```bash
cp backend/.env.example backend/.env
docker compose up --build
```

API docs → <http://localhost:8000/docs>

### Without Docker

```bash
# Backend
cd backend
uv sync
uv run python -m spacy download en_core_web_sm
cp .env.example .env
uv run uvicorn app.main:app --reload   # → :8000

# Frontend (separate terminal)
cd frontend
npm install
npm run dev   # → :5173
```

## Tests

```bash
cd backend
python -m venv .testvenv && .testvenv/bin/pip install -e ".[dev]"
.testvenv/bin/python -m spacy download en_core_web_sm
.testvenv/bin/python -m pytest tests/ -v
```

Covers: NLP unit tests (8) + API endpoint smoke tests (8).

## API

| Method | Path                      | Description                                              |
|--------|---------------------------|----------------------------------------------------------|
| GET    | `/jobs`                   | List postings (`skip`, `limit`, `location`)              |
| GET    | `/trends/skills`          | Top skills by frequency (`top_n`)                        |
| GET    | `/trends/roles`           | Most common job titles (`top_n`)                         |
| GET    | `/trends/skills/history`  | Weekly skill counts over time (`skills[]`, `weeks`)      |
| GET    | `/trends/stats`           | Summary stats (total jobs, companies, last scraped)      |
| POST   | `/scrape`                 | Trigger a manual scrape (`keywords`, `max_pages`)        |
| GET    | `/health`                 | Health check                                             |

## Project structure

```
backend/
  app/
    main.py           # FastAPI app, lifespan DB init + scheduler start
    database.py       # Async SQLAlchemy engine + get_db dependency
    models.py         # JobPosting ORM model (skills as TEXT[])
    schemas.py        # Pydantic v2 request/response models
    scheduler.py      # APScheduler — runs scrape every 6 hours
    routes/
      jobs.py         # GET /jobs
      trends.py       # /trends/* aggregation endpoints
      scrape.py       # POST /scrape
    services/
      nlp.py          # spaCy skill extractor
      scraper.py      # Core scrape pipeline: listings → descriptions → NLP → DB
  scraper/
    linkedin.py       # LinkedIn guest endpoint scraper + 429 backoff
  tests/
    test_nlp.py       # NLP unit tests
    test_api.py       # API smoke tests
  pyproject.toml

frontend/
  src/
    App.tsx                         # Dashboard layout + data loading
    api/jobs.ts                     # Typed API fetchers
    components/
      SkillHistoryChart.tsx         # Recharts LineChart — skill demand over time
      SkillsChart.tsx               # Recharts BarChart — top skills
      RolesChart.tsx                # Recharts BarChart — top roles
      JobTable.tsx                  # Searchable job listing
```
