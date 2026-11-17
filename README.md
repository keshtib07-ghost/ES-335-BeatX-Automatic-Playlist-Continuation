# BeatX

Seed-based playlist continuation for ES335. BeatX studies how seed count affects recommendation quality and whether title-derived context improves collaborative filtering.

[Playlist Studio](https://keshtib07-ghost.github.io/ES-335-Nextrack-for-Spotify/) · [Research Summary](https://keshtib07-ghost.github.io/ES-335-Nextrack-for-Spotify/research.html) · [Research Deep Dive](https://keshtib07-ghost.github.io/ES-335-Nextrack-for-Spotify/research-deep-dive.html) · [Getting started](guides/getting-started.md)

## Current deployment status

The website and Research interactions are published on GitHub Pages. Real playlist generation needs the Python API and the existing trained artifacts on a model host. That hosted model has not yet been verified. Studio reports a disconnected model when the backend is unavailable; it does not substitute sample rankings.

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

## Recorded evidence

The recorded full run processed 1,000,000 playlists and trained collaborative filtering on 804,485. For 5,000 fresh test queries with three seeds, NDCG@20 was 0.0372 for popularity, 0.2497 for CF and 0.2513 for the selected title-aware ranker.

These scores measure withheld-track recovery. Playlist-title labels do not establish perceived musical mood. The original 20,000-playlist pilot is documented separately in the [model study](guides/model-study.md). Published aggregates are available on the Research page; trained arrays are not included in the source clone.

## Sources and disclosure

The study uses the Spotify Million Playlist Dataset from the RecSys Challenge 2018. See the [detailed study](guides/model-study.md) for source references and limitations.

Codex assisted with implementation and documentation. The original title audit was AI-assisted and needs student review. Describe the team's own contributions and AI use in the course submission.
