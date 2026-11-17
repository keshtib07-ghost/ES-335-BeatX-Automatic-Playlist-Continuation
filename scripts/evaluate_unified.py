"""Compare the final ranker against two controls on held-out playlists."""

import hashlib
import heapq
import json
from pathlib import Path
from unittest.mock import patch

import numpy as np

from playlist_model.__main__ import scores_for, summary
from playlist_model.million import open_dataset, rank_candidates, read_json
from scripts.seed_study import FIELDS, previous_groups
from scripts.serve_million_demo import Demo

root = Path('runs/million')
source, split, run = root / 'mpd.sqlite3', root / 'split.sqlite3', root / 'model'
bulk = root / 'catalogue-enrichment/catalogue_enrichment.sqlite3'
demo = Demo(source, split, run, False, profiles=root / 'profiles-v2-expanded',
            catalogue_profiles=bulk if bulk.is_file() else None)
profile, ranker = demo.profiles, demo.ranker
if profile is None:
    raise SystemExit('Expanded song profiles are missing.')

def key(value):
    return hashlib.blake2b(f'unified-eval-v1:{value}'.encode(), digest_size=8).digest()

def eligible(data, excluded):
    seen = set(excluded)
    for row in data.rows('test', FIELDS):
        pid, _, _, count, group = row
        if count == 20 and group not in seen:
            seen.add(group)
            yield key(pid), row

metrics = {name: [] for name in ('seeds_only', 'seeds_and_title', 'unified')}
lengths = {name: [] for name in metrics}

with open_dataset(source, split) as data, demo.catalogue(with_bulk=True) as db:
    old = read_json(run / 'test_metrics.json')
    frozen = read_json(run / 'frozen_settings.json')
    excluded = previous_groups(data, 'test', old['sample'], frozen)
    rows = heapq.nsmallest(300, eligible(data, excluded), key=lambda pair: pair[0])
    if not rows:
        raise SystemExit('No eligible held-out playlists with exactly 20 tracks.')
    for number, (_, (pid, title, payload, count, _)) in enumerate(rows, 1):
        tracks = sorted(map(int, data.recordings(payload, count)), key=lambda t: key(f'{pid}:{t}'))
        seeds, targets = np.asarray(tracks[:5], dtype=np.int32), set(tracks[5:])
        warm = seeds[ranker.counts[seeds] > 0]
        if len(warm):
            items, scores, fallback = ranker.candidates(warm)
            plain = rank_candidates(items, scores, fallback, np.zeros(len(items)), 0)
        else:
            plain = ranker.popularity(seeds, 20)
        with patch.object(profile, 'seed_context', return_value=set()):
            title_only, *_ = profile.recommend(ranker, seeds, title, {}, db)
        unified, *_ = profile.recommend(ranker, seeds, title, {}, db)
        for name, result in zip(metrics, (plain, title_only, unified)):
            metrics[name].append(scores_for(result, targets))
            lengths[name].append(len(result))
        if number % 50 == 0:
            print(f'{number}/{len(rows)} playlists', flush=True)

scores = summary({name: np.asarray(values) for name, values in metrics.items()},
                 np.ones(len(rows), dtype=bool))
for name in scores:
    scores[name]['mean_results'] = float(np.mean(lengths[name]))
report = json.dumps({'queries': len(rows), 'seeds': 5, 'hidden_tracks': 15,
                     'manual_tags': 'not evaluated', 'results': scores}, indent=2)
(root / 'unified-evaluation.json').write_text(report + '\n', encoding='utf-8')
print(report)
