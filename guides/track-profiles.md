# Build song profiles locally

Run these from the repository root in the existing WSL virtual environment. The verified full MPD staging and split databases must already exist. The enrichment pilot also uses the existing collaborative-filtering training index.

```bash
source .venv/bin/activate
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
python scripts/track_profiles.py build
```

The title classifier learns from every training title by default, using labels from the title rules. Use `build --title-limit 60000` to reproduce the previous fitting budget. When refitting with a different limit, give the builder a separate `--output` directory. The profile builder processes all training playlists, combines the rule and classifier labels, honours explicit negation, and counts exact duplicate playlist groups once. The stored counts support a continuous, smoothed lift per context tag. For example, a lift of `2` means twice the training baseline for that tag after smoothing. A category with no evidence has an unknown lift. Party tags use all groups with at least one context label as the comparison set, so the broad parent tag can carry a signal. There is no percentage cutoff for tagging songs.

Year and tempo never come from playlist text. A decade in the title is a request about the desired playlist. A recording's era comes from its documented release date. The four requested eras are `80s`, `90s`, `00s`, and `10s`. `other` is a known release outside those decades. A blank era means the year is unknown.

## Check the reports

Reports are written under `runs/million/profiles-v2/`.

| File | What to inspect |
| --- | --- |
| `tag_report.json` | Number of training titles used to fit the classifier, plus track, playlist, and validation review counts. |
| `tag_coverage.csv` | Per-tag training and validation counts. The F1 column measures agreement with keyword rules. It needs human-reviewed labels to represent tag accuracy. |
| `title_tag_review.csv` | Ambiguous cues, rule/classifier disagreements and negated cues flagged in the sampled validation titles. The last column is blank for review notes. |
| `tags/` | The classifier and disk-backed track vote counts. Keep these with the local run. |

Run `python scripts/track_profiles.py export-flags` to scan the entire catalogue and produce `track_tag_flags.csv.gz` and `track_flag_report.json`. The compressed CSV has one row per above-baseline context association, with track name, category, votes and lift. It also lists era labels from attempted metadata lookups with their match status. This is a queue for reviewing evidence. It does not certify that a human reviewed each track. The JSON counts tracks with and without positive context evidence.

Inspect any track from the full catalogue using the Spotify ID from its track link. Replace `TRACK_ID` with the actual ID.

```bash
python scripts/track_profiles.py inspect TRACK_ID --playlist-title '90s Rainy Road Trip'
```

## Pilot MusicBrainz and AcousticBrainz coverage

Run this separately from the offline build. The contact is sent as part of the MusicBrainz client identifier. Use your own project URL or contact email. The pilot deterministically samples both popular and less common tracks from the training index.

```bash
python scripts/track_profiles.py enrich --limit 30 \
  --contact 'https://github.com/keshtib07-ghost/ES-335-Nextrack-for-Spotify'
```

The pilot accepts a provisional match only when one MusicBrainz recording agrees on exact normalized title and artist, comparable version, and duration within two seconds. It uses MusicBrainz's `first-release-date` and AcousticBrainz's recording analysis when present. Bass and treble figures are low/high-band mean energy divided by the same analysis document's total mean spectral energy. The original Essentia version is recorded when available. Missing or invalid figures stay blank. Review matches manually before using them for strict decade filters or merging different Spotify IDs.

- `enrichment_pilot.csv` contains every completed lookup, including successful matches.
- `enrichment_issues.csv` contains every unresolved match and each attempted track with missing fields.
- `enrichment_report.json` gives field coverage, match status, and progress for the current sample. `audio_lookup_pending` means the recording match and any release date are saved and the audio request can be retried.

The pilot retries temporary network errors and service timeouts. If MusicBrainz stays unavailable it saves progress and reports where it stopped. If AcousticBrainz stays unavailable the pilot saves the release metadata and continues with MusicBrainz. Run the same command to reuse completed lookups and retry pending audio. Share the JSON summary first and keep the generated CSVs and database local. Date and audio coverage apply to the attempted tracks.

If the MusicBrainz search endpoint returns repeated HTTP 503 responses, add `--recording-source listenbrainz` to the same pilot command. The public ListenBrainz lookup checks the artist, track, and album, then compares recording duration within two seconds. It reads the recording's first release date from the ListenBrainz recording metadata endpoint. Matches stay provisional until reviewed. The pilot retains existing matches and tries unresolved rows with the new provider. `recording_source` in the CSV shows how each row was looked up.

If the album-based pilot leaves tracks unresolved, rerun the same command with `--recording-source listenbrainz-search`. This searches across album editions and accepts a provisional match only when normalized artist and title agree, edition cues are compatible, and one candidate has a duration within two seconds of the input. The pilot reports ambiguous candidates and preserves existing matches, including matches whose audio data is still missing.

Run an individual song-and-artist search without opening the MPD databases:

```bash
PYTHONPATH=src python scripts/track_profiles.py lookup-name 'Run Away - Radio Edit' 'Sunstroke Project' \
  --contact 'https://github.com/keshtib07-ghost/ES-335-Nextrack-for-Spotify'
```

The lookup accepts accent and punctuation differences and allows an MPD artist to be the primary artist on a joint credit. A search with just the title and artist marks a unique result `candidate_without_duration`. Include `--duration-ms` and `--album` when available to check the edition and duration. The title-and-artist fallback accepts duration differences up to five seconds in either direction, and keeps multiple eligible recordings unresolved. Reported `known_release_year` comes from a linked release and is distinct from the recording's first release date. Audio values come from AcousticBrainz when it has data for the selected recording.

To retry existing unresolved pilot tracks with these rules and save the results, use `enrich --recording-source listenbrainz-credits` in the directory that holds their `enrichment.sqlite3`. Existing matched profiles are reused, and unresolved candidates stay in `enrichment_issues.csv`. Keep this public API pass small. Bulk dumps and exact-ID joins are more suitable for catalogue-scale coverage.

For manually confirmed matches, create a CSV with `track_id,recording_id` headers containing Spotify IDs and reviewed MusicBrainz MBIDs. Import those rows through `enrich --reviewed-map path/to/reviewed.csv --contact ...`. This fetches the reviewed recording's profile, reports unavailable data and exports `verified_recording_map.csv` for a future resplit. The optional `--recording-map` argument to `split_million.py` accepts that file. Using it to merge aliases requires a fresh output directory for the split and model. The local song-profile ranker suppresses duplicates with the same reviewed MBID in recommendations.

## Join the Spotify snapshot to all staged tracks

From the repository root, download the pinned public CSV and join it to the staged MPD catalogue by Spotify ID.

```bash
mkdir -p private-data
curl -fL --retry 3 \
  'https://huggingface.co/datasets/khushimalviya/spotify-tracks-dataset/resolve/927b3db3dde9e40ba111d2064cae3ebda437de3a/spotify_tracks.csv' \
  -o private-data/spotify_tracks.csv.part &&
mv private-data/spotify_tracks.csv.part private-data/spotify_tracks.csv &&
python scripts/join_spotify_snapshot.py --csv private-data/spotify_tracks.csv
```

The default source is `runs/million/mpd.sqlite3` and the default output directory is `runs/million/profiles-v2-expanded`. Pass `--output` to use the directory where your pilot's `enrichment.sqlite3` lives. Pass `--source` if the staged MPD database lives elsewhere.

- `spotify_snapshot.sqlite3` stores one row per matching `spotify_id` with `bpm` and `catalogue_release_date`. An empty or conflicting value stays blank. A catalogue date can describe a later edition of the same recording.
- `spotify_snapshot_report.json` reports exact ID coverage and how many tracks still need each field. For each field, `new` counts IDs that gained a value and `combined` includes any existing MusicBrainz/AcousticBrainz coverage in the same output directory. The two date fields stay separate and `any_release_date` counts a track once even if both fields exist.

The join reads the two existing databases and stores metadata in its own output. The CSV contains no measurements for bass or treble. This is a coverage pass while the permissions for model use of the snapshot are being established.

## Enrich the full catalogue with multiple sources

Run this from the repository root with an existing `runs/million/mpd.sqlite3` and the CSV downloaded above. The optional second Spotify snapshot requires `pyarrow`.

```bash
python -m pip install pyarrow
mkdir -p private-data
curl -fL --retry 3 -o private-data/spotify-audio.parquet \
  'https://huggingface.co/datasets/P-Arpan/Mood_Based_Music_Search/resolve/67fc77da5087838836d33f9b98c9a72e5acbcd60/Spotify_Audio_features.parquet'
curl -fL --retry 3 -o private-data/mb-recording.tar.xz \
  'https://data.metabrainz.org/pub/musicbrainz/data/json-dumps/20261114-001001/recording.tar.xz'
PYTHONPATH=src python -m scripts.enrich_catalogue \
  --spotify-parquet private-data/spotify-audio.parquet \
  --musicbrainz private-data/mb-recording.tar.xz \
  --acoustic-online-limit 400 \
  --contact 'https://github.com/keshtib07-ghost/ES-335-Nextrack-for-Spotify'
```

Every staged Spotify ID gets one `profiles` row in `runs/million/catalogue-enrichment/catalogue_enrichment.sqlite3`. The report gives the number of tracks with all four fields together. An exact Spotify ID takes precedence over a title-and-artist match. The metadata fallback needs compatible version cues, a duration difference of at most five seconds, and a unique candidate. AcousticBrainz supplies measurements by MusicBrainz recording ID. Online audio lookups use batches of at most 25 and reuse the results already in `acoustic_web_cache.sqlite3` on a rerun.

The compact MusicBrainz recording dump covers a subset of MusicBrainz recordings. Pass `--musicbrainz-releases private-data/release.tar.xz` with the official release dump to match its tracks and obtain release dates. Spotify catalogue dates and MusicBrainz dates occupy separate columns. Pass `--acoustic-archive /path/to/lowlevel.tar.zst` once per official AcousticBrainz low-level JSON archive for offline spectral coverage. Reading `.tar.zst` needs the `zstd` executable. Leaving out `--acoustic-online-limit` runs the joins offline. The Spotify sources are included for a coverage audit. Check data permissions before using the results for training.

## Try the profile filters and Spotify export

To use the new ranker, run `python scripts/serve_million_demo.py` and open `http://127.0.0.1:8000/`. It automatically finds the new song-profile index. Explicit era filters require reviewed dates. Other context choices affect ranking. Tracks with missing BPM may still appear. Bass and treble preferences use the measured subset. The existing benchmark remains tied to the previous tagger.

To enable album artwork and private Spotify playlist export, create a Spotify Web API app in your developer dashboard and add this exact redirect URI:

```text
http://127.0.0.1:8000/
```

Start the server with the app's Client ID. The browser uses Spotify OAuth with PKCE and the `playlist-modify-private` scope. You only need the Client ID.

```bash
python scripts/serve_million_demo.py --spotify-client-id YOUR_SPOTIFY_CLIENT_ID
```

Choose **Generate & save to Spotify** or preview and choose **Save to Spotify**. The saved track order matches the visible list. The open link appears after Spotify confirms the tracks. A retry after playlist creation uses the existing playlist. Spotify's Development Mode requires the account to be allowed to use the app. GitHub Pages runs a small real-song preview with illustrative rankings. The full catalogue, artwork lookup and Spotify export are exercised with the local server and an authorized Spotify account.
