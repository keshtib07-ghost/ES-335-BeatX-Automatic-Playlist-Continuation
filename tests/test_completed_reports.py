"""Check the completed evidence and its public interpretation without inference."""

import copy
import csv
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from scripts.export_research_bundle import ROOT, build_exports
from scripts.review_research_results import check, refresh
import test_research_exports as export_tests


class CompletedReportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = ROOT / 'docs/data/research'
        cls.report = json.loads((directory / 'studio_evaluation.json').read_text())
        cls.eda = json.loads((directory / 'eda_full.json').read_text())

    def test_completed_reports_are_consistent(self):
        check(self.report, self.eda)

    def test_decreasing_prefix_recall_is_rejected(self):
        report = copy.deepcopy(self.report)
        report['cohorts']['all_queries']['cutoffs']['20']['unified']['recall'] = 0
        with self.assertRaisesRegex(ValueError, 'recall falls'):
            check(report, self.eda)

    def test_distribution_count_mismatch_is_rejected(self):
        eda = copy.deepcopy(self.eda)
        eda['partitions']['train']['playlist_length']['counts'][0] += 1
        with self.assertRaisesRegex(ValueError, 'distribution'):
            check(self.report, eda)

    def test_static_studio_scores_match_the_saved_report(self):
        parser = export_tests.ResearchExportTests()
        metrics = ('ndcg', 'recall', 'precision', 'hit_rate')
        values = self.report['cohorts']['all_queries']['cutoffs']['20']
        for filename, table_id, methods, extra in (
            ('research.html', 'summary-studio', ('popularity', 'cf', 'unified', 'unified_seed_bpm'), ()),
            ('research-deep-dive.html', 'studio-static-scores', self.report['methods'], ('artist_diversity',)),
        ):
            expected = [f'{values[method][metric]:.5f}' for method in methods for metric in (*metrics, *extra)]
            self.assertEqual(parser.table_values(filename, table_id), expected)

    def test_every_studio_csv_value_matches_its_source(self):
        rows = list(csv.DictReader(io.StringIO(build_exports(ROOT / 'docs')['studio_scores.csv'])))
        self.assertEqual(len(rows), 5 * 20 * 6 * 6)
        for row in rows:
            expected = self.report['cohorts'][row['cohort']]['cutoffs'][row['k']][row['method']][row['metric']]
            self.assertEqual(float(row['value']), expected)

    def test_refresh_keeps_current_scores_visible_and_is_repeatable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'docs/data/research').mkdir(parents=True)
            for filename, report in (('studio_evaluation.json', self.report), ('eda_full.json', self.eda)):
                (root / 'docs/data/research' / filename).write_text(json.dumps(report))
            for name in ('research.html', 'research-deep-dive.html'):
                (root / 'docs' / name).write_text((ROOT / 'docs' / name).read_text())
            refresh(root)
            first = (root / 'docs/research.html').read_text()
            refresh(root)
            self.assertEqual(first, (root / 'docs/research.html').read_text())

            class Visibility(HTMLParser):
                depth = 0
                score_depth = None

                def handle_starttag(self, tag, attrs):
                    if tag == 'details':
                        self.depth += 1
                    if dict(attrs).get('id') == 'summary-studio-results':
                        self.score_depth = self.depth

                def handle_endtag(self, tag):
                    if tag == 'details':
                        self.depth -= 1
            parser = Visibility()
            parser.feed(first)
            self.assertEqual(parser.score_depth, 0)


if __name__ == '__main__':
    unittest.main()
