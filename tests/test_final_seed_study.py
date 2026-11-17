"""Check fixed references, fresh cohorts and publication of measured results."""

from contextlib import nullcontext
import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from scripts.studio_seed_study import (BUDGETS, METHODS, fixed_query, measure,
    prior_final_groups, refresh_pages, select_budget, study_sample)
from scripts.seed_study import sample_hash


class FinalSeedStudyTests(unittest.TestCase):
    def test_more_seeds_never_shrink_the_hidden_reference(self):
        pool, references = fixed_query(42, range(30))
        reversed_pool, reversed_refs = fixed_query(42, reversed(range(30)))
        np.testing.assert_array_equal(pool, reversed_pool)
        self.assertEqual(references, reversed_refs)
        self.assertEqual(len(references), 10)
        for count in BUDGETS:
            self.assertFalse(set(pool[:count]) & references)
            self.assertFalse(set(pool[count:]) & references)
        self.assertEqual(set(pool) | references, set(range(30)))

    def test_sample_has_one_representative_per_fresh_group(self):
        rows = [(1, '', b'', 30, b'old'), (2, '', b'', 20, b'short'),
                (3, '', b'', 25, b'a'), (4, '', b'', 25, b'a'), (5, '', b'', 30, b'b')]
        data = SimpleNamespace(rows=lambda *args: rows)
        selected = study_sample(data, 'test', {b'old'}, 100)
        self.assertEqual({row[-1] for row in selected}, {b'a', b'b'})
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected, study_sample(data, 'test', {b'old'}, 100))

    def test_previous_final_cohort_must_match_its_fingerprint(self):
        rows = [(1, '', b'', 25, b'a'), (2, '', b'', 30, b'b')]
        report = {'freeze': {'split': 'split', 'seeds': 5, 'queries': 2,
                             'query_sha256': sample_hash([1, 2])}}
        data = SimpleNamespace(identity='split')
        with patch('scripts.studio_seed_study.sample_rows', return_value=rows), \
             patch('scripts.studio_seed_study.exclusions', return_value=(set(), {})):
            self.assertEqual(prior_final_groups(data, Path('.'), report, set()), {b'a', b'b'})
            report['freeze']['query_sha256'] = 'different'
            with self.assertRaisesRegex(ValueError, 'Cannot verify'):
                prior_final_groups(data, Path('.'), report, set())

    def test_seed_budget_uses_the_first_validation_count_reaching_95_percent(self):
        curve = [.1, .3, .5, .95, .97, 1.]
        validation = {'budgets': {str(n): {'cutoffs': {'20': {'unified': {'ndcg': value}}}}
                                  for n, value in zip(BUDGETS, curve)}}
        self.assertEqual(select_budget(validation), 5)

    def measured_fixture(self, output):
        pid = 7
        _, references = fixed_query(pid, range(30))
        targets = sorted(references)
        rows = [(pid, 'Gym', b'', 30, b'group')]
        data = SimpleNamespace(recordings=lambda *args: range(30))
        ranker = SimpleNamespace(counts=np.ones(100), popular=np.arange(100))
        demo = SimpleNamespace(ranker=ranker, catalogue=lambda **kwargs: nullcontext(None))

        def final_rankings(demo, seeds, title, db):
            plain = np.array(targets[:2])
            final = np.array([90, 91]) if len(seeds) < 3 else plain
            rankings = {method: plain for method in METHODS}
            rankings['unified'] = final
            return rankings, ['gym'], '', plain, len(seeds) >= 2

        with patch('scripts.studio_seed_study.query_rankings', side_effect=final_rankings) as infer:
            report = measure(data, demo, rows, np.arange(100) % 3, 'test', output)
            self.assertEqual(infer.call_count, len(BUDGETS))
        return report, data, demo, rows

    def test_all_seed_counts_use_final_inference_and_resume_measured_checkpoints(self):
        with TemporaryDirectory() as directory:
            output = Path(directory)
            report, data, demo, rows = self.measured_fixture(output)
            self.assertEqual(report['budgets']['1']['cutoffs']['20']['unified']['recall'], 0)
            self.assertEqual(report['budgets']['3']['cutoffs']['20']['unified']['recall'], .2)
            self.assertEqual(report['budgets']['3']['cutoffs']['20']['unified']['precision'], .1)
            self.assertGreater(report['budgets']['3']['marginal_seed_gain']['ndcg_delta'], 0)
            self.assertEqual(report['budgets']['20']['cutoffs']['1']['unified']['precision'], 1)
            with patch('scripts.studio_seed_study.query_rankings', side_effect=AssertionError('Must use checkpoint')):
                repeated = measure(data, demo, rows, np.arange(100) % 3, 'test', output)
            self.assertEqual(report, repeated)

    def test_static_publication_updates_answers_without_relabeling_the_old_study(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            measured, *_ = self.measured_fixture(root)
            report = {'chosen_seed_budget': 3, 'seed_budgets': list(BUDGETS), 'test': measured}
            docs = root / 'docs'
            docs.mkdir()
            source = Path(__file__).resolve().parents[1] / 'docs'
            for name in ('research.html', 'research-deep-dive.html'):
                (docs / name).write_text((source / name).read_text())
            refresh_pages(report, docs)
            first = (docs / 'research-deep-dive.html').read_text()
            refresh_pages(report, docs)
            self.assertEqual(first, (docs / 'research-deep-dive.html').read_text())
            self.assertIn('Validation selected 3 seeds', first)
            self.assertIn('Measured at six seed counts', first)
            self.assertIn('Earlier title model: seed-count study', first)
            self.assertIn('id="seed-curve"', first)
            self.assertNotIn('Awaiting the new run', first)
            self.assertIn('Validation selected 3 seeds', (docs / 'research.html').read_text())


if __name__ == '__main__':
    unittest.main()
