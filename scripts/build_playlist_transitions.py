"""Learn directed next-track evidence from raw training playlist positions."""

import argparse
import json
import os
import sqlite3
import zipfile
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from prepare_million import inspect_archive
from playlist_model.data import track_id
from playlist_model.million import open_dataset, read_json, write_json
from playlist_model.sequence import Transitions, adjacency_recall, edge_key


VERSION = 'ordered-transition-v1'


def ordered_indices(row, by_id, aliases):
    def position(pair):
        ordinal, track = pair
        return track.get('pos') if isinstance(track.get('pos'), int) else ordinal

    tracks = sorted(enumerate(row['tracks']), key=position)
    seen, result = set(), []
    for _, item in tracks:
        value = by_id.get(track_id(item.get('track_uri')))
        if value is None:
            continue
        if aliases is not None:
            value = int(aliases[value])
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def write_pair_counts(edges, path):
    edges.sort()
    start, retained = 0, 0
    with (path / 'pairs.u64').open('wb') as pairs, (path / 'support.u32').open('wb') as support:
        while start < len(edges):
            end = min(start + 1_000_000, len(edges))
            if end < len(edges):
                end = int(np.searchsorted(edges, edges[end - 1], side='right'))
            keys, counts = np.unique(edges[start:end], return_counts=True)
            keep = counts >= 2
            keys[keep].astype('<u8', copy=False).tofile(pairs)
            counts[keep].astype('<u4').tofile(support)
            retained += int(keep.sum())
            start = end
    return retained


def run(args):
    destination = args.output
    if destination.exists():
        raise ValueError('Sequence output already exists; choose another folder for a different run')
    taken = read_json(args.model / 'index' / 'summary.json')
    counts = np.diff(np.load(args.model / 'index' / 'track_offsets.npy', mmap_mode='r'))
    with open_dataset(args.source, args.split, args.allow_partial_source) as data, \
            zipfile.ZipFile(args.zip) as archive:
        members, info = inspect_archive(archive)
        if info['archive_signature'] != data.identity['split']['archive_signature'] or taken['identity'] != data.identity:
            raise ValueError('ZIP, split and training index must all belong to the same run')
        training = np.zeros(1_000_000, dtype=bool)
        training[np.load(args.model / 'index' / 'train_pids.npy', mmap_mode='r')] = True
        by_id = dict(data.connection.execute('SELECT spotify_id, track_index FROM catalogue'))
        heldout = set(row[0] for row in data.sample('test', 'p.pid', args.queries, 340, eligible=True))
        heldout_sequences = {}
        destination.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(dir=destination.parent, prefix='.sequence-') as temp:
            path = Path(temp)
            raw = path / 'training_edges.tmp'
            edges = np.memmap(raw, dtype='<u8', mode='w+', shape=(taken['training_memberships'],))
            total, seen_train = 0, 0
            for step, member in enumerate(members.values(), start=1):
                batch = []
                with archive.open(member) as handle:
                    records = json.load(handle)['playlists']
                for row in records:
                    pid = row['pid']
                    if not training[pid] and pid not in heldout:
                        continue
                    items = ordered_indices(row, by_id, data.aliases)
                    if training[pid]:
                        seen_train += 1
                        batch.extend(edge_key(a, b) for a, b in zip(items, items[1:]))
                    elif len(items) >= 20:
                        heldout_sequences[pid] = items[:20]
                edges[total:total + len(batch)] = batch
                total += len(batch)
                if step % 100 == 0 or step == len(members):
                    print(f'Loaded positions from {step:,}/{len(members):,} slices', flush=True)
            if seen_train != taken['training_playlists']:
                raise ValueError('Raw ZIP did not reproduce the training playlist count')
            print(f'Counting {total:,} directed training transitions', flush=True)
            pairs = write_pair_counts(edges[:total], path)
            del edges
            raw.unlink()
            model = Transitions(path, counts)
            observations = []
            for pid in sorted(heldout_sequences):
                reference = heldout_sequences[pid]
                scrambled = np.random.default_rng(pid + 340).permutation(reference[1:]).tolist()
                result, observed = model.order(scrambled, anchor=reference[0])
                observations.append((adjacency_recall(reference, [reference[0], *scrambled]),
                                     adjacency_recall(reference, [reference[0], *result]), observed / len(result)))
            if not observations:
                raise ValueError('No sampled test playlists had 20 distinct tracks for sequence evaluation')
            random, ordered, trained = map(float, np.mean(observations, axis=0))
            report = {'version': VERSION, 'identity': data.identity, 'training_playlists': seen_train,
                      'directed_training_edges': total, 'pairs_with_at_least_two_observations': pairs,
                      'evaluation': {'eligible_test_sequences': len(observations), 'sampled_playlists': len(heldout),
                                     'random_adjacency_recall': random, 'ordered_adjacency_recall': ordered,
                                     'ordered_transitions_with_training_evidence': trained}}
            del model
            write_json(path / 'summary.json', report)
            os.replace(path, destination)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--zip', type=Path)
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    parser.add_argument('--model', type=Path, default=Path('runs/million/model'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/sequence'))
    parser.add_argument('--site-output', type=Path, default=Path('docs/sequence_experiment.js'))
    parser.add_argument('--queries', type=int, default=500)
    parser.add_argument('--allow-partial-source', action='store_true')
    parser.add_argument('--export-only', action='store_true')
    args = parser.parse_args()
    try:
        if args.queries < 1:
            raise ValueError('Query count must be positive')
        if not args.export_only and args.zip is None:
            raise ValueError('Supply the full MPD ZIP with --zip')
        report = read_json(args.output / 'summary.json') if args.export_only else run(args)
        public = {key: report[key] for key in ('training_playlists', 'directed_training_edges',
                                                'pairs_with_at_least_two_observations', 'evaluation')}
        args.site_output.parent.mkdir(parents=True, exist_ok=True)
        args.site_output.write_text(f'window.NEXT_TRACK_SEQUENCE = {json.dumps(public, indent=2)};\n', encoding='utf-8')
        print(json.dumps(public, indent=2))
    except (OSError, ValueError, KeyError, sqlite3.Error, zipfile.BadZipFile) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
