# From a completed local run to live BeatX

A completed training run and a deployed website are separate states. You do not need to repeat training.

## How the website works

GitHub stores the project source. GitHub Pages runs the browser interface, including the Research interactions. A separate Python server loads the trained recommender and answers the Studio's search and recommendation requests. Spotify login lets a visitor save the generated result into their account.

The current source includes that API connection, but no hosted model or transferred local checkpoint has been verified yet.

## Step 1. Inventory the existing project

Keep your current local folder intact. Do not start by deleting files or replacing it with a new clone.

Download the read-only inventory script without pulling changes into the messy working folder:

```bash
cd ~/projects/playlist-model
curl -fL https://raw.githubusercontent.com/keshtib07-ghost/ES-335-Nextrack-for-Spotify/main/scripts/local_inventory.py -o /tmp/beatx-local-inventory.py
python3 /tmp/beatx-local-inventory.py --root "$PWD" --output /tmp/beatx-local-inventory.json
```

The report lists file paths and sizes. It includes Git status so local edits can be preserved. It does not include file contents or upload anything. Environment folders and credential-named files are excluded. Symlink targets are not followed, and incomplete scans are marked.

Share the JSON report for review. If the output already exists, choose another output filename outside the project folder.

## Step 2. Preserve the trained run and local code

Review the report before deciding which files belong in a transfer. Keep locally modified source code and the completed run together until their matching versions are identified.

Small reviewed source files belong in this GitHub repository. Preserve trained binaries in versioned storage. GitHub Releases or LFS may be suitable after checking file sizes. Keep private databases in private storage. Store the selected artifact version and checksums in the source repository so the same model can be restored.

Ordinary GitHub commits cannot contain files over 100 MiB. A GitHub release asset must be under 2 GiB. Do not use a public release to publish private training data.

Use the [private backup helper](private-backup.md) to preserve the existing run with verified per-file checksums before transferring it. No trained files have been backed up merely by running the inventory or reorganising this repository.

## Step 3. Make a clean local checkout

Once local edits are preserved and the model artifacts are backed up, clone the organised repository into a new folder beside the existing one. Cloning downloads your repository to your computer. Forking creates another repository on GitHub.

Restore the verified artifacts into the documented `runs/million/` layout. Compare their checksums before running anything. Keep the old folder until the clean checkout reproduces its recommendations.

## Step 4. Check real local inference

Install the documented Python dependencies, then start `scripts/serve_million_demo.py`. Search for known songs and compare a recommendation with your previous local run. This verifies the trained model still works after organisation.

## Step 5. Host the model

Choose a Python/container host after checking artifact sizes and measuring memory use. The host needs private storage for the trained artifacts and a public HTTPS API. Hosting may require a provider account or payment; choose it before provisioning resources.

Follow [deployment](deployment.md) to run the existing Docker image configuration. The API must pass its readiness check with the real artifacts loaded.

## Step 6. Connect the website

Set `modelApiBase` in `docs/config.js` to the deployed HTTPS API address. Push that configuration to GitHub and wait for Pages deployment. The frontend URL can stay the same.

## Step 7. Verify the whole experience

Generate recommendations on the public Studio. Compare the output with the local model for the same inputs. Check the deployed filters. Sign into Spotify and save the generated playlist. Verify its link opens the expected tracks.

Call the project fully live only after that check succeeds.
