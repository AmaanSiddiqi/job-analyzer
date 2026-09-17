"""Score cached LLM predictions against the gold set, versus the spaCy baseline.

Needs no API key and no DB — it reads eval/gold/predictions/*.jsonl, so the
report can be regenerated freely.

**The comparison is only fair after normalization.** Gold labels are free-form
strings from the annotator ("data modelling", "Node.js"), the baseline emits its
own ~130-term vocabulary, and the LLM emits canonical taxonomy ids. Comparing
raw strings would score spelling, not extraction. So every set — gold,
baseline, LLM — is mapped through taxonomy/skills.yaml before scoring, and the
baseline's *raw* number is also reported so the frozen 0.460 stays traceable.

Usage:
    uv run python -m eval.scripts.score_llm --report ../reports/extraction_eval_llm.md
"""

import argparse
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from app.services.nlp import extract_skills
from eval.jsonl import read_jsonl
from eval.schemas import GoldExtractionLabel
from eval.scripts.predict_llm import CONFIGS, load_predictions
from taxonomy.config import get_normalizer


def normalize(skills: list[str]) -> set[str]:
    """Canonical ids only. Unmappable strings are dropped from both sides of
    the comparison, so no extractor is penalized for a gap in the taxonomy."""
    mapped, _ = get_normalizer().normalize(skills)
    return set(mapped)


def prf1(predicted: set[str], gold: set[str]) -> tuple[float, float, float]:
    if not predicted and not gold:
        return 1.0, 1.0, 1.0
    tp = len(predicted & gold)
    p = tp / len(predicted) if predicted else 0.0
    r = tp / len(gold) if gold else 0.0
    f1 = 2 * p * r / (p + r) if (p + r) else 0.0
    return p, r, f1


@dataclass
class Scored:
    label: str
    n: int
    n_human_verified: int
    micro: tuple[float, float, float]
    macro: tuple[float, float, float]
    verified_micro: tuple[float, float, float]
    failures: int = 0
    cost_usd: Decimal = Decimal(0)
    retries: int = 0
    # eligibility/visa yield — not scored against gold (no labels yet), but
    # reported so the flagship signal's hit rate is visible
    with_min_years: int = 0
    with_visa: int = 0
    worst: list[tuple[str, float, list[str], list[str]]] = field(default_factory=list)


def _aggregate(
    label: str, rows: list[tuple[GoldExtractionLabel, set[str]]], **extra
) -> Scored:
    tp = fp = fn = 0
    vtp = vfp = vfn = 0
    macro: list[tuple[float, float, float]] = []
    worst: list[tuple[str, float, list[str], list[str]]] = []
    for gold_row, predicted in rows:
        gold_set = normalize(gold_row.skills)
        p, r, f1 = prf1(predicted, gold_set)
        macro.append((p, r, f1))
        tp += len(predicted & gold_set)
        fp += len(predicted - gold_set)
        fn += len(gold_set - predicted)
        if gold_row.human_verified:
            vtp += len(predicted & gold_set)
            vfp += len(predicted - gold_set)
            vfn += len(gold_set - predicted)
        worst.append(
            (
                f"{gold_row.company} — {gold_row.title}"[:60],
                f1,
                sorted(predicted - gold_set)[:6],
                sorted(gold_set - predicted)[:6],
            )
        )

    n = len(rows)
    return Scored(
        label=label,
        n=n,
        n_human_verified=sum(1 for g, _ in rows if g.human_verified),
        micro=_micro(tp, fp, fn),
        macro=(
            sum(m[0] for m in macro) / n,
            sum(m[1] for m in macro) / n,
            sum(m[2] for m in macro) / n,
        ),
        verified_micro=_micro(vtp, vfp, vfn),
        worst=sorted(worst, key=lambda w: w[1])[:10],
        **extra,
    )


def _micro(tp: int, fp: int, fn: int) -> tuple[float, float, float]:
    p = tp / (tp + fp) if (tp + fp) else 0.0
    r = tp / (tp + fn) if (tp + fn) else 0.0
    return p, r, (2 * p * r / (p + r) if (p + r) else 0.0)


def score_baseline_raw(gold: list[GoldExtractionLabel]) -> Scored:
    """The frozen P0 comparison: raw strings on both sides, no normalization.

    Kept only so the historical F1 0.460 stays reproducible from this harness.
    It scores spelling as much as extraction, which is why every other row in
    the report is normalized.
    """
    tp = fp = fn = 0
    macro: list[tuple[float, float, float]] = []
    for row in gold:
        predicted = set(extract_skills(row.raw_description))
        gold_set = set(row.skills)
        macro.append(prf1(predicted, gold_set))
        tp += len(predicted & gold_set)
        fp += len(predicted - gold_set)
        fn += len(gold_set - predicted)
    n = len(gold)
    return Scored(
        label="baseline_extractor (spaCy), raw strings — the frozen P0 number",
        n=n,
        n_human_verified=sum(1 for g in gold if g.human_verified),
        micro=_micro(tp, fp, fn),
        macro=(
            sum(m[0] for m in macro) / n,
            sum(m[1] for m in macro) / n,
            sum(m[2] for m in macro) / n,
        ),
        verified_micro=(0.0, 0.0, 0.0),
    )


def score_baseline_normalized(gold: list[GoldExtractionLabel]) -> Scored:
    """Baseline mapped through the taxonomy — the apples-to-apples comparison."""
    rows = [(row, normalize(extract_skills(row.raw_description))) for row in gold]
    return _aggregate("baseline_extractor (spaCy), normalized", rows)


def score_config(gold: list[GoldExtractionLabel], config_name: str) -> Scored | None:
    preds = load_predictions(config_name)
    if not preds:
        return None
    rows: list[tuple[GoldExtractionLabel, set[str]]] = []
    failures = 0
    cost = Decimal(0)
    retries = 0
    with_min_years = with_visa = 0
    for row in gold:
        pred = preds.get(row.listing_id)
        if pred is None:
            continue  # not predicted yet (partial run) — excluded, not counted
        if pred.get("failed"):
            failures += 1
            # A failed extraction predicts nothing: counts as total recall loss
            # for this listing rather than being quietly dropped.
            rows.append((row, set()))
            continue
        cost += Decimal(pred.get("cost_usd", "0"))
        retries += max(0, int(pred.get("attempts", 1)) - 1)
        comp = pred["components"]
        rows.append((row, normalize([*comp.get("skills", []), *comp.get("skills_unmapped", [])])))
        if (comp.get("eligibility") or {}).get("min_years_experience") is not None:
            with_min_years += 1
        visa = comp.get("visa") or {}
        if any(
            visa.get(k) is not None
            for k in (
                "sponsorship_available",
                "requires_existing_authorization",
                "citizenship_or_pr_required",
            )
        ):
            with_visa += 1
    if not rows:
        return None
    cfg = CONFIGS[config_name]
    return _aggregate(
        f"{config_name} ({cfg.model}, thinking={'on' if cfg.thinking else 'off'})",
        rows,
        failures=failures,
        cost_usd=cost,
        retries=retries,
        with_min_years=with_min_years,
        with_visa=with_visa,
    )


def render(results: list[Scored], baseline_raw: Scored, gold_path: Path) -> str:
    llm = [r for r in results if r.label.startswith(("sonnet", "haiku"))]
    best = max(llm, key=lambda r: r.micro[2]) if llm else None
    n = results[0].n if results else 0
    verified = results[0].n_human_verified if results else 0

    lines = [
        "# Extraction eval — LLM vs frozen spaCy baseline",
        "",
        f"Generated {datetime.now(UTC).isoformat(timespec='seconds')} against `{gold_path}`",
        "",
        f"**{n} listings scored** — {verified}/{n} human-verified "
        f"({verified / n:.0%} if n>0). Treat auto-accepted rows as a weaker signal.",
        "",
        "## Headline",
        "",
    ]
    if best:
        delta = best.micro[2] - baseline_raw.micro[2]
        lines += [
            f"Best configuration: **{best.label}** — micro F1 **{best.micro[2]:.3f}** "
            f"vs the frozen baseline's **{baseline_raw.micro[2]:.3f}** "
            f"(**{delta:+.3f}**).",
            "",
        ]
    lines += [
        "| Extractor | Precision | Recall | F1 | F1 (human-verified only) | Cost | Failures |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in [baseline_raw, *results]:
        cost = f"${r.cost_usd:.4f}" if r.cost_usd else "—"
        vf1 = f"{r.verified_micro[2]:.3f}" if r.verified_micro[2] else "—"
        lines.append(
            f"| {r.label} | {r.micro[0]:.3f} | {r.micro[1]:.3f} | {r.micro[2]:.3f} "
            f"| {vf1} | {cost} | {r.failures} |"
        )

    lines += [
        "",
        "### Why two baseline rows",
        "",
        "The frozen P0 number (F1 0.460) compared *raw strings*: the baseline's "
        "vocabulary against the annotator's free-form labels. That scores spelling "
        "as much as extraction — `data modelling` vs `data modeling` counts as a "
        "miss. The normalized row maps every extractor through "
        "`taxonomy/skills.yaml` first, which is the apples-to-apples comparison; "
        "both are shown so the historical number stays traceable.",
        "",
        "## Cost projection (measured, not estimated)",
        "",
        "| Config | $/listing | 7,200-listing backfill | via Batch API (50%) |",
        "|---|---|---|---|",
    ]
    for r in llm:
        per = r.cost_usd / r.n if r.n else Decimal(0)
        lines.append(
            f"| {r.label} | ${per:.4f} | ${per * 7200:.0f} | ${per * 7200 / 2:.0f} |"
        )

    lines += [
        "",
        "## Flagship signal yield",
        "",
        "Not scored against gold (no eligibility labels yet — that's the next "
        "review pass); reported so the rates can be sanity-checked against the "
        "corpus-wide regex scan that motivated the pivot (experience stated in "
        "27.9% of postings, visa signals <1%).",
        "",
        "| Config | listings with min_years_experience | with any visa signal |",
        "|---|---|---|",
    ]
    for r in llm:
        lines.append(
            f"| {r.label} | {r.with_min_years}/{r.n} ({100 * r.with_min_years / r.n:.0f}%) "
            f"| {r.with_visa}/{r.n} ({100 * r.with_visa / r.n:.0f}%) |"
        )

    if best:
        lines += ["", f"## Worst listings — {best.label}", "",
                  "| Listing | F1 | False positives | False negatives |", "|---|---|---|---|"]
        for name, f1, fps, fns in best.worst:
            lines.append(f"| {name} | {f1:.2f} | {', '.join(fps) or '—'} | {', '.join(fns) or '—'} |")
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=Path("eval/gold/extraction_skills.jsonl"))
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()

    gold = list(read_jsonl(args.gold, GoldExtractionLabel))
    if not gold:
        raise SystemExit(f"no gold rows in {args.gold}")

    # Only score listings that at least one config actually predicted, so a
    # partial (cheap) run reports honestly on its own subset.
    predicted_ids = set()
    for name in CONFIGS:
        predicted_ids |= set(load_predictions(name))
    scored_gold = [g for g in gold if g.listing_id in predicted_ids] or gold

    baseline_raw = score_baseline_raw(scored_gold)
    results = [score_baseline_normalized(scored_gold)]
    for name in sorted(CONFIGS):
        s = score_config(scored_gold, name)
        if s:
            results.append(s)

    if len(results) == 1:
        raise SystemExit(
            "No LLM predictions found. Run: uv run python -m eval.scripts.predict_llm "
            "--config sonnet-nothinking --limit 10"
        )

    report = render(results, baseline_raw, args.gold)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report, encoding="utf-8")
    print(report)
    print(f"\nReport written to {args.report}")


if __name__ == "__main__":
    main()
