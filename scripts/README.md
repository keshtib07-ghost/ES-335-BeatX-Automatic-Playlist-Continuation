# Full Spotify MPD preparation and split

Keep the original archive and any verified track metadata outside Git. The `runs/` directory holds local SQLite databases and summaries.

## Read the original ZIP and verify the database

```bash
python3 scripts/prepare_million.py scan --zip "$MPD_ZIP"
python3 scripts/prepare_million.py prepare --zip "$MPD_ZIP" --output runs/million
python3 scripts/prepare_million.py verify --output runs/million
```

Each slice is verified and committed separately. The same command can resume an interrupted run.

## Build a fresh grouped split

```bash
python3 scripts/split_million.py build
python3 scripts/split_million.py verify
```

The default input is `runs/million/mpd.sqlite3`. The project writes a separate `runs/million/split.sqlite3` and aggregate `split_summary.json`. Each row of the `assigned_splits` view has a playlist ID, split, group fingerprint, canonical recording count, and development-set flags. The assignment target is 80% train, 10% validation, and 10% test, before the pilot restrictions. Exact track sets always stay together. All playlists in the 20 slices pinned by `artifacts/source_manifest.json` go to training, along with any exact copies elsewhere in the full dataset. This protects the new validation and test sets from the already examined pilot. Three-seed evaluation requires at least four distinct recordings.

Without verified aliases, groups use exact Spotify track IDs. To use verified recording groups, build a separate split with `--recording-map /path/to/verified.csv --output runs/million-verified`. The CSV uses `track_id` and `recording_id` columns. The code only merges IDs that share an explicit recording ID, using the smallest observed index as the representative. The CSV's SHA-256 is bound to the run. `recording_aliases` records nonidentity mappings for downstream training.

Stopping with Ctrl+C preserves committed batches. Rerun `build` with the same inputs and output path to resume.
