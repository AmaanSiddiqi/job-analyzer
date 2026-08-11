"""
Keyboard-driven review flow — step (2)/(3) of CLAUDE.md's machine-assisted
labeling protocol.

Selection policy (keeps human time under budget for ~150 items):
  - Every disagreement (annotator vs. baseline_extractor) is queued for
    mandatory manual review.
  - A random 25% of the agreements are also queued, as an audit sample.
  - The remaining 75% of agreements are auto-accepted straight from the
    annotator draft, with human_verified=False and
    verification_method="auto_accept_agreement" — so anyone reading
    eval/gold/extraction_skills.jsonl later can see exactly which rows a
    human actually looked at (CLAUDE.md: "Store a human_verified flag per
    label so published eval claims stay honest").

Reality check: baseline_extractor's vocabulary is a fixed ~200 terms, so
almost any real listing "disagrees" with a richer annotator model just by
mentioning a skill outside that list — the mandatory-disagreement rule can
end up queuing nearly everything, defeating the time-budget point of the
25%-audit design. --sample-size caps the manual queue at N items (seeded
random pick, disagreements first) when that happens; everything outside
the sampled N auto-accepts with verification_method=
"auto_accept_unreviewed_disagreement" instead of "auto_accept_agreement",
so it's still honestly distinguishable in the gold file. Omit --sample-size
to fall back to the full mandatory-disagreement policy as written above.

Resumable: rows already present in --out (by listing_id) are skipped, so
you can review in multiple short sittings instead of one two-hour sprint.

Usage:
    uv run python -m eval.scripts.review_cli \
        --in eval/gold/extraction_skills.draft.jsonl \
        --out eval/gold/extraction_skills.jsonl \
        --sample-size 40
"""

import argparse
import random
import textwrap
from pathlib import Path
from typing import Literal

from eval.jsonl import read_jsonl
from eval.schemas import DraftExtractionLabel, GoldExtractionLabel

AUDIT_SAMPLE_RATE = 0.25


def _print_listing(d: DraftExtractionLabel) -> None:
    print("\n" + "=" * 78)
    print(f"{d.company} — {d.title}  [{d.listing_id}]")
    print("-" * 78)
    snippet = textwrap.shorten(d.raw_description.replace("\n", " "), width=400, placeholder=" …")
    print(snippet)
    print("-" * 78)
    print(f"annotator ({d.annotator_model}): {sorted(d.annotator_skills)}")
    print(f"baseline  (spaCy):              {sorted(d.baseline_skills)}")
    if d.disagreement:
        only_annotator = set(d.annotator_skills) - set(d.baseline_skills)
        only_baseline = set(d.baseline_skills) - set(d.annotator_skills)
        print(f"  DISAGREEMENT — annotator-only: {sorted(only_annotator)}")
        print(f"                 baseline-only:  {sorted(only_baseline)}")


def _prompt(d: DraftExtractionLabel) -> list[str] | Literal["skip", "quit"]:
    choice = input(
        "[Enter]=accept annotator  [b]=accept baseline  [skill,list]=custom  [s]=skip  [q]=quit: "
    ).strip()
    if choice == "":
        return d.annotator_skills
    if choice.lower() == "b":
        return d.baseline_skills
    if choice.lower() == "s":
        return "skip"
    if choice.lower() == "q":
        return "quit"
    return [s.strip().lower() for s in choice.split(",") if s.strip()]


def review(in_path: Path, out_path: Path, seed: int | None, sample_size: int | None) -> None:
    drafts = list(read_jsonl(in_path, DraftExtractionLabel))
    already_done = {g.listing_id for g in read_jsonl(out_path, GoldExtractionLabel)}
    drafts = [d for d in drafts if d.listing_id not in already_done]

    disagreements = [d for d in drafts if d.disagreement]
    agreements = [d for d in drafts if not d.disagreement]

    rng = random.Random(seed)
    audit_sample_ids = {
        d.listing_id for d in rng.sample(agreements, k=round(len(agreements) * AUDIT_SAMPLE_RATE))
    }

    full_manual_queue = disagreements + [d for d in agreements if d.listing_id in audit_sample_ids]
    auto_accept_agreements = [d for d in agreements if d.listing_id not in audit_sample_ids]

    unreviewed_disagreements: list[DraftExtractionLabel] = []
    if sample_size is not None and len(full_manual_queue) > sample_size:
        shuffled = full_manual_queue[:]
        rng.shuffle(shuffled)
        manual_queue = shuffled[:sample_size]
        sampled_ids = {d.listing_id for d in manual_queue}
        unreviewed_disagreements = [d for d in full_manual_queue if d.listing_id not in sampled_ids]
    else:
        manual_queue = full_manual_queue

    print(
        f"{len(drafts)} unreviewed rows: {len(disagreements)} disagreements, "
        f"{len(audit_sample_ids)} random-audited agreements -> "
        f"{len(manual_queue)} queued for manual review, "
        f"{len(auto_accept_agreements)} auto-accepted agreements, "
        f"{len(unreviewed_disagreements)} auto-accepted disagreements (sample-size cap)."
    )

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as f:
        for d in auto_accept_agreements:
            gold = GoldExtractionLabel(
                listing_id=d.listing_id,
                source=d.source,
                title=d.title,
                company=d.company,
                raw_description=d.raw_description,
                skills=d.annotator_skills,
                annotator_model=d.annotator_model,
                human_verified=False,
                verification_method="auto_accept_agreement",
                disagreement_with_baseline=False,
            )
            f.write(gold.model_dump_json() + "\n")

        for d in unreviewed_disagreements:
            gold = GoldExtractionLabel(
                listing_id=d.listing_id,
                source=d.source,
                title=d.title,
                company=d.company,
                raw_description=d.raw_description,
                skills=d.annotator_skills,
                annotator_model=d.annotator_model,
                human_verified=False,
                verification_method="auto_accept_unreviewed_disagreement",
                disagreement_with_baseline=True,
                notes="Disagreement not manually reviewed — excluded by --sample-size cap.",
            )
            f.write(gold.model_dump_json() + "\n")

        for i, d in enumerate(manual_queue, 1):
            _print_listing(d)
            print(f"({i}/{len(manual_queue)} manual review items)")
            result = _prompt(d)
            if result == "quit":
                print(f"Stopping. {i - 1}/{len(manual_queue)} manually reviewed and saved.")
                break
            if result == "skip":
                continue
            skills = result
            gold = GoldExtractionLabel(
                listing_id=d.listing_id,
                source=d.source,
                title=d.title,
                company=d.company,
                raw_description=d.raw_description,
                skills=skills,
                annotator_model=d.annotator_model,
                human_verified=True,
                verification_method="manual_review",
                disagreement_with_baseline=d.disagreement,
            )
            f.write(gold.model_dump_json() + "\n")
            f.flush()

    print(f"\nSaved to {out_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--in", dest="in_path", type=Path, default=Path("eval/gold/extraction_skills.draft.jsonl")
    )
    parser.add_argument("--out", type=Path, default=Path("eval/gold/extraction_skills.jsonl"))
    parser.add_argument(
        "--seed", type=int, default=42, help="audit-sample RNG seed, for reproducibility"
    )
    parser.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="cap the manual-review queue at N items (random, disagreements first) instead of "
        "reviewing every disagreement — see module docstring for why this matters in practice",
    )
    args = parser.parse_args()

    review(args.in_path, args.out, args.seed, args.sample_size)


if __name__ == "__main__":
    main()
