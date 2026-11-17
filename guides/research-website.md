# Research page and evidence downloads

The report lives in `docs/research.html`, with its own `research.css` and `research.js`. Studio and the shared stylesheet are unchanged. Serve the static site from the repository root:

```bash
python -m http.server 8765 --directory docs
```

Open `http://localhost:8765/research.html`. Studio can also be opened from this server, but its full local-model API requires the server described in [site.md](website.md). A `/api/status` 404 on a plain static server is an expected Studio probe.

## Evidence and scope

All measured chart values come from the existing public aggregate files:

- `docs/experiment.js`: Experiment A, 5,000 three-seed test queries.
- `docs/seed_experiment.js`: Experiment B, 1,500 validation and 1,500 test queries across six seed budgets, including ablations and diagnostic cases.
- `docs/sequence_experiment.js`: separate order-recovery comparison on fixed known tracks.

The two ranking protocols use different cohorts and reference sets. Their three-seed scores must not be compared as if one model changed. Paired bootstrap intervals describe differences, not individual-model scores. The report keeps the original exports intact and does not retune on test.

The ranking-score and metric tools are labeled teaching examples. Only the budget-rule explorer uses saved validation scores; it does not change the published 95% rule. Expanded profiles, bass, treble, BPM, era and ALS/BPR have no measured ranking gain in these exports. Missing EDA distributions and validation-grid scores are explicitly described rather than invented. Current source code documents the implementation; it is not independent verification of the original private run.

## Rubric map and beginner explanations

The report maps all ten ES335 rubric criteria to sections without claiming a grade. The overview, training-scope table and viva questions distinguish the full CF training split from the 60,000-title classifier fitting cap and the all-training context aggregation pass. The cap is a configurable choice, not an experimentally established optimum.

The unified Studio explanation is pinned to implementation commit `1fd19b1ecdd7a3546d52d21989de02d7582e0184`. Keep its 19-tag taxonomy, filter behaviour, boost grid and deployment status separate from the 12-tag A/B benchmarks and their selected weight 1. New evaluation scripts write local outputs; do not infer scores or the selected unified weight from the existence of those scripts. Update this source snapshot and its statements when verified implementation or deployment evidence changes.

The method-status table separates weak baselines, structural failures, small gains, code revisions and untested proposals. The conclusion and viva notes use existing public evidence. Neither the rubric map nor this documentation update trains or evaluates a model. Research works on static GitHub Pages; current Studio generation needs a live Python API and must not substitute illustrative rankings.

## Update results

After producing new frozen experiment exports through the existing pipeline, regenerate the public downloads:

```bash
python scripts/export_research_bundle.py
python scripts/export_research_bundle.py --check
```

The export reads JSON assignments without executing JavaScript, writes deterministic CSV/JSON, and records source-file SHA-256 hashes. It never reads private MPD data or trains a model. Hashes identify public exports only. Review the report's interpretation and any fixed headline numbers whenever the underlying experiment changes. Avoid replacing an old benchmark with a differently constructed experiment under the same label.

## Validation

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m unittest discover -s tests -v
node tests/test_research_frontend.cjs
node tests/test_spotify_frontend.cjs
python scripts/export_research_bundle.py --check
```

The additional checks cover download fidelity/staleness, safe parsing, metric arithmetic, context abstention, validation-only budget selection, and saved marginal-gain claims. Browser review should exercise all selectors, ranges, metric examples and error cases at desktop and mobile widths, check links/downloads, and inspect console errors and page overflow. Chart data tables provide exact values alongside accessible SVG descriptions. Charts may scroll within their own figure on narrow screens to preserve readable axes.
