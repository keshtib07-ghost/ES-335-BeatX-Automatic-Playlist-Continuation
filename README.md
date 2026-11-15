# Playlist continuation from a title and seed songs

This is a clean implementation for ES 335. It asks whether automatically inferred, playlist-derived tags improve hidden-recording recovery over ordinary item-based collaborative filtering given three visible recordings. A separate audit checks whether the title classifier understands the requested tags.

## Million-playlist run and website

- [Prepare and split the full MPD](scripts/README.md)
- [Train, validate, and evaluate the full model](scripts/full_training.md)
- [Run the local trained demo and publish the static site](scripts/site.md)
- [Compare six seed budgets, title methods, and playback order](scripts/extended_study.md)

The full run processed 1,000,000 playlists and trained collaborative filtering on 804,485. On a fixed sample of 5,000 fresh test playlists with three visible seeds, NDCG@20 was 0.0372 for popularity, 0.2497 for collaborative filtering, and 0.2513 for the selected title-aware ranker. Among the 660 queries with inferred tags, the last two scores were 0.2041 and 0.2166. These scores measure recovery of withheld tracks. The original 20,000-playlist pilot is documented below as a separate run.

## 1. Set up the local environment

Use Python 3.11 or newer. Python 3.12 is the version used for the reference run.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export PYTHONPATH="$PWD/src"
python -m unittest discover -s tests -v
```

On Ubuntu or WSL, if venv creation reports missing `ensurepip`, install `python3-venv` first. Run these commands from the extracted `playlist-model` folder.

## 2. Prepare the data

```bash
python download_pilot.py
```

The reproducibility manifest pins 20 slices of the Spotify Million Playlist Dataset to a specific public mirror commit and Git blob hashes. That is about 650 MiB of raw JSON and 20,000 playlists. The script verifies existing files before reusing them. For an existing private MPD copy, `fit --input` accepts a directory with `mpd.slice.*.json` files (including subfolders) or a single MPD JSON file. Use the exact 20 slices in `artifacts/source_manifest.json` to reproduce the reference run.

The raw unit is a playlist containing zero or more distinct recording memberships after cleaning. Duplicate occurrences of a Spotify ID collapse to one membership. The preparation step allocates exact recording-set groups to a deterministic 80/10/10 target split. Playlist IDs 0–999, used to design the taxonomy, and their duplicate groups go to training. Validation and test lists are written to `split.csv` during training. Playlist title, three visible seeds, and optional explicitly selected tags are the inference-time inputs. Hidden references are unavailable to the ranker.

### Optional verified catalogue enrichment

The raw MPD has Spotify track IDs and names. It lacks reliable recording equivalence, original release year, and BPM. Supply a privately stored and documented `--metadata verified-metadata.csv` with columns:

```csv
track_id,recording_id,release_year,bpm
```

Only assign a shared `recording_id` to IDs verified to be the same recording. The parser also accepts rows for metadata-only enrichment with a distinct recording ID. The year is the verified first release year of that recording. Leave unreliable year and BPM fields blank. If multiple valid year rows are supplied for a merged recording, the code uses the earliest supplied date. BPM observations for the same recording that differ by more than 3 BPM stay unknown. Record the metadata source and licence. The reference run uses no external enrichment and thus reports zero verified merges and no verified era or BPM coverage. Estimates derived from a title are never substituted for recording metadata.

## 3. Review labels and train

The reference audit `artifacts/ai-title-audit.csv` contains 154 AI-reviewed labels for a deterministic sample of held-out titles. It is a small audit of title interpretation and has limited coverage for rare tags. It is separate from the keyword labels used to fit the classifier on the training split. Validation labels support threshold selection where there are enough reviewed positives. Keyword-label agreement is reported separately. Review the taxonomy and annotation judgments yourself before making course claims.

To create a fresh review sheet, use:

```bash
python -m playlist_model sample-titles --input private-data \
  --output private-data/my-title-review.csv --per-split 80
```

Use `--metadata` consistently for review and training if applicable. The `tags` field accepts a quoted, comma-separated label list, `unknown` for a reviewed title with no supported tag, or `skip` for an uncertain or unreviewed title. Available labels are `sad`, `chill`, `upbeat`, `gym`, `study`, `sleep`, `dance`, `party`, `rave`, `rainy`, `summer`, and `winter`. Decades are extracted separately as title intent and depend on verified release-year metadata at ranking time.

Reproduce the fixed reference validation and test run:

```bash
OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 python -m playlist_model fit \
  --input private-data --output runs/pilot \
  --annotations artifacts/ai-title-audit.csv --evaluate-test
```

For new experiments, omit `--evaluate-test` while designing and tuning. Choose the split, labels, settings and metric before evaluating a new holdout. The reference run wrote `freeze.json` with selected title thresholds, tag weight and split checksum before scoring test. The prespecified half-weight arm is diagnostic. Settings continue to be selected on validation.

### What training computes

1. **Title tags.** Word and character TF-IDF features feed one logistic regression per tag. Clear cues supply weak training labels and reviewed examples can override them. The model can assign several labels or abstain.
2. **Recording context.** Each exact playlist group provides at most one vote per tag to its recordings. Evidence for a tag is divided by the number of playlists with a usable label in its category. A smoothed rate is compared to the training background rate. Recordings with little evidence get conservative scores. Display badges use the initial rule of five positive votes, 40% support and lift above 1.
3. **Continuation.** Count training-playlist co-occurrences in sparse matrices, compute shrinkage-adjusted cosine neighbours, and add the scores from the three seeds. Popularity backs up empty candidate pools. The tag model reranks the same candidates based on positive tag lift. Year and tempo are separate optional constraints when matching metadata is available.
4. **Evaluate.** Compare popularity, plain collaborative filtering, and tag-aware collaborative filtering on the same three seeds and references. Report Recall@20, NDCG@20, Precision@20, and Hit Rate@20 overall and for titles the tagger labeled. Unseen reference recordings remain in the denominator. The paired bootstrap resamples exact playlist groups.

## 4. Try the trained model

Search for songs in the training catalogue:

```bash
python -m playlist_model find --model runs/pilot/model.joblib 'eye of the tiger'
```

Use the Spotify IDs returned by search, one flag per song:

```bash
python -m playlist_model recommend --model runs/pilot/model.joblib \
  --title 'Rainy Night Study' --seed ID_1 --seed ID_2 --seed ID_3
```

Verified example using Yiruma, Yann Tiersen and Steve Anderson recordings in this pilot:

```bash
python -m playlist_model recommend --model runs/pilot/model.joblib \
  --title 'Rainy Night Study' \
  --seed 7fnqltLx83HsYLQajzCYRk \
  --seed 3YYKrn3iGOAel605Znt3ai \
  --seed 64fGW0tyU2caV8ddFLUUBj
```

Output includes inferred tags, tags applied, recommendations, training votes behind supported tags, and missing metadata notices. Add `--tag chill` to directly choose a tag, `--era 1990` to request verified 1990s tracks, or `--bpm-range 120 128` to request an explicit range. Only load local model files from a trusted run. Joblib checkpoints can execute code when deserialized.

## Evidence and limits

| Three seeds per held-out playlist | Recall@20 | NDCG@20 |
| --- | ---: | ---: |
| Popularity | 0.01220 | 0.03758 |
| Plain collaborative filtering | 0.07641 | 0.20114 |
| Collaborative filtering with title tags | 0.07650 | 0.20223 |

The reference split contains 16,242 training, 1,854 validation, and 1,904 test playlists. The 241 test queries with an inferred tag had NDCG@20 of 0.15047 for plain CF and 0.15909 for the selected tag-aware ranking. The fixed half-weight diagnostic also improved tagged-query NDCG on this sample. Scores measure recovery of withheld recordings. The separate 76-title AI-reviewed test audit gave supported-tag macro F1 of 0.667 for both the learned classifier and its keyword baseline. Several rare tags had zero audited test positives. This is evidence of a small ranking gain, with no observed title-audit gain over the rules in that small sample.

- `artifacts/evaluation.json` contains the reference run's aggregate results. `runs/pilot/` contains your locally generated checkpoint and evaluation files.
- A match against keyword labels measures agreement with the rules, not verified music mood. The small AI-assisted title audit and title-based recording scores are separate. A listening audit is needed to support claims about human-perceived mood.
- This is a 20,000-playlist pilot on an identified subset. It cannot support claims about all million playlists. Near-duplicate playlists and duplicates missed by the recording-ID mapping can still cross splits.
- Title tags are sparse and often describe intentions such as studying or exercising. Users can supply their own tags. Raw playlists, title review records with strings, and trained files containing per-recording data should remain private unless applicable terms permit sharing.

## Sources and AI-use disclosure

- Chen, C.-W., Lamere, P., Schedl, M., and Zamani, H. (2018). *RecSys Challenge 2018: Automatic Music Playlist Continuation*. https://doi.org/10.1145/3240323.3240342
- Dataset access and rules: https://www.aicrowd.com/challenges/spotify-million-playlist-dataset-challenge/challenge_rules
- Sarwar, B., Karypis, G., Konstan, J., and Riedl, J. (2001). *Item-Based Collaborative Filtering Recommendation Algorithms*. https://doi.org/10.1145/371920.372071
- scikit-learn text features and multilabel learning: https://scikit-learn.org/stable/modules/feature_extraction.html#text-feature-extraction and https://scikit-learn.org/stable/modules/multiclass.html
- Codex assisted with the design, code, title annotations, results checks and documentation. Audit annotations were made by Codex, not by the project students. The students should review the implementation and evidence and describe their own contributions in the final disclosure.
