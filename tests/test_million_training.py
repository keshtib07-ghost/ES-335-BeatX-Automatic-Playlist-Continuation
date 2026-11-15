import sqlite3
import struct
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from playlist_model.million import DiskRanker, build_index, make_seeds, rank_candidates
from playlist_model.ranker import PlaylistRanker


class DiskTrainingTests(unittest.TestCase):
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
