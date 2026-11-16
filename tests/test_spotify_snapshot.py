import json
import sqlite3
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from scripts.join_spotify_snapshot import DATABASE, REPORT, join_snapshot
from scripts.prepare_million import SCHEMA


class SpotifySnapshotTests(unittest.TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.mpd = self.root / 'mpd.sqlite3'
        self.csv = self.root / 'snapshot.csv'
        self.output = self.root / 'profiles'
        self.output.mkdir()

    def create_catalogue(self, *identifiers):
        with sqlite3.connect(self.mpd) as db:
            db.executescript(SCHEMA)
            db.execute('INSERT INTO run_info VALUES (?, ?)', ('identity', '{"archive_signature": "mpd"}'))
            db.executemany('INSERT INTO catalogue VALUES (?, ?, ?, ?, ?, ?)',
                           ((i, identifier, '', '', '', None) for i, identifier in enumerate(identifiers)))

    def add_existing_profile(self, identifier, signature):
        with sqlite3.connect(self.output / 'enrichment.sqlite3') as db:
            db.execute('CREATE TABLE identity (key TEXT PRIMARY KEY, value TEXT)')
            db.execute('INSERT INTO identity VALUES (?, ?)',
                       ('run', json.dumps({'split': {'archive_signature': signature}})))
            db.execute('CREATE TABLE lookups (spotify_id TEXT PRIMARY KEY, profile TEXT)')
            db.execute('INSERT INTO lookups VALUES (?, ?)',
                       (identifier, json.dumps({'release_date': '1999', 'bpm': 117, 'bass_share': 0})))

    def test_joins_exact_ids_without_double_counting_existing_measurements(self):
        a, b, c, d = (character * 22 for character in 'ABCD')
        self.create_catalogue(a, b, c, d)
        self.add_existing_profile(a, 'mpd')
        self.csv.write_text('id,release_date,tempo\n'
                            f'{a},2002-05,120\n{a},,120\n'
                            f'{b},2013-02-29,nan\n{b},2013,92\n{b},2014,94\n'
                            f'{c},2020-02-29,100\n{d.lower()},2022,140\ninvalid,2023,50\n')
        report = join_snapshot(self.csv, self.mpd, self.output)
        self.assertEqual(report['exact_id_matches'], 3)
        self.assertEqual(report['mpd_tracks_without_exact_id_match'], 1)
        self.assertEqual(report['snapshot_csv']['invalid_id_rows'], 1)
        self.assertEqual(report['matched_ids_with_duplicate_snapshot_rows'], 2)
        self.assertEqual(report['matched_ids_with_conflicting_catalogue_dates'], 1)
        self.assertEqual(report['matched_ids_with_conflicting_bpm'], 1)
        coverage = report['coverage_by_field']
        self.assertEqual(coverage['bpm'], {'existing': 1, 'snapshot': 2, 'new': 1, 'combined': 2, 'missing': 2})
        self.assertEqual(coverage['any_release_date'], coverage['bpm'])
        self.assertEqual(coverage['first_recording_release_date']['combined'], 1)
        self.assertEqual(coverage['catalogue_release_date']['combined'], 2)
        self.assertEqual(coverage['bass_share']['combined'], 1)
        self.assertEqual(coverage['treble_share']['combined'], 0)
        with sqlite3.connect(self.output / DATABASE) as db:
            self.assertEqual(db.execute('SELECT * FROM spotify_tracks ORDER BY spotify_id').fetchall(),
                             [(a, '2002-05', 120), (b, None, None), (c, '2020-02-29', 100)])
        self.assertEqual(json.loads((self.output / REPORT).read_text()), report)

    def test_failed_rerun_preserves_last_successful_output(self):
        identifier = 'A' * 22
        self.create_catalogue(identifier)
        self.csv.write_text(f'id,release_date,tempo\n{identifier},1999,100\n')
        report = join_snapshot(self.csv, self.mpd, self.output)
        self.add_existing_profile(identifier, 'other archive')
        with self.assertRaisesRegex(ValueError, 'different MPD archive'):
            join_snapshot(self.csv, self.mpd, self.output)
        self.assertEqual(json.loads((self.output / REPORT).read_text()), report)
        with sqlite3.connect(self.output / DATABASE) as db:
            self.assertEqual(db.execute('SELECT bpm FROM spotify_tracks').fetchone(), (100,))
