# Next Track website

The public GitHub Pages site includes interactive explorers of the held-out results and the seed-count study, plus an illustrative playlist demo with fictional tracks. Its static files live under `docs/`. Use the local server below to query the actual trained model and your private MPD catalogue.

## Run locally

From the repository root with the project's virtual environment active:

```bash
export PYTHONPATH="$PWD/src"
python scripts/export_site_results.py
python scripts/serve_million_demo.py
```

Open `http://127.0.0.1:8000` in your browser. The demo should show **Local trained model**. Search by song or artist or paste a Spotify track link. Select up to twenty distinct seeds and use a title such as `Rainy Night Study`. Switch methods and select **Compare with plain CF** to inspect outputs side by side in the playlist panel. The search and recommendations use your own local SQLite and model files. The server binds only to loopback. The [extended study commands](extended_study.md) generate the seed-count charts and enable playback ordering.

To preview the public site experience, serve just the `docs/` directory:

```bash
python3 -m http.server 8001 --directory docs
```

Open `http://127.0.0.1:8001`. There should be a fictional-catalogue demo, and changing the cohort in **Results** should switch between 5,000 and 660 queries. The result exporter writes only aggregates, with no playlist titles, IDs, file paths, or model artifacts. The narrative and split counts in `index.html` describe the verified November 15 submission run. Update them if publishing results from a different experiment.

## Publish when ready

Create a GitHub repository, push the completed local Git commits, and select **Settings → Pages → Deploy from a branch → `main` → `/docs` → Save**. Test the published Pages URL in a private browser window. The topic explorer and fictional demo run entirely in the browser. GitHub Pages does not run the local Python server.

Submit the live Pages URL and the source repository URL. Keep the raw archives, SQLite databases, catalogue metadata, local model checkpoints, and credentials out of Git. The source README and model scripts explain how to reproduce the offline experiment from a legitimate MPD copy.
