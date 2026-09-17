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

from app.extraction.client import extract_one
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
    # effort="" because Haiku 4.5 rejects `output_config` outright rather than
    # ignoring it — the first run of this config failed 150/150 on that alone.
    "haiku-nothinking": EvalConfig(
        "haiku-nothinking", "claude-haiku-4-5", thinking=False, effort=""
    ),
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


async def predict(
    config: EvalConfig, gold_path: Path, limit: int | None, concurrency: int = 6
) -> None:
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
          f"thinking={config.thinking}, concurrency={concurrency}")
    settings = config.settings()
    PREDICTIONS_DIR.mkdir(parents=True, exist_ok=True)
    spend = Decimal(0)
    failures = 0
    finished = 0

    # Bounded concurrency: 450 sequential calls across three configs is over an
    # hour of wall-clock for no reason. Each row is independent and the sink is
    # keyed by listing_id, so order doesn't matter — but writes still need the
    # lock, since two coroutines appending at once would interleave a line.
    gate = asyncio.Semaphore(concurrency)
    write_lock = asyncio.Lock()

    async with anthropic.AsyncAnthropic() as client:
        with prediction_path(config.name).open("a") as sink:

            async def emit(record: dict) -> None:
                async with write_lock:
                    sink.write(json.dumps(record) + "\n")
                    sink.flush()

            async def one(row: GoldExtractionLabel) -> None:
                nonlocal spend, failures, finished
                async with gate:
                    try:
                        result = await extract_one(
                            client,
                            settings,
                            title=row.title,
                            company=row.company,
                            location=None,
                            description=row.raw_description,
                        )
                    except Exception as e:
                        # Deliberately broad. ExtractionFailed is the expected
                        # case, but anything else escaping here used to abort
                        # the whole asyncio.gather — a 150-listing paid run lost
                        # 60% of its work to one bad row, twice. One listing's
                        # failure must never cost the batch.
                        failures += 1
                        finished += 1
                        kind = type(e).__name__
                        print(f"  [{finished}/{len(todo)}] FAILED {row.listing_id}: {kind}: {e}")
                        # Record the failure so scoring counts it against the
                        # config rather than silently omitting it.
                        await emit(
                            {
                                "listing_id": row.listing_id,
                                "config": config.name,
                                "model": config.model,
                                "prompt_version": PROMPT_VERSION,
                                "failed": True,
                                "error": f"{kind}: {e}"[:500],
                            }
                        )
                        return

                    cost = price_call(
                        result.model,
                        result.input_tokens,
                        result.output_tokens,
                        cache_read_tokens=result.cache_read_tokens,
                        cache_write_tokens=result.cache_write_tokens,
                    )
                    spend += cost
                    finished += 1
                    await emit(
                        {
                            "listing_id": row.listing_id,
                            "config": config.name,
                            "model": result.model,
                            "prompt_version": result.prompt_version,
                            "failed": False,
                            "attempts": result.attempts,
                            "input_tokens": result.input_tokens,
                            "output_tokens": result.output_tokens,
                            "cache_read_tokens": result.cache_read_tokens,
                            "cache_write_tokens": result.cache_write_tokens,
                            "cost_usd": str(cost),
                            "components": result.components.model_dump(mode="json"),
                        }
                    )
                    if finished % 10 == 0 or finished == len(todo):
                        print(f"  [{finished}/{len(todo)}] spend so far ${spend:.4f}")

            results = await asyncio.gather(
                *(one(row) for row in todo), return_exceptions=True
            )
            for row, outcome in zip(todo, results, strict=True):
                if isinstance(outcome, BaseException):
                    print(f"  UNRECORDED {row.listing_id}: "
                          f"{type(outcome).__name__}: {outcome}")

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
    parser.add_argument(
        "--concurrency", type=int, default=6, help="in-flight requests (back off on 429s)"
    )
    args = parser.parse_args()
    asyncio.run(predict(CONFIGS[args.config], args.gold, args.limit, args.concurrency))


if __name__ == "__main__":
    main()
