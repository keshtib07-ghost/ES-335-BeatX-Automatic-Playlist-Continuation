"""Check scientific download fidelity, not presentation markup."""
import csv
import io
import json
from html.parser import HTMLParser
from pathlib import Path
import tempfile
import unittest

from scripts.export_research_bundle import ROOT, build_exports, export, read_public_script


class ResearchExportTests(unittest.TestCase):
    def table_values(self, filename, table_id):
        class Scores(HTMLParser):
            active = False

            def __init__(self):
                super().__init__()
                self.values = []
                self.in_value = False

            def handle_starttag(self, tag, attrs):
                if tag == 'table' and dict(attrs).get('id') == table_id:
                    self.active = True
                if self.active and tag == 'td':
                    self.in_value = True

            def handle_endtag(self, tag):
                if tag == 'table':
                    self.active = False
                if tag == 'td':
                    self.in_value = False

            def handle_data(self, value):
                if self.active and self.in_value and value.strip():
                    self.values.append(value.strip())

        parser = Scores()
        parser.feed((ROOT / 'docs' / filename).read_text(encoding='utf-8'))
        return parser.values

    def test_summary_scores_match_published_benchmark(self):
        benchmark = read_public_script(ROOT / 'docs/experiment.js', 'NEXT_TRACK_EXPERIMENT')
        expected = [f'{benchmark["all_queries"][method][metric]:.5f}'
                    for method in ('popularity', 'collaborative_filtering', 'selected_tag_ranker')
                    for metric in ('ndcg_at_20', 'recall_at_20')]
        self.assertEqual(self.table_values('research.html', 'summary-benchmark'), expected)

    def test_weight_table_matches_frozen_validation_results(self):
        benchmark = read_public_script(ROOT / 'docs/experiment.js', 'NEXT_TRACK_EXPERIMENT')
        scores = benchmark['weight_validation']['scores']
        expected = [f'{float(row[cohort]):.6f}' for row in scores.values()
                    for cohort in ('all_queries', 'title_tagged_queries')]
        self.assertEqual(self.table_values('research-deep-dive.html', 'weight-validation'), expected)
        chosen_weight = max(scores, key=lambda weight: scores[weight]['title_tagged_queries'])
        self.assertEqual(float(chosen_weight), benchmark['selected_tag_weight'])

    def test_csv_values_are_identical_to_public_source(self):
        outputs = build_exports(ROOT / 'docs')
        bundle = json.loads(outputs['research_bundle.json'])
        rows = list(csv.DictReader(io.StringIO(outputs['seed_scores.csv'])))
        self.assertTrue(rows)
        for row in rows:
            expected = bundle['seed_study'][row['partition']]['budgets'][row['seeds']][row['cohort']][row['method']][row['metric']]
            self.assertEqual(float(row['value']), expected)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(outputs['benchmark.csv'])))), 24)
        self.assertEqual(len(list(csv.DictReader(io.StringIO(outputs['marginal_gains.csv'])))), 10)

    def test_deterministic_export_and_stale_check(self):
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory)
            export(ROOT / 'docs', destination)
            export(ROOT / 'docs', destination, check=True)
            (destination / 'benchmark.csv').write_text('tampered', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'benchmark.csv'):
                export(ROOT / 'docs', destination, check=True)

    def test_does_not_execute_javascript_or_accept_nonfinite_values(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'input.js'
            for text in ('window.EXAMPLE = {}; alert(1);', 'window.EXAMPLE = {"value": NaN};'):
                script.write_text(text, encoding='utf-8')
                with self.assertRaises(ValueError):
                    read_public_script(script, 'EXAMPLE')


if __name__ == '__main__':
    unittest.main()
