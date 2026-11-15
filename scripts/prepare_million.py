"""Inventory an MPD ZIP and stage its playlist memberships on disk."""

import argparse
import hashlib
import json
import re
import shutil
import sqlite3
import struct
import time
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath


SLICE_NAME = re.compile(r'mpd\.slice\.(\d+)-(\d+)\.json\Z')
TRACK_URI = re.compile(r'(?:spotify:track:)?([A-Za-z0-9]{22})\Z')
SLICE_SIZE = 1000
FULL_STARTS = set(range(0, 1_000_000, SLICE_SIZE))
VERSION = 'mpd-staging-v1'

SCHEMA = '''
CREATE TABLE IF NOT EXISTS run_info (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS catalogue (
    track_index INTEGER PRIMARY KEY,
    spotify_id TEXT NOT NULL UNIQUE,
    track_name TEXT NOT NULL,
    artist_name TEXT NOT NULL,
    album_name TEXT NOT NULL,
    duration_ms INTEGER
);
CREATE TABLE IF NOT EXISTS playlists (
    pid INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    track_count INTEGER NOT NULL,
    track_indices BLOB NOT NULL CHECK (length(track_indices) = 4 * track_count)
);
CREATE TABLE IF NOT EXISTS completed_slices (
    slice_start INTEGER PRIMARY KEY,
    pathname TEXT NOT NULL,
    playlist_count INTEGER NOT NULL,
    raw_tracks INTEGER NOT NULL,
    invalid_tracks INTEGER NOT NULL,
    repeated_tracks INTEGER NOT NULL,
    memberships INTEGER NOT NULL,
    seconds REAL NOT NULL
);
'''


def inspect_archive(archive):
    members = {}
    for item in archive.infolist():
        if item.is_dir():
            continue
        match = SLICE_NAME.fullmatch(PurePosixPath(item.filename).name)
        if match is None:
            continue
        low, high = map(int, match.groups())
        if low not in FULL_STARTS or high != low + SLICE_SIZE - 1 or low in members:
            raise ValueError(f'Duplicate or invalid slice range: {item.filename}')
        members[low] = item
    if not members:
        raise ValueError('No MPD training slices found. Supply the main dataset ZIP.')
    members = dict(sorted(members.items()))
    signature = [[low, item.filename, item.CRC, item.file_size] for low, item in members.items()]
    missing = sorted(FULL_STARTS - members.keys())
    return members, {
        'archive_slices': len(members),
        'expected_playlists_in_archive': len(members) * SLICE_SIZE,
        'has_all_expected_slices': not missing,
        'uncompressed_json_gib': round(sum(item.file_size for item in members.values()) / 2**30, 2),
        'archive_signature': hashlib.sha256(json.dumps(signature, separators=(',', ':')).encode()).hexdigest(),
        'first_missing_slice_starts': missing[:10],
    }


def normalize_slice(payload, low, pathname):
    rows = payload.get('playlists') if isinstance(payload, dict) else None
    if not isinstance(rows, list) or len(rows) != SLICE_SIZE:
        raise ValueError(f'Expected exactly {SLICE_SIZE} playlists in {pathname}')
    valid_pids = set(range(low, low + SLICE_SIZE))
    catalogue, playlists = {}, []
    raw_tracks = invalid_tracks = repeated_tracks = 0
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError(f'Invalid playlist object in {pathname}')
        pid = row.get('pid')
        if type(pid) is not int or pid not in valid_pids:
            raise ValueError(f'Duplicate or out-of-range playlist id {pid!r} in {pathname}')
        valid_pids.remove(pid)
        title = row.get('name')
        tracks = row.get('tracks')
        if not isinstance(tracks, list):
            raise ValueError(f'Invalid tracks field for playlist {pid} in {pathname}')
        ids = set()
        for track in tracks:
            raw_tracks += 1
            uri = track.get('track_uri') if isinstance(track, dict) else None
            match = TRACK_URI.fullmatch(uri) if isinstance(uri, str) else None
            if not match:
                invalid_tracks += 1
                continue
            identifier = match[1]
            if identifier in ids:
                repeated_tracks += 1
                continue
            ids.add(identifier)
            if identifier not in catalogue:
                names = [track.get(field) for field in ('track_name', 'artist_name', 'album_name')]
                duration = track.get('duration_ms')
                catalogue[identifier] = tuple(name if isinstance(name, str) else '' for name in names) + (
                    duration if type(duration) is int and 0 < duration < 2**31 else None,
                )
        playlists.append((pid, title if isinstance(title, str) else '', ids))
    return catalogue, playlists, (raw_tracks, invalid_tracks, repeated_tracks)


def configure(connection, inventory):
    connection.execute('PRAGMA journal_mode=WAL')
    connection.execute('PRAGMA synchronous=FULL')
    connection.execute('PRAGMA cache_size=-32768')
    connection.executescript(SCHEMA)
    identity = json.dumps({'version': VERSION, **inventory}, sort_keys=True)
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        connection.execute("INSERT OR IGNORE INTO run_info VALUES ('identity', ?)", (identity,))
        saved = connection.execute("SELECT value FROM run_info WHERE key='identity'").fetchone()[0]
        if saved != identity:
            raise ValueError('This output belongs to a different ZIP inventory or staging version. Use another output folder.')


def track_lookup(connection, metadata):
    ids = sorted(metadata)
    existing = {}
    for start in range(0, len(ids), 500):
        chunk = ids[start:start + 500]
        markers = ','.join('?' for _ in chunk)
        existing.update(connection.execute(
            f'SELECT spotify_id, track_index FROM catalogue WHERE spotify_id IN ({markers})', chunk))
    first_new = connection.execute('SELECT COALESCE(MAX(track_index) + 1, 0) FROM catalogue').fetchone()[0]
    new_rows = [(identifier, *metadata[identifier]) for identifier in ids if identifier not in existing]
    if first_new + len(new_rows) > 2**32:
        raise ValueError('The track catalogue exceeds the storage format')
    connection.executemany('INSERT INTO catalogue VALUES (?, ?, ?, ?, ?, ?)',
                           ((index, *row) for index, row in enumerate(new_rows, first_new)))
    existing.update((row[0], index) for index, row in enumerate(new_rows, first_new))
    return existing


def store_slice(connection, low, pathname, metadata, rows, counts, start):
    with connection:
        connection.execute('BEGIN IMMEDIATE')
        if connection.execute('SELECT 1 FROM completed_slices WHERE slice_start=?', (low,)).fetchone():
            return False
        lookup = track_lookup(connection, metadata)
        memberships = sum(len(ids) for _, _, ids in rows)
        raw_count, invalid_count, repeated_count = counts
        if raw_count != memberships + invalid_count + repeated_count:
            raise ValueError(f'Track count reconciliation failed for {pathname}')

        def records():
            for pid, title, ids in rows:
                indices = sorted(lookup[identifier] for identifier in ids)
                yield pid, title, len(indices), struct.pack(f'<{len(indices)}I', *indices)

        connection.executemany('INSERT INTO playlists VALUES (?, ?, ?, ?)', records())
        connection.execute('INSERT INTO completed_slices VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                           (low, pathname, len(rows), *counts, memberships, time.monotonic() - start))
        return True


def report(connection, database, inventory):
    committed = connection.execute('''
        SELECT COUNT(*), COALESCE(SUM(playlist_count), 0), COALESCE(SUM(raw_tracks), 0),
               COALESCE(SUM(invalid_tracks), 0), COALESCE(SUM(repeated_tracks), 0),
               COALESCE(SUM(memberships), 0), COALESCE(SUM(seconds), 0)
        FROM completed_slices
    ''').fetchone()
    slices, playlists, raw, invalid, repeated, memberships, seconds = committed
    tracks = connection.execute('SELECT COUNT(*) FROM catalogue').fetchone()[0]
    return {**inventory, 'database': database.name, 'committed_slices': slices,
            'verified_playlist_ids': playlists, 'unique_spotify_track_ids': tracks,
            'raw_track_rows': raw, 'invalid_track_rows': invalid, 'repeated_track_rows': repeated,
            'playlist_track_memberships': memberships, 'committed_slice_seconds': round(seconds, 1),
            'archive_fully_staged': slices == inventory['archive_slices'],
            'million_playlist_preprocessing_complete': slices == 1000 and playlists == 1_000_000}


def prepare(archive, members, inventory, output, max_slices):
    output.mkdir(parents=True, exist_ok=True)
    database = output / 'mpd.sqlite3'
    print(f'Output free space: {shutil.disk_usage(output).free / 2**30:.1f} GiB', flush=True)
    with closing(sqlite3.connect(database, timeout=60)) as connection:
        configure(connection, inventory)
        done = set(row[0] for row in connection.execute('SELECT slice_start FROM completed_slices'))
        for position, (low, item) in enumerate(members.items(), start=1):
            if max_slices is not None and position > max_slices:
                break
            if low in done:
                continue
            start = time.monotonic()
            with archive.open(item) as member:
                payload = json.load(member)
            metadata, rows, counts = normalize_slice(payload, low, item.filename)
            del payload
            if store_slice(connection, low, item.filename, metadata, rows, counts, start):
                print(f'Committed slice {position}/{len(members)} (IDs {low}–{low + SLICE_SIZE - 1}) '
                      f'in {time.monotonic() - start:.1f}s', flush=True)
        summary = report(connection, database, inventory)
    destination = output / 'prep_summary.json'
    temporary = output / '.prep_summary.tmp'
    temporary.write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
    temporary.replace(destination)
    return summary


def verify(output):
    database = (output / 'mpd.sqlite3').resolve()
    with closing(sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True)) as connection:
        identity = json.loads(connection.execute("SELECT value FROM run_info WHERE key='identity'").fetchone()[0])
        if identity.pop('version') != VERSION:
            raise ValueError('Unsupported staging version')
        summary = report(connection, database, identity)
        actual = connection.execute('SELECT COUNT(*), COALESCE(SUM(track_count), 0) FROM playlists').fetchone()
        expected = (summary['verified_playlist_ids'], summary['playlist_track_memberships'])
        if actual != expected:
            raise ValueError(f'Staging counts mismatch: database has {actual}, checkpoint ledger has {expected}')
        if connection.execute('PRAGMA quick_check').fetchone() != ('ok',):
            raise ValueError('SQLite integrity check failed')
    return {**summary, 'database_verification': 'ok'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    scan = commands.add_parser('scan', help='Inspect ZIP member names without decompressing their contents')
    scan.add_argument('--zip', required=True, type=Path)
    staging = commands.add_parser('prepare', help='Stage each slice in one resumable database transaction')
    staging.add_argument('--zip', required=True, type=Path)
    staging.add_argument('--output', type=Path, default=Path('runs/million'))
    staging.add_argument('--max-slices', type=int, help='Stage only the first N slices to measure local performance')
    staging.add_argument('--allow-subset', action='store_true', help='Permit a known partial archive for developer testing')
    audit = commands.add_parser('verify', help='Check database integrity and reconcile membership totals')
    audit.add_argument('--output', type=Path, default=Path('runs/million'))
    args = parser.parse_args()
    try:
        if args.command == 'verify':
            result = verify(args.output)
        else:
            with zipfile.ZipFile(args.zip) as archive:
                members, inventory = inspect_archive(archive)
                result = {'zip': str(args.zip), **inventory}
                if args.command == 'prepare':
                    if args.max_slices is not None and args.max_slices < 1:
                        raise ValueError('--max-slices must be positive')
                    if not inventory['has_all_expected_slices'] and not args.allow_subset:
                        raise ValueError(f'Found {len(members)} slices, expected all 1,000. Run scan to see the missing ranges.')
                    result = prepare(archive, members, inventory, args.output, args.max_slices)
        print(json.dumps(result, indent=2), flush=True)
    except KeyboardInterrupt:
        parser.exit(130, '\nStopped. Committed slices are safe. Rerun the same prepare command to resume.\n')
    except (OSError, ValueError, sqlite3.Error, zipfile.BadZipFile) as error:
        parser.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
