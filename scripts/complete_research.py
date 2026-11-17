"""Evaluate the frozen Studio pipeline and export real metrics for every K.

Run with: PYTHONPATH=src python -m scripts.complete_research
This loads existing artifacts. It never trains, tunes or changes deployment.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import heapq
from importlib import metadata
import json
from pathlib import Path
import platform
import sys

import numpy as np

from playlist_model.__main__ import paired_interval
from playlist_model.million import open_dataset, rank_candidates, read_json, write_json
from scripts.seed_study import FIELDS, artist_index, fresh_sample, previous_groups
from scripts.serve_million_demo import Demo

VERSION = 'frozen-studio-evaluation-v1'
METHODS = ('popularity', 'cf', 'standard_title', 'unified_no_title', 'unified', 'unified_seed_bpm')
CUTOFFS = tuple(range(1, 21))


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def metrics_at_k(ranking, references, k):
    if not references or k < 1:
        raise ValueError('A nonempty reference set and positive K are required')
    ranks = list(ranking)[:k]
    if len(ranks) != len(set(ranks)):
        raise ValueError('A ranking must contain distinct tracks')
    positions = [i for i, item in enumerate(ranks) if item in references]
    dcg = sum(1 / np.log2(i + 2) for i in positions)
    ideal = sum(1 / np.log2(i + 2) for i in range(min(k, len(references))))
    return [len(positions) / len(references), dcg / ideal, len(positions) / k, float(bool(positions))]


def sample_rows(data, excluded, seeds, limit):
    def candidates():
        seen = set(excluded)
        for row in data.rows('test', FIELDS):
            if row[3] <= seeds or row[4] in seen:
                continue
            seen.add(row[4])
            key = hashlib.sha256(f'{VERSION}|sample|{row[0]}'.encode()).digest()
            yield key, row
    return [row for _, row in heapq.nsmallest(limit, candidates(), key=lambda item: item[0])]


def exclusions(data, root):
    # The earlier 100k work is development evidence. Exclude whole groups, not
    # merely matching playlist IDs, from this final cohort.
    groups = {row[0] for row in data.connection.execute(
        'SELECT DISTINCT group_hash FROM splits.assigned_splits WHERE pid < 100000')}
    counts = {'historical_first_100k_groups': len(groups)}
    for model in (root / 'model', root / 'model-full-titles'):
        if not (model / 'test_metrics.json').is_file():
            continue
        frozen = read_json(model / 'frozen_settings.json')
        report = read_json(model / 'test_metrics.json')
        prior = previous_groups(data, 'test', report['sample'], frozen)
        groups.update(prior)
        counts[model.name + '_benchmark_groups'] = len(prior)
        # Its deterministic earlier seed-study sample can be recreated exactly.
        seed_rows = fresh_sample(data, 'test', prior, 1500)
        groups.update(row[-1] for row in seed_rows)
        counts[model.name + '_seed_study_groups'] = len(seed_rows)
        # Conservatively reserve both historical unified evaluation cohorts,
        # even if their output JSON is no longer available locally.
        def old_rows(salt, extra, limit):
            seen = set(prior) | set(extra)
            def rows():
                for row in data.rows('test', FIELDS):
                    if row[3] != 20 or row[4] in seen:
                        continue
                    seen.add(row[4])
                    yield row
            return heapq.nsmallest(limit, rows(), key=lambda row:
                hashlib.blake2b(f'{salt}:{row[0]}'.encode(), digest_size=8).digest())
        first = old_rows('unified-eval-v1', (), 300)
        second = old_rows('boost-test-v1', (row[-1] for row in first), 150)
        groups.update(row[-1] for row in first + second)
    counts['total_excluded_groups'] = len(groups)
    return groups, counts


def summarize(records, selected, catalogue_size):
    subset = [row for row in records if selected(row)]
    if not subset:
        return {'queries': 0, 'cutoffs': {}}
    output = {'queries': len(subset), 'cutoffs': {}}
    names = ('recall', 'ndcg', 'precision', 'hit_rate')
    for k in CUTOFFS:
        output['cutoffs'][str(k)] = {
            method: dict(zip(names, map(float, np.mean([row['scores'][method][str(k)]
                                                       for row in subset], axis=0))))
            for method in METHODS}
        for method in METHODS:
            artists = [row.get('artists', {}).get(method, [])[:k] for row in subset]
            diversity = []
            for values in artists:
                known = [value for value in values if value >= 0]
                diversity.append(len(set(known)) / len(known) if known else 0.)
            distinct = {track for row in subset for track in row.get('rankings', {}).get(method, [])[:k]}
            output['cutoffs'][str(k)][method].update(
                artist_diversity=float(np.mean(diversity)),
                catalogue_coverage=len(distinct) / catalogue_size if catalogue_size else 0.)
    return output


def public_report(records, freeze):
    size = freeze.get('training_catalogue_tracks', 0)
    cohorts = {
        'all_queries': summarize(records, lambda row: True, size),
        'title_tagged': summarize(records, lambda row: bool(row['context']), size),
        'all_seeds_known': summarize(records, lambda row: row['known_seeds'] == freeze['seeds'], size),
        'some_seeds_unseen': summarize(records, lambda row: row['known_seeds'] < freeze['seeds'], size),
        'seed_tempo_available': summarize(records, lambda row: row.get('tempo_eligible', False), size),
    }
    groups = [row['group'] for row in records]
    delta = np.array([row['scores']['unified']['20'][1] - row['scores']['cf']['20'][1] for row in records])
    cases = {}
    indexes = {'largest_gain': int(np.argmax(delta)), 'largest_loss': int(np.argmin(delta)),
               'first_zero_hit': next((i for i, row in enumerate(records)
                                       if row['scores']['unified']['20'][3] == 0), None)}
    for name, index in indexes.items():
        if index is None:
            cases[name] = None
            continue
        row = records[index]
        cases[name] = {key: row[key] for key in ('known_seeds', 'reference_count', 'unseen_references',
            'candidate_recall', 'result_count', 'context', 'note', 'hit_ranks')}
        cases[name]['ndcg_delta'] = float(delta[index])
    return {'schema_version': 1, 'kind': 'frozen_studio_heldout_evaluation',
            'measured_utc': datetime.now(timezone.utc).isoformat(), 'freeze': freeze,
            'methods': list(METHODS), 'cutoffs': list(CUTOFFS), 'cohorts': cohorts,
            'paired_unified_minus_cf_ndcg_at_20_95_ci': paired_interval(delta, groups, np.ones(len(records), bool)),
            'unified_failures': {'zero_hit_queries': sum(row['scores']['unified']['20'][3] == 0 for row in records),
                'short_outputs': sum(row['result_count'] < 20 for row in records),
                'mean_candidate_recall': float(np.mean([row['candidate_recall'] for row in records])),
                'unseen_reference_occurrences': sum(row['unseen_references'] for row in records)},
            'cases': cases,
            'scope': 'Same sampled queries and references for all methods and cutoffs. The BPM ablation uses a prespecified +/-10 BPM window around the median of at least two known seed tempos; it falls back to ordinary Studio when tempo is unavailable. No hidden reference determines the tempo target. Explicit user tags are absent; their contract is checked separately. Unknown unrecorded development cohorts cannot be certified.'}


def choose_path(root, choices):
    for name in choices:
        path = root / name
        if path.is_dir():
            return path
    raise ValueError('Existing trained artifacts not found: ' + ' or '.join(str(root / x) for x in choices))


def run(args):
    root = args.data
    source, split = root / 'mpd.sqlite3', root / 'split.sqlite3'
    model = args.model or choose_path(root, ('model-full-titles', 'model'))
    profiles = args.profiles or choose_path(root, ('profiles-v2-expanded-full-titles', 'profiles-v2-expanded'))
    if (args.output / 'studio_evaluation.json').exists():
        raise ValueError('Final scores already exist. Use --export-only; do not retune this holdout.')
    bulk = root / 'catalogue-enrichment/catalogue_enrichment.sqlite3'
    demo = Demo(source, split, model, False, profiles=profiles,
                catalogue_profiles=bulk if bulk.is_file() else None)
    if demo.profiles is None:
        raise ValueError('The unified Studio profiles are required')
    artifact_files = [model / 'frozen_settings.json', *sorted((model / 'index').glob('*.npy')),
                      *sorted((model / 'tags').glob('*')), *sorted((profiles / 'tags').glob('*'))]
    settings = profiles / 'ranking_settings.json'
    if settings.is_file():
        artifact_files.append(settings)
    fingerprints = {str(path.relative_to(root)): digest(path) for path in artifact_files if path.is_file()}
    with open_dataset(source, split) as data:
        excluded, excluded_counts = exclusions(data, root)
        rows = sample_rows(data, excluded, args.seeds, args.queries)
        if not rows:
            raise ValueError('No eligible unused test groups remain')
        freeze = {'protocol': VERSION, 'model_id': digest(model / 'frozen_settings.json'),
                  'artifacts_sha256': fingerprints, 'split': data.identity,
                  'runtime': {'python': platform.python_version(),
                              **{name: metadata.version(name) for name in ('numpy', 'scipy', 'scikit-learn', 'joblib')}},
                  'runtime_source_sha256': {name: digest(Path(sys.modules[name].__file__)) for name in
                      ('playlist_model.million', 'playlist_model.profile_ranker', 'scripts.serve_million_demo')},
                  'seeds': args.seeds, 'queries': len(rows), 'requested_queries': args.queries,
                  'context_weight': demo.profiles.context_weight,
                  'training_catalogue_tracks': len(demo.ranker.popular),
                  'tempo_ablation': 'At least two known seed tempos; median +/-10 BPM, clipped to 30..300. No test tuning.',
                  'query_sha256': hashlib.sha256(','.join(str(r[0]) for r in rows).encode()).hexdigest(),
                  'selection': 'Frozen deployed settings. No tuning or model selection in this command.',
                  'exclusions': excluded_counts, 'manual_filters': 'none', 'cutoffs': list(CUTOFFS)}
        if args.expected_model_id and freeze['model_id'] != args.expected_model_id:
            raise ValueError('The selected local model does not match the deployed model ID')
        args.output.mkdir(parents=True, exist_ok=True)
        freeze_path = args.output / 'evaluation_freeze.json'
        if freeze_path.exists() and read_json(freeze_path) != freeze:
            raise ValueError('Existing evaluation freeze differs. Keep that holdout unchanged.')
        write_json(freeze_path, freeze)  # Written before opening any test references.
        records = []
        artists = artist_index(data)
        with demo.catalogue(with_bulk=True) as db:
            for i, (pid, title, payload, count, group) in enumerate(rows, 1):
                tracks = sorted(map(int, data.recordings(payload, count)), key=lambda track:
                    hashlib.sha256(f'{VERSION}|tracks|{pid}|{track}'.encode()).digest())
                seeds = np.asarray(tracks[:args.seeds], dtype=np.int32)
                targets = set(tracks[args.seeds:])
                items, scores, fallback = demo.ranker.candidates(seeds)
                labels = np.flatnonzero(demo.tags.tagger.predict([title])[0])
                unified, context, _, note = demo.profiles.recommend(demo.ranker, seeds, title, {}, db)
                without_title, *_ = demo.profiles.recommend(demo.ranker, seeds, '', {}, db)
                seed_metadata = demo.profiles.metadata(db)
                demo.profiles.add_bulk_metadata(db, seeds, seed_metadata)
                tempos = [seed_metadata.get(int(seed), {}).get('bpm') for seed in seeds]
                tempos = [float(value) for value in tempos if value is not None and 30 <= float(value) <= 300]
                tempo_eligible = len(tempos) >= 2
                if tempo_eligible:
                    target = float(np.median(tempos))
                    tempo_filters = {'min_bpm': max(30, int(np.floor(target - 10))),
                                     'max_bpm': min(300, int(np.ceil(target + 10)))}
                    tempo_ranked, *_ = demo.profiles.recommend(demo.ranker, seeds, title, tempo_filters, db)
                else:
                    tempo_ranked = unified
                rankings = {
                    'popularity': demo.ranker.popularity(seeds, 20),
                    'cf': rank_candidates(items, scores, fallback, np.zeros(len(items)), 0),
                    'standard_title': rank_candidates(items, scores, fallback, demo.tags.bonus(items, labels), demo.weight),
                    'unified_no_title': without_title, 'unified': unified, 'unified_seed_bpm': tempo_ranked}
                records.append({'pid': pid, 'group': group.hex(), 'reference_count': len(targets),
                    'known_seeds': int(np.count_nonzero(demo.ranker.counts[seeds])),
                    'unseen_references': int(sum(demo.ranker.counts[t] == 0 for t in targets)),
                    'candidate_recall': len(targets.intersection(items)) / len(targets),
                    'result_count': len(unified), 'context': context, 'note': note,
                    'tempo_eligible': tempo_eligible,
                    'rankings': {name: list(map(int, ranking)) for name, ranking in rankings.items()},
                    'artists': {name: list(map(int, artists[ranking])) for name, ranking in rankings.items()},
                    'hit_ranks': {name: [n + 1 for n, t in enumerate(ranking) if t in targets]
                                  for name, ranking in rankings.items()},
                    'scores': {name: {str(k): metrics_at_k(ranking, targets, k) for k in CUTOFFS}
                               for name, ranking in rankings.items()}})
                if i % 50 == 0 or i == len(rows):
                    print(f'Scored {i}/{len(rows)} frozen Studio queries', flush=True)
    write_json(args.output / 'private_query_scores.json', records)
    return public_report(records, freeze), source, split, model


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, default=Path('runs/million'))
    cli.add_argument('--model', type=Path)
    cli.add_argument('--profiles', type=Path)
    cli.add_argument('--queries', type=int, default=1000)
    cli.add_argument('--seeds', type=int, default=5)
    cli.add_argument('--expected-model-id')
    cli.add_argument('--output', type=Path, default=Path('runs/million/research-completion'))
    cli.add_argument('--public-dir', type=Path, default=Path('docs/data/research'))
    cli.add_argument('--export-only', action='store_true')
    args = cli.parse_args()
    if not 1 <= args.seeds <= 20 or args.queries < 1:
        cli.error('Use 1 to 20 seeds and a positive query count')
    try:
        if args.export_only:
            report = read_json(args.output / 'studio_evaluation.json')
        else:
            report, source, split, model = run(args)
            write_json(args.output / 'studio_evaluation.json', report)
            from scripts.research_eda import full_eda
            write_json(args.output / 'eda_full.json', full_eda(source, split, model))
        args.public_dir.mkdir(parents=True, exist_ok=True)
        write_json(args.public_dir / 'studio_evaluation.json', report)
        eda = args.output / 'eda_full.json'
        if eda.exists():
            write_json(args.public_dir / 'eda_full.json', read_json(eda))
        from scripts.export_research_additions import export as export_additions
        from scripts.export_research_bundle import export as export_bundle
        docs = args.public_dir.parent.parent
        export_additions(args.public_dir, docs / 'research_extra_data.js')
        export_bundle(docs, args.public_dir)
        print(f'Published {report["cohorts"]["all_queries"]["queries"]} actual held-out Studio queries.')
    except (ValueError, OSError, KeyError) as error:
        cli.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
