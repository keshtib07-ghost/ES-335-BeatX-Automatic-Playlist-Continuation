"""Export measured EDA from verified pilot slices or the complete staging DB."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from contextlib import closing

import numpy as np

from scripts.download_pilot import git_blob_sha1

LENGTH_EDGES = (0, 10, 20, 40, 60, 100, 150, 200, 300)
SUPPORT_EDGES = (0, 1, 2, 5, 10, 20, 50, 100, 1000, 10000, 1000000)


def histogram(values, edges):
    values = np.asarray(values)
    bins = [int(np.count_nonzero((values >= low) & (values < high)))
            for low, high in zip(edges, edges[1:])]
    bins.append(int(np.count_nonzero(values >= edges[-1])))
    labels = [f'{low}\u2013{high - 1}' for low, high in zip(edges, edges[1:])]
    labels.append(f'{edges[-1]}+')
    return {'labels': labels, 'counts': bins, 'total': int(len(values))}


def distributions(lengths, support, titles, groups):
    support = np.asarray(support)
    positive = support[support > 0]
    head = max(1, int(np.ceil(len(positive) * .01)))
    return {'playlist_length': histogram(lengths, LENGTH_EDGES),
            'track_support': histogram(positive, SUPPORT_EDGES),
            'title_length': histogram([len(t) for t in titles], (0, 1, 5, 10, 20, 40, 80)),
            'duplicate_group_size': histogram(list(groups.values()), (1, 2, 3, 5, 10, 20, 50)),
            'playlist_length_quantiles': dict(zip(('min', 'q25', 'median', 'q75', 'max'),
                                                  map(float, np.quantile(lengths, [0, .25, .5, .75, 1])))),
            'distinct_tracks': len(positive), 'memberships': int(positive.sum()),
            'top_one_percent_membership_share': float(np.sort(positive)[-head:].sum() / positive.sum()),
            'singleton_tracks': int(np.count_nonzero(positive == 1)),
            'empty_titles': sum(not t.strip() for t in titles),
            'non_ascii_titles': sum(not t.isascii() for t in titles),
            'extra_exact_group_members': sum(v - 1 for v in groups.values()),
            'text_note': 'Character/script summaries are not language identification.'}


def pilot_eda(directory, manifest):
    source = json.loads(manifest.read_text())
    support, groups = Counter(), Counter()
    lengths, titles, hashes = [], [], {}
    raw = repeated = invalid = 0
    for item in source['slices']:
        path = directory / item['filename']
        if git_blob_sha1(path) != item['git_blob_sha1']:
            raise ValueError(f'Unverified source slice: {path.name}')
        hashes[path.name] = item['git_blob_sha1']
        payload = json.loads(path.read_bytes())
        for row in payload['playlists']:
            ids = []
            for track in row['tracks']:
                raw += 1
                match = re.fullmatch(r'spotify:track:([A-Za-z0-9]{22})', track.get('track_uri', ''))
                if match:
                    ids.append(match[1])
                else:
                    invalid += 1
            unique = sorted(set(ids))
            repeated += len(ids) - len(unique)
            support.update(unique)
            groups[hashlib.sha256(','.join(unique).encode()).hexdigest()] += 1
            lengths.append(len(unique))
            titles.append(row.get('name') or '')
    return {'schema_version': 1, 'kind': 'verified_training_pilot_eda',
            'scope': 'All 20,000 playlists in the original pinned training pilot. These slices were forced into training. This is a descriptive subset, not an estimate of the full MPD distribution.',
            'source': {'repository': source['repository'], 'commit': source['commit'], 'git_blob_sha1': hashes},
            'playlists': len(lengths), 'raw_occurrences': raw, 'repeat_occurrences_removed': repeated,
            'invalid_occurrences': invalid, 'all_playlists': distributions(lengths, list(support.values()), titles, groups),
            'metadata': {'bpm_in_raw_mpd': False, 'bass_in_raw_mpd': False,
                         'note': 'Raw MPD does not provide verified BPM or spectral bass. Enrichment coverage needs a separate source-backed audit.'}}


def full_eda(source, split, model):
    from playlist_model.million import DiskRanker, open_dataset
    result = {'schema_version': 1, 'kind': 'full_staging_eda',
              'scope': 'Measured from the complete staged MPD and its existing grouped split. No models are fitted.',
              'partitions': {}}
    with open_dataset(source, split) as data:
        for part in ('train', 'validation', 'test'):
            rows = list(data.rows(part, 'p.title, s.recording_count, s.group_hash'))
            titles = [row[0] for row in rows]
            lengths = [row[1] for row in rows]
            groups = Counter(row[2] for row in rows)
            result['partitions'][part] = {
                'playlists': len(rows), 'playlist_length': histogram(lengths, LENGTH_EDGES),
                'title_length': histogram([len(t) for t in titles], (0, 1, 5, 10, 20, 40, 80)),
                'duplicate_group_size': histogram(list(groups.values()), (1, 2, 3, 5, 10, 20, 50)),
                'empty_titles': sum(not t.strip() for t in titles),
                'non_ascii_titles': sum(not t.isascii() for t in titles)}
        result['identity'] = data.identity
        result['playlists'] = sum(row['playlists'] for row in result['partitions'].values())
    ranker = DiskRanker(model / 'index')
    counts = ranker.counts[ranker.counts > 0]
    head = max(1, int(np.ceil(len(counts) * .01)))
    result['training_track_support'] = histogram(counts, SUPPORT_EDGES)
    result['top_one_percent_membership_share'] = float(np.sort(counts)[-head:].sum() / counts.sum())
    result['text_note'] = 'Non-ASCII is a script diagnostic, not language identification.'
    return result


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--pilot-dir', type=Path)
    cli.add_argument('--manifest', type=Path, default=Path('artifacts/source_manifest.json'))
    cli.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    cli.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    cli.add_argument('--model', type=Path, default=Path('runs/million/model-full-titles'))
    cli.add_argument('--output', type=Path, default=Path('docs/data/research/eda.json'))
    args = cli.parse_args()
    result = pilot_eda(args.pilot_dir, args.manifest) if args.pilot_dir else full_eda(args.source, args.split, args.model)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(f'Measured EDA for {result["playlists"]:,} playlists: {args.output}')


if __name__ == '__main__':
    main()
