"""Select the context boost on validation, then score a fresh held-out cohort."""

import hashlib
import heapq
import json
from pathlib import Path

import numpy as np

from playlist_model.__main__ import scores_for, summary
from playlist_model.million import open_dataset, read_json, write_json
from scripts.seed_study import FIELDS, previous_groups
from scripts.serve_million_demo import Demo

ROOT = Path('runs/million')
RUN = ROOT / 'model'
PROFILES = ROOT / 'profiles-v2-expanded'
WEIGHTS = (0.0, 0.15, 0.35)
LIMIT = 150

def key(text):
    return hashlib.blake2b(text.encode(), digest_size=8).digest()

def sample(data, part, excluded, salt, limit):
    def eligible():
        seen = set(excluded)
        for row in data.rows(part, FIELDS):
            if row[3] == 20 and row[4] not in seen:
                seen.add(row[4])
                yield row
    return heapq.nsmallest(limit, eligible(), key=lambda row: key(f'{salt}:{row[0]}'))

def measure(data, db, demo, rows, weights):
    if not rows:
        raise SystemExit('No eligible playlists for this evaluation.')
    values = {str(weight): [] for weight in weights}
    for pid, title, payload, count, _ in rows:
        tracks = sorted(map(int, data.recordings(payload, count)),
                        key=lambda track: key(f'unified-eval-v2:{pid}:{track}'))
        seeds, targets = np.array(tracks[:5], dtype=np.int32), set(tracks[5:])
        for weight in weights:
            demo.profiles.context_weight = weight
            ranks, *_ = demo.profiles.recommend(demo.ranker, seeds, title, {}, db)
            values[str(weight)].append(scores_for(ranks, targets))
    return summary({name: np.array(rows) for name, rows in values.items()},
                   np.ones(len(rows), dtype=bool))

def main():
    source, split = ROOT / 'mpd.sqlite3', ROOT / 'split.sqlite3'
    bulk = ROOT / 'catalogue-enrichment/catalogue_enrichment.sqlite3'
    demo = Demo(source, split, RUN, False, profiles=PROFILES,
                catalogue_profiles=bulk if bulk.is_file() else None)
    if demo.profiles is None:
        raise SystemExit('Expanded song profiles are missing.')
    frozen = read_json(RUN / 'frozen_settings.json')
    with open_dataset(source, split) as data, demo.catalogue(with_bulk=True) as db:
        previous = {}
        for part in ('validation', 'test'):
            old = read_json(RUN / f'{part}_metrics.json')
            previous[part] = previous_groups(data, part, old['sample'], frozen)

        val = sample(data, 'validation', previous['validation'], 'boost-val-v1', LIMIT)
        validation = measure(data, db, demo, val, WEIGHTS)
        weight = max(WEIGHTS, key=lambda w: (validation[str(w)]['ndcg_at_20'], -w))
        print(f'Validation selected boost {weight:g}', flush=True)

        prior_test = sample(data, 'test', previous['test'], 'unified-eval-v1', 300)
        excluded = previous['test'] | {row[4] for row in prior_test}
        test = sample(data, 'test', excluded, 'boost-test-v1', LIMIT)
        test_weights = (0.0, weight) if weight else (0.0,)
        held_out = measure(data, db, demo, test, test_weights)

    write_json(PROFILES / 'ranking_settings.json', {'weight': weight, 'split': demo.profiles.split})
    report = {'weight': weight, 'validation_queries': len(val), 'test_queries': len(test),
              'validation': validation, 'fresh_test': held_out,
              'manual_tag_behavior': 'checked separately in unit tests'}
    write_json(ROOT / 'unified-tuning.json', report)
    print(json.dumps(report, indent=2))

if __name__ == '__main__':
    main()
