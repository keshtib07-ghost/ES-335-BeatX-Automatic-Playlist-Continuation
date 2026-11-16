"""Compare title-cue coverage and test one-hop song-tag inference."""

import argparse
import csv
import json
import math
import sqlite3
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

import numpy as np

from playlist_model.million import DiskRanker, make_seeds, open_dataset, rank_candidates, read_json, write_json
from playlist_model.profile_tags import CONTEXT_AXIS, CONTEXT_TAGS, EXPANDED_CUES_VERSION, TAXONOMY_VERSION, weak_context

if __package__:
    from .seed_study import artist_index
    from .track_profiles import write_csv
else:
    from seed_study import artist_index
    from track_profiles import write_csv


GRAPH_TAGS = ('chill', 'drive', 'gym', 'study_focus')
THRESHOLDS = (.03, .06, .10, .20)
NEIGHBOURS = 40
SEED = 33507


def audit_title_rules(data, output):
    counts, by_tag, examples = Counter(), Counter(), defaultdict(list)
    for pid, title in data.rows('train', 'p.pid, p.title'):
        old, new = weak_context(title), weak_context(title, expanded=True)
        counts.update({'titles_checked': 1, 'old_rule_tagged_titles': bool(old), 'expanded_rule_tagged_titles': bool(new),
                       'newly_tagged_titles': bool(not old and new), 'previous_tags_lost': bool(old - new)})
        for tag in sorted(new - old):
            by_tag[tag] += 1
            if len(examples[tag]) < 40:
                examples[tag].append((pid, title, '|'.join(sorted(old)), tag, ''))
    write_csv(output / 'title_cue_review.csv', ('playlist_id', 'title', 'previous_tags', 'added_tag', 'judgment'),
              (row for tag in CONTEXT_TAGS for row in examples[tag]))
    return {**counts, 'new_assignments_by_tag': dict(by_tag)}


def profile_flags(data, folder, version):
    path = folder / 'tags'
    identity = read_json(path / 'summary.json')['identity']
    if identity['split'] != data.identity['split'] or identity['taxonomy_version'] != version:
        raise ValueError(f'{folder} has the wrong data split or cue revision.')
    votes = np.load(path / 'track_tag_votes.npy', mmap_mode='r')
    totals = np.load(path / 'track_axis_totals.npy', mmap_mode='r')
    prior = np.load(path / 'tag_priors.npy')
    flags = np.empty(votes.shape, dtype=bool)
    for start in range(0, len(votes), 32768):
        part = slice(start, start + 32768)
        flags[part] = (prior > 0) & (votes[part] > 0) & (votes[part] > totals[part][:, CONTEXT_AXIS] * prior)
    return flags, votes


def score_neighbours(ids, weights, anchors, artist_ids):
    """Eligible votes from direct anchors; normalise by all relevant neighbours."""
    votes = anchors[ids]
    denominator = weights.sum()
    scores = weights @ votes / denominator if denominator else np.zeros(anchors.shape[1])
    support = votes.sum(axis=0)
    sources, artists = [], []
    for column in votes.T:
        artist_set = set(artist_ids[ids[column]]) - {-1}
        artists.append(len(artist_set))
        sources.append(ids[column][:3])
    trusted = (support >= 2) & (np.array(artists) >= 2)
    return np.where(trusted, scores, 0.), support, artists, sources


def pick_sample(items, limit, rng):
    if len(items) <= limit:
        return rng.permutation(items)
    return rng.choice(items, limit, replace=False)


def track_info(data, index):
    return data.connection.execute('SELECT spotify_id, track_name, artist_name FROM catalogue WHERE track_index=?',
                                   (int(index),)).fetchone()


def make_review(data, output, anchors, sample, graph_score, per_arm, rng):
    rows = []
    for col, tag in enumerate(GRAPH_TAGS):
        direct_items = np.flatnonzero(anchors[:, col])
        graph_items = np.array([i for i in sample if graph_score(i)[0][col] >= THRESHOLDS[1]], dtype=np.int32)
        near_items = np.array([i for i in sample if 0 < graph_score(i)[0][col] < THRESHOLDS[1]], dtype=np.int32)
        for arm, pool in (('direct', direct_items), ('graph', graph_items), ('below_graph_gate', near_items)):
            for track in pick_sample(pool, per_arm, rng):
                scores, support, artists, sources = graph_score(track) if arm != 'direct' else (None, None, None, None)
                ids = '|'.join(track_info(data, other)[0] for other in sources[col]) if sources is not None else ''
                rows.append((track, tag, arm, float(scores[col]) if scores is not None else '',
                             int(support[col]) if support is not None else '', artists[col] if artists is not None else '', ids))
    rng.shuffle(rows)
    blind, key = [], []
    for i, (track, tag, arm, score, count, artists, source_ids) in enumerate(rows, start=1):
        spotify, title, artist = track_info(data, track)
        review_id = f'T{i:04d}'
        blind.append((review_id, spotify, title, artist, tag, f'https://open.spotify.com/track/{spotify}', '', ''))
        key.append((review_id, spotify, tag, arm, score, count, artists, source_ids))
    write_csv(output / 'blind_song_review.csv', ('review_id', 'spotify_id', 'title', 'artist', 'tag', 'spotify_url', 'judgment', 'notes'), blind)
    write_csv(output / 'song_review_key.csv', ('review_id', 'spotify_id', 'tag', 'arm', 'graph_score',
                                              'voting_neighbours', 'distinct_artists', 'example_neighbour_ids'), key)
    return len(blind)


def run_graph(data, args):
    base, _ = profile_flags(data, args.baseline, TAXONOMY_VERSION)
    direct, votes = profile_flags(data, args.expanded, EXPANDED_CUES_VERSION)
    cols = [CONTEXT_TAGS.index(tag) for tag in GRAPH_TAGS]
    anchors = direct[:, cols] & (votes[:, cols] >= 3)
    base_covered, covered = base.any(axis=1), direct.any(axis=1)
    original_intent, expanded_intent = base[:, cols], direct[:, cols]
    direct_counts = {tag: {'original': int(base[:, col].sum()), 'expanded': int(direct[:, col].sum())}
                     for col, tag in enumerate(CONTEXT_TAGS)}
    del base, direct, votes
    if read_json(args.model / 'index/summary.json')['identity'] != data.identity:
        raise ValueError('Collaborative-filtering index belongs to a different run.')
    ranker = DiskRanker(args.model / 'index')
    artists = artist_index(data)
    rng = np.random.default_rng(SEED)

    @lru_cache(maxsize=20_000)
    def graph_score(index):
        ids, weights = ranker.neighbours(int(index))
        return score_neighbours(ids[:NEIGHBOURS], weights[:NEIGHBOURS], anchors, artists)

    before, after = int(base_covered.sum()), int(covered.sum())
    report = {'track_ids_checked': data.track_count, 'original_direct_positive': before, 'expanded_direct_positive': after,
              'newly_covered_by_expansion': int((covered & ~base_covered).sum()),
              'lost_direct_coverage_after_expansion': int((base_covered & ~covered).sum()),
              'unflagged_with_no_training_appearances': int(((ranker.counts == 0) & ~covered).sum()),
              'direct_flags_by_tag': direct_counts, 'graph_tags': GRAPH_TAGS, 'graph_thresholds': THRESHOLDS,
              'by_training_support': {}}
    sampled = []
    estimate = np.zeros(len(THRESHOLDS))
    strata = [('1–4', 1, 4), ('5–19', 5, 19), ('20+', 20, int(ranker.counts.max()))]
    for label, lower, upper in strata:
        pool = np.flatnonzero((ranker.counts >= lower) & (ranker.counts <= upper) & ~covered)
        sample = pick_sample(pool, args.per_stratum, rng)
        sampled.extend(map(int, sample))
        print(f'Scoring {len(sample)} unflagged tracks with {label} training appearances', flush=True)
        details = [graph_score(int(i)) for i in sample]
        scores = np.array([item[0] for item in details]).reshape(-1, len(GRAPH_TAGS))
        supporting = np.array([item[1] for item in details]).reshape(-1, len(GRAPH_TAGS))
        thresholds = {}
        for index, threshold in enumerate(THRESHOLDS):
            accepted = scores >= threshold
            any_ = int(accepted.any(axis=1).sum())
            rate = any_ / len(sample) if len(sample) else 0.
            estimate[index] += rate * len(pool)
            thresholds[str(threshold)] = {'tracks': any_, 'share': rate if len(sample) else None,
                                          'by_tag': dict(zip(GRAPH_TAGS, map(int, accepted.sum(axis=0)))),
                                          'median_voting_neighbours': float(np.median(supporting[accepted])) if any_ else None}
        report['by_training_support'][label] = {'eligible_catalogue_tracks': len(pool), 'sampled_tracks': len(sample),
                                               'thresholds': thresholds}
    report['estimated_extra_catalogue_tracks'] = {str(threshold): round(estimate[i]) for i, threshold in enumerate(THRESHOLDS)}

    counts = Counter()
    intent = defaultdict(Counter)

    @lru_cache(maxsize=512)
    def top20(pid, payload, count):
        seeds, _ = make_seeds(pid, data.recordings(payload, count))
        pool, scores, fallback = ranker.candidates(seeds)
        result = rank_candidates(pool, scores, fallback, np.zeros(len(pool)), 0.)
        unlabelled = result[~covered[result]]
        inferred = np.array([graph_score(int(i))[0] for i in unlabelled]).reshape(-1, len(GRAPH_TAGS)) >= THRESHOLDS[1]
        return result, inferred

    matched_queries = 0
    validation = data.sample('validation', 'p.pid,p.track_indices,s.recording_count', args.queries, salt=SEED, eligible=True)
    for pid, payload, count in validation:
        result, inferred = top20(pid, payload, count)
        counts['recommendation_slots'] += len(result)
        counts['original_direct'] += int(base_covered[result].sum())
        counts['expanded_direct'] += int(covered[result].sum())
        counts['expanded_plus_graph_at_0.06'] += int(covered[result].sum() + inferred.any(axis=1).sum())
        matched_queries += bool(len(result))

    intent_pool = data.sample('validation', 'p.pid,p.title,p.track_indices,s.recording_count',
                              max(6_000, args.intent_queries), salt=SEED + 1, eligible=True)
    intent_sample = defaultdict(list)
    for i in rng.permutation(len(intent_pool)):
        pid, title, payload, count = intent_pool[i]
        desired = weak_context(title, expanded=True)
        for tag in GRAPH_TAGS:
            if tag in desired and len(intent_sample[tag]) < args.intent_queries:
                intent_sample[tag].append((pid, payload, count))

    for col, tag in enumerate(GRAPH_TAGS):
        for row in intent_sample[tag]:
            result, inferred = top20(*row)
            bucket = intent[tag]
            bucket['queries'] += 1
            bucket['recommendation_slots'] += len(result)
            bucket['original_direct'] += int(original_intent[result, col].sum())
            expanded = int(expanded_intent[result, col].sum())
            bucket['expanded_direct'] += expanded
            bucket['expanded_plus_graph_at_0.06'] += expanded + int(inferred[:, col].sum())
    methods = ('original_direct', 'expanded_direct', 'expanded_plus_graph_at_0.06')
    report['validation_top20'] = {'queries': matched_queries, **counts, 'coverage': {
        name: counts[name] / counts['recommendation_slots'] if counts['recommendation_slots'] else None for name in methods}}
    report['validation_top20_matching_query_title_tag'] = {tag: dict(intent[tag]) for tag in GRAPH_TAGS}
    report['blind_review_rows'] = make_review(data, args.output, anchors, sampled, graph_score,
                                              args.review_per_tag_arm, rng)
    write_json(args.output / 'graph_report.json', report)
    return report


def precision(counts):
    yes, no = counts['yes'], counts['no']
    total = yes + no
    if not total:
        return {'yes': yes, 'no': no, 'unsure': counts['unsure'], 'acceptance': None, 'wilson_95_interval': None}
    value, z = yes / total, 1.96
    width = z * math.sqrt(value * (1-value) / total + z*z / (4*total*total))
    center = value + z*z / (2*total)
    bounds = [(center - width) / (1 + z*z/total), (center + width) / (1 + z*z/total)]
    return {'yes': yes, 'no': no, 'unsure': counts['unsure'], 'acceptance': value,
            'wilson_95_interval': [max(0., bounds[0]), min(1., bounds[1])]}


def score_review(output, review):
    with (output / 'song_review_key.csv').open(encoding='utf-8-sig', newline='') as handle:
        key = {row['review_id']: row for row in csv.DictReader(handle)}
    batches, tags, cutoffs = defaultdict(Counter), defaultdict(Counter), defaultdict(Counter)
    seen = set()
    with review.open(encoding='utf-8-sig', newline='') as handle:
        for row in csv.DictReader(handle):
            identifier = row['review_id']
            judgment = row['judgment'].strip().casefold()
            if not judgment:
                continue
            if identifier in seen or identifier not in key or judgment not in ('yes', 'no', 'unsure'):
                raise ValueError(f'Invalid review entry {identifier}. Use yes, no or unsure once per ID.')
            source = key[identifier]
            if (row['spotify_id'], row['tag']) != (source['spotify_id'], source['tag']):
                raise ValueError(f'Track or tag changed for review entry {identifier}.')
            seen.add(identifier)
            arm, tag = source['arm'], source['tag']
            batches[arm][judgment] += 1
            tags[f'{arm}/{tag}'][judgment] += 1
            if source['graph_score']:
                for threshold in THRESHOLDS:
                    if float(source['graph_score']) >= threshold:
                        cutoffs[str(threshold)][judgment] += 1
    report = {'reviewed_rows': len(seen), 'by_method': {arm: precision(c) for arm, c in batches.items()},
              'by_method_and_tag': {arm: precision(c) for arm, c in tags.items()},
              'graph_review_by_threshold': {str(t): precision(cutoffs[str(t)]) for t in THRESHOLDS}}
    write_json(output / 'review_metrics.json', report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/tag-coverage-study'))
    parser.add_argument('--allow-partial-source', action='store_true')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('titles')
    graph = commands.add_parser('graph')
    graph.add_argument('--model', type=Path, default=Path('runs/million/model'))
    graph.add_argument('--baseline', type=Path, default=Path('runs/million/profiles-v2'))
    graph.add_argument('--expanded', type=Path, default=Path('runs/million/profiles-v2-expanded'))
    graph.add_argument('--per-stratum', type=int, default=400)
    graph.add_argument('--queries', type=int, default=100)
    graph.add_argument('--intent-queries', type=int, default=25)
    graph.add_argument('--review-per-tag-arm', type=int, default=15)
    reviewed = commands.add_parser('review-metrics')
    reviewed.add_argument('csv', type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    try:
        if args.command == 'review-metrics':
            result = score_review(args.output, args.csv)
        else:
            with open_dataset(args.source, args.split, args.allow_partial_source) as data:
                if args.command == 'titles':
                    result = audit_title_rules(data, args.output)
                    write_json(args.output / 'title_cue_report.json', result)
                else:
                    if min(args.per_stratum, args.queries, args.intent_queries, args.review_per_tag_arm) < 1:
                        raise ValueError('Sample sizes must be positive.')
                    if (args.output / 'blind_song_review.csv').exists():
                        raise ValueError('The review sheet already exists. Use a new --output folder for another pilot.')
                    result = run_graph(data, args)
        print(json.dumps(result, indent=2, ensure_ascii=False))
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
