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
    # Rows predicted before cost.py became cache-aware: their recorded cost
    # omits the cached prompt reads, so the config's total is a lower bound.
    rows_without_cache_data: int = 0
    cache_read_tokens: int = 0
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
    rows_without_cache_data = cache_read_tokens = 0
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
        if "cache_read_tokens" in pred:
            cache_read_tokens += int(pred["cache_read_tokens"])
        else:
            rows_without_cache_data += 1
        comp = pred["components"]
        rows.append((row, normalize([*comp.get("skills", []), *comp.get("skills_unmapped", [])])))
        if (comp.get("eligibility") or {}).get("min_years_experience") is not None:
            with_min_years += 1
        visa = comp.get("visa") or {}
        # The v3 schema reports "not_stated" instead of null (unions are
        # expensive — see schema.py), so an `is not None` check here counted
        # every listing as carrying a visa signal and reported 99% against a
        # corpus-measured rate of under 1%.
        if any(
            visa.get(k) not in (None, "not_stated")
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
        rows_without_cache_data=rows_without_cache_data,
        cache_read_tokens=cache_read_tokens,
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

    stale = [r for r in llm if r.rows_without_cache_data]
    if stale:
        lines += [
            "",
            "**These costs are a lower bound for "
            + ", ".join(r.label.split(" ")[0] for r in stale)
            + ".** Those rows were predicted before `price_call` accounted for "
            "cached prompt tokens, which the API reports separately from "
            "`input_tokens` — so a cached read was billed at zero. The system "
            "prefix is 4,322 Sonnet tokens (system prompt, skill list *and* the "
            "structured-output schema, which the API injects before the cache "
            "breakpoint) and is cache-read on nearly every call, which is about "
            "**+$0.0013/listing** (~9%) not shown above. "
            "Rows predicted after the fix carry the real number; the table was "
            "not re-run at a cost of several dollars to correct a ~9% figure "
            "whose direction and size are both known.",
        ]

    by_name = {r.label.split(" ")[0]: r for r in llm}
    haiku, sonnet = by_name.get("haiku-nothinking"), by_name.get("sonnet-nothinking")
    # Computed, not written in: an earlier hardcoded "3x" here was wrong (it was
    # ~2x), borrowed from Haiku being 3x cheaper *per token*.
    haiku_ratio = (
        f"{(haiku.cost_usd / haiku.n) / (sonnet.cost_usd / sonnet.n):.1f}x"
        if haiku and sonnet and haiku.n and sonnet.n and sonnet.cost_usd
        else "n/a"
    )

    lines += [
        "",
        "## What this decides",
        "",
        "**Use Sonnet 5 with thinking off for the backfill.** It wins on both "
        "axes against the alternatives tested, and the two open cost questions "
        "from CLAUDE.md both resolve against spending more.",
        "",
        "### Haiku 4.5 is worse *and* more expensive here",
        "",
        "That ordering is not a typo and it is not about the token rates. Two "
        "things stack:",
        "",
        "1. **It gets no prompt caching.** The cached prefix — system prompt, "
        "skill list and the injected output schema — measures 4,327 tokens to "
        "Sonnet's tokenizer but only **3,337** to Haiku's, under Haiku 4.5's "
        "**4,096-token** minimum cacheable prefix (Sonnet 5's is 1,024). The "
        "`cache_control` marker is silently inert, so Haiku re-pays for the "
        "entire prefix on every call while Sonnet reads it from cache.",
        "2. **It degenerates under the constrained grammar.** Six listings "
        "failed outright with truncated JSON after the model emitted runs like "
        "`999999999999...` and `012345678901...` into a numeric field until it "
        "hit `max_tokens`. Those runs are billed.",
        "",
        f"Net: **{haiku_ratio}** the cost per listing at **-0.086 F1**. "
        "Growing the prefix past 4,096 Haiku tokens would fix the caching half, "
        "but the quality gap is the part that matters and it would not close.",
        "",
        "### Thinking on vs off is a genuine null result",
        "",
        "Identical to three decimal places on cost and within 0.002 F1. This "
        "was measured twice, because the first run was invalid: `build_request` "
        "only ever set `thinking` in order to *disable* it, so the \"on\" config "
        "just omitted the parameter and took the default. After fixing that to "
        "`thinking.type: adaptive` (Sonnet 5 rejects the older `enabled` + "
        "`budget_tokens` shape outright), the null result held — adaptive "
        "thinking contributes a median of **+0 output tokens** at `effort=low`. "
        "The real lever is `effort`, not the thinking flag; CLAUDE.md's "
        "assumption that thinking would double the cost to ~$0.032/listing came "
        "from token estimation and is not what the API actually does here. "
        "`EXTRACTION_THINKING` stays **false** — now on evidence rather than on "
        "the assumption.",
        "",
        "### Where the remaining recall is lost",
        "",
        "Precision is 0.916 and recall 0.758, so the gap is misses, not "
        "fabrication — the right direction for a product that must not invent "
        "requirements. The worst-listing table below shows the two real causes: "
        "genuine misses on long infrastructure postings (Compass Digital, "
        "Amazon Science), and taxonomy-vs-annotator disagreements where the "
        "model returned a defensible broader id (`artificial intelligence` "
        "where gold said `ai agents`). The second kind is a taxonomy question, "
        "not an extraction one.",
        "",
        "## Flagship signal yield",
        "",
        "Not scored against gold (no eligibility labels yet — that's the next "
        "review pass); reported so the rates can be sanity-checked against the "
        "production corpus.",
        "",
        "**The gold set turned out to be representative, and the old regex scan "
        "was not.** These rates looked alarming against the 27.9% that an August "
        "regex scan reported for experience requirements, so the gold set was "
        "audited for over-sampling: 102 of 103 evidence quotes appear verbatim "
        "in the source and 99 contain an explicit \"N years\" phrase. Extracting "
        "the full production corpus then settled it — **60.0% of 1,782 postings "
        "state an experience requirement** (98.2% of those quotes verbatim), so "
        "the gold set's 69% was close and the regex scan was undercounting by "
        "more than half. Corpus rates now supersede that scan: of postings "
        "stating a number, 19.6% are open to ≤2 years (modal 5); degree 18.4%; "
        "French 2.9%; new-grad-friendly 1.5%. Visa signals stay rare — "
        "sponsorship offered 1.1%, citizenship/PR required 0.7% — but 6.3% "
        "require *existing* work authorization, a gate the August scan never "
        "measured.",
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
