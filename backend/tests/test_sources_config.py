"""companies.yaml loads, validates, and rejects malformed configs. No network."""

import pytest
from pydantic import ValidationError

from sources.config import Company, SourcesConfig, load_companies


def test_real_companies_yaml_loads() -> None:
    config = load_companies()
    assert config.version == 1
    # The reviewed list starts at 65; shrinking below 50 means something broke.
    assert len(config.companies) >= 50


def test_real_companies_yaml_boards_and_tokens_sane() -> None:
    config = load_companies()
    for c in config.companies:
        assert c.board in ("greenhouse", "lever", "ashby")
        # Board tokens are URL path segments — no spaces or slashes.
        assert " " not in c.token and "/" not in c.token


def test_duplicate_board_token_rejected() -> None:
    company = {"name": "A", "hq": "Toronto, ON", "board": "lever", "token": "a"}
    with pytest.raises(ValidationError, match="duplicate board entry"):
        SourcesConfig(
            version=1,
            companies=(
                Company(**company),
                Company(**{**company, "name": "B"}),
            ),
        )


def test_duplicate_name_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate company name"):
        SourcesConfig(
            version=1,
            companies=(
                Company(name="Acme", hq="Toronto, ON", board="lever", token="a"),
                Company(name="acme", hq="Toronto, ON", board="ashby", token="b"),
            ),
        )


def test_unknown_board_rejected() -> None:
    with pytest.raises(ValidationError):
        Company(name="A", hq="Toronto, ON", board="workday", token="a")  # type: ignore[arg-type]


def test_empty_token_rejected() -> None:
    with pytest.raises(ValidationError):
        Company(name="A", hq="Toronto, ON", board="lever", token="   ")
