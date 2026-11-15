import argparse
import csv
import hashlib
import json
from pathlib import Path

import joblib
import numpy as np

from .data import PARTITIONS, playlist_query, read_dataset, stable_hash, track_id
from .ranker import PlaylistRanker, recommend
from .tagger import (TAGS, TitleTagger, classification_metrics, grouped_recording_evidence,
                     label_training_titles, normalize, read_annotations)


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def design_sample(input_path, output, sample_size, seed, metadata):
    playlists, *_ = read_dataset(input_path, metadata)
    with Path(output).open('w', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow(['pid', 'split', 'title', 'tags'])
        for subset in PARTITIONS:
            rows = [p for p in playlists if p.split == subset]
            rows.sort(key=lambda p: stable_hash(f'annotation-{seed}', str(p.pid)))
            for row in rows[:sample_size]:
                writer.writerow([row.pid, row.split, row.title, 'skip'])


def scores_for(ranks, targets, k=20):
    hits = [index for index, item in enumerate(ranks) if item in targets]
    ideal = sum(1 / np.log2(i + 2) for i in range(min(k, len(targets))))
    return np.asarray((len(hits) / len(targets), sum(1 / np.log2(i + 2) for i in hits) / ideal,
                       len(hits) / k, int(bool(hits))))


def evaluate(playlists, bundle, strengths):
    ranking, tagger = bundle['ranker'], bundle['tagger']
    predictions = tagger.predict([p.title for p in playlists])
    runs = {'popularity': [], 'cf': [], **{f'tags_{x:g}': [] for x in strengths if x}}
    groups, labeled, seed_cold, incomplete_targets = [], [], 0, 0
    target_count = 0
    for row, tag_row in zip(playlists, predictions):
        query = playlist_query(row, bundle['tracks'])
        if query is None:
            continue
        seeds, targets = query
        columns = np.flatnonzero(tag_row)
        groups.append(row.fingerprint)
        labeled.append(bool(len(columns)))
        seed_cold += int(not ranking.counts[seeds].any())
        incomplete_targets += sum(ranking.counts[item] == 0 for item in targets)
        target_count += len(targets)
        items, weights = ranking.candidates(seeds)
        runs['popularity'].append(scores_for(ranking.popularity(seeds), targets))
        runs['cf'].append(scores_for(ranking.recommend_from(items, weights), targets))
        for strength in strengths:
            if strength:
                ranks = ranking.recommend_from(items, weights, columns, bundle['lifts'], strength)
                runs[f'tags_{strength:g}'].append(scores_for(ranks, targets))
    if not groups:
        raise ValueError('No eligible playlists have more than three recordings')
    return ({name: np.asarray(values) for name, values in runs.items()}, np.asarray(labeled), groups,
            {'queries': len(groups), 'title_conditioned_queries': int(sum(labeled)),
             'all_seeds_cold': seed_cold, 'unseen_reference_occurrences': int(incomplete_targets),
             'all_reference_occurrences': target_count})


def tagger_audit(tagger, playlists, annotations, known_titles):
    title_text = [row.title for row in playlists]
    guessed = tagger.predict(title_text)
    weak = label_training_titles(playlists, {})
    reviewed = np.asarray([i for i, row in enumerate(playlists) if row.pid in annotations], dtype=int)
    novel = np.asarray([normalize(row.title) not in known_titles for row in playlists], dtype=bool)
    truth = label_training_titles(playlists, annotations)
    return {'rule_agreement': classification_metrics(weak, guessed),
            'rule_agreement_unseen_titles': classification_metrics(weak[novel], guessed[novel]),
            'reviewed_classifier': classification_metrics(truth[reviewed], guessed[reviewed]),
            'reviewed_rule_baseline': classification_metrics(truth[reviewed], weak[reviewed])}


def summary(metrics, mask):
    names = ('recall_at_20', 'ndcg_at_20', 'precision_at_20', 'hit_rate_at_20')
    return {name: dict(zip(names, map(float, table[mask].mean(axis=0)))) for name, table in metrics.items()} if mask.any() else {}


def paired_interval(differences, groups, mask):
    if not mask.any():
        return None
    _, inverse = np.unique(np.array(groups)[mask], return_inverse=True)
    group_sizes = np.bincount(inverse)
    sums = np.bincount(inverse, weights=differences[mask])
    rng = np.random.default_rng(335)
    draws = []
    for _ in range(500):
        draw = rng.integers(0, len(sums), size=len(sums))
        draws.append(sums[draw].sum() / group_sizes[draw].sum())
    return [float(value) for value in np.quantile(draws, [.025, .975])]


def fit(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    playlists, tracks, aliases, data, split_counts = read_dataset(args.input, args.metadata)
    annotations = read_annotations(args.annotations)
    splits = {part: [p for p in playlists if p.split == part] for part in PARTITIONS}
    train, val, test = (splits[part] for part in PARTITIONS)
    with (output / 'split.csv').open('w', encoding='utf-8', newline='') as handle:
        writer = csv.writer(handle)
        writer.writerow(('pid', 'group', 'split'))
        writer.writerows((p.pid, p.fingerprint, p.split) for p in playlists)
    initial = label_training_titles(train, annotations)
    train_titles, val_titles = [p.title for p in train], [p.title for p in val]
    tagger = TitleTagger().fit(train_titles, initial)
    sources = tagger.select_thresholds(val_titles, label_training_titles(val, annotations),
                                       np.asarray([p.pid in annotations for p in val], dtype=bool))
    print(f'Trained title tagger from {len(train):,} training titles', flush=True)
    predicted = tagger.predict(train_titles)
    for index, playlist in enumerate(train):
        if playlist.pid in annotations:
            predicted[index] = [tag in annotations[playlist.pid] for tag in TAGS]
    tally, opportunities, lifts, prior = grouped_recording_evidence(train, predicted, len(tracks))
    ranker = PlaylistRanker(len(tracks), train)
    bundle = {'tagger': tagger, 'tracks': tracks, 'aliases': aliases, 'ranker': ranker,
              'lifts': lifts, 'tally': tally, 'opportunities': opportunities}
    grid = (0., .25, .5, 1., 2.)
    measurements, labeled, _, query_stats = evaluate(val, bundle, grid)
    target_mask = labeled if labeled.any() else np.ones(len(labeled), dtype=bool)
    baseline = measurements['cf'][target_mask, 1].mean()
    objective = {x: float((measurements[f'tags_{x:g}'][target_mask, 1].mean() if x else baseline)) for x in grid}
    strength = max(grid, key=lambda x: (objective[x], -x))
    bundle['strength'] = strength
    freeze = {'seeds': 3, 'k': 20, 'split_sha256': hashlib.sha256((output / 'split.csv').read_bytes()).hexdigest(),
              'title_thresholds': dict(zip(TAGS, map(float, tagger.thresholds))),
              'threshold_label_source': sources, 'validation_tag_weight_objective': objective,
              'tag_weight': strength, 'candidate_neighbours': ranker.neighbours,
              'similarity_shrinkage': ranker.shrinkage, 'context_prior_strength': 20,
              'tag_display_starting_rule': {'min_votes': 5, 'min_rate': .40, 'min_lift_strict': 1.0}}
    write_json(output / 'freeze.json', freeze)
    print(f'Validation selected context weight {strength:g}', flush=True)
    known_titles = {normalize(title) for title in train_titles}
    report = {'data': data, 'split': split_counts, 'frozen_settings': freeze,
              'training': {'tracks': len(ranker.popular),
                           'title_tags': dict(zip(TAGS, map(int, predicted.sum(axis=0)))),
                           'title_annotations': {part: sum(p.pid in annotations for p in rows) for part, rows in splits.items()},
                           'tag_priors': dict(zip(TAGS, map(float, prior)))},
              'validation': {'queries': query_stats, 'all': summary(measurements, np.ones(len(labeled), bool)),
                             'tagged_titles': summary(measurements, labeled),
                             'title_tagger': tagger_audit(tagger, val, annotations, known_titles)}}
    if args.evaluate_test:
        # Both weights were explicitly included in the validation grid. The fixed .5 arm is diagnostic only.
        measured, labeled, groups, query_stats = evaluate(test, bundle, sorted({strength, .5}))
        chosen = measured[f'tags_{strength:g}'] if strength else measured['cf']
        delta = measured['tags_0.5'][:, 1] - measured['cf'][:, 1]
        measured['selected_ranker'] = chosen
        report['test'] = {'queries': query_stats, 'all': summary(measured, np.ones(len(labeled), bool)),
                          'tagged_titles': summary(measured, labeled),
                          'diagnostic_half_weight_minus_cf_ndcg_95_ci_tagged': paired_interval(delta, groups, labeled),
                          'title_tagger': tagger_audit(tagger, test, annotations, known_titles)}
        print(f'Scored {len(labeled):,} held-out continuation queries', flush=True)
    ranker.cache.clear()
    joblib.dump(bundle, output / 'model.joblib', compress=3)
    write_json(output / 'evaluation.json', report)
    print(json.dumps({'data': data, 'split': split_counts, 'selected_tag_weight': strength,
                      'test': report.get('test', {}).get('all')}, indent=2), flush=True)


def main():
    parser = argparse.ArgumentParser(prog='playlist-model')
    commands = parser.add_subparsers(dest='command', required=True)
    review = commands.add_parser('sample-titles')
    review.add_argument('--input', required=True)
    review.add_argument('--output', required=True)
    review.add_argument('--per-split', type=int, default=50)
    review.add_argument('--sample-seed', default='335')
    review.add_argument('--metadata')
    train = commands.add_parser('fit')
    train.add_argument('--input', required=True)
    train.add_argument('--output', required=True)
    train.add_argument('--metadata')
    train.add_argument('--annotations')
    train.add_argument('--evaluate-test', action='store_true')
    search = commands.add_parser('find')
    search.add_argument('--model', required=True)
    search.add_argument('query')
    search.add_argument('--limit', type=int, default=10)
    rec = commands.add_parser('recommend')
    rec.add_argument('--model', required=True)
    rec.add_argument('--title', default='')
    rec.add_argument('--seed', action='append', required=True, help='A Spotify track ID or track URI')
    rec.add_argument('--tag', action='append', choices=TAGS)
    rec.add_argument('--era', type=int, choices=(1970, 1980, 1990, 2000, 2010, 2020))
    rec.add_argument('--bpm-range', type=float, nargs=2)
    args = parser.parse_args()
    try:
        if args.command == 'sample-titles':
            design_sample(args.input, args.output, args.per_split, args.sample_seed, args.metadata)
        elif args.command == 'fit':
            fit(args)
        else:
            bundle = joblib.load(args.model)
            if args.command == 'find':
                words = args.query.casefold().split()
                matched = [(i, track) for i, track in enumerate(bundle['tracks'])
                           if all(word in f'{track.title} {track.artist}'.casefold() for word in words)]
                matched.sort(key=lambda pair: (-int(bundle['ranker'].counts[pair[0]]), pair[1].title))
                print(json.dumps([{'title': track.title, 'artist': track.artist, 'spotify_id': track.spotify_id,
                                   'training_playlists': int(bundle['ranker'].counts[i])}
                                  for i, track in matched[:args.limit]], ensure_ascii=False, indent=2))
            else:
                seeds = [track_id(seed) for seed in args.seed]
                if len(seeds) not in range(1, 4) or None in seeds:
                    raise ValueError('Supply one to three valid Spotify IDs or track URIs')
                print(json.dumps(recommend(bundle, args.title, seeds, args.tag, args.era, args.bpm_range),
                                 ensure_ascii=False, indent=2))
    except (OSError, ValueError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    main()
