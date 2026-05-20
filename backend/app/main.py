import logging
import os
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO)

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .database import engine, Base
from .routes import jobs, trends, scrape
from . import scheduler

load_dotenv()


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    interval = int(os.getenv("SCRAPE_INTERVAL_HOURS", "6"))
    scheduler.start(interval)

    yield

    scheduler.stop()


app = FastAPI(
    title="Canada Job Analyzer",
    version="0.1.0",
    lifespan=lifespan,
)

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
