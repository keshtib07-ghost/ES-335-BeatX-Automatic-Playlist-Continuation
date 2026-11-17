"""Measure the frozen final pipeline at six nested seed counts.

Uses the deployed inference code when launched by studio_seed_study_azure.sh.
The same playlists and hidden songs are used at every seed count. No fitting
or ranking-parameter selection takes place in this command.
"""

import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import heapq
import html
from pathlib import Path
import platform
import re
import sys

import numpy as np

from playlist_model.__main__ import paired_interval
from playlist_model.million import open_dataset, rank_candidates, read_json, write_json
from scripts.complete_research import (CUTOFFS, METHODS, choose_path, digest,
                                      exclusions, metrics_at_k, sample_rows, summarize)
from scripts.seed_study import BUDGETS, FIELDS, artist_index, fresh_sample, previous_groups, sample_hash
from scripts.serve_million_demo import Demo

VERSION = 'frozen-final-pipeline-seed-study-v1'


def atomic_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    write_json(temporary, value)
    temporary.replace(path)


def refresh_pages(report, docs):
    """Publish the measured seed answer in static HTML as well as the chart."""
    chosen = report['chosen_seed_budget']
    answer = (f'Validation selected {chosen} seeds using the fixed 95% rule. '
              'This is the smallest tested count near the best validation NDCG@20; it is not a universal minimum.')
    rows = []
    for n in report['seed_budgets']:
        budget = report['test']['budgets'][str(n)]
        scores = budget['cutoffs']['20']
        low, high = budget['paired_final_minus_cf_ndcg_at_20_95_ci']
        rows.append(f'<tr><th scope="row">{n}</th><td>{scores["unified"]["ndcg"]:.5f}</td>'
                    f'<td>{scores["unified"]["recall"]:.5f}</td><td>{scores["cf"]["ndcg"]:.5f}</td>'
                    f'<td>[{low:+.5f}, {high:+.5f}]</td></tr>')
    table = ('<div id="final-seed-pending"><h3>Measured final-pipeline seed curves</h3>'
             '<div class="table-wrap"><table><caption>Same hidden songs at every seed count; test scores at K = 20.</caption>'
             '<thead><tr><th>Seeds</th><th>Final NDCG</th><th>Final Recall</th><th>CF NDCG</th><th>Final minus CF: 95% interval</th></tr></thead>'
             '<tbody>' + ''.join(rows) + '</tbody></table></div><p>' + answer + '</p></div>')
    for name in ('research.html', 'research-deep-dive.html'):
        path = docs / name
        text = path.read_text()
        for identity in ('final-seed-answer', 'summary-final-seed-answer'):
            text = re.sub(r'(<p id="' + identity + r'">).*?(</p>)',
                          lambda m: m[1] + html.escape(answer) + m[2], text, flags=re.S)
        text = text.replace('id="final-seed-coverage">Awaiting the new run',
                            'id="final-seed-coverage">Measured at six seed counts')
        if name == 'research-deep-dive.html':
            text = re.sub(r'(<p id="final-seed-status">).*?(</p>)', lambda m:
                m[1] + f'{report["test"]["queries"]:,} test playlists; six seed counts; frozen final pipeline.' + m[2], text, flags=re.S)
            pattern = r'<!-- final-seed-static:start -->.*?<!-- final-seed-static:end -->'
            if re.search(pattern, text, flags=re.S):
                text = re.sub(pattern, lambda _: '<!-- final-seed-static:start -->' + table + '<!-- final-seed-static:end -->', text, flags=re.S)
                text = text.replace('id="final-seed-downloads" hidden', 'id="final-seed-downloads"')
        path.write_text(text)


def fixed_query(pid, items):
    tracks = sorted(map(int, items), key=lambda track: hashlib.sha256(
        f'{VERSION}|tracks|{pid}|{track}'.encode()).digest())
    return np.asarray(tracks[:max(BUDGETS)], dtype=np.int32), set(tracks[max(BUDGETS):])


def legacy_exclusions(data, root, partition):
    groups = {row[0] for row in data.connection.execute(
        'SELECT DISTINCT group_hash FROM splits.assigned_splits WHERE pid < 100000')}
    for name in ('model', 'model-full-titles'):
        model = root / name
        if not (model / 'test_metrics.json').is_file():
            continue
        frozen = read_json(model / 'frozen_settings.json')
        sample = (read_json(model / 'test_metrics.json')['sample'] if partition == 'test'
                  else frozen['validation_query_sample'])
        prior = previous_groups(data, partition, sample, frozen)
        groups.update(prior)
        groups.update(row[-1] for row in fresh_sample(data, partition, prior, 1500))
    return groups


def prior_final_groups(data, root, report, base_excluded):
    """Recreate a previous private cohort, verifying its published fingerprint."""
    freeze = report['freeze']
    if freeze['split'] != data.identity:
        raise ValueError('The previous final evaluation belongs to another split')
    # The completed report predates the additional exact-20-track exclusions.
    # Support either recorded protocol, but accept a reconstruction only when
    # every selected playlist agrees with the saved query fingerprint.
    alternatives = [base_excluded, exclusions(data, root)[0]]
    for excluded in alternatives:
        rows = sample_rows(data, excluded, freeze['seeds'], freeze['queries'])
        if sample_hash(row[0] for row in rows) == freeze['query_sha256']:
            return {row[-1] for row in rows}
    raise ValueError('Cannot verify the earlier final-evaluation cohort. Keep its private query manifest; do not silently reuse that holdout.')


def study_sample(data, partition, excluded, limit):
    def candidates():
        seen = set(excluded)
        for row in data.rows(partition, FIELDS):
            if row[3] <= max(BUDGETS) or row[-1] in seen:
                continue
            seen.add(row[-1])
            key = hashlib.sha256(f'{VERSION}|{partition}|{row[0]}'.encode()).digest()
            yield key, row
    return [row for _, row in heapq.nsmallest(limit, candidates(), key=lambda value: value[0])]


def query_rankings(demo, seeds, title, db):
    items, scores, fallback = demo.ranker.candidates(seeds)
    labels = np.flatnonzero(demo.tags.tagger.predict([title])[0])
    final, context, _, note = demo.profiles.recommend(demo.ranker, seeds, title, {}, db)
    without_title, *_ = demo.profiles.recommend(demo.ranker, seeds, '', {}, db)
    seed_metadata = demo.profiles.metadata(db)
    demo.profiles.add_bulk_metadata(db, seeds, seed_metadata)
    tempos = [seed_metadata.get(int(seed), {}).get('bpm') for seed in seeds]
    tempos = [float(value) for value in tempos if value is not None and 30 <= float(value) <= 300]
    eligible = len(tempos) >= 2
    if eligible:
        target = float(np.median(tempos))
        filters = {'min_bpm': max(30, int(np.floor(target - 10))),
                   'max_bpm': min(300, int(np.ceil(target + 10)))}
        tempo, *_ = demo.profiles.recommend(demo.ranker, seeds, title, filters, db)
    else:
        tempo = final
    return {
        'popularity': demo.ranker.popularity(seeds, 20),
        'cf': rank_candidates(items, scores, fallback, np.zeros(len(items)), 0),
        'standard_title': rank_candidates(items, scores, fallback, demo.tags.bonus(items, labels), demo.weight),
        'unified_no_title': without_title, 'unified': final, 'unified_seed_bpm': tempo,
    }, context, note, items, eligible


def select_budget(validation):
    curve = [validation['budgets'][str(n)]['cutoffs']['20']['unified']['ndcg'] for n in BUDGETS]
    return next(n for n, score in zip(BUDGETS, curve) if score >= .95 * max(curve))


def measure(data, demo, rows, artists, partition, output):
    section = {'queries': len(rows), 'budgets': {}}
    previous, previous_n = None, None
    groups = [row[-1].hex() for row in rows]
    size = len(demo.ranker.popular)
    for n in BUDGETS:
        checkpoint = output / f'private_{partition}_{n}_scores.json'
        if checkpoint.exists():
            records = read_json(checkpoint)
            if [r['pid'] for r in records] != [row[0] for row in rows]:
                raise ValueError('A checkpoint contains a different query cohort')
            print(f'Resuming {partition}: {n} seeds from its completed checkpoint', flush=True)
        else:
            records = []
            with demo.catalogue(with_bulk=True) as db:
                for i, (pid, title, payload, count, group) in enumerate(rows, 1):
                    reserve, targets = fixed_query(pid, data.recordings(payload, count))
                    seeds = reserve[:n]
                    rankings, context, note, items, tempo = query_rankings(demo, seeds, title, db)
                    records.append({'pid': pid, 'group': group.hex(), 'known_seeds': int(np.count_nonzero(demo.ranker.counts[seeds])),
                        'context': context, 'note': note, 'tempo_eligible': tempo,
                        'candidate_recall': len(targets.intersection(items)) / len(targets),
                        'reference_count': len(targets), 'result_count': len(rankings['unified']),
                        'rankings': {name: list(map(int, ranking)) for name, ranking in rankings.items()},
                        'artists': {name: list(map(int, artists[ranking])) for name, ranking in rankings.items()},
                        'scores': {name: {str(k): metrics_at_k(ranking, targets, k) for k in CUTOFFS}
                                   for name, ranking in rankings.items()}})
                    if i % 50 == 0 or i == len(rows):
                        print(f'{partition}: {n} seeds, {i}/{len(rows)} playlists', flush=True)
            atomic_json(checkpoint, records)
        aggregate = summarize(records, lambda row: True, size)
        values = np.array([r['scores']['unified']['20'][1] for r in records])
        delta = values - np.array([r['scores']['cf']['20'][1] for r in records])
        aggregate.update(all_seeds_known=sum(r['known_seeds'] == n for r in records),
            tempo_eligible=sum(r['tempo_eligible'] for r in records),
            zero_hit_queries=sum(r['scores']['unified']['20'][3] == 0 for r in records),
            short_outputs=sum(r['result_count'] < 20 for r in records),
            mean_candidate_recall=float(np.mean([r['candidate_recall'] for r in records])),
            paired_final_minus_cf_ndcg_at_20_95_ci=paired_interval(delta, groups, np.ones(len(rows), bool)))
        if previous is not None:
            change = values - previous
            aggregate['marginal_seed_gain'] = {'from_seeds': previous_n,
                'ndcg_delta': float(change.mean()), 'ndcg_per_added_seed': float(change.mean() / (n - previous_n)),
                'paired_ndcg_95_ci': paired_interval(change, groups, np.ones(len(rows), bool))}
        section['budgets'][str(n)] = aggregate
        previous, previous_n = values, n
    return section


def run(args):
    root = args.data
    model = args.model or choose_path(root, ('model-full-titles', 'model'))
    profiles = args.profiles or choose_path(root, ('profiles-v2-expanded-full-titles', 'profiles-v2-expanded'))
    if (args.output / 'studio_seed_study.json').exists():
        raise ValueError('Completed scores already exist. Use --export-only to publish them again.')
    source, split = root / 'mpd.sqlite3', root / 'split.sqlite3'
    bulk = root / 'catalogue-enrichment/catalogue_enrichment.sqlite3'
    demo = Demo(source, split, model, False, profiles=profiles, catalogue_profiles=bulk if bulk.is_file() else None)
    if demo.profiles is None:
        raise ValueError('Final pipeline profiles are required')
    files = [model / 'frozen_settings.json', *sorted((model / 'index').glob('*.npy')),
             *sorted((model / 'tags').glob('*')), *sorted((profiles / 'tags').glob('*'))]
    files += [p for p in (source, split, profiles / 'ranking_settings.json', profiles / 'enrichment.sqlite3', bulk) if p.is_file()]
    for path in files:
        wal = Path(str(path) + '-wal')
        if wal.exists() and wal.stat().st_size:
            raise ValueError(f'Active SQLite WAL for {path.name}; checkpoint that job before evaluation.')
    hashes = {str(p.relative_to(root)): digest(p) for p in files if p.is_file()}
    with open_dataset(source, split) as data:
        excluded = {part: legacy_exclusions(data, root, part) for part in ('validation', 'test')}
        previous = read_json(args.prior_report)
        excluded['test'].update(prior_final_groups(data, root, previous, excluded['test']))
        # Reserve the known earlier exact-20-track unified cohorts as well.
        excluded['test'].update(exclusions(data, root)[0])
        samples = {part: study_sample(data, part, excluded[part], args.queries) for part in excluded}
        if any(len(rows) < args.queries for rows in samples.values()):
            raise ValueError('Not enough fresh groups for the requested sample size')
        freeze = {'protocol': VERSION, 'model_id': digest(model / 'frozen_settings.json'),
            'split': data.identity, 'artifacts_sha256': hashes, 'context_weight': demo.profiles.context_weight,
            'runtime': {'python': platform.python_version(), **{name: metadata.version(name) for name in ('numpy', 'scipy', 'scikit-learn', 'joblib')}},
            'runtime_source_sha256': {name: digest(Path(sys.modules[name].__file__)) for name in
                ('playlist_model.million', 'playlist_model.profile_ranker', 'playlist_model.profile_tags',
                 'playlist_model.tagger', 'playlist_model.ranker', 'scripts.serve_million_demo',
                 'scripts.complete_research', 'scripts.seed_study', __name__)},
            'samples': {part: {'queries': len(rows), 'query_sha256': sample_hash(row[0] for row in rows),
                'excluded_groups': len(excluded[part])} for part, rows in samples.items()},
            'prior_evaluation_sha256': digest(args.prior_report), 'training_catalogue_tracks': len(demo.ranker.popular),
            'seed_budgets': list(BUDGETS), 'cutoffs': list(CUTOFFS), 'methods': list(METHODS),
            'selection': 'Frozen ranking settings. Seed budget selected only on validation NDCG@20.',
            'manual_filters': 'none', 'tempo_ablation': 'At least two known seed tempos; median +/-10 BPM. Otherwise use the ordinary final pipeline.'}
        if args.expected_model_id and freeze['model_id'] != args.expected_model_id:
            raise ValueError('The local model ID differs from the active deployed model')
        args.output.mkdir(parents=True, exist_ok=True)
        freeze_path = args.output / 'seed_study_freeze.json'
        if freeze_path.exists() and read_json(freeze_path) != freeze:
            raise ValueError('Frozen inputs or the protocol changed. Keep the existing cohort unchanged.')
        atomic_json(freeze_path, freeze)
        artists = artist_index(data)
        validation = measure(data, demo, samples['validation'], artists, 'validation', args.output)
        chosen = select_budget(validation)
        selection = {'chosen_seed_budget': chosen, 'validation': validation,
                     'rule': 'Smallest tested seed count reaching 95% of the best validation final-pipeline NDCG@20.'}
        selection_path = args.output / 'seed_selection.json'
        if selection_path.exists() and read_json(selection_path) != selection:
            raise ValueError('The recorded validation decision changed')
        atomic_json(selection_path, selection)  # Written before scoring any test ranking.
        test = measure(data, demo, samples['test'], artists, 'test', args.output)
    if any(digest(root / name) != expected for name, expected in hashes.items()):
        raise ValueError('An input changed during evaluation; no public scores were published.')
    return {'schema_version': 1, 'kind': 'frozen_final_pipeline_seed_study',
        'measured_utc': datetime.now(timezone.utc).isoformat(), 'freeze': freeze,
        'seed_budgets': list(BUDGETS), 'cutoffs': list(CUTOFFS), 'methods': list(METHODS),
        'chosen_seed_budget': chosen, 'seed_rule': selection['rule'],
        'reference_protocol': 'Same playlist groups and hidden songs at every seed count. Twenty deterministic tracks form a nested seed pool. Unrevealed pool tracks receive no recovery credit.',
        'validation': validation, 'test': test,
        'scope': 'Final pipeline relevance order before playback reordering. Settings are frozen; manual tags and era filters are not evaluated. Different seed counts share references; this longer-playlist cohort is separate from the five-seed evaluation.'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, default=Path('runs/million'))
    cli.add_argument('--model', type=Path)
    cli.add_argument('--profiles', type=Path)
    cli.add_argument('--queries', type=int, default=1000)
    cli.add_argument('--expected-model-id')
    cli.add_argument('--prior-report', type=Path, default=Path('docs/data/research/studio_evaluation.json'))
    cli.add_argument('--output', type=Path, default=Path('runs/million/final-seed-study'))
    cli.add_argument('--public-dir', type=Path, default=Path('docs/data/research'))
    cli.add_argument('--export-only', action='store_true')
    args = cli.parse_args()
    if args.queries < 1:
        cli.error('Query count must be positive')
    try:
        path = args.output / 'studio_seed_study.json'
        report = read_json(path) if args.export_only else run(args)
        if not args.export_only:
            atomic_json(path, report)
        args.public_dir.mkdir(parents=True, exist_ok=True)
        atomic_json(args.public_dir / 'studio_seed_study.json', report)
        from scripts.export_research_additions import export
        from scripts.export_research_bundle import export as export_bundle
        docs = args.public_dir.parent.parent
        refresh_pages(report, docs)
        export(args.public_dir, docs / 'research_extra_data.js')
        export_bundle(docs, args.public_dir)
        print(f'Published final-pipeline curves at all six seed counts. Validation selected {report["chosen_seed_budget"]} seeds.')
    except (OSError, ValueError, KeyError) as error:
        cli.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
