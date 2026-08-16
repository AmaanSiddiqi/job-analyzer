"""Board client normalization against recorded fixtures — no live network.

Fixtures under tests/fixtures/boards/ are trimmed real responses
(knak/greenhouse, waveapps/lever, noibu/ashby) captured 2026-08-16.
"""

import json
from datetime import UTC
from pathlib import Path

import httpx
import pytest
import respx

from app.ingestion.boards import (
    BoardFetchError,
    fetch_ashby,
    fetch_greenhouse,
    fetch_lever,
    html_to_text,
)

FIXTURES = Path(__file__).parent / "fixtures" / "boards"


def _fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture
async def client():
    async with httpx.AsyncClient() as c:
        yield c


@respx.mock
async def test_greenhouse_normalization(client):
    respx.get("https://boards-api.greenhouse.io/v1/boards/knak/jobs?content=true").respond(
        json=_fixture("greenhouse")
    )
    listings = await fetch_greenhouse(client, "knak", "Knak")

    assert len(listings) == 2
    first = listings[0]
    assert first.source_type == "greenhouse"
    assert first.source_name == "knak"
    assert first.company == "Knak"
    assert first.source_url.startswith("http")
    assert first.external_id.isdigit()
    assert first.posted_at is not None and first.posted_at.tzinfo is not None
    # content was entity-escaped HTML — normalization must fully strip it
    assert "&lt;" not in first.description and "<" not in first.description
    assert len(first.description) > 50


@respx.mock
async def test_lever_normalization(client):
    respx.get("https://api.lever.co/v0/postings/waveapps?mode=json").respond(
        json=_fixture("lever")
    )
    listings = await fetch_lever(client, "waveapps", "Wave")

    assert len(listings) == 2
    first = listings[0]
    assert first.source_type == "lever"
    assert first.title
    assert first.location  # from categories.allLocations
    assert first.posted_at is not None and first.posted_at.tzinfo == UTC
    # description assembles the plain-text parts and the HTML lists
    assert "<li>" not in first.description
    assert len(first.description) > 100


@respx.mock
async def test_ashby_normalization_filters_unlisted(client):
    respx.get("https://api.ashbyhq.com/posting-api/job-board/noibu").respond(
        json=_fixture("ashby")
    )
    listings = await fetch_ashby(client, "noibu", "Noibu")

    # fixture has 2 jobs, one with isListed=false
    assert len(listings) == 1
    only = listings[0]
    assert only.source_type == "ashby"
    assert only.payload["isListed"] is True
    assert only.description


@respx.mock
async def test_http_error_raises_board_fetch_error(client):
    respx.get("https://boards-api.greenhouse.io/v1/boards/dead/jobs?content=true").respond(404)
    with pytest.raises(BoardFetchError, match="HTTP 404"):
        await fetch_greenhouse(client, "dead", "Dead Co")


@respx.mock
async def test_bad_payload_raises_board_fetch_error(client):
    respx.get("https://api.lever.co/v0/postings/weird?mode=json").respond(json={"not": "a list"})
    with pytest.raises(BoardFetchError, match="not a postings list"):
        await fetch_lever(client, "weird", "Weird Co")


def test_html_to_text_strips_markup():
    text = html_to_text("<p>Hello <b>world</b></p><ul><li>a</li></ul>")
    assert "<" not in text and ">" not in text
    assert text.split() == ["Hello", "world", "a"]
    assert html_to_text("") == ""
