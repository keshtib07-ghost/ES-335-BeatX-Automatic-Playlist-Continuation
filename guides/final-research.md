# Completed research evidence

## Final-pipeline seed counts

Both final-pipeline studies are complete. The new seed-count study uses 1,000
validation playlists and a separate 1,000-playlist test cohort. At K = 20:

| Input seeds | Test NDCG | Test Recall | Test Hit Rate |
| --- | --- | --- | --- |
| 1 | 0.14282 | 0.05709 | 62.2% |
| 5 | 0.23467 | 0.09944 | 80.0% |
| 20 | 0.32273 | 0.13142 | 86.8% |

Validation selected 20 seeds under the fixed 95% rule. Twenty is the largest
count tested. This does not establish an earlier stopping point or a universal
optimum. At 20 seeds, the final-minus-CF NDCG difference is +0.00036, with paired
95% interval [-0.00134, +0.00206]. Three of the six test intervals lie above
zero; the comparisons are pointwise, without a multiple-comparison adjustment.

The five-seed continuation test and seed-count study have different hidden-song
sets and cohorts. Their five-seed scores are not interchangeable. The original
title-model curves remain under Development history.

The uploaded seed report matches all 17 shared model/profile hashes in the
five-seed report. Its freeze additionally fingerprints the staging, split and
enrichment databases, with inference-source hashes. The published source report
is retained unchanged.

For a fresh reproduction, run the experiment from the repository on the machine
that has your existing Azure key. Activate the project's virtual environment first.

```bash
git pull --ff-only
bash scripts/studio_seed_study_azure.sh
```

This uses the running API's exact Docker image and its read-only trained files.
It scores 1,000 validation playlists and 1,000 separate fresh test playlists at
seed counts 1, 2, 3, 5, 10 and 20. The same hidden songs remain fixed at every
seed count. It excludes known earlier development cohorts and verifies the
previous final evaluation's query fingerprint before excluding that cohort.

All six comparison arms are included: popularity, CF, the earlier title method,
the final pipeline without a title, the final pipeline, and the final pipeline
with the fixed seed-derived BPM filter. Every arm is scored at K = 1 to 20.

The output includes Recall, NDCG, Precision, Hit Rate, artist variety and
catalogue coverage. Paired 95% group-bootstrap intervals accompany the
final-minus-CF comparison and gains between successive seed counts at K = 20.
Validation alone selects the smallest seed count reaching 95% of its best
final-pipeline NDCG@20. Test scores never change a ranking setting.

Only aggregates are downloaded. The script refreshes the graphs, static score
table, research-question answer, evidence status and CSV downloads. Send back
`docs/data/research/studio_seed_study.json`, or commit the generated files so
they can be reviewed from GitHub. The generated files are:

```text
docs/data/research/studio_seed_study.json
docs/data/research/studio_seed_scores.csv
docs/data/research/studio_seed_differences.csv
docs/data/research/provenance.json
docs/data/research/research_bundle.json
docs/research_extra_data.js
docs/research.html
docs/research-deep-dive.html
```

Private per-budget checkpoints remain in the staging directory printed by the
Azure command. A completed report is not overwritten. The API keeps running.

For a local trained run, use:

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m scripts.studio_seed_study
```

To republish a copied aggregate without running inference again, use:

```bash
PYTHONPATH=src python -m scripts.studio_seed_study --export-only --output docs/data/research
```

Research now starts with the two proposal questions. The K explorer rescales
actual saved hit positions. It does not invent average scores at other cutoffs.

The main data plots now cover all 1,000,000 staged playlists and separate the
existing splits. The verified 20,000-playlist pilot remains available as earlier
evidence. It is not substituted for the full distribution.

The Studio audit sends 11 fixed requests to the deployed model. It includes
unknown seeds and conflicting context. It checks a narrow tempo range and
duplicate seed input. It does not write to Spotify. These are functional checks,
not hidden-song recovery scores.

## Completed result

The five-seed study used 1,000 held-out queries against the active Azure runtime. Studio
reached NDCG@20 0.26347 and Recall@20 0.10662. Its paired gain over CF is
uncertain. The BPM filter reduces recovery on the known-tempo subset.

The saved freeze records 17 model/profile hashes and the runtime versions. It
does not include source or enrichment database hashes. Keep those private input
snapshots for reproduction; the model ID alone does not certify every input.

## Evaluate the deployed model on a new protocol

From the local repository where the existing Azure key is available:

```bash
git pull --ff-only
bash scripts/complete_research_azure.sh
```

This uses a separate container made from the live API's image. It loads the
active artifacts read-only. It does not restart the API or change its settings.
Only aggregate reports are copied back. Commit the generated files under
`docs/` to publish the new evidence. Do not commit `runs/`.

The script uses the existing key at `~/.ssh/beatx-api_key.pem`. Set
`BEATX_AZURE_KEY` if it is elsewhere. Never upload that key to GitHub.

## Use a local trained run instead

```bash
PYTHONPATH=src OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 \
  python -m scripts.complete_research
```

This prefers `model-full-titles` and `profiles-v2-expanded-full-titles`.
Use `--model` and `--profiles` to select explicit paths. A local run evaluates
those artifacts; it is the deployed model only if the artifacts and runtime
match Azure. The Azure command avoids that ambiguity.

## What the evaluator measures

The default cohort has up to 1,000 fresh exact-playlist groups. Each query has
five deterministic seeds. Every remaining track is a reference, including
training-unseen songs. Short and long playlists are eligible.

The comparison includes popularity and plain CF. It measures the standard title
model, then Studio with and without a title. The BPM arm uses a fixed ±10 BPM
window around the median of at least two known seed tempos. If fewer are known,
it uses ordinary Studio. The known-tempo subset is reported separately.

Each method is scored at every K from 1 to 20. Recall and NDCG measure recovery.
Precision and Hit Rate describe output quality from different angles. Artist
variety is within-list diversity. Catalogue coverage is aggregate reach.

The protocol excludes the first 100k development cohort and its exact copies.
It also excludes the known earlier benchmark, seed-study and unified-test
cohorts. No test result chooses a weight. The freeze records artifact hashes
before scoring. Unknown historical development sets still need an explicit
record before calling the holdout completely untouched.

The command also computes full EDA by split. It writes diagnostic Studio cases.
The website loads the completed reports. Refresh their interpretation with
`python -m scripts.review_research_results`; this reads scores without inference. It keeps the old benchmark and seed curves under their own scope.

## Repeat publication without repeating test evaluation

```bash
PYTHONPATH=src python -m scripts.complete_research --export-only
python scripts/export_research_bundle.py --check
```

A completed test report cannot be overwritten. Re-exporting changes the display,
not the evidence.

## Check the completed public evidence

```bash
python -m scripts.review_research_results --check-only
python scripts/export_research_bundle.py --check
```

The review checks metric bounds and prefix consistency. It reconciles distribution
counts and recomputes each saved case’s NDCG difference from its hit ranks.
