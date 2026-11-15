"""Run the prespecified seed-count and title-context ablation on fresh queries."""

import argparse
import hashlib
import heapq
import json
import sqlite3
from collections import defaultdict
from pathlib import Path

import numpy as np

from playlist_model.__main__ import paired_interval, scores_for, summary
from playlist_model.million import open_dataset, rank_candidates, read_json, write_json
from playlist_model.million_eval import load_training
from playlist_model.tagger import TAG_COLUMN, weak_tags


BUDGETS = (1, 2, 3, 5, 10, 20)
METHODS = ('popularity', 'cf', 'keyword_title', 'learned_title')
FIELDS = 'p.pid, p.title, p.track_indices, s.recording_count, s.group_hash'
VERSION = 'seed-study-v1'


def sample_hash(pids):
    return hashlib.sha256(','.join(map(str, pids)).encode()).hexdigest()


def previous_groups(data, part, sample, frozen):
    rows = data.sample(part, 'p.pid, s.group_hash', frozen['query_limit_per_partition'],
                       sample['sample_seed'], eligible=True)
    if sample_hash(row[0] for row in rows) != sample['sampled_pid_sha256']:
        raise ValueError(f'The saved {part} sampling fingerprint does not match the split')
    return {row[1] for row in rows}


def fresh_sample(data, part, excluded, limit):
    def candidates():
        for row in data.rows(part, FIELDS):
            pid, _, _, count, group = row
            if count > max(BUDGETS) and group not in excluded:
                key = hashlib.blake2b(f'{VERSION}|sample|{part}|{pid}'.encode(), digest_size=8).digest()
                yield key, row
    return [row for _, row in heapq.nsmallest(limit, candidates(), key=lambda value: value[0])]


def fixed_query(pid, items):
    order = sorted(map(int, items), key=lambda track: hashlib.blake2b(
        f'{VERSION}|tracks|{pid}|{track}'.encode(), digest_size=8).digest())
    reserve = np.array(order[:max(BUDGETS)], dtype=np.int32)
    return reserve, set(order[max(BUDGETS):])


def artist_index(data):
    artists = {}
    result = np.full(data.track_count, -1, dtype=np.int32)
    for index, name in data.connection.execute('SELECT track_index, artist_name FROM catalogue'):
        key = (name or '').strip().casefold()
        if key:
            result[index] = artists.setdefault(key, len(artists))
    return result


def audit_case(pid, n, targets, seeds, candidates, plain, tagged, labels, counts, delta):
    return {'case': hashlib.sha256(f'{VERSION}|case|{pid}'.encode()).hexdigest()[:10],
            'seeds': n, 'known_seeds': int(np.count_nonzero(counts[seeds])),
            'withheld_tracks': len(targets), 'withheld_seen_in_training': sum(bool(counts[i]) for i in targets),
            'withheld_in_cf_candidates': len(targets.intersection(candidates)), 'inferred_tag_count': len(labels),
            'plain_hit_ranks': [i + 1 for i, track in enumerate(plain) if track in targets],
            'tagged_hit_ranks': [i + 1 for i, track in enumerate(tagged) if track in targets], 'ndcg_delta': delta}


def measure(data, ranker, tag_evidence, artists, rows, weight, chosen_budget=None):
    if not rows:
        raise ValueError('No fresh playlists with more than 20 distinct tracks')
    inferred = tag_evidence.tagger.predict([row[1] for row in rows])
    tagged_mask = inferred.any(axis=1)
    group_ids = [row[-1].hex() for row in rows]
    methods_by_budget = {n: defaultdict(list) for n in BUDGETS}
    extra = {n: defaultdict(list) for n in BUDGETS}
    coverage = {n: {key: set() for key in METHODS} for n in BUDGETS}
    cold_by_budget = dict.fromkeys(BUDGETS, 0)
    one_percent = max(1, int(np.ceil(len(ranker.popular) / 100)))
    head = np.zeros(data.track_count, dtype=bool)
    head[ranker.popular[:one_percent]] = True
    worst, best, miss = None, None, None
    for index, (pid, title, payload, count, _) in enumerate(rows):
        reserve, hidden = fixed_query(pid, data.recordings(payload, count))
        learned = np.flatnonzero(inferred[index])
        keyword = np.array(sorted(TAG_COLUMN[tag] for tag in weak_tags(title)), dtype=np.intp)
        for n in BUDGETS:
            seeds = reserve[:n]
            cold_by_budget[n] += int(not ranker.counts[seeds].any())
            items, scores, fallback = ranker.candidates(seeds)
            plain = rank_candidates(items, scores, fallback, np.zeros(len(items)), 0.)
            keyword_ranking = rank_candidates(items, scores, fallback, tag_evidence.bonus(items, keyword), weight)
            learned_ranking = rank_candidates(items, scores, fallback, tag_evidence.bonus(items, learned), weight)
            ranked = (ranker.popularity(seeds, 20), plain, keyword_ranking, learned_ranking)
            for method, result in zip(METHODS, ranked):
                methods_by_budget[n][method].append(scores_for(result, hidden))
                ids = artists[result]
                known = ids[ids >= 0]
                extra[n][method].append((len(np.unique(known)) / len(known) if len(known) else 0.,
                                         float(head[result].mean()) if len(result) else 0.,
                                         int(len(known)), len(result)))
                coverage[n][method].update(map(int, result))
            if n == chosen_budget:
                delta = float(methods_by_budget[n]['learned_title'][-1][1] - methods_by_budget[n]['cf'][-1][1])
                if delta > 1e-12 and (best is None or delta > best['ndcg_delta']):
                    best = audit_case(pid, n, hidden, seeds, items, plain, learned_ranking, learned, ranker.counts, delta)
                if delta < -1e-12 and (worst is None or delta < worst['ndcg_delta']):
                    worst = audit_case(pid, n, hidden, seeds, items, plain, learned_ranking, learned, ranker.counts, delta)
                if miss is None and not hidden.intersection(learned_ranking):
                    miss = audit_case(pid, n, hidden, seeds, items, plain, learned_ranking, learned, ranker.counts, delta)
        if (index + 1) % 100 == 0 or index + 1 == len(rows):
            print(f'Scored {index + 1:,}/{len(rows):,} playlists at all six budgets', flush=True)

    budgets = {}
    all_rows = np.ones(len(rows), bool)
    earlier, earlier_count = None, None
    for n in BUDGETS:
        values = {name: np.asarray(rows_) for name, rows_ in methods_by_budget[n].items()}
        deltas = values['learned_title'][:, 1] - values['cf'][:, 1]
        overall = summary(values, all_rows)
        for method in METHODS:
            artists_share, popular_share, artist_slots, slots = np.asarray(extra[n][method]).T
            overall[method].update(artist_diversity=float(artists_share.mean()),
                                   popular_track_share=float(popular_share.mean()),
                                   known_artist_slot_share=float(artist_slots.sum() / max(slots.sum(), 1)),
                                   unique_recommended_tracks=len(coverage[n][method]),
                                   catalogue_coverage=len(coverage[n][method]) / len(ranker.popular))
        budgets[str(n)] = {'all_queries': overall, 'title_tagged_queries': summary(values, tagged_mask),
                           'all_seeds_unseen': cold_by_budget[n],
                           'tag_effect': {'improved': int(np.count_nonzero(deltas > 1e-12)),
                                          'worsened': int(np.count_nonzero(deltas < -1e-12)),
                                          'unchanged': int(np.count_nonzero(abs(deltas) <= 1e-12)),
                                          'mean_ndcg_delta': float(deltas.mean()),
                                          'paired_ndcg_95_ci_tagged': paired_interval(deltas, group_ids, tagged_mask)}}
        learned_ndcg = values['learned_title'][:, 1]
        if earlier is not None:
            change = learned_ndcg - earlier
            budgets[str(n)]['marginal_seed_gain'] = {'from_seeds': earlier_count,
                'ndcg_delta': float(change.mean()), 'ndcg_per_added_seed': float(change.mean() / (n - earlier_count)),
                'paired_ndcg_95_ci': paired_interval(change, group_ids, all_rows)}
        earlier, earlier_count = learned_ndcg, n
    return {'queries': len(rows), 'title_tagged_queries': int(tagged_mask.sum()),
            'sampled_pid_sha256': sample_hash(row[0] for row in rows), 'budgets': budgets,
            'cases': {'largest_gain': best, 'largest_loss': worst, 'first_zero_hit': miss}}


def run(args):
    base, target = args.model, args.output
    frozen = read_json(base / 'frozen_settings.json')
    old_test = read_json(base / 'test_metrics.json')
    if old_test['freeze_sha256'] != hashlib.sha256((base / 'frozen_settings.json').read_bytes()).hexdigest():
        raise ValueError('Previous test and its frozen settings do not match')
    target.mkdir(parents=True, exist_ok=True)
    report_path = target / 'seed_study.json'
    if report_path.exists():
        raise ValueError('Seed study already exists. Use --export-only to publish its aggregates')
    with open_dataset(args.source, args.split, args.allow_partial_source) as data:
        ranker, tags, signatures = load_training(data, base)
        if frozen['identity'] != data.identity or signatures != frozen['training_summary_sha256']:
            raise ValueError('Training, split and frozen ranker must match')
        artists = artist_index(data)
        weight = frozen['selected_tag_weight']
        identity = {'version': VERSION, 'queries_per_split': args.queries, 'split': data.identity,
                    'frozen_ranker_sha256': old_test['freeze_sha256'], 'budgets': list(BUDGETS)}
        design_path = target / 'seed_freeze.json'
        if design_path.exists():
            design = read_json(design_path)
            if design['identity'] != identity:
                raise ValueError('Existing seed study uses a different design; choose a different output directory')
        else:
            exclude = previous_groups(data, 'validation', frozen['validation_query_sample'], frozen)
            print('Evaluating fresh validation playlists', flush=True)
            validation = measure(data, ranker, tags, artists, fresh_sample(data, 'validation', exclude, args.queries), weight)
            curve = [validation['budgets'][str(n)]['all_queries']['learned_title']['ndcg_at_20'] for n in BUDGETS]
            peak = max(curve)
            chosen = next(n for n, score in zip(BUDGETS, curve) if score >= .95 * peak)
            design = {'identity': identity, 'chosen_seed_budget': chosen, 'validation': validation}
            write_json(design_path, design)
        exclude = previous_groups(data, 'test', old_test['sample'], frozen)
        print(f'Validation selected {design["chosen_seed_budget"]} seeds. Evaluating fresh test playlists', flush=True)
        test = measure(data, ranker, tags, artists, fresh_sample(data, 'test', exclude, args.queries), weight,
                       design['chosen_seed_budget'])
    report = {'version': VERSION, 'seed_budgets': list(BUDGETS), 'chosen_seed_budget': design['chosen_seed_budget'],
              'seed_rule': 'Smallest tested budget attaining at least 95% of peak validation NDCG@20 for the learned-title ranker.',
              'reference_protocol': 'Same playlist cohort and reference set at every budget. First 20 deterministic shuffled tracks form the seed pool. Unrevealed seed-pool tracks may be candidates but do not receive credit.',
              'tag_weight': weight, 'training_catalogue_tracks': len(ranker.popular),
              'validation': design['validation'], 'test': test}
    write_json(report_path, report)
    return report


def site_report(report):
    public = {**report}
    for partition in ('validation', 'test'):
        section = {key: value for key, value in report[partition].items() if key != 'sampled_pid_sha256'}
        section['cases'] = {name: {key: value for key, value in case.items() if key != 'case'} if case else None
                            for name, case in section['cases'].items()}
        public[partition] = section
    return public


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    parser.add_argument('--model', type=Path, default=Path('runs/million/model'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/seed-study'))
    parser.add_argument('--site-output', type=Path, default=Path('docs/seed_experiment.js'))
    parser.add_argument('--queries', type=int, default=1500)
    parser.add_argument('--allow-partial-source', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.queries < 1:
            raise ValueError('Query count must be positive')
        report = read_json(args.output / 'seed_study.json') if args.export_only else run(args)
        payload = json.dumps(site_report(report), ensure_ascii=True, indent=2, allow_nan=False)
        args.site_output.parent.mkdir(parents=True, exist_ok=True)
        args.site_output.write_text(f'window.NEXT_TRACK_SEED_STUDY = {payload};\n', encoding='utf-8')
        print(f'Validation chose {report["chosen_seed_budget"]} seeds. Site data written to {args.site_output}.')
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
