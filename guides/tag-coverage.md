# Improve and review context tagging

The study compares the existing context profiles with a new cue revision. The 20,000 development playlists informed additions such as `roadtrip`, `chillin`, `crossfit`, and `sleepytime`. The comparison runs on your existing MPD split and uses the same collaborative-filtering index. A song name or album name supplies no new tag in this study.

## Run on the existing data

```bash
export PYTHONPATH="$PWD/src"
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1
EXPANDED=runs/million/profiles-v2-expanded
python scripts/tag_coverage_study.py titles
python scripts/track_profiles.py --output "$EXPANDED" build --expanded-title-cues
```

`titles` reports exact old and new rule coverage across training titles. `title_cue_review.csv` contains examples supporting each rule addition. Start the website with the revised direct tags using `python scripts/serve_million_demo.py --profiles "$EXPANDED"`.

## Add release years and sound profiles

Run the [metadata enrichment pilot](track-profiles.md) against the same profiles that the website uses:

```bash
python scripts/track_profiles.py --output "$EXPANDED" enrich --limit 30 \
  --contact 'https://github.com/keshtib07-ghost/ES-335-BeatX-Automatic-Playlist-Continuation'
```

## Archived graph experiment

The website uses direct title tags from training playlists. The graph experiment added tags to two of 2,000 recommendation slots beyond the expanded title cues. The run and its review remain reproducible with `python scripts/tag_coverage_study.py graph`.

The default pilot checks `chill`, `drive`, `gym`, and `study_focus`. It uses training-only cosine similarity with shrinkage from the existing recommender. A direct tag can vote if it appeared in at least three distinct tagged playlist groups. For each previously unflagged track, the pilot examines up to 40 neighbours and requires at least two voting tracks by different known artists per tag. The score divides similarity mass from qualifying neighbours by similarity mass from all included neighbours. It is an evidence score, not a probability. Inferred tags do not feed back into the next song's score.

`graph_report.json` includes exact original and expanded catalogue coverage, counts by tag, coverage gained and lost, tracks with no training appearances, and graph suggestions at four cutoffs. It samples unflagged tracks separately by training support and weights the coverage estimate by the number of tracks in each stratum. These estimates describe potential flags. They do not measure the quality of the flags.

The validation top-20 section measures how many tracks in the **same** recommendation lists get a tag under each method. A separate sample stratified by title cue checks context-specific coverage on up to 25 playlists per pilot tag. Recommendation order stays fixed. The comparison measures tag visibility and agreement with the title cue. Recall and NDCG can be evaluated in a later ranking experiment.

## Review by listening

Open `runs/million/tag-coverage-study/blind_song_review.csv`. Use its links to spot-check the song and fill `judgment` with `yes`, `no`, or `unsure` for the tag shown. Rows are shuffled. The separate `song_review_key.csv` records the method and example neighbours. Keep it closed during review.

After saving the file:

```bash
python scripts/tag_coverage_study.py review-metrics runs/million/tag-coverage-study/blind_song_review.csv
```

The score report separates approval rates by method, tag and graph cutoff, with 95% Wilson intervals and counts of unsure responses. The sheet deliberately samples graph candidates and below-cutoff controls, so its rates describe reviewed examples.
