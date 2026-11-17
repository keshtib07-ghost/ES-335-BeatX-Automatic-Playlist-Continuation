"""Measure the public Studio's edge-case behaviour without writing to Spotify.

This is a reproducible functional audit, not a held-out relevance experiment.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

SEEDS = ['7fnqltLx83HsYLQajzCYRk', '3YYKrn3iGOAel605Znt3ai', '64fGW0tyU2caV8ddFLUUBj']
UNKNOWN = 'ZZZZZZZZZZZZZZZZZZZZZZ'


def request(base, path, body=None):
    payload = None if body is None else json.dumps(body).encode()
    req = Request(base.rstrip('/') + path, data=payload, headers={
        'Content-Type': 'application/json', 'Origin': 'https://keshtib07-ghost.github.io'})
    started = time.monotonic()
    try:
        with urlopen(req, timeout=55) as response:
            return response.status, json.load(response), time.monotonic() - started
    except HTTPError as error:
        return error.code, json.load(error), time.monotonic() - started


def cases():
    specs = [
        ('title_only_study', 'Rainy Night Study', [], {}, 200),
        ('title_only_gym', 'Gym workout', [], {}, 200),
        ('no_context', 'My playlist', [], {}, 200),
        ('unknown_seed', 'Gym workout', [UNKNOWN], {}, 200),
        ('mixed_seeds', 'Study focus', [SEEDS[0], UNKNOWN], {}, 200),
        ('known_study', 'Study focus', SEEDS, {}, 200),
        ('conflicting_title', 'Gym workout', SEEDS, {}, 200),
        ('explicit_gym', 'Gym workout', SEEDS, {'tags': ['gym']}, 200),
        ('explicit_conflict', 'Gym workout', SEEDS, {'tags': ['study_focus']}, 200),
        ('restrictive_tempo', 'Study focus', SEEDS, {'min_bpm': 299, 'max_bpm': 300}, 200),
        ('duplicate_seeds', 'Study focus', [SEEDS[0], SEEDS[0]], {}, 400),
    ]
    for name, title, seeds, filters, expected in specs:
        yield name, {'title': title, 'seeds': seeds, 'method': 'unified', 'filters': filters}, expected


def audit(base):
    code, before, _ = request(base, '/api/status')
    if code != 200 or not before.get('unified_model'):
        raise ValueError('A loaded unified model is required for this audit')
    rows, rankings = [], {}
    for name, body, expected in cases():
        code, response, seconds = request(base, '/api/recommend', body)
        tracks = response.get('tracks', [])
        ids = [track['id'] for track in tracks]
        artists = Counter(track.get('artist') for track in tracks if track.get('artist'))
        known_artists = sum(artists.values())
        checks = {
            'expected_http_status': code == expected,
            'no_duplicate_track_ids': len(ids) == len(set(ids)),
            'seeds_excluded': not set(ids).intersection(body['seeds']),
            'at_most_20': len(ids) <= 20,
        }
        if code == 200:
            checks['uses_unified_method'] = response.get('method') == 'unified'
        row = {'case': name, 'request': body, 'http_status': code, 'expected_http_status': expected,
               'results': len(ids), 'known_seeds': response.get('known_seeds'),
               'applied_context': response.get('tags', []),
               'note': response.get('filter_note', response.get('error', '')),
               'artist_diversity': len(artists) / known_artists if known_artists else None,
               'largest_artist_share': max(artists.values()) / known_artists if known_artists else None,
               'known_bpm_results': sum(track.get('profile', {}).get('bpm') is not None for track in tracks),
               'seconds': round(seconds, 3), 'checks': checks,
               'ranking_sha256': hashlib.sha256(','.join(ids).encode()).hexdigest()}
        rows.append(row)
        rankings[name] = ids
        print(f'{name}: HTTP {code}, {len(ids)} results', flush=True)
    code, after, _ = request(base, '/api/status')
    if code != 200 or before.get('model_id') != after.get('model_id'):
        raise ValueError('Model identity changed during the audit; discard this run')
    a, b = rankings['known_study'], rankings['conflicting_title']
    return {'schema_version': 1, 'kind': 'live_functional_audit',
            'measured_utc': datetime.now(timezone.utc).isoformat(), 'api': base,
            'model_id': before['model_id'], 'cases': rows,
            'comparison': {'same_seed_different_title_overlap_at_20': len(set(a) & set(b)),
                           'same_seed_different_title_same_order': a == b},
            'all_contract_checks_passed': all(all(row['checks'].values()) for row in rows),
            'scope': 'Prespecified constructed requests against the deployed API. No hidden references or listener judgments. This is not Recall, NDCG or a population failure rate.'}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--api', default='https://beatx-api-keshav.centralindia.cloudapp.azure.com')
    cli.add_argument('--output', type=Path, default=Path('docs/data/research/studio_audit.json'))
    args = cli.parse_args()
    report = audit(args.api)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    if not report['all_contract_checks_passed']:
        raise SystemExit('Audit saved; one or more contract checks failed. Inspect the report.')


if __name__ == '__main__':
    main()
