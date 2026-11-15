import csv
import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path

from scripts import split_million as split


def members(indices):
    return struct.pack(f'<{len(indices)}I', *indices)


class GroupedSplitTests(unittest.TestCase):
    def setUp(self):
        workspace = tempfile.TemporaryDirectory()
        self.addCleanup(workspace.cleanup)
        root = Path(workspace.name)
        self.source = root / 'source.sqlite3'
        self.out = root / 'run'
        self.manifest = root / 'pilot.json'
        self.manifest.write_text(json.dumps({'slices': [{'filename': 'mpd.slice.1000-1999.json'}]}))
        self.base = next(
            (0, 1, 2, index) for index in range(3, 120)
            if split.default_partition(split.hash_memberships(4, members((0, 1, 2, index)), None)[0]) != 'train'
        )
        with sqlite3.connect(self.source) as connection:
            connection.executescript('''
                CREATE TABLE run_info (key TEXT, value TEXT);
                CREATE TABLE completed_slices (playlist_count INTEGER);
                CREATE TABLE catalogue (track_index INTEGER PRIMARY KEY, spotify_id TEXT UNIQUE);
                CREATE TABLE playlists (pid INTEGER PRIMARY KEY, track_count INTEGER, track_indices BLOB);
                INSERT INTO completed_slices VALUES (3);
            ''')
            connection.execute('INSERT INTO run_info VALUES (?, ?)', ('identity', json.dumps({
                'version': 'mpd-staging-v1', 'archive_signature': 'test', 'has_all_expected_slices': False,
            })))
            connection.executemany('INSERT INTO catalogue VALUES (?, ?)', ((i, f'{i:022d}') for i in range(150)))
            connection.executemany('INSERT INTO playlists VALUES (?, ?, ?)', [
                (9, 4, members(self.base)), (1001, 4, members(self.base)),
                (2001, 5, members((*self.base, 140))),
            ])

    def run_build(self, mapping=None, maximum=None):
        return split.build(self.source, self.out, self.manifest, mapping, maximum, allow_partial=True)

    def assigned(self):
        with sqlite3.connect(self.out / 'split.sqlite3') as connection:
            return connection.execute('SELECT pid, split, recording_count FROM assigned_splits ORDER BY pid').fetchall()

    def test_resume_promotes_earlier_duplicate_when_pilot_arrives(self):
        first = self.run_build(maximum=1)
        self.assertEqual(first['assigned_playlists'], 1)
        self.assertNotEqual(self.assigned()[0][1], 'train')
        final = self.run_build()
        self.assertEqual(self.assigned()[:2], [(9, 'train', 4), (1001, 'train', 4)])
        self.assertEqual(final['pilot_and_exact_copies_in_train'], 2)
        self.assertEqual(final['pilot_playlists_outside_train'], 0)
        self.assertEqual(split.verify(self.out)['database_verification'], 'ok')

    def test_verified_aliases_merge_before_grouping(self):
        mapping = self.manifest.with_suffix('.csv')
        with mapping.open('w', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(('track_id', 'recording_id'))
            writer.writerows([(f'{0:022d}', 'same'), (f'{140:022d}', 'same')])
        result = self.run_build(mapping)
        self.assertEqual(result['spotify_ids_mapped_to_another_index'], 1)
        self.assertEqual(result['exact_playlist_groups'], 1)
        self.assertEqual(self.assigned(), [(9, 'train', 4), (1001, 'train', 4), (2001, 'train', 4)])
        with self.assertRaisesRegex(ValueError, 'different source'):
            self.run_build()


if __name__ == '__main__':
    unittest.main()
