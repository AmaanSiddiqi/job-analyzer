"""POST /ingest/boards: auth, feature flag, and happy path (service patched)."""

from unittest.mock import AsyncMock, patch

import pytest

from app.ingestion.service import SourceCounts
from app.settings import get_settings


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    monkeypatch.setenv("ADMIN_API_KEY", "test-admin-key")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_requires_admin_key(client):
    resp = await client.post("/ingest/boards")
    assert resp.status_code == 401


async def test_flag_off_returns_503(client, monkeypatch):
    monkeypatch.setenv("ENABLE_BOARD_INGESTION", "false")
    get_settings.cache_clear()
    resp = await client.post("/ingest/boards", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 503
    assert "ENABLE_BOARD_INGESTION" in resp.json()["detail"]


async def test_flag_on_runs_ingestion(client, monkeypatch):
    monkeypatch.setenv("ENABLE_BOARD_INGESTION", "true")
    get_settings.cache_clear()
    fake_counts = {
        "greenhouse": SourceCounts(fetched=3, kept=2, filtered_location=1, new_raw=2, new_postings=2)
    }
    with patch("app.routes.ingest.run_board_ingestion", new=AsyncMock(return_value=fake_counts)):
        resp = await client.post("/ingest/boards", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources"]["greenhouse"]["fetched"] == 3
    assert body["sources"]["greenhouse"]["new_raw"] == 2
    assert body["sources"]["greenhouse"]["failed_boards"] == []


async def test_aggregators_flag_off_returns_503(client, monkeypatch):
    monkeypatch.setenv("ENABLE_AGGREGATOR_INGESTION", "false")
    get_settings.cache_clear()
    resp = await client.post("/ingest/aggregators", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 503
    assert "ENABLE_AGGREGATOR_INGESTION" in resp.json()["detail"]


async def test_aggregators_no_credentials_returns_503(client, monkeypatch):
    monkeypatch.setenv("ENABLE_AGGREGATOR_INGESTION", "true")
    for var in ("ADZUNA_APP_ID", "ADZUNA_APP_KEY", "JOOBLE_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    get_settings.cache_clear()
    resp = await client.post("/ingest/aggregators", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 503
    assert "credentials" in resp.json()["detail"]


async def test_aggregators_happy_path(client, monkeypatch):
    monkeypatch.setenv("ENABLE_AGGREGATOR_INGESTION", "true")
    monkeypatch.setenv("JOOBLE_API_KEY", "k")
    get_settings.cache_clear()
    fake = {
        "adzuna": SourceCounts(fetched=10, kept=9, filtered_location=1, new_raw=9),
        "jooble": SourceCounts(fetched=5, kept=5, new_raw=4),
        "new_company_suggestions": 3,
    }
    with patch("app.routes.ingest.run_aggregator_ingestion", new=AsyncMock(return_value=fake)):
        resp = await client.post("/ingest/aggregators", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["new_company_suggestions"] == 3
    assert body["sources"]["adzuna"]["kept"] == 9


async def test_suggestions_yaml_endpoint(client):
    with patch(
        "app.routes.ingest.render_yaml_suggestions",
        new=AsyncMock(return_value='  - name: "Maple Analytics"\n'),
    ):
        resp = await client.get("/ingest/suggestions", headers={"X-Admin-Key": "test-admin-key"})
    assert resp.status_code == 200
    assert resp.text.startswith('  - name: "Maple Analytics"')
