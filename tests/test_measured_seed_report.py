"""Verify every published final-seed value against the uploaded aggregate."""

import copy
import csv
import io
import json
import hashlib
from pathlib import Path
import unittest

from scripts.export_research_bundle import ROOT, build_exports, read_public_script
from scripts.studio_seed_study import check_report
import test_research_exports as export_tests


class MeasuredSeedReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / 'docs/data/research'
        cls.report = json.loads((directory / 'studio_seed_study.json').read_text())
        cls.previous_bytes = (directory / 'studio_evaluation.json').read_bytes()
        cls.previous = json.loads(cls.previous_bytes)

    def test_same_trained_artifacts_and_inference_code_as_five_seed_test(self):
        check_report(self.report, self.previous, self.previous_bytes)

    def test_rejects_changed_artifacts_and_test_selected_budget(self):
        report = copy.deepcopy(self.report)
        report['freeze']['artifacts_sha256']['model/tags/title_tagger.joblib'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'artifact changed'):
            check_report(report, self.previous)
        report = copy.deepcopy(self.report)
        report['chosen_seed_budget'] = 5
        with self.assertRaisesRegex(ValueError, 'validation-only'):
            check_report(report)

    def test_rejects_inconsistent_gains_prefixes_and_failure_counts(self):
        for change, message in (
            (lambda r: r['test']['budgets']['20']['marginal_seed_gain'].update(ndcg_delta=99), 'Marginal'),
            (lambda r: r['test']['budgets']['20']['cutoffs']['20']['unified'].update(recall=0), 'recall falls'),
            (lambda r: r['test']['budgets']['20'].update(zero_hit_queries=0), 'zero-hit'),
        ):
            report = copy.deepcopy(self.report)
            change(report)
            with self.assertRaisesRegex(ValueError, message):
                check_report(report)

    def test_all_8640_csv_metric_cells_are_identical_to_the_source(self):
        outputs = build_exports(ROOT / 'docs')
        rows = list(csv.DictReader(io.StringIO(outputs['studio_seed_scores.csv'])))
        self.assertEqual(len(rows), 2 * 6 * 20 * 6 * 6)
        for row in rows:
            expected = self.report[row['partition']]['budgets'][row['seeds']]['cutoffs'][row['k']][row['method']][row['metric']]
            self.assertEqual(float(row['value']), expected)
        differences = list(csv.DictReader(io.StringIO(outputs['studio_seed_differences.csv'])))
        self.assertEqual(len(differences), 22)
        for row in differences:
            budget = self.report[row['partition']]['budgets'][row['to_seeds']]
            if row['comparison'] == 'final_minus_cf':
                expected = budget['cutoffs']['20']['unified']['ndcg'] - budget['cutoffs']['20']['cf']['ndcg']
                interval = budget['paired_final_minus_cf_ndcg_at_20_95_ci']
            else:
                expected = budget['marginal_seed_gain']['ndcg_delta']
                interval = budget['marginal_seed_gain']['paired_ndcg_95_ci']
            self.assertEqual(float(row['ndcg_delta_at_20']), expected)
            self.assertEqual([float(row['paired_ci_low']), float(row['paired_ci_high'])], interval)

    def test_browser_bundle_and_raw_report_are_identical(self):
        additions = read_public_script(ROOT / 'docs/research_extra_data.js', 'BEATX_RESEARCH_ADDITIONS')
        self.assertEqual(additions['studio_seed_study'], self.report)

    def test_research_pages_load_the_current_data_bundle(self):
        version = hashlib.sha256((ROOT / 'docs/research_extra_data.js').read_bytes()).hexdigest()[:12]
        for name in ('research.html', 'research-deep-dive.html'):
            self.assertIn(f'src="research_extra_data.js?v={version}"', (ROOT / 'docs' / name).read_text())

    def test_static_score_tables_match_the_measured_report(self):
        parser = export_tests.ResearchExportTests()
        expected = []
        for n in self.report['seed_budgets']:
            budget = self.report['test']['budgets'][str(n)]
            scores = budget['cutoffs']['20']
            expected += [f'{scores["unified"]["ndcg"]:.5f}', f'{scores["unified"]["recall"]:.5f}',
                         f'{scores["cf"]["ndcg"]:.5f}',
                         '[' + ', '.join(f'{v:+.5f}' for v in budget['paired_final_minus_cf_ndcg_at_20_95_ci']) + ']']
        self.assertEqual(parser.table_values('research-deep-dive.html', 'final-seed-static-scores'), expected)
        summary = []
        for n in self.report['seed_budgets']:
            scores = self.report['test']['budgets'][str(n)]['cutoffs']['20']['unified']
            summary += [f'{scores["ndcg"]:.5f}', f'{scores["recall"]:.5f}', f'{100 * scores["hit_rate"]:.1f}%']
        self.assertEqual(parser.table_values('research.html', 'summary-final-seed-scores'), summary)


if __name__ == '__main__':
    unittest.main()
