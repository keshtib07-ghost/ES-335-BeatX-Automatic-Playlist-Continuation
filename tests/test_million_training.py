import json
import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import joblib
import numpy as np

from playlist_model.million import Dataset, DiskRanker, build_index, fit_tags, make_seeds, rank_candidates
from playlist_model.ranker import PlaylistRanker


class DiskTrainingTests(unittest.TestCase):
    def test_title_fit_defaults_to_every_training_title(self):
        titles = ('study music playlist', 'study mix playlist', 'gym music playlist', 'gym mix playlist',
                  'validationonly music', 'validationonly mix', 'testonly music', 'testonly mix')
        partitions = ('train',) * 4 + ('validation',) * 2 + ('test',) * 2
        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(':memory:') as connection:
            connection.executescript('''
                ATTACH DATABASE ':memory:' AS splits;
                CREATE TABLE run_info (key TEXT, value TEXT);
                CREATE TABLE playlists (pid INTEGER, title TEXT, track_indices BLOB);
                CREATE TABLE splits.split_info (key TEXT, value TEXT);
                CREATE TABLE splits.assigned_splits (pid INTEGER, split TEXT, recording_count INTEGER, group_hash BLOB);
                CREATE TABLE splits.recording_aliases (track_index INTEGER, recording_index INTEGER);
                CREATE TABLE splits.playlist_assignments (group_hash BLOB);
                CREATE TABLE splits.playlist_groups (group_hash BLOB, split TEXT);
            ''')
            connection.execute("INSERT INTO run_info VALUES ('identity', ?)", (json.dumps({
                'version': 'mpd-staging-v1', 'archive_signature': 'fixture',
            }),))
            connection.execute("INSERT INTO splits.split_info VALUES ('identity', ?)", (json.dumps({
                'version': 'mpd-grouped-split-v1', 'archive_signature': 'fixture',
                'source_playlists': len(titles), 'source_track_indices': 1,
            }),))
            connection.executemany('INSERT INTO playlists VALUES (?, ?, ?)',
                                   ((i, title, struct.pack('<i', 0)) for i, title in enumerate(titles)))
            connection.executemany('INSERT INTO splits.assigned_splits VALUES (?, ?, 1, ?)',
                                   ((i, partition, bytes([i])) for i, partition in enumerate(partitions)))
            data = Dataset(connection, allow_partial=True)
            run = Path(temp) / 'full'
            result = fit_tags(data, run)
            self.assertEqual(result['classifier_training_titles'], 4)
            self.assertEqual(result['train_playlists_scored_for_song_tags'], 4)
            self.assertEqual(result['validation_rule_agreement']['titles'], 2)
            tagger = joblib.load(run / 'tags/title_tagger.joblib')
            vocabulary = dict(tagger.features.transformer_list)['words'].vocabulary_
            self.assertIn('study', vocabulary)
            self.assertIn('gym', vocabulary)
            self.assertNotIn('validationonly', vocabulary)
            self.assertNotIn('testonly', vocabulary)
            self.assertEqual(fit_tags(data, run, 4), result)
            capped = fit_tags(data, Path(temp) / 'sample', 2)
            self.assertEqual(capped['classifier_training_titles'], 2)
            self.assertEqual(capped['train_playlists_scored_for_song_tags'], 4)

    def test_disk_index_matches_pilot_ranking(self):
        rows = [(0, 1, 2, 3), (0, 2, 4, 5), (0, 1, 2, 4), (1, 3, 4, 6), (2, 4, 5, 6)]
        with tempfile.TemporaryDirectory() as temp, sqlite3.connect(':memory:') as connection:
            connection.executescript('''
                ATTACH DATABASE ':memory:' AS splits;
                CREATE TABLE splits.assigned_splits (recording_count INTEGER, split TEXT);
            ''')
            connection.executemany('INSERT INTO splits.assigned_splits VALUES (?, ?)', [(4, 'train')] * len(rows))
            data = SimpleNamespace(identity={'pilot': True}, track_count=8, connection=connection,
                                   rows=lambda *_: ((i, struct.pack('<4i', *row), len(row)) for i, row in enumerate(rows)),
                                   recordings=lambda payload, _: np.frombuffer(payload, dtype='<i4'))
            path = Path(temp)
            first = build_index(data, path)
            self.assertEqual(first, build_index(data, path))
            self.assertEqual(first['training_memberships'], 20)
            disk = DiskRanker(path / 'index')
            pilot = PlaylistRanker(8, [SimpleNamespace(tracks=row) for row in rows])
            for seed in ([0, 1, 2], [3, 5, 7]):
                a, b, fallback = disk.candidates(seed, k=4)
                candidates, scores = pilot.candidates(seed, k=4)
                expected = pilot.recommend_from(candidates, scores, k=4)
                np.testing.assert_array_equal(expected, rank_candidates(a, b, fallback, np.zeros(len(b)), 0., k=4))
            DiskRanker.neighbours.cache_clear()

    def test_seed_selection_excludes_references(self):
        items = np.arange(10, dtype=np.int32)
        seeds, targets = make_seeds(453, items)
        repeat, _ = make_seeds(453, items[::-1])
        np.testing.assert_array_equal(repeat, seeds)
        self.assertEqual(len(seeds), 3)
        self.assertFalse(targets.intersection(seeds))
        self.assertEqual(targets.union(seeds), set(items))


if __name__ == '__main__':
    unittest.main()
