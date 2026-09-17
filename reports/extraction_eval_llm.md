# Extraction eval — LLM vs frozen spaCy baseline

Generated 2026-09-17T11:43:51+00:00 against `eval/gold/extraction_skills.jsonl`

**150 listings scored** — 40/150 human-verified (27% if n>0). Treat auto-accepted rows as a weaker signal.

## Headline

Best configuration: **sonnet-nothinking (claude-sonnet-5, thinking=off)** — micro F1 **0.830** vs the frozen baseline's **0.460** (**+0.370**).

| Extractor | Precision | Recall | F1 | F1 (human-verified only) | Cost | Failures |
|---|---|---|---|---|---|---|
| baseline_extractor (spaCy), raw strings — the frozen P0 number | 0.874 | 0.312 | 0.460 | — | — | 0 |
| baseline_extractor (spaCy), normalized | 0.928 | 0.503 | 0.652 | 0.664 | — | 0 |
| haiku-nothinking (claude-haiku-4-5, thinking=off) | 0.864 | 0.654 | 0.744 | 0.727 | $4.1196 | 6 |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | 0.916 | 0.758 | 0.830 | 0.844 | $2.0852 | 1 |
| sonnet-thinking (claude-sonnet-5, thinking=on) | 0.916 | 0.757 | 0.829 | 0.847 | $2.0740 | 1 |

### Why two baseline rows

The frozen P0 number (F1 0.460) compared *raw strings*: the baseline's vocabulary against the annotator's free-form labels. That scores spelling as much as extraction — `data modelling` vs `data modeling` counts as a miss. The normalized row maps every extractor through `taxonomy/skills.yaml` first, which is the apples-to-apples comparison; both are shown so the historical number stays traceable.

## Cost projection (measured, not estimated)

| Config | $/listing | 7,200-listing backfill | via Batch API (50%) |
|---|---|---|---|
| haiku-nothinking (claude-haiku-4-5, thinking=off) | $0.0275 | $198 | $99 |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | $0.0139 | $100 | $50 |
| sonnet-thinking (claude-sonnet-5, thinking=on) | $0.0138 | $100 | $50 |

## Flagship signal yield

Not scored against gold (no eligibility labels yet — that's the next review pass); reported so the rates can be sanity-checked against the corpus-wide regex scan that motivated the pivot (experience stated in 27.9% of postings, visa signals <1%).

| Config | listings with min_years_experience | with any visa signal |
|---|---|---|
| haiku-nothinking (claude-haiku-4-5, thinking=off) | 9/150 (6%) | 144/150 (96%) |
| sonnet-nothinking (claude-sonnet-5, thinking=off) | 103/150 (69%) | 149/150 (99%) |
| sonnet-thinking (claude-sonnet-5, thinking=on) | 103/150 (69%) | 149/150 (99%) |

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
