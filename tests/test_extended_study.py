import tempfile
import unittest
from pathlib import Path

import numpy as np

from scripts.seed_study import BUDGETS, fixed_query, fresh_sample
from scripts.serve_million_demo import spotify_reference
from playlist_model.sequence import Transitions, adjacency_recall, edge_key


class ExtendedStudyTests(unittest.TestCase):
    def test_seed_budgets_share_one_reference_set(self):
        items = np.arange(25)
        pool, reference = fixed_query(1029, items)
        repeated, _ = fixed_query(1029, items[::-1])
        np.testing.assert_array_equal(pool, repeated)
        self.assertEqual(len(reference), 5)
        for n in BUDGETS:
            self.assertFalse(set(pool[:n]).intersection(reference))
        self.assertEqual(set(pool).union(reference), set(items))

    def test_sampling_excludes_prior_groups_and_short_lists(self):
        class Fixture:
            def rows(self, *_):
                return [(1, '', b'', 21, b'old'), (2, '', b'', 20, b'new'), (3, '', b'', 22, b'newer')]

        result = fresh_sample(Fixture(), 'test', {b'old'}, 5)
        self.assertEqual([row[0] for row in result], [3])

    def test_playback_keeps_the_set_and_uses_directed_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            np.array([edge_key(0, 2), edge_key(2, 1)], dtype='<u8').tofile(path / 'pairs.u64')
            np.array([12, 14], dtype='<u4').tofile(path / 'support.u32')
            model = Transitions(path, np.full(4, 25))
            order, observed = model.order([1, 2, 3], anchor=0)
            self.assertEqual(order, [2, 1, 3])
            self.assertEqual(observed, 2)
            self.assertEqual(adjacency_recall([0, 2, 1, 3], [0, *order]), 1.)
            self.assertEqual(model.strength(2, [0])[0], 0.)

    def test_exact_spotify_link_lookup(self):
        identifier = '7fnqltLx83HsYLQajzCYRk'
        self.assertEqual(spotify_reference(f'https://open.spotify.com/track/{identifier}?si=example'), identifier)
        self.assertEqual(spotify_reference(f'spotify:track:{identifier}'), identifier)
        self.assertIsNone(spotify_reference(f'https://example.com/track/{identifier}'))


if __name__ == '__main__':
    unittest.main()
