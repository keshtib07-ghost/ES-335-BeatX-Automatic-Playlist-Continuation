"""Exercise context agreement and no-seed paths in the unified studio."""

import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from playlist_model.profile_ranker import ProfileRanker, reconcile_context
from playlist_model.profile_tags import CONTEXT_TAGS


class UnifiedRecommendationTests(unittest.TestCase):
    def test_agree_within_category_and_combine_categories(self):
        groups, conflicts = reconcile_context(set(), {'happy', 'chill', 'rainy'}, {'chill', 'drive'})
        self.assertEqual(groups, [{'chill'}, {'rainy'}, {'drive'}])
        self.assertEqual(conflicts, [])

    def test_explicit_tags_ignore_title_and_resolve_seed_conflicts(self):
        groups, conflicts = reconcile_context({'happy'}, {'sad', 'gym'}, {'chill', 'study_focus'})
        self.assertEqual(groups, [{'happy'}, {'study_focus'}])
        self.assertEqual(conflicts, [('selected filters', 'seeds')])

    def setUp(self):
        self.profile = ProfileRanker.__new__(ProfileRanker)
        self.profile.catalogue_profiles = None
        self.profile.expanded = True
        self.profile.tagger = None
        self.profile.metadata = lambda catalogue: {}
        self.profile.track_tags = lambda index, limit=4: ['study_focus'] if index == 0 else []
        tags = {1: {'study_focus'}, 2: {'gym'}, 3: {'gym', 'rainy'}, 4: {'rainy'}}
        self.profile.context_matrix = lambda pool, groups: np.array(
            [[2.0 if tags.get(index, set()) & group else 1.0 for group in groups] for index in pool]
        ).reshape((len(pool), len(groups)))
        self.ranker = SimpleNamespace(
            counts=np.array([5, 10, 8, 4, 2]),
            candidates=lambda seeds, k: (np.array([1, 2]), np.array([1.0, .2]), np.empty(0, dtype=int)),
            popularity=lambda exclude, limit: np.array([i for i in (1, 2, 3, 4) if i not in exclude][:limit], dtype=int),
        )

    def recommend(self, title_tags=(), seeds=(), filters=None, title='Test title'):
        prediction = [[tag in title_tags for tag in CONTEXT_TAGS]]
        with patch('playlist_model.profile_ranker.predicted_context', return_value=prediction):
            return self.profile.recommend(self.ranker, np.array(seeds, dtype=int), title,
                                          filters or {}, None)

    def test_title_wins_against_seed_tags_without_discarding_cooccurrence(self):
        result, tags, _, note = self.recommend(('gym',), (0,))
        self.assertEqual(result[:2].tolist(), [2, 3])
        self.assertEqual(tags, ['gym'])
        self.assertIn('conflicting seeds', note)

    def test_manual_tags_skip_title_prediction_and_decade_hints(self):
        with patch('playlist_model.profile_ranker.predicted_context') as predict:
            result, tags, _, _ = self.profile.recommend(
                self.ranker, np.array([], dtype=int), '90s Gym', {'tags': ['rainy']}, None)
        predict.assert_not_called()
        self.assertEqual(result.tolist(), [3, 4])
        self.assertEqual(tags, ['rainy'])

    def test_manual_tags_keep_seed_context_in_other_categories(self):
        _, tags, _, _ = self.recommend(('gym',), (0,), {'tags': ['rainy']})
        self.assertEqual(tags, ['rainy', 'study_focus'])

    def test_no_seeds_uses_title_when_no_tags_were_selected(self):
        result, tags, _, _ = self.recommend(('gym', 'rainy'))
        self.assertEqual(result[0], 3)
        self.assertEqual(tags, ['gym', 'rainy'])

    def test_no_seeds_or_tags_uses_training_popularity(self):
        result, _, _, note = self.recommend()
        self.assertEqual(result.tolist(), [1, 2, 3, 4])
        self.assertIn('training popularity', note)


if __name__ == '__main__':
    unittest.main()
