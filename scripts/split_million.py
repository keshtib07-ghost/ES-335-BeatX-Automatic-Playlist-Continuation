"""Build a fresh grouped split from the disk-backed MPD staging database."""

import argparse
import csv
import hashlib
import json
import re
import sqlite3
import struct
from array import array
from contextlib import closing
from pathlib import Path


VERSION = 'mpd-grouped-split-v1'
BATCH_SIZE = 5000
SLICE_NAME = re.compile(r'mpd\.slice\.(\d+)-(\d+)\.json\Z')
TRACK_ID = re.compile(r'(?:spotify:track:)?([A-Za-z0-9]{22})\Z')
SPLITS = ('train', 'validation', 'test')
SCHEMA = '''
CREATE TABLE IF NOT EXISTS split_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS recording_aliases (
    track_index INTEGER PRIMARY KEY,
    recording_index INTEGER NOT NULL CHECK(recording_index < track_index)
);
CREATE TABLE IF NOT EXISTS playlist_groups (
    group_hash BLOB PRIMARY KEY CHECK(length(group_hash)=32),
    split TEXT NOT NULL CHECK(split IN ('train', 'validation', 'test')),
    forced_train INTEGER NOT NULL CHECK(forced_train IN (0, 1))
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS playlist_assignments (
    pid INTEGER PRIMARY KEY,
    group_hash BLOB NOT NULL REFERENCES playlist_groups(group_hash),
    recording_count INTEGER NOT NULL CHECK(recording_count >= 0),
    is_pilot INTEGER NOT NULL CHECK(is_pilot IN (0, 1))
);
CREATE VIEW IF NOT EXISTS assigned_splits AS
SELECT a.pid, g.split, a.group_hash, a.recording_count, a.is_pilot, g.forced_train
FROM playlist_assignments AS a JOIN playlist_groups AS g USING (group_hash);
'''


def read_only_uri(path):
    return path.resolve().as_uri() + '?mode=ro'


def digest_file(path):
    digest = hashlib.sha256()
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def pilot_slice_starts(path):
    starts = set()
    for entry in json.loads(path.read_text(encoding='utf-8'))['slices']:
        name = entry['filename']
        match = SLICE_NAME.fullmatch(name)
        if not match:
            raise ValueError(f'Invalid pilot slice filename: {name}')
        low, high = map(int, match.groups())
        if low % 1000 or high != low + 999 or low >= 1_000_000 or low in starts:
            raise ValueError(f'Invalid or duplicate pilot slice range: {name}')
        starts.add(low)
    if not starts:
        raise ValueError('Pilot manifest has no development slices')
    return starts


def read_source_identity(connection, allow_partial):
    row = connection.execute("SELECT value FROM run_info WHERE key='identity'").fetchone()
    if row is None:
        raise ValueError('The source has no MPD staging identity')
    identity = json.loads(row[0])
    slices, playlists = connection.execute('''
        SELECT COUNT(*), COALESCE(SUM(playlist_count), 0) FROM completed_slices
    ''').fetchone()
    tracks = connection.execute('SELECT COALESCE(MAX(track_index) + 1, 0) FROM catalogue').fetchone()[0]
    if identity.get('version') != 'mpd-staging-v1' or not playlists:
        raise ValueError('Expected a nonempty MPD staging database')
    full = slices == 1000 and playlists == 1_000_000 and identity.get('has_all_expected_slices') is True
    if not full and not allow_partial:
        raise ValueError(f'The staging database has {slices} slices and {playlists} playlists. Finish preparation first.')
    return {'archive_signature': identity['archive_signature'], 'source_slices': slices,
            'source_playlists': playlists, 'source_track_indices': tracks, 'source_is_full_mpd': full}


def setup_recording_aliases(connection, source_uri, mapping, mapping_digest):
    connection.execute('''
        CREATE TEMP TABLE reviewed_map (spotify_id TEXT PRIMARY KEY, recording_id TEXT NOT NULL) WITHOUT ROWID
    ''')

    def valid_rows():
        with mapping.open(encoding='utf-8-sig', newline='') as handle:
            reader = csv.DictReader(handle)
            if not {'track_id', 'recording_id'}.issubset(reader.fieldnames or []):
                raise ValueError('Recording map must contain track_id and recording_id columns')
            for line, row in enumerate(reader, start=2):
                identifier = TRACK_ID.fullmatch((row.get('track_id') or '').strip())
                recording = (row.get('recording_id') or '').strip()
                if identifier is None or not recording:
                    raise ValueError(f'Invalid verified recording mapping on CSV line {line}')
                yield identifier[1], recording

    connection.execute('ATTACH DATABASE ? AS mpd', (source_uri,))
    try:
        with connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.executemany('INSERT INTO reviewed_map VALUES (?, ?)', valid_rows())
            if digest_file(mapping) != mapping_digest:
                raise ValueError('Recording map changed during import')
            total = connection.execute('SELECT COUNT(*) FROM reviewed_map').fetchone()[0]
            connection.execute('''
                CREATE TEMP TABLE observed_map AS
                SELECT c.track_index, m.recording_id FROM reviewed_map AS m
                JOIN mpd.catalogue AS c USING (spotify_id)
            ''')
            observed = connection.execute('SELECT COUNT(*) FROM observed_map').fetchone()[0]
            connection.execute('''
                INSERT INTO recording_aliases
                SELECT m.track_index, r.representative
                FROM observed_map AS m
                JOIN (SELECT recording_id, MIN(track_index) AS representative
                      FROM observed_map GROUP BY recording_id) AS r USING (recording_id)
                WHERE m.track_index <> r.representative
            ''')
            connection.execute('DROP TABLE observed_map')
            connection.execute('DROP TABLE reviewed_map')
            connection.execute("INSERT INTO split_info VALUES ('map_counts', ?)",
                               (json.dumps({'mapping_rows': total, 'matched_tracks': observed}),))
    finally:
        connection.execute('DETACH DATABASE mpd')


def configure(connection, identity, source_uri, mapping):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA synchronous=FULL')
    connection.execute('PRAGMA foreign_keys=ON')
    connection.execute('PRAGMA cache_size=-32768')
    connection.executescript(SCHEMA)
    serialized = json.dumps(identity, sort_keys=True)
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("INSERT OR IGNORE INTO split_info VALUES ('identity', ?)", (serialized,))
        saved = connection.execute("SELECT value FROM split_info WHERE key='identity'").fetchone()[0]
        if saved != serialized:
            raise ValueError('This split belongs to a different source, pilot manifest, or recording map. Use a new output folder.')
    if not connection.execute("SELECT 1 FROM split_info WHERE key='map_counts'").fetchone():
        if mapping is not None:
            setup_recording_aliases(connection, source_uri, mapping, identity['recording_map_sha256'])
        else:
            with connection:
                connection.execute("INSERT INTO split_info VALUES ('map_counts', ?)",
                                   (json.dumps({'mapping_rows': 0, 'matched_tracks': 0}),))


def hash_memberships(count, payload, aliases):
    if aliases is not None:
        indices = sorted({aliases[index] for (index,) in struct.iter_unpack('<I', payload)})
        count, payload = len(indices), struct.pack(f'<{len(indices)}I', *indices)
    return hashlib.sha256(payload).digest(), count


def default_partition(group_hash):
    draw = hashlib.sha256(b'ES335-million-split-v1\0' + group_hash).digest()
    bucket = int.from_bytes(draw[:8], 'big') % 10_000
    return 'train' if bucket < 8000 else 'validation' if bucket < 9000 else 'test'


def assign_batch(connection, rows, pilot_starts, aliases):
    changes, assignments = [], []
    for pid, count, payload in rows:
        group_hash, recording_count = hash_memberships(count, payload, aliases)
        is_pilot = int((pid // 1000 * 1000) in pilot_starts)
        changes.append((group_hash, 'train' if is_pilot else default_partition(group_hash), is_pilot))
        assignments.append((pid, group_hash, recording_count, is_pilot))
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.executemany('''
            INSERT INTO playlist_groups VALUES (?, ?, ?)
            ON CONFLICT(group_hash) DO UPDATE SET split='train', forced_train=1
            WHERE excluded.forced_train=1 AND playlist_groups.forced_train=0
        ''', changes)
        connection.executemany('INSERT INTO playlist_assignments VALUES (?, ?, ?, ?)', assignments)


def report(connection, identity):
    totals = {split: {'playlists': 0, 'eligible_three_seed_queries': 0} for split in SPLITS}
    outside, forced = 0, 0
    for split, count, eligible, pilot_count, forced_count in connection.execute('''
        SELECT split, COUNT(*), SUM(recording_count > 3), SUM(is_pilot), SUM(forced_train)
        FROM assigned_splits GROUP BY split
    '''):
        totals[split] = {'playlists': count, 'eligible_three_seed_queries': eligible}
        if split != 'train':
            outside += pilot_count
        forced += forced_count
    assignments, pilots = connection.execute('''
        SELECT COUNT(*), COALESCE(SUM(is_pilot), 0) FROM playlist_assignments
    ''').fetchone()
    groups = connection.execute('SELECT COUNT(*) FROM playlist_groups').fetchone()[0]
    aliases = connection.execute('SELECT COUNT(*) FROM recording_aliases').fetchone()[0]
    mapping = json.loads(connection.execute("SELECT value FROM split_info WHERE key='map_counts'").fetchone()[0])
    if outside or sum(row['playlists'] for row in totals.values()) != assignments:
        raise ValueError('Invalid split: missing groups or pilot playlists outside training')
    complete = assignments == identity['source_playlists']
    expected_pilots = len(identity['pilot_slice_starts']) * 1000
    if complete and identity['source_is_full_mpd']:
        if pilots != expected_pilots:
            raise ValueError(f'Expected {expected_pilots} pilot playlists in training, found {pilots}')
        if any(not row['eligible_three_seed_queries'] for row in totals.values()):
            raise ValueError('A full partition has no eligible three-seed queries')
    return {**identity, **mapping, 'assigned_playlists': assignments, 'exact_playlist_groups': groups,
            'extra_exact_group_members': assignments - groups, 'pilot_playlists': pilots,
            'pilot_playlists_outside_train': outside, 'pilot_and_exact_copies_in_train': forced,
            'spotify_ids_mapped_to_another_index': aliases, 'splits': totals, 'source_fully_split': complete,
            'million_playlist_split_complete': complete and identity['source_is_full_mpd']}


def build(source, output, manifest, mapping, max_playlists, allow_partial):
    output.mkdir(parents=True, exist_ok=True)
    database = output / 'split.sqlite3'
    if database.resolve() == source.resolve():
        raise ValueError('Source and split databases must be different files')
    source_uri = read_only_uri(source)
    pilot_starts = pilot_slice_starts(manifest)
    with closing(sqlite3.connect(source_uri, uri=True)) as raw, closing(sqlite3.connect(database, uri=True)) as split:
        identity = {'version': VERSION, **read_source_identity(raw, allow_partial),
                    'pilot_manifest_sha256': digest_file(manifest), 'pilot_slice_starts': sorted(pilot_starts),
                    'recording_map_sha256': digest_file(mapping) if mapping else None}
        configure(split, identity, source_uri, mapping)
        aliases = None
        if split.execute('SELECT 1 FROM recording_aliases LIMIT 1').fetchone():
            aliases = array('I', range(identity['source_track_indices']))
            for track_index, recording_index in split.execute('SELECT track_index, recording_index FROM recording_aliases'):
                aliases[track_index] = recording_index
        assigned, last_pid = split.execute('SELECT COUNT(*), COALESCE(MAX(pid), -1) FROM playlist_assignments').fetchone()
        want = identity['source_playlists'] if max_playlists is None else min(max_playlists, identity['source_playlists'])
        rows = raw.execute('SELECT pid, track_count, track_indices FROM playlists WHERE pid>? ORDER BY pid', (last_pid,))
        while assigned < want and (batch := rows.fetchmany(min(BATCH_SIZE, want - assigned))):
            assign_batch(split, batch, pilot_starts, aliases)
            assigned += len(batch)
            if assigned == want or assigned % 50_000 == 0:
                print(f'Assigned {assigned:,}/{want:,} playlists', flush=True)
        if assigned < want:
            raise ValueError(f'The source ledger promises {want:,} playlists but only {assigned:,} were read')
        summary = report(split, identity)
    temporary = output / '.split_summary.tmp'
    temporary.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    temporary.replace(output / 'split_summary.json')
    return summary


def verify(output):
    with closing(sqlite3.connect(read_only_uri(output / 'split.sqlite3'), uri=True)) as connection:
        row = connection.execute("SELECT value FROM split_info WHERE key='identity'").fetchone()
        if not row:
            raise ValueError('The split database has no run identity')
        identity = json.loads(row[0])
        if identity.get('version') != VERSION:
            raise ValueError('Unsupported split database version')
        summary = report(connection, identity)
        if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('Split database integrity check failed')
    return {**summary, 'database_verification': 'ok'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    stage = commands.add_parser('build', help='Build or resume the grouped split')
    stage.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    stage.add_argument('--output', type=Path, default=Path('runs/million'))
    stage.add_argument('--pilot-manifest', type=Path, default=Path('artifacts/source_manifest.json'))
    stage.add_argument('--recording-map', type=Path, help='Optional verified CSV of track_id and recording_id')
    stage.add_argument('--max-playlists', type=int, help='Checkpoint after the first N source playlists')
    stage.add_argument('--allow-partial-source', action='store_true', help='Use a pilot-sized staging database for development')
    audit = commands.add_parser('verify', help='Reconcile counts and check database integrity')
    audit.add_argument('--output', type=Path, default=Path('runs/million'))
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            result = verify(args.output)
        else:
            if args.max_playlists is not None and args.max_playlists < 1:
                raise ValueError('--max-playlists must be positive')
            result = build(args.source, args.output, args.pilot_manifest, args.recording_map,
                           args.max_playlists, args.allow_partial_source)
        print(json.dumps(result, indent=2), flush=True)
    except KeyboardInterrupt:
        parser.exit(130, '\nStopped. Committed batches are safe. Rerun build with the same inputs to resume.\n')
    except (OSError, ValueError, KeyError, sqlite3.Error) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
