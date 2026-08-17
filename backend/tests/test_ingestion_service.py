"""Ingestion service: location filter, content hash, and a full run over
respx-mocked boards with a mock DB session. No live network, no Postgres."""

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import httpx  # noqa: F401  — respx activates against httpx's transport
import pytest
import respx

from app.ingestion.service import content_hash, looks_canadian, run_board_ingestion
from app.settings import get_settings
from sources.config import Company

FIXTURES = Path(__file__).parent / "fixtures" / "boards"


@pytest.fixture(autouse=True)
def _fresh_settings(monkeypatch):
    """Each test gets Settings rebuilt from its own env."""
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


class TestLooksCanadian:
    @pytest.mark.parametrize(
        "location",
        [
            "Toronto, Ontario",
            "Ottawa, Canada",
            "Remote (Canada)",
            "Canada Remote",
            "KOHO (CAN)",
            "Kitchener-Waterloo, ON",
            "Montréal, QC",
            "Vancouver, British Columbia",
            "Remote",  # bare remote with no foreign scope → keep
            None,  # unknown → keep
        ],
    )
    def test_keeps(self, location):
        assert looks_canadian(location)

    @pytest.mark.parametrize(
        "location",
        [
            "San Francisco, CA",
            "New York, NY",
            "Remote US",
            "Remote - USA",
            "London, England, United Kingdom",
            "Berlin, Germany",
            "EMEA - Remote",
            # foreign city + remote tag must not slip through the remote path
            "Amsterdam | Remote",
            "Tokyo | Remote",
            "Washington, DC | Remote",
            "Korea | Remote",
            # Victoria the Australian state, not Victoria BC
            "Melbourne, Victoria",
            "Santiago | Latin America",
            "Cambridge, MA | Massachusetts",
            "Remote in the US | Remote",
            "USA, Remote",
            # qualified remote: naming a place scopes the role there, even when
            # the country isn't in the foreign list
            "Remote Saudi Arabia",
            "Remote, KSA",
            "Remote - Nairobi",
            # unrecognized place beside a remote tag = scoped there
            "Hamburg | Remote",
            "Manila | Remote",
            # US state codes
            "Pittsburgh, PA",
            "Lenexa, KS",
            "New Castle, CO",
            "新北市, New Taipei City, Taiwan",
        ],
    )
    def test_drops(self, location):
        assert not looks_canadian(location)

    @pytest.mark.parametrize(
        "location",
        [
            # Canadian places outside the city list must not be dropped by the
            # unrecognized-place rule (no remote qualifier → lean keep)
            "Pointe Claire",
            "Laval",
            "Angus, ON",
            "TBD",
            "Grocery Ont-East",
        ],
    )
    def test_unrecognized_place_without_remote_leans_keep(self, location):
        assert looks_canadian(location)

    @pytest.mark.parametrize(
        "location",
        [
            "Remote",  # unqualified remote stays unknown → keep
            "Remote - Hybrid",
            "Remote, North America",  # region includes Canada
            "Americas | Remote",
        ],
    )
    def test_unqualified_or_ca_inclusive_remote_keeps(self, location):
        assert looks_canadian(location)

    def test_us_word_boundary_does_not_hit_australia(self):
        # "AUStralia" contains "us" — must be caught by the country name,
        # not by a substring US match misfiring on arbitrary text
        assert not looks_canadian("Sydney, Australia")
        assert looks_canadian("Angus, ON")  # "us" inside a word never matches

    @pytest.mark.parametrize(
        "location",
        [
            # any Canadian segment rescues a multi-location listing
            "Toronto | San Francisco | New York | Remote",
            "United States | Canada | Remote",
            "London, ON",  # province code beats the foreign city list
            "Montreal | Remote",
        ],
    )
    def test_multi_location_keeps(self, location):
        assert looks_canadian(location)


class TestContentHash:
    def test_stable_under_whitespace_and_case(self):
        a = content_hash("Engineer", "Acme", "Toronto, ON", "Build   things")
        b = content_hash("engineer", "ACME", "toronto,  on", "build things")
        assert a == b

    def test_changes_when_description_changes(self):
        a = content_hash("Engineer", "Acme", "Toronto, ON", "v1")
        b = content_hash("Engineer", "Acme", "Toronto, ON", "v2")
        assert a != b


def _mock_db():
    """AsyncSession stand-in whose execute() reports rowcount=1 (row inserted)."""
    session = AsyncMock()
    result = MagicMock()
    result.rowcount = 1
    session.execute = AsyncMock(return_value=result)
    return session


def _companies():
    return (
        Company(name="Knak", hq="Ottawa, ON", board="greenhouse", token="knak"),
        Company(name="Wave", hq="Toronto, ON", board="lever", token="waveapps"),
        Company(name="Noibu", hq="Ottawa, ON", board="ashby", token="noibu"),
    )


def _mount_fixtures():
    respx.get("https://boards-api.greenhouse.io/v1/boards/knak/jobs?content=true").respond(
        json=json.loads((FIXTURES / "greenhouse.json").read_text())
    )
    respx.get("https://api.lever.co/v0/postings/waveapps?mode=json").respond(
        json=json.loads((FIXTURES / "lever.json").read_text())
    )
    respx.get("https://api.ashbyhq.com/posting-api/job-board/noibu").respond(
        json=json.loads((FIXTURES / "ashby.json").read_text())
    )


@respx.mock
async def test_full_run_counts_and_writes(monkeypatch):
    monkeypatch.setenv("BOARD_CANADA_ONLY", "true")
    _mount_fixtures()
    db = _mock_db()

    counts = await run_board_ingestion(db, companies=_companies())

    assert set(counts) == {"greenhouse", "lever", "ashby"}
    assert counts["greenhouse"].fetched == 2
    assert counts["lever"].fetched == 2
    assert counts["ashby"].fetched == 1  # unlisted job filtered by the client
    total_kept = sum(c.kept for c in counts.values())
    assert total_kept >= 1
    # two INSERTs (raw + posting) per kept listing, then one commit
    assert db.execute.await_count == 2 * total_kept
    db.commit.assert_awaited_once()
    assert all(c.failed_boards == [] for c in counts.values())


@respx.mock
async def test_failed_board_does_not_abort_run():
    respx.get("https://boards-api.greenhouse.io/v1/boards/knak/jobs?content=true").respond(500)
    respx.get("https://api.lever.co/v0/postings/waveapps?mode=json").respond(
        json=json.loads((FIXTURES / "lever.json").read_text())
    )
    respx.get("https://api.ashbyhq.com/posting-api/job-board/noibu").respond(
        json=json.loads((FIXTURES / "ashby.json").read_text())
    )
    db = _mock_db()

    counts = await run_board_ingestion(db, companies=_companies())

    assert counts["greenhouse"].failed_boards == ["knak"]
    assert counts["greenhouse"].fetched == 0
    assert counts["lever"].fetched == 2  # run continued past the failure
    db.commit.assert_awaited_once()


@respx.mock
async def test_canada_filter_off_keeps_everything(monkeypatch):
    monkeypatch.setenv("BOARD_CANADA_ONLY", "false")
    _mount_fixtures()
    db = _mock_db()

    counts = await run_board_ingestion(db, companies=_companies())

    assert all(c.filtered_location == 0 for c in counts.values())
    assert sum(c.kept for c in counts.values()) == sum(c.fetched for c in counts.values())
