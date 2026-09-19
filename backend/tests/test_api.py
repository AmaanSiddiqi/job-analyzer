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
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    monkeypatch.delenv("ENABLE_LINKEDIN_SCRAPER", raising=False)
    r = await client.post(
        "/scrape",
        json={"keywords": "software engineer", "max_pages": 1},
        headers={"X-Admin-Key": "test-key"},
    )
    assert r.status_code == 503
    assert "ENABLE_LINKEDIN_SCRAPER" in r.json()["detail"]


async def test_scrape_bulk_disabled_by_default(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    monkeypatch.delenv("ENABLE_LINKEDIN_SCRAPER", raising=False)
    r = await client.post("/scrape/bulk", json={}, headers={"X-Admin-Key": "test-key"})
    assert r.status_code == 503


async def test_mutating_routes_503_when_admin_key_unconfigured(client, monkeypatch):
    """Fails closed, per AUDIT.md §1: unset ADMIN_API_KEY disables the route, not opens it."""
    monkeypatch.delenv("ADMIN_API_KEY", raising=False)
    r = await client.post("/scrape", json={})
    assert r.status_code == 503
    assert "ADMIN_API_KEY" in r.json()["detail"]

    r = await client.post("/jobs", json={})
    assert r.status_code == 503


async def test_mutating_routes_reject_missing_or_wrong_key(client, monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")

    r = await client.post("/scrape", json={})  # no header at all
    assert r.status_code == 401

    r = await client.post("/scrape", json={}, headers={"X-Admin-Key": "wrong"})
    assert r.status_code == 401


async def test_create_job_requires_admin_key(client, monkeypatch):
    """Auth is enforced before the route body runs — 401 regardless of payload shape."""
    monkeypatch.setenv("ADMIN_API_KEY", "test-key")
    r = await client.post("/jobs", json={})
    assert r.status_code == 401


async def test_skill_history_reports_share_of_each_weeks_postings(client, mock_db):
    """The chart plots share, not count: counts are not comparable across the
    LinkedIn -> board source change. Row values mirror the verified scratch-DB
    run: 9 of 30 postings in the board-backfill week ask for python."""
    from datetime import date
    from types import SimpleNamespace

    from tests.conftest import _MockResult

    mock_db.execute.return_value = _MockResult(
        rows=[
            SimpleNamespace(week=date(2026, 8, 24), skill="python", n=9, total=30),
            SimpleNamespace(week=date(2026, 8, 31), skill="python", n=3, total=8),
        ]
    )
    r = await client.get("/trends/skills/history", params={"skills": ["python"]})
    assert r.status_code == 200
    points = r.json()["series"][0]["data"]
    assert [(p["count"], p["total"], p["share"]) for p in points] == [
        (9, 30, 0.3),
        (3, 8, 0.375),
    ]
