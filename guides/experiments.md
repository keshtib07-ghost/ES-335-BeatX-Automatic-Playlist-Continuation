# Seed-count and playback-order studies

These are the earlier title-model studies, preserved as development evidence.
The final pipeline now has its own measured seed-count study and a separate
five-seed continuation test. See [final-research.md](final-research.md) for the
completed results and reproduction commands.

Use the existing full-MPD `runs/million/model` outputs and leave the original three-seed report intact. From the WSL repository root with your virtual environment active:

```bash
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python scripts/seed_study.py --queries 1500
MPD_ZIP="/mnt/c/Users/tibre/Downloads/spotify_million_playlist_dataset.zip"
python scripts/build_playlist_transitions.py --zip "$MPD_ZIP"
python scripts/serve_million_demo.py
```

Both analysis scripts write private summaries under `runs/million/` and publish only aggregate browser data into `docs/seed_experiment.js` and `docs/sequence_experiment.js`. Use `--export-only` to regenerate those site assets from existing completed reports. The site labels the new analyses as pending until the assets have results.

## Seed count, title and tagging

The seed-count study selects fresh deterministic validation and test samples, excluding the exact playlist groups represented in the earlier three-seed samples in each partition. It restricts the shared cohort to playlists with more than 20 distinct recordings. It deterministically reserves 20 tracks, then exposes nested prefixes of length 1, 2, 3, 5, 10, and 20. Every seed count has the same withheld reference set. An unrevealed seed-pool track may still be recommended and receives no credit.

The comparisons are popularity, plain CF, CF with keyword title labels, and CF with learned title labels. The last two use the same trained recording-tag evidence and previously validated tag weight, so their contrast tests query-time label inference. The difference between plain CF and either contextual ranker measures the effect of adding title context. The title-tagged subset is defined by the learned classifier. Its metric denominator is distinct from the full sample.

Before reading the fresh test scores, the script selects the **smallest seed budget reaching 95% of the best mean validation NDCG@20** for the learned-title ranker. The report gives marginal gains and paired group-bootstrap intervals. This rule is an offline criterion for diminishing returns. It does not estimate the universal number of tracks a listener needs.

Each budget reports Recall@20, NDCG@20, Precision@20, Hit Rate@20, artist diversity, catalogue coverage, and a popularity diagnostic. Artist diversity is the mean per-list fraction of distinct artists among slots with a known artist. Catalogue coverage counts distinct recommendations across the fixed sample relative to the training catalogue. The popularity diagnostic is the mean fraction of displayed tracks in the top 1% by training support. The largest gain, largest loss, and first zero-hit case are illustrative selections, with opaque identifiers and aggregate rank positions.

## Playback order

The co-occurrence model uses unordered track sets. The additional script reopens the original ZIP and reads track positions to count directed transitions between adjacent distinct recordings in training playlists. It saves a local sorted lookup and compares its greedy order with original playlists using the same 20 known recordings, keeping the first track fixed. The seeded shuffle is the baseline. Directed adjacency recall measures recovery of original order. It does not measure perceived flow or whether the recommendation model selected the right tracks.

In the local playlist studio, the **Playback flow** switch orders the same recommended tracks using transition evidence, starting from the last selected seed. Unsupported steps preserve relevance order among the remaining tracks. The evidence display counts supported transitions including the one from the last seed. For a new query there is no withheld reference, so the studio displays seed support, output count, comparison overlap, and transition evidence. Recall and NDCG are confined to the offline studies.

The measured catalogue still uses exact Spotify IDs. A verified recording crosswalk, trusted BPM, or release-era metadata can support separate experiments. Those features and ALS/BPR have not been evaluated in the reported full run.
