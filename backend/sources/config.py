"""Typed loader for sources/companies.yaml.

The YAML is the reviewed, canonical list of company job boards we ingest
from. Ingestion code (P1 PR: board clients) consumes `load_companies()`;
nothing should read the YAML directly.
"""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

BoardType = Literal["greenhouse", "lever", "ashby"]

_DEFAULT_PATH = Path(__file__).parent / "companies.yaml"


class Company(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    hq: str
    board: BoardType
    token: str

    @field_validator("name", "hq", "token")
    @classmethod
    def _non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("must be non-empty")
        return v.strip()


class SourcesConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: int
    companies: tuple[Company, ...]

    @model_validator(mode="after")
    def _no_duplicates(self) -> "SourcesConfig":
        seen_boards: set[tuple[str, str]] = set()
        seen_names: set[str] = set()
        for c in self.companies:
            key = (c.board, c.token)
            if key in seen_boards:
                raise ValueError(f"duplicate board entry: {c.board}/{c.token}")
            seen_boards.add(key)
            name = c.name.lower()
            if name in seen_names:
                raise ValueError(f"duplicate company name: {c.name}")
            seen_names.add(name)
        return self


def load_companies(path: Path = _DEFAULT_PATH) -> SourcesConfig:
    with path.open() as f:
        data = yaml.safe_load(f)
    return SourcesConfig.model_validate(data)
