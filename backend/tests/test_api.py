"""Smoke tests for FastAPI endpoints."""



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


async def test_scrape_disabled_by_default(client, monkeypatch):
    """scraper/linkedin.py is deprecated (CLAUDE.md) — off unless explicitly enabled."""
    monkeypatch.delenv("ENABLE_LINKEDIN_SCRAPER", raising=False)
    r = await client.post("/scrape", json={"keywords": "software engineer", "max_pages": 1})
    assert r.status_code == 503
    assert "ENABLE_LINKEDIN_SCRAPER" in r.json()["detail"]


async def test_scrape_bulk_disabled_by_default(client, monkeypatch):
    monkeypatch.delenv("ENABLE_LINKEDIN_SCRAPER", raising=False)
    r = await client.post("/scrape/bulk", json={})
    assert r.status_code == 503
