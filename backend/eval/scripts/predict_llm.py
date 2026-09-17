"""Run the production LLM extractor over the gold set and cache the results.

Separated from scoring on purpose: predictions cost money, scoring doesn't.
Cached predictions mean the report can be regenerated, re-normalized, or
re-scored for free, and CI can score without an API key.

Usage:
    # cheap validation run first — always do this before spending on all 150
    uv run python -m eval.scripts.predict_llm --config sonnet-nothinking --limit 10

    # the three configs that answer P1's open cost questions
    uv run python -m eval.scripts.predict_llm --config sonnet-nothinking
    uv run python -m eval.scripts.predict_llm --config sonnet-thinking
    uv run python -m eval.scripts.predict_llm --config haiku-nothinking

Each run appends to eval/gold/predictions/{config}.jsonl and skips listings
already predicted for that config, so an interrupted run resumes for free.
"""

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path

from app.extraction.client import ExtractionFailed, extract_one
from app.extraction.cost import price_call
from app.extraction.prompts import PROMPT_VERSION
from app.settings import Settings
from eval.jsonl import read_jsonl
from eval.schemas import GoldExtractionLabel

PREDICTIONS_DIR = Path("eval/gold/predictions")


@dataclass(frozen=True)
class EvalConfig:
    """One extractor configuration under test."""

    name: str
    model: str
    thinking: bool
    effort: str = "low"

    def settings(self) -> Settings:
        return Settings(
            extraction_model=self.model,
            extraction_thinking=self.thinking,
            extraction_effort=self.effort,
            extraction_max_tokens=4096,
        )


# The three configs that answer P1's two open questions: is the cheaper model
# good enough, and is adaptive thinking worth 2x the cost?
CONFIGS: dict[str, EvalConfig] = {
    "sonnet-nothinking": EvalConfig("sonnet-nothinking", "claude-sonnet-5", thinking=False),
    "sonnet-thinking": EvalConfig("sonnet-thinking", "claude-sonnet-5", thinking=True),
    "haiku-nothinking": EvalConfig("haiku-nothinking", "claude-haiku-4-5", thinking=False),
}


def prediction_path(config: str) -> Path:
    return PREDICTIONS_DIR / f"{config}.jsonl"


def load_predictions(config: str, prompt_version: str = PROMPT_VERSION) -> dict[str, dict]:
    """Cached predictions for a config at one prompt version, keyed by listing_id.

    Filtering on prompt_version is not optional bookkeeping. The file is
    append-only across runs, so without it a row from an older prompt would
    count as "already predicted" — the run would skip the listing and the report
    would silently mix two prompts, which is exactly the comparison CLAUDE.md
    requires be kept attributable. Later rows win, so a re-run overwrites.
    """
    path = prediction_path(config)
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open() as f:
        for line in f:
            if line.strip():
                row = json.loads(line)
                if row.get("prompt_version") == prompt_version:
                    out[row["listing_id"]] = row
    return out


async def predict(config: EvalConfig, gold_path: Path, limit: int | None) -> None:
    import anthropic

    if not os.getenv("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY is not set.")

    gold = list(read_jsonl(gold_path, GoldExtractionLabel))
    done = load_predictions(config.name)
    todo = [row for row in gold if row.listing_id not in done]
    if limit:
        todo = todo[:limit]
    if not todo:
        print(f"[{config.name}] nothing to do — {len(done)} predictions already cached")
        return

    print(f"[{config.name}] {len(todo)} to predict ({len(done)} cached), model={config.model} "
          f"thinking={config.thinking}")
    settings = config.settings()
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    spend = Decimal(0)
    failures = 0

    async with anthropic.AsyncAnthropic() as client:
        with prediction_path(config.name).open("a") as sink:
            for i, row in enumerate(todo, 1):
                try:
                    result = await extract_one(
                        client,
                        settings,
                        title=row.title,
                        company=row.company,
                        location=None,
                        description=row.raw_description,
                    )
                except ExtractionFailed as e:
                    failures += 1
                    print(f"  [{i}/{len(todo)}] FAILED {row.listing_id}: {e}")
                    # Record the failure so scoring counts it against the config
                    # rather than silently omitting it.
                    sink.write(
                        json.dumps(
                            {
                                "listing_id": row.listing_id,
                                "config": config.name,
                                "model": config.model,
                                "prompt_version": PROMPT_VERSION,
                                "failed": True,
                                "error": str(e)[:500],
                            }
                        )
                        + "\n"
                    )
                    sink.flush()
                    continue

                cost = price_call(result.model, result.input_tokens, result.output_tokens)
                spend += cost
                sink.write(
                    json.dumps(
                        {
                            "listing_id": row.listing_id,
                            "config": config.name,
                            "model": result.model,
                            "prompt_version": result.prompt_version,
                            "failed": False,
                            "attempts": result.attempts,
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "cost_usd": str(cost),
                            "components": result.components.model_dump(mode="json"),
                        }
                    )
                    + "\n"
                )
                sink.flush()
                if i % 10 == 0 or i == len(todo):
                    print(f"  [{i}/{len(todo)}] spend so far ${spend:.4f}")

    per = spend / len(todo) if todo else Decimal(0)
    print(f"[{config.name}] done — {len(todo) - failures} ok, {failures} failed, "
          f"${spend:.4f} total, ${per:.4f}/listing")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", choices=sorted(CONFIGS), required=True)
    parser.add_argument("--gold", type=Path, default=Path("eval/gold/extraction_skills.jsonl"))
    parser.add_argument(
        "--limit", type=int, default=None, help="cap listings this run (use for a cheap dry run)"
    )
    args = parser.parse_args()
    asyncio.run(predict(CONFIGS[args.config], args.gold, args.limit))


if __name__ == "__main__":
    main()
