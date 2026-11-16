import unittest

import numpy as np

from scripts.tag_coverage_study import score_neighbours, precision
from playlist_model.profile_tags import weak_context


class TagCoverageStudyTests(unittest.TestCase):
    def test_expanded_playlist_cues_have_an_independent_revision(self):
        samples = [('Roadtrip 🚗', 'drive'), ('Crossfit', 'gym'), ('Just Chillin’', 'chill'),
                   ('Romantica', 'romantic'), ('Sleepytime', 'sleep')]
        for title, label in samples:
            self.assertNotIn(label, weak_context(title))
            self.assertIn(label, weak_context(title, expanded=True))
        for ambiguous in ('Highway', 'Chillin’ Like a Villain', 'No roadtrip'):
            self.assertFalse(weak_context(ambiguous, expanded=True))

    def test_graph_suppresses_single_artist_and_single_anchor(self):
        ids = np.arange(4)
        weights = np.array([.4, .3, .2, .1])
        anchor = np.array([[1, 1], [1, 0], [1, 0], [0, 0]], dtype=bool)
        scores, count, artist_count, examples = score_neighbours(ids, weights, anchor, np.array([0, 0, 1, 4]))
        np.testing.assert_allclose(scores, [.9, 0.])
        np.testing.assert_array_equal(count, [3, 1])
        self.assertEqual(artist_count, [2, 1])
        np.testing.assert_array_equal(examples[0], [0, 1, 2])
        no_diversity, *_ = score_neighbours(ids, weights, anchor, np.zeros(4, dtype=int))
        np.testing.assert_array_equal(no_diversity, [0., 0.])

    def test_review_uncertainty_is_counted_separately(self):
        from collections import Counter
        result = precision(Counter(yes=3, no=1, unsure=2))
        self.assertEqual(result['acceptance'], .75)
        self.assertEqual(result['unsure'], 2)
        lower, upper = result['wilson_95_interval']
        self.assertLess(lower, .75)
        self.assertGreater(upper, .75)


if __name__ == '__main__':
    unittest.main()
