# BeatX website

BeatX has three pages. `docs/index.html` is the Playlist Studio. `docs/research.html` is the default Research Summary; `docs/research-deep-dive.html` keeps the complete report, measured results and study interactions. The research pages link through Summary / Deep Dive navigation. The Studio requests rankings from the trained Python API. See [deployment](deployment.md) to connect a hosted model to GitHub Pages. If no backend is connected, Studio reports the missing connection and disables generation. It does not substitute illustrative rankings. The local server below also serves actual trained-model recommendations.

## Run locally

From the repository root with the project's virtual environment active:

```bash
export PYTHONPATH="$PWD/src"
python scripts/export_site_results.py
python scripts/serve_million_demo.py
```

Open `http://127.0.0.1:8000` in your browser. The Studio should show **Trained model connected**. Search by song or artist or paste a Spotify track link. Select up to twenty distinct seeds and use a title such as `Rainy Night Study`. Switch methods and select **Compare with plain CF** to inspect outputs side by side in the playlist panel. The search and recommendations use your own local SQLite and model files. The server binds only to loopback. Open `http://127.0.0.1:8000/research.html` for the research page. The [extended study commands](experiments.md) generate the seed-count charts and enable playback ordering.

When available, the server loads expanded title tags and the existing `runs/million/catalogue-enrichment/catalogue_enrichment.sqlite3` file automatically. Use `CF + song profiles` to see the category filters. Era prefers a reviewed recording release date and labels fallback Spotify dates as catalogue editions. A BPM filter excludes tracks without a known tempo. Filters can return fewer than 20 results when the available candidates lack matching metadata. The existing evaluation results still describe the benchmark methods and do not measure this filter behavior.

Album artwork loads without Spotify sign-in through Spotify’s public oEmbed endpoint. Catalogue artwork is looked up and cached for the page session. Missing or unavailable artwork retains a placeholder.

To create a Spotify playlist, register `http://127.0.0.1:8000/` as a redirect URI in your Spotify app and start the server with `--spotify-client-id YOUR_CLIENT_ID`. On GitHub Pages, register `https://keshtib07-ghost.github.io/ES-335-BeatX-Automatic-Playlist-Continuation/` and set the public Client ID in `docs/config.js`. A visitor can also enter a Client ID in the one-time setup dialog. No Client Secret is used. Spotify account authorization uses PKCE with `playlist-modify-private`.

Use **Save to Spotify**. The draft survives the authorization redirect. The saved playlist starts with the seed songs in their selected order, followed by the recommended additions in the displayed relevance or playback order. A song that appears in both is saved once at its first position. For example, three seed songs and twenty distinct additions produce a 23-track playlist. The seeds belong to the generated result; editing the seed selection takes effect after generating again. After Spotify confirms every track was saved, the app shows **Open in Spotify**. A failed item write can be retried without creating a duplicate playlist. Actual account authorization and playlist creation require an enabled Spotify app and an eligible account.

Run the Spotify integration tests with `node --test tests/test_spotify_frontend.cjs`. These use mocked Spotify responses; they do not create playlists in an account.

To inspect the static interface without a Python model, serve just the `docs/` directory:

```bash
python3 -m http.server 8001 --directory docs
```

Open `http://127.0.0.1:8001`. The Studio should report a disconnected model unless `docs/config.js` points to a running API. Open `research.html` for the summary, then choose **Deep Dive** and change the cohort in **Results** to switch between 5,000 and 657 queries. The result exporter writes only aggregates, with no playlist titles, IDs, file paths, or model artifacts. Update the report and summary together when publishing results from a different experiment.

## Publish when ready

Push the completed local Git commits to `main`, and select **Settings → Pages → Deploy from a branch → `main` → `/docs` → Save**. Test the published Pages URL in a private browser window. The Research interactions run in the browser. Studio requires the deployed model API configured in `docs/config.js`. GitHub Pages does not run the local Python server.

Submit the live Pages URL and the source repository URL. Keep the raw archives, SQLite databases, catalogue metadata, local model checkpoints, and credentials out of Git. The source README and model scripts explain how to reproduce the offline experiment from a legitimate MPD copy.
