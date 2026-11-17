# BeatX

Automatic playlist continuation from seed tracks for ES335. BeatX studies how seed count affects recommendation quality and whether title-derived context improves collaborative filtering.

[Playlist Studio](https://keshtib07-ghost.github.io/ES-335-BeatX-Automatic-Playlist-Continuation/) · [Research Summary](https://keshtib07-ghost.github.io/ES-335-BeatX-Automatic-Playlist-Continuation/research.html) · [Research Deep Dive](https://keshtib07-ghost.github.io/ES-335-BeatX-Automatic-Playlist-Continuation/research-deep-dive.html) · [Getting started](guides/getting-started.md)

## Current deployment status

GitHub Pages hosts Studio and Research. Studio generates playlists through the [Azure model API](https://beatx-api-keshav.centralindia.cloudapp.azure.com/api/status), which serves the frozen full-title run and expanded song profiles.

If training already finished on your computer, preserve that run. Do not retrain to deploy it. Start with the [local inventory and deployment steps](guides/getting-started.md).

## Repository map

| Folder | Contents |
| --- | --- |
| `src/playlist_model/` | Model implementation and inference logic |
| `scripts/` | Runnable preparation, training and export commands |
| `docs/` | GitHub Pages website and published research aggregates |
| `guides/` | Setup, research and deployment documentation |
| `tests/` | Model and website checks |
| `artifacts/` | Versioned pilot evidence and data provenance |
| `deploy/` | Backend server configuration |

The root `Dockerfile` packages the model API source. The requirements files pin the Python environment. Ignored `runs/` folders hold local model outputs and SQLite files.

## Existing local training run

To inspect the current checkout without moving or uploading its files:

```bash
python3 scripts/local_inventory.py --root . --output /tmp/beatx-local-inventory.json
```

For a messy or outdated checkout, use the standalone download command in [getting started](guides/getting-started.md). It does not require a Git pull.

Review local edits before making a fresh clone. Large trained files need separate versioned storage. The cleaned repository can then be cloned locally and the matching artifacts restored.

## Run and deploy

- [Run Studio locally and configure Spotify](guides/website.md)
- [Deploy the frozen model API](guides/deployment.md)
- [Prepare and split MPD](guides/data-preparation.md)
- [Reproduce full training and evaluation](guides/training.md)
- [Inspect seed-count experiments](guides/experiments.md)
- [Review context profiles](guides/track-profiles.md)
- [Read the detailed study and pilot results](guides/model-study.md)

Run commands from the repository root with the virtual environment active and `PYTHONPATH=src`.

```bash
python -m unittest discover -s tests -v
node --test tests/*.cjs
```

## Research updates

The two proposal questions lead both Research pages. The report includes a K explorer based on actual saved cases. Full-data distributions cover each split. Eleven live Studio requests document fallback and filtering limits.

[Completed Studio evaluation and reproduction steps](guides/final-research.md). On 1,000 five-seed held-out queries, Studio reaches Recall@20 of 0.10662 and NDCG@20 of 0.26347. Its gain over plain CF is uncertain. The fixed seed-tempo filter lowers recovery.

The final pipeline also has a seed-count study on 1,000 validation and 1,000 separate test playlists. With the same hidden songs at every count, test NDCG@20 rises from 0.14282 at one seed to 0.32273 at 20; Recall@20 rises from 0.05709 to 0.13142. Validation selects 20 under the fixed 95% rule, the largest count tested. The report keeps this study separate from the five-seed continuation test and the earlier title-model experiments.

## Recorded evidence

Collaborative filtering and both title classifiers use the full split of 804,485 training playlists. On 5,000 held-out queries with three seeds, NDCG@20 was 0.03723 for popularity, 0.24966 for CF and 0.25126 for the standard title-aware ranker. The final pipeline has its own five-seed and seed-count evaluations. Compare methods within each study.

These scores measure withheld-track recovery. Playlist-title labels do not establish perceived musical mood. The original 20,000-playlist pilot is documented separately in the [model study](guides/model-study.md). Published aggregates are available on the Research page; trained arrays are not included in the source clone.

## Sources and disclosure

The study uses the Spotify Million Playlist Dataset from the RecSys Challenge 2018. See the [detailed study](guides/model-study.md) for source references and limitations.

Codex assisted with implementation and documentation. The pilot title audit used AI-assisted annotations.
