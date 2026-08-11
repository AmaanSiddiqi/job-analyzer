"""Tiny JSONL read/write helpers shared by the eval scripts."""

from collections.abc import Iterator, Sequence
from pathlib import Path

from pydantic import BaseModel


def read_jsonl[T: BaseModel](path: Path, model: type[T]) -> Iterator[T]:
    if not path.exists():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                yield model.model_validate_json(line)


def write_jsonl(path: Path, rows: Sequence[BaseModel], append: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        for row in rows:
            f.write(row.model_dump_json() + "\n")
