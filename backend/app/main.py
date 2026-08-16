import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from . import scheduler
from .rate_limit import limiter
from .routes import jobs, scrape, trends

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic migrations now (backend/alembic/) — run
    # `alembic upgrade head` as a deploy step, not here. See AUDIT.md §5.
    interval = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    scheduler.start(interval)

    yield

    scheduler.stop()


app = FastAPI(
    title="Canada Job Analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]  # slowapi's handler signature is narrower than Starlette's generic Exception handler type

app.add_middleware(
    CORSMiddleware,
    allow_origins=[os.getenv("CORS_ORIGIN", "http://localhost:5173")],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(jobs.router)
app.include_router(trends.router)
app.include_router(scrape.router)


@app.get("/health")
async def health():
    return {"status": "ok"}
