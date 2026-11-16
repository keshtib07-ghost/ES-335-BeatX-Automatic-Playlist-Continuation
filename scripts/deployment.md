# Deploy the existing trained model

Training has already produced the frozen recommender locally. Deployment loads those outputs into a Python service; it does not repeat training.

GitHub Pages serves the interface under `docs/`. It does not execute the Python recommender. Keep that URL and host the model API on a Python/container server with enough disk and memory for the full run. No model host or trained artifacts are provisioned by adding these source files.

## 1. Identify the available artifacts

From the repository root on the machine where training completed:

```bash
python scripts/deployment_files.py
```

The command reports files and byte sizes without uploading data. The API expects the existing `runs/million/` layout containing `mpd.sqlite3`, `split.sqlite3` and the `model/` folder. Keep optional profile directories and the sequence index if those capabilities are needed. Raw MPD download archives are not needed. The report alone does not validate model integrity.

Do not commit the data to Git or bake it into a public container image. Transfer it to private server storage and mount it read-only. This first deployment reuses the current SQLite source; it does not require a new data export.

## 2. Run the API

On a machine with Docker and the artifacts:

```bash
docker build -t beatx-api .
docker run --rm -p 8080:8080 \
  --mount type=bind,source="$(pwd)/runs/million",target=/data,readonly \
  -e BEATX_ALLOWED_ORIGINS=https://keshtib07-ghost.github.io \
  beatx-api
```

The mounted files must be readable by container user 10001. For a cloud deployment, set `BEATX_DATA_DIR` to the mounted directory, or mount it at `/data`. The service uses `PORT` when provided by the host.

Without Docker, install `requirements-serve.txt`, set `PYTHONPATH=src` and `BEATX_DATA_DIR`, then start:

```bash
gunicorn --config deploy/gunicorn.conf.py 'scripts.serve_model_api:create_app()'
```

The API runs one model worker. Candidate generation is serialized to bound peak memory. Measure real memory usage and cold-start times with the full artifacts before choosing host capacity. Place the service behind the host's HTTPS endpoint.

Startup verifies the frozen settings against the existing source/split identity and training summaries through the same loader used by the local demo. Incomplete or mismatched artifacts prevent startup. The production loader expects the full one-million-playlist source. No fallback model is loaded.

`GET /healthz` and `GET /api/status` return readiness only after model loading succeeds. Status includes the frozen-settings hash and training playlist count. These endpoints do not prove recommendation quality or replace an actual query check.

## 3. Connect GitHub Pages

Set the deployed HTTPS backend origin in `docs/config.js`:

```js
window.BEATX_CONFIG = {
  modelApiBase: 'https://YOUR-DEPLOYED-MODEL-HOST',
  spotifyClientId: 'ceb9d936fa93468bbf05e0b29a9e2afe'
};
```

Use the real host URL. An empty `modelApiBase` uses the website's origin, which supports the existing local demo but cannot provide Python inference on GitHub Pages.

Push the configuration and wait for Pages deployment. Studio checks `/api/status` on every load, enables song search when the model is ready and sends requests to `/api/recommend`. Backend errors stay visible; sample rankings are not substituted. Drafts from the earlier illustrative preview are not restored as model predictions.

The backend allows the exact GitHub Pages origin by default. For another frontend, add its origin to comma-separated `BEATX_ALLOWED_ORIGINS`. Origins have no repository path. This enables browser access; it is not API authentication.

Spotify authorization still happens in the visitor's browser with PKCE. The Spotify redirect remains the GitHub Pages Studio address. A Spotify Client Secret is not needed by this recommender.

## 4. Verify before calling it live

Check the public status endpoint. Then search a song in Studio and generate a playlist from real seeds. Compare the same request with the local model, using the same artifacts and settings. Check method comparison and every optional profile filter that was deployed. Finally save the generated recommendations to Spotify.

The source tests cover the API contract and request forwarding. They do not establish that the full local checkpoint has been deployed, and they do not log into a Spotify account.

```bash
python -m unittest discover -s tests -v
node --test tests/*.cjs
```
