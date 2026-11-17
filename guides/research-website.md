# Research page and evidence downloads

Research opens with a short summary at `docs/research.html`. The full report and all its interactions live at `docs/research-deep-dive.html`, using `research.css` and `research.js`. Both pages have Summary / Deep Dive navigation; the summary ends with a full-report link. Existing section bookmarks at `research.html#...` route to the corresponding Deep Dive section through `research-summary.js`. Studio's navigation still points to `research.html`; its API configuration is preserved. Serve the static site from the repository root:

```bash
python -m http.server 8765 --directory docs
```

Open `http://localhost:8765/research.html` for the summary or `http://localhost:8765/research-deep-dive.html` for the full report. Studio can also be opened from this server, but its full local-model API requires the server described in [site.md](website.md). A `/api/status` 404 on a plain static server is an expected Studio probe.

## Evidence and scope

The public aggregate files cover three protocols.

- `docs/experiment.js` contains the full-title standard reranker’s 5,000-query validation weight grid and 5,000 three-seed test results. Its frozen-settings hash matches the deployed model.
- `docs/seed_experiment.js` contains the earlier fixed-reference seed-count study with its original fitted tagger, 1,500 validation queries, 1,500 test queries, ablations and diagnostic cases.
- `docs/sequence_experiment.js` contains the order-recovery comparison on fixed known tracks.

Compare methods on the same cohort and reference set. Paired bootstrap intervals describe the differences between rankers. The ranking-score and metric tools use illustrative examples. The budget explorer uses the earlier study’s saved validation scores.

## Report scope

The Deep Dive follows a Studio request through offline preparation, title tagging, known and unfamiliar seeds, collaborative retrieval, filters and fallback. Both fitted classifiers use all 804,485 training titles. The three-seed benchmark measures the standard 12-tag reranker. Studio serves the expanded 19-tag profiles and has a separate ranking evaluation protocol. Preserve that scope in the prose, charts and downloadable provenance.

The rubric map links to the evidence. The public Contributions section records the student-confirmed roles: shared ideation; Sanidhya's initial modelling framework, algorithm selection, first training run, shrinkage-factor choice and research content; and Keshav's retraining, model improvements, website, hosting and Spotify integration. Viva preparation questions are not published on the website. The “What the tags mean” note describes the weak supervision used by both classifiers. Headline scores and validation weight values have static tables for readers with JavaScript disabled. The interactive chart labels use the query counts in the source export.

## Update results

After testing a frozen full-title run, regenerate its public aggregate and evidence downloads:

```bash
python scripts/export_site_results.py --input runs/million/model-full-titles/test_metrics.json
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

## Current additions

The proposal questions appear first. `research_additions.js` renders K-dependent case metrics and measured EDA. It also displays the live Studio audit. `research_extra_data.js` contains those measured reports.

See [final-research.md](final-research.md) to score the exact deployed pipeline. The command publishes true mean metrics at every K and full EDA by split. It keeps the older experiments separate.
