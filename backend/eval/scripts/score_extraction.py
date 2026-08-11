"""
Score baseline_extractor against a gold set: per-listing set-based P/R/F1 on
`skills`, aggregated micro and macro, rendered to a markdown report.

Usage:
    uv run python -m eval.scripts.score_extraction \
        --gold eval/gold/extraction_skills.jsonl \
        --report reports/extraction_eval.md

    # CI / no DB / no API key needed:
    uv run python -m eval.scripts.score_extraction \
        --gold eval/fixtures/smoke_listings.jsonl \
        --report reports/extraction_eval_smoke.md
"""

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from app.services.nlp import extract_skills
from eval.jsonl import read_jsonl
from eval.schemas import GoldExtractionLabel


@dataclass
class RowScore:
    listing_id: str
    company: str
    title: str
    precision: float
    recall: float
    f1: float
    human_verified: bool
    false_positives: list[str] = field(default_factory=list)
    false_negatives: list[str] = field(default_factory=list)


@dataclass
class ScoreResults:
    n: int
    n_human_verified: int
    micro: tuple[float, float, float]  # precision, recall, f1
    macro: tuple[float, float, float]
    per_row: list[RowScore]


def _prf1(predicted: set[str], gold: set[str]) -> tuple[float, float, float]:
    if not predicted and not gold:
        return 1.0, 1.0, 1.0
    tp = len(predicted & gold)
    precision = tp / len(predicted) if predicted else 0.0
    recall = tp / len(gold) if gold else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def score(gold_path: Path) -> ScoreResults:
    gold_rows = list(read_jsonl(gold_path, GoldExtractionLabel))
    if not gold_rows:
        raise SystemExit(f"No gold rows found in {gold_path}. Run eval-review first.")

    per_row: list[RowScore] = []
    tp_total = fp_total = fn_total = 0
    for row in gold_rows:
        predicted = set(extract_skills(row.raw_description))
        gold_skills = set(row.skills)
        precision, recall, f1 = _prf1(predicted, gold_skills)
        per_row.append(
            RowScore(
                listing_id=row.listing_id,
                company=row.company,
                title=row.title,
                precision=precision,
                recall=recall,
                f1=f1,
                human_verified=row.human_verified,
                false_positives=sorted(predicted - gold_skills),
                false_negatives=sorted(gold_skills - predicted),
            )
        )
        tp_total += len(predicted & gold_skills)
        fp_total += len(predicted - gold_skills)
        fn_total += len(gold_skills - predicted)

    micro_p = tp_total / (tp_total + fp_total) if (tp_total + fp_total) else 0.0
    micro_r = tp_total / (tp_total + fn_total) if (tp_total + fn_total) else 0.0
    micro_f1 = 2 * micro_p * micro_r / (micro_p + micro_r) if (micro_p + micro_r) else 0.0
    macro_p = sum(r.precision for r in per_row) / len(per_row)
    macro_r = sum(r.recall for r in per_row) / len(per_row)
    macro_f1 = sum(r.f1 for r in per_row) / len(per_row)
    n_verified = sum(r.human_verified for r in per_row)

    return ScoreResults(
        n=len(per_row),
        n_human_verified=n_verified,
        micro=(micro_p, micro_r, micro_f1),
        macro=(macro_p, macro_r, macro_f1),
        per_row=per_row,
    )


def render_report(results: ScoreResults, gold_path: Path) -> str:
    micro_p, micro_r, micro_f1 = results.micro
    macro_p, macro_r, macro_f1 = results.macro
    lines = [
        "# Extraction eval — baseline_extractor (spaCy)",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} against `{gold_path}`",
        "",
        f"**{results.n} listings** — **{results.n_human_verified}/{results.n} "
        f"human-verified** ({results.n_human_verified / results.n:.0%}). "
        "Numbers below cover all rows; treat auto-accepted rows as a weaker signal "
        "than the human-verified subset when the two diverge.",
        "",
        "| Metric | Precision | Recall | F1 |",
        "|---|---|---|---|",
        f"| Micro (pooled) | {micro_p:.3f} | {micro_r:.3f} | {micro_f1:.3f} |",
        f"| Macro (per-listing avg) | {macro_p:.3f} | {macro_r:.3f} | {macro_f1:.3f} |",
        "",
        "## Worst listings by F1",
        "",
        "| Listing | F1 | False positives | False negatives |",
        "|---|---|---|---|",
    ]
    worst = sorted(results.per_row, key=lambda r: r.f1)[:15]
    for r in worst:
        fp = ", ".join(r.false_positives) or "—"
        fn = ", ".join(r.false_negatives) or "—"
        lines.append(f"| {r.company} — {r.title} | {r.f1:.2f} | {fp} | {fn} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    results = score(args.gold)
    report = render_report(results, args.gold)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")

    print(report)
    print(f"\nReport written to {args.report}")


if __name__ == "__main__":
    main()
