# Full MPD training and evaluation

Run from your local repository with the virtual environment active. Use the verified `runs/million/mpd.sqlite3` and `runs/million/split.sqlite3` databases.

```bash
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python scripts/train_million.py index
python scripts/train_million.py tags
python scripts/train_million.py validate --queries 5000
python scripts/train_million.py test
```

The collaborative index uses every training playlist and stores the forward and reverse sparse indices on disk. Its only large temporary allocations are sparse arrays for conversion, not a dense track-by-track matrix. The text model fits on a fixed 60,000-title sample from training and predicts every training title in batches. It calibrates its title cutoffs against keyword labels on up to 5,000 validation titles. Those labels are weak supervision. Their agreement with the classifier does not measure human perception. The code aggregates song-tag votes once per exact training group and by the relevant label category.

Validation compares popularity, ordinary collaborative filtering, and the tag-aware ranker. The default evaluation draws up to 5,000 eligible playlists per held-out partition using fixed seeds, with three visible recordings per query. Validation selects the tag weight and writes `frozen_settings.json`. Test uses that file and the same query budget. It writes `test_metrics.json` with Recall@20, NDCG@20, Precision@20, and Hit Rate@20 overall and for title-tagged queries, plus paired intervals for NDCG differences. The test command refuses to overwrite an existing result.

Every completed stage is saved independently under `runs/million/model/`. Rerun `index` or `tags` to reuse a completed stage or restart an interrupted one. `index/summary.json` records the number of training playlists, memberships, and candidate recordings. `tags/summary.json` records training title counts and weak-label validation metrics. The contents of `runs/` stay local.

The default split uses exact Spotify track IDs. For an experiment with a verified crosswalk, build the separate split first and supply its database with `--split runs/million-verified/split.sqlite3 --run runs/million-verified/model` before the subcommand. Keep the raw source database argument the same. Training consumes the canonical index mapping from the split. Era and BPM metadata are separate from this ranking experiment.
