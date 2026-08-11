"""
Draft-label listings_pool.jsonl with a stronger annotator model (Claude),
compute baseline_extractor's output for the same listings, and flag
disagreements — this is step (1) of CLAUDE.md's machine-assisted labeling
protocol. Output still needs review_cli.py before it's a trustworthy gold
set; nothing here sets human_verified=True.

Usage:
    export ANTHROPIC_API_KEY=...
    uv run python -m eval.scripts.draft_label \
        --in eval/gold/listings_pool.jsonl \
        --out eval/gold/extraction_skills.draft.jsonl

Uses a model different from the production extractor (spaCy PhraseMatcher,
not an LLM at all) by construction — see CLAUDE.md's eval protocol note on
why same-model labeling would be circular.
"""

import argparse
import json
import os
import sys
from pathlib import Path

from app.services.nlp import extract_skills
from eval.jsonl import read_jsonl, write_jsonl
from eval.schemas import DraftExtractionLabel, PoolListing

DEFAULT_MODEL = os.getenv("EVAL_ANNOTATOR_MODEL", "claude-opus-5")

_SYSTEM_PROMPT = """You extract technical skills mentioned in a job posting.

Return ONLY a JSON array of lowercase skill strings — no prose, no markdown
fences. Include programming languages, frameworks, libraries, databases,
cloud/infra tools, and named methodologies (e.g. "ci/cd", "agile") that the
posting explicitly asks for or mentions as used on the team. Do not include
soft skills, degrees, or years-of-experience phrases. Multi-word skills are
fine (e.g. "machine learning", "spring boot"). Deduplicate. If nothing
qualifies, return [].

Example output: ["python", "react", "postgresql", "aws", "ci/cd"]"""


def _call_annotator(client, model: str, description: str) -> list[str]:
    """One call + one retry-with-error-appended, per CLAUDE.md's extraction
    validation rule (schema validation failure -> one retry, then dead-letter).
    Here "dead-letter" just means: log and return [] rather than crash the batch."""
    text = description[:20_000]  # keep prompts bounded; skills rarely hide past this
    last_error = None
    for _attempt in range(2):
        prompt = f"Job posting:\n\n{text}"
        if last_error:
            prompt += (
                f"\n\nYour previous response failed to parse as a JSON array: "
                f"{last_error}. Return ONLY a valid JSON array this time."
            )
        try:
            resp = client.messages.create(
                model=model,
                max_tokens=1024,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = resp.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.strip("`").removeprefix("json").strip()
            skills = json.loads(raw)
            if not isinstance(skills, list):
                raise ValueError("response was not a JSON array")
            return sorted({str(s).strip().lower() for s in skills if str(s).strip()})
        except Exception as e:  # noqa: BLE001 — dead-letter on anything, this is a batch job
            last_error = str(e)
    print(f"  [dead-letter] annotator call failed twice: {last_error}", file=sys.stderr)
    return []


def draft_label(in_path: Path, out_path: Path, model: str, limit: int | None) -> int:
    try:
        import anthropic
    except ImportError:
        print(
            "The 'anthropic' package isn't installed. Run: uv sync --extra eval",
            file=sys.stderr,
        )
        raise SystemExit(1) from None

    if not os.getenv("ANTHROPIC_API_KEY"):
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        raise SystemExit(1)

    client = anthropic.Anthropic()
    pool = list(read_jsonl(in_path, PoolListing))
    if limit:
        pool = pool[:limit]

    drafts: list[DraftExtractionLabel] = []
    for i, listing in enumerate(pool, 1):
        print(f"[{i}/{len(pool)}] {listing.company} — {listing.title}")
        annotator_skills = _call_annotator(client, model, listing.raw_description)
        baseline_skills = extract_skills(listing.raw_description)
        drafts.append(
            DraftExtractionLabel(
                listing_id=listing.listing_id,
                source=listing.source,
                title=listing.title,
                company=listing.company,
                raw_description=listing.raw_description,
                annotator_skills=annotator_skills,
                baseline_skills=baseline_skills,
                disagreement=set(annotator_skills) != set(baseline_skills),
                annotator_model=model,
            )
        )

    write_jsonl(out_path, drafts)
    n_disagree = sum(d.disagreement for d in drafts)
    print(f"\nWrote {len(drafts)} draft labels to {out_path} ({n_disagree} disagree with baseline)")
    return len(drafts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="in_path", type=Path, default=Path("eval/gold/listings_pool.jsonl"))
    parser.add_argument("--out", type=Path, default=Path("eval/gold/extraction_skills.draft.jsonl"))
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="cap listings processed (e.g. for a dry run)")
    args = parser.parse_args()

    draft_label(args.in_path, args.out, args.model, args.limit)


if __name__ == "__main__":
    main()
