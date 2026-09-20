# Extraction eval — LLM vs frozen spaCy baseline

Generated 2026-09-20T08:36:13+00:00 against `eval/gold/extraction_skills.jsonl`

**150 listings scored** — 40/150 human-verified (27% if n>0). Treat auto-accepted rows as a weaker signal.

## Headline

Best configuration: **sonnet-nothinking (claude-sonnet-5, thinking=off)** — micro F1 **0.830** vs the frozen baseline's **0.460** (**+0.370**).

| Extractor | Precision | Recall | F1 | F1 (human-verified only) | Cost | Failures |
|---|---|---|---|---|---|---|
| baseline_extractor (spaCy), raw strings — the frozen P0 number | 0.874 | 0.312 | 0.460 | — | — | 0 |
| baseline_extractor (spaCy), normalized | 0.928 | 0.503 | 0.652 | 0.664 | — | 0 |
| haiku-nothinking (claude-haiku-4-5, thinking=off) | 0.864 | 0.654 | 0.744 | 0.727 | $4.1196 | 6 |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | 0.916 | 0.758 | 0.830 | 0.844 | $2.0852 | 1 |
| sonnet-thinking (claude-sonnet-5, thinking=on) | 0.913 | 0.757 | 0.828 | 0.845 | $2.0711 | 1 |

### Why two baseline rows

The frozen P0 number (F1 0.460) compared *raw strings*: the baseline's vocabulary against the annotator's free-form labels. That scores spelling as much as extraction — `data modelling` vs `data modeling` counts as a miss. The normalized row maps every extractor through `taxonomy/skills.yaml` first, which is the apples-to-apples comparison; both are shown so the historical number stays traceable.

## Cost projection (measured, not estimated)

| Config | $/listing | 7,200-listing backfill | via Batch API (50%) |
|---|---|---|---|
| haiku-nothinking (claude-haiku-4-5, thinking=off) | $0.0275 | $198 | $99 |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | $0.0139 | $100 | $50 |
| sonnet-thinking (claude-sonnet-5, thinking=on) | $0.0138 | $99 | $50 |

**These costs are a lower bound for haiku-nothinking, sonnet-nothinking, sonnet-thinking.** Those rows were predicted before `price_call` accounted for cached prompt tokens, which the API reports separately from `input_tokens` — so a cached read was billed at zero. The system prefix is 4,322 Sonnet tokens (system prompt, skill list *and* the structured-output schema, which the API injects before the cache breakpoint) and is cache-read on nearly every call, which is about **+$0.0013/listing** (~9%) not shown above. Rows predicted after the fix carry the real number; the table was not re-run at a cost of several dollars to correct a ~9% figure whose direction and size are both known.

## What this decides

**Use Sonnet 5 with thinking off for the backfill.** It wins on both axes against the alternatives tested, and the two open cost questions from CLAUDE.md both resolve against spending more.

### Haiku 4.5 is worse *and* more expensive here

That ordering is not a typo and it is not about the token rates. Two things stack:

1. **It gets no prompt caching.** The cached prefix — system prompt, skill list and the injected output schema — measures 4,327 tokens to Sonnet's tokenizer but only **3,337** to Haiku's, under Haiku 4.5's **4,096-token** minimum cacheable prefix (Sonnet 5's is 1,024). The `cache_control` marker is silently inert, so Haiku re-pays for the entire prefix on every call while Sonnet reads it from cache.
2. **It degenerates under the constrained grammar.** Six listings failed outright with truncated JSON after the model emitted runs like `999999999999...` and `012345678901...` into a numeric field until it hit `max_tokens`. Those runs are billed.

Net: **2.0x** the cost per listing at **-0.086 F1**. Growing the prefix past 4,096 Haiku tokens would fix the caching half, but the quality gap is the part that matters and it would not close.

### Thinking on vs off is a genuine null result

Identical to three decimal places on cost and within 0.002 F1. This was measured twice, because the first run was invalid: `build_request` only ever set `thinking` in order to *disable* it, so the "on" config just omitted the parameter and took the default. After fixing that to `thinking.type: adaptive` (Sonnet 5 rejects the older `enabled` + `budget_tokens` shape outright), the null result held — adaptive thinking contributes a median of **+0 output tokens** at `effort=low`. The real lever is `effort`, not the thinking flag; CLAUDE.md's assumption that thinking would double the cost to ~$0.032/listing came from token estimation and is not what the API actually does here. `EXTRACTION_THINKING` stays **false** — now on evidence rather than on the assumption.

### Where the remaining recall is lost

Precision is 0.916 and recall 0.758, so the gap is misses, not fabrication — the right direction for a product that must not invent requirements. The worst-listing table below shows the two real causes: genuine misses on long infrastructure postings (Compass Digital, Amazon Science), and taxonomy-vs-annotator disagreements where the model returned a defensible broader id (`artificial intelligence` where gold said `ai agents`). The second kind is a taxonomy question, not an extraction one.

## Flagship signal yield

Not scored against gold (no eligibility labels yet — that's the next review pass); reported so the rates can be sanity-checked against the production corpus.

**The gold set turned out to be representative, and the old regex scan was not.** These rates looked alarming against the 27.9% that an August regex scan reported for experience requirements, so the gold set was audited for over-sampling: 102 of 103 evidence quotes appear verbatim in the source and 99 contain an explicit "N years" phrase. Extracting the full production corpus then settled it — **60.0% of 1,782 postings state an experience requirement** (98.2% of those quotes verbatim), so the gold set's 69% was close and the regex scan was undercounting by more than half. Corpus rates now supersede that scan: of postings stating a number, 19.6% are open to ≤2 years (modal 5); degree 18.4%; French 2.9%; new-grad-friendly 1.5%. Visa signals stay rare — sponsorship offered 1.1%, citizenship/PR required 0.7% — but 6.3% require *existing* work authorization, a gate the August scan never measured.

| Config | listings with min_years_experience | with any visa signal |
|---|---|---|
| haiku-nothinking (claude-haiku-4-5, thinking=off) | 9/150 (6%) | 1/150 (1%) |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | 103/150 (69%) | 9/150 (6%) |
| sonnet-thinking (claude-sonnet-5, thinking=on) | 103/150 (69%) | 8/150 (5%) |

## Worst listings — sonnet-nothinking (claude-sonnet-5, thinking=off)

| Listing | F1 | False positives | False negatives |
|---|---|---|---|
| TD — Software Engineer I | 0.00 | code review, incident management, unit testing | — |
| Doppel — Software Engineer, Simulation | 0.00 | artificial intelligence, full-stack development, large language models | — |
| Honda Canada Inc. — Traducteur/Traductrice bilingue/ Bilingu | 0.00 | — | project management |
| Crossing Hurdles — Software Engineer | Remote | 0.00 | artificial intelligence | — |
| Compass Digital — Site Reliability Engineer | 0.00 | — | api design, automation, aws, azure, ci/cd, cybersecurity |
| KNIGHTLABS — Research Associate | 0.40 | data analysis | automation, data quality |
| INDRA — Machine Learning Engineer | 0.43 | artificial intelligence, azure | ai agents, cloud architecture, compliance, github copilot, kafka, mlops |
| ThoughtStorm — Software Developer | 0.50 | api design | full-stack development |
| Nango — Backend Engineer | 0.50 | scalability, system design | backend development, relational databases |
| Amazon Science — Data Scientist, Private Brand Analytics | 0.52 | — | a/b testing, big data, data engineering, data science, data visualization, feature engineering |
