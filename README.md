# Vancouver Job Analyzer

Scrapes Vancouver job postings from LinkedIn's public guest endpoints, extracts skills with spaCy NLP, and visualizes hiring trends in a React dashboard.

## Stack

| Layer     | Tech                                           |
|-----------|------------------------------------------------|
| Backend   | Python 3.12, FastAPI, SQLAlchemy (async)       |
| Database  | PostgreSQL 16                                  |
| Scraping  | LinkedIn public guest API, httpx, BeautifulSoup|
| NLP       | spaCy `en_core_web_sm`                         |
| Frontend  | React 18, TypeScript, Tailwind CSS, Recharts   |
| Deploy    | Railway (backend), Vercel (frontend)           |
| Deps      | uv                                             |

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
uv run uvicorn app.main:app --reload

# Frontend
cd frontend
npm install
npm run dev   # → http://localhost:5173
```

## API

| Method | Path              | Description                                      |
|--------|-------------------|--------------------------------------------------|
| GET    | /jobs             | List postings (`skip`, `limit`, `location`)      |
| GET    | /jobs/{id}        | Single posting                                   |
| POST   | /jobs             | Ingest a posting                                 |
| GET    | /trends/skills    | Top skills by frequency (`top_n`)                |
| GET    | /trends/roles     | Most common job titles (`top_n`)                 |
| POST   | /scrape           | Scrape LinkedIn, run NLP, upsert to DB           |
| GET    | /health           | Health check                                     |

## Project structure

```
backend/
  app/
    main.py           # FastAPI app, CORS (reads CORS_ORIGIN from env), lifespan DB init
    database.py       # Async SQLAlchemy engine + get_db dependency
    models.py         # JobPosting ORM model (skills as TEXT[])
    schemas.py        # Pydantic v2 request/response models
    routes/
      jobs.py         # /jobs CRUD
      trends.py       # /trends/skills and /trends/roles aggregation
    services/
      nlp.py          # (TODO) spaCy skill extractor
  scraper/
    linkedin.py       # LinkedIn guest endpoint scraper
  pyproject.toml      # uv-managed dependencies
  Dockerfile

frontend/             # Vite + React + TypeScript scaffold (not yet built out)
  src/
    App.tsx
    main.tsx
    index.css
```

## Scraper

`backend/scraper/linkedin.py` targets the public endpoint:

```
GET https://www.linkedin.com/jobs-guest/jobs/api/seeMoreJobPostings/search
    ?keywords=<query>&location=Vancouver%2C+BC&start=<offset>
```

Usage:

```python
from scraper.linkedin import scrape

jobs = await scrape("software engineer", max_pages=4)
```

Returns a list of dicts with `title`, `company`, `location`, `source_url`. The `raw_description` and `skills` fields are empty until the NLP pipeline runs.
