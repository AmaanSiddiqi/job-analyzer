"""Smoke tests for FastAPI endpoints."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.main import app
from app.database import get_db


async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


async def test_skills_trends_shape(client):
    r = await client.get("/trends/skills")
    assert r.status_code == 200
    body = r.json()
    assert "total_jobs" in body
    assert "top_skills" in body
    assert isinstance(body["top_skills"], list)


async def test_roles_trends_shape(client):
    r = await client.get("/trends/roles")
    assert r.status_code == 200
    body = r.json()
    assert "total_jobs" in body
    assert "top_roles" in body
    assert isinstance(body["top_roles"], list)


async def test_stats_shape(client):
    r = await client.get("/trends/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total_jobs" in body
    assert "total_companies" in body
    assert "last_scraped" in body


async def test_skill_history_shape(client):
    r = await client.get("/trends/skills/history", params={"skills": ["python", "javascript"], "weeks": 4})
    assert r.status_code == 200
    body = r.json()
    assert "series" in body
    assert isinstance(body["series"], list)


async def test_jobs_list_shape(client):
    r = await client.get("/jobs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


async def test_skill_history_empty_db_returns_empty_series(client):
    r = await client.get("/trends/skills/history")
    assert r.status_code == 200
    assert r.json()["series"] == []


async def test_trends_top_n_validation(client):
    r = await client.get("/trends/skills", params={"top_n": 0})
    assert r.status_code == 422

    r = await client.get("/trends/skills", params={"top_n": 101})
    assert r.status_code == 422
