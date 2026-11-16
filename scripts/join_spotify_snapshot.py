"""Join a local Spotify metadata snapshot to MPD by exact, case-sensitive track ID."""

import argparse
import csv
import hashlib
import json
import math
import re
import sqlite3
from contextlib import closing
from datetime import date
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory


TRACK_ID = re.compile(r'[A-Za-z0-9]{22}')
RELEASE_DATE = re.compile(r'\d{4}(?:-\d{2}(?:-\d{2})?)?', re.ASCII)
DATABASE = 'spotify_snapshot.sqlite3'
REPORT = 'spotify_snapshot_report.json'


def catalogue_date(value):
    value = (value or '').strip()
    if not RELEASE_DATE.fullmatch(value):
        return None
    parts = [int(part) for part in value.split('-')]
    try:
        date(*(parts + [1] * (3 - len(parts))))
    except ValueError:
        return None
    return value


def positive_bpm(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def snapshot_rows(reader, counts):
    for row in reader:
        counts['rows'] += 1
        identifier = (row['id'] or '').strip()
        if not TRACK_ID.fullmatch(identifier):
            counts['invalid_id_rows'] += 1
            continue
        yield identifier, catalogue_date(row['release_date']), positive_bpm(row['tempo'])


def stage_snapshot(db, path):
    counts = {'rows': 0, 'invalid_id_rows': 0}
    db.execute('CREATE TEMP TABLE incoming (spotify_id TEXT, catalogue_release_date TEXT, bpm REAL)')
    with path.open(encoding='utf-8-sig', newline='') as handle:
        reader = csv.DictReader(handle)
        if not {'id', 'release_date', 'tempo'}.issubset(reader.fieldnames or []):
            raise ValueError('Snapshot CSV requires id, release_date and tempo columns.')
        rows = snapshot_rows(reader, counts)
        while batch := list(islice(rows, 10_000)):
            db.executemany('INSERT INTO incoming VALUES (?, ?, ?)', batch)
    if counts['rows'] == counts['invalid_id_rows']:
        raise ValueError('Snapshot CSV has no valid Spotify IDs.')
    return counts


def attach(db, name, path):
    # Schema names are fixed by the callers, and paths are passed as parameters.
    db.execute(f'ATTACH DATABASE ? AS {name}', (path.resolve().as_uri() + '?mode=ro',))


def original_profile_coverage(db, path, signature):
    fields = ('first_recording_release_date', 'bpm', 'bass_share', 'treble_share', 'any_release_date')
    existing = dict.fromkeys(fields, 0)
    overlap = dict.fromkeys(fields, 0)
    if path.is_file():
        attach(db, 'profiles', path)
        identity = db.execute("SELECT value FROM profiles.identity WHERE key='run'").fetchone()
        if identity is None or json.loads(identity[0]).get('split', {}).get('archive_signature') != signature:
            raise ValueError('Existing enrichment cache belongs to a different MPD archive.')
        for profile_json, snapshot_date, snapshot_bpm in db.execute('''
            SELECT p.profile, s.catalogue_release_date, s.bpm FROM profiles.lookups AS p
            JOIN mpd.catalogue AS c ON c.spotify_id = p.spotify_id COLLATE BINARY
            LEFT JOIN spotify_tracks AS s ON s.spotify_id = p.spotify_id COLLATE BINARY
        '''):
            profile = json.loads(profile_json)
            has_date = catalogue_date(profile.get('release_date')) is not None
            has_bpm = positive_bpm(profile.get('bpm')) is not None
            existing['first_recording_release_date'] += has_date
            existing['any_release_date'] += has_date
            existing['bpm'] += has_bpm
            existing['bass_share'] += profile.get('bass_share') is not None
            existing['treble_share'] += profile.get('treble_share') is not None
            overlap['any_release_date'] += has_date and snapshot_date is not None
            overlap['bpm'] += has_bpm and snapshot_bpm is not None
    return existing, overlap


def join_snapshot(csv_path, source, output):
    output.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix='.spotify-snapshot-', dir=output) as temporary:
        temporary = Path(temporary)
        database = temporary / DATABASE
        with closing(sqlite3.connect(database, uri=True)) as db, db:
            attach(db, 'mpd', source)
            identity = db.execute("SELECT value FROM mpd.run_info WHERE key='identity'").fetchone()
            if identity is None:
                raise ValueError('MPD database has no staging identity.')
            signature = json.loads(identity[0])['archive_signature']
            total = db.execute('SELECT COUNT(*) FROM mpd.catalogue').fetchone()[0]
            slices = db.execute('SELECT COUNT(*) FROM mpd.completed_slices').fetchone()[0]
            if not total:
                raise ValueError('MPD catalogue is empty.')
            with csv_path.open('rb') as handle:
                digest = hashlib.file_digest(handle, 'sha256').hexdigest()
            counts = stage_snapshot(db, csv_path)
            db.execute('''
                CREATE TEMP TABLE matched AS
                SELECT i.spotify_id, COUNT(*) AS input_rows,
                       COUNT(DISTINCT i.catalogue_release_date) AS dates,
                       COUNT(DISTINCT i.bpm) AS tempos,
                       MIN(i.catalogue_release_date) AS catalogue_release_date, MIN(i.bpm) AS bpm
                FROM incoming AS i JOIN mpd.catalogue AS c ON c.spotify_id = i.spotify_id COLLATE BINARY
                GROUP BY i.spotify_id
            ''')
            db.execute('''
                CREATE TABLE spotify_tracks (
                    spotify_id TEXT PRIMARY KEY, catalogue_release_date TEXT, bpm REAL
                ) WITHOUT ROWID
            ''')
            db.execute('''
                INSERT INTO spotify_tracks
                SELECT spotify_id, CASE WHEN dates = 1 THEN catalogue_release_date END,
                       CASE WHEN tempos = 1 THEN bpm END FROM matched
            ''')
            matched, duplicate_ids, date_conflicts, bpm_conflicts = db.execute('''
                SELECT COUNT(*), COUNT(CASE WHEN input_rows > 1 THEN 1 END),
                       COUNT(CASE WHEN dates > 1 THEN 1 END), COUNT(CASE WHEN tempos > 1 THEN 1 END)
                FROM matched
            ''').fetchone()
            dates, bpms = db.execute('SELECT COUNT(catalogue_release_date), COUNT(bpm) FROM spotify_tracks').fetchone()
            prior_path = output / 'enrichment.sqlite3'
            existing, overlap = original_profile_coverage(db, prior_path, signature)
            snapshot = {**dict.fromkeys(existing, 0), 'catalogue_release_date': dates,
                        'any_release_date': dates, 'bpm': bpms}
            coverage = {}
            for field, count in snapshot.items():
                prior = existing.get(field, 0)
                added = count - overlap.get(field, 0)
                coverage[field] = {'existing': prior, 'snapshot': count, 'new': added,
                                   'combined': prior + added, 'missing': total - prior - added}
            report = {
                'version': 'spotify-id-snapshot-v1',
                'mpd_archive_signature': signature,
                'mpd_committed_slices': slices,
                'mpd_catalogue_tracks': total,
                'snapshot_csv': {'file': csv_path.name, 'sha256': digest, **counts},
                'exact_id_matches': matched,
                'mpd_tracks_without_exact_id_match': total - matched,
                'matched_ids_with_duplicate_snapshot_rows': duplicate_ids,
                'matched_ids_with_conflicting_catalogue_dates': date_conflicts,
                'matched_ids_with_conflicting_bpm': bpm_conflicts,
                'included_existing_enrichment': prior_path.is_file(),
                'coverage_by_field': coverage,
            }
            db.execute('CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('INSERT INTO metadata VALUES (?, ?)', ('report', json.dumps(report)))
        (temporary / REPORT).write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
        database.replace(output / DATABASE)
        (temporary / REPORT).replace(output / REPORT)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--csv', type=Path, required=True, help='Local snapshot CSV containing id, release_date and tempo')
    parser.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    parser.add_argument('--output', type=Path, default=Path('runs/million/profiles-v2-expanded'))
    args = parser.parse_args()
    try:
        report = join_snapshot(args.csv, args.source, args.output)
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f'Spotify snapshot join failed: {error}\n')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
