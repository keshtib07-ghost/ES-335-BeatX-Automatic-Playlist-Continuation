# Preserve the completed local run

The reported workspace contains about 1.95 GB under `runs/` and 1.00 GB under `private-data/`, using decimal units. The basic file-presence probe passed. This establishes file availability; real model loading is still unverified.

Two untracked local files also need preserving: `export_song_batch.py` and `songs_batch_01.csv`.

## Create a private backup

Wait for any training or database-enrichment job to finish. Keep the existing project folder intact. The standalone helper creates new archives outside that folder, then verifies the content of each archived file against its SHA-256.

```bash
curl -fL https://raw.githubusercontent.com/keshtib07-ghost/ES-335-BeatX-Automatic-Playlist-Continuation/main/scripts/backup_workspace.py -o /tmp/beatx-backup.py
python3 /tmp/beatx-backup.py create \
  --root "$HOME/projects/playlist-model" \
  --output "$HOME/beatx-private-backup"
```

The output directory must be new. Allow a few minutes for compression and verification. The helper checks available disk space using a conservative estimate before writing archives.

The output contains:

| File | Contents |
| --- | --- |
| `beatx-runs.tar.gz` | All local run outputs, including trained artifacts and working databases |
| `beatx-inputs.tar.gz` | The existing `private-data/` folder |
| `beatx-source.tar.gz` | The remaining project files, including the local export script and CSV |
| `manifest.json` | The source Git commit and checksums for all archived files |

The helper excludes virtual environments and Git internals. It records skipped paths, including symlinks and credential-named files. It does not detect every possible hardcoded credential, so keep the archives private. A nonempty SQLite WAL or journal blocks the backup until database writers are closed. A changed source file prevents the backup from being marked complete.

A backup directory without `manifest.json` is incomplete. A successfully verified local backup has not yet been uploaded to GitHub.

## Store the archives on GitHub

Create a separate **private** repository named `BeatX-private-artifacts`. Initialise it with a README. Keep the main BeatX source repository public.

In the private repository, open **Releases**, choose **Draft a new release**, and create a tag such as `local-run-v1`. Attach the three archives and `manifest.json`, then publish the release. GitHub release assets must each be under 2 GiB; the helper checks that limit. Private releases remain available only to people with repository access.

These archives are binary release assets. They are not ordinary Git commits and are not downloaded automatically by cloning the source repository.

After uploading, download the assets into a new directory and verify them:

```bash
python3 /tmp/beatx-backup.py verify --backup /path/to/downloaded-assets
```

Only consider the remote backup verified after that download check passes. Keep the original project until a clean checkout with restored artifacts reproduces its recommendations.

## Continue deployment

Review the local export script before adding it to the organised source repository. Restore the selected trained artifacts into the clean checkout. Measure the live model's memory use before choosing a VPS. Storage size alone does not establish the RAM requirement.

See [getting started](getting-started.md) and [deployment](deployment.md).
