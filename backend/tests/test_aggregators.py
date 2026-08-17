"""Adzuna/Jooble client normalization against fixtures — no live network.

Fixture shapes follow the public API docs; the first run with real
credentials validates them against reality (clients are defensive about
missing fields either way).
"""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.ingestion.aggregators import fetch_adzuna, fetch_jooble
from app.settings import Settings

FIXTURES = Path(__file__).parent / "fixtures" / "aggregators"


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "adzuna_app_id": "test-id",
        "adzuna_app_key": "test-key",
        "jooble_api_key": "test-jooble-key",
        "adzuna_pages_per_keyword": 1,
        "jooble_pages_per_keyword": 1,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@respx.mock
async def test_adzuna_normalization(client):
    respx.get(url__regex=r"https://api\.adzuna\.com/v1/api/jobs/ca/search/1.*").respond(
        json=json.loads((FIXTURES / "adzuna.json").read_text())
    )
    listings = await fetch_adzuna(client, _settings(), "software engineer")

    # 3 results in fixture, one lacks a company → skipped
    assert len(listings) == 2
    first = listings[0]
    assert first.source_type == "adzuna"
    assert first.source_name == "adzuna-ca"
    assert first.company == "Maple Analytics"
    # <strong> markup stripped from title
    assert first.title == "Senior Software Engineer"
    assert first.location == "Toronto, Ontario"
    assert first.posted_at is not None and first.posted_at.tzinfo is not None
    assert "sponsorship" in first.description.lower()


@respx.mock
async def test_jooble_normalization(client):
    respx.post("https://jooble.org/api/test-jooble-key").respond(
        json=json.loads((FIXTURES / "jooble.json").read_text())
    )
    listings = await fetch_jooble(client, _settings(), "machine learning engineer")

    assert len(listings) == 2
    first = listings[0]
    assert first.source_type == "jooble"
    assert first.external_id == "987654321"
    assert first.company == "Laurentide AI"
    # <b> and &nbsp; cleaned out of the snippet
    assert "<b>" not in first.description and "\xa0" not in first.description
    assert "pytorch" in first.description.lower()


@respx.mock
async def test_adzuna_stops_paging_after_short_page(client):
    route = respx.get(url__regex=r"https://api\.adzuna\.com/v1/api/jobs/ca/search/\d.*").respond(
        json=json.loads((FIXTURES / "adzuna.json").read_text())
    )
    await fetch_adzuna(client, _settings(adzuna_pages_per_keyword=3), "software engineer")
    # fixture page has <50 results → treated as the last page, no page 2/3 calls
    assert route.call_count == 1
