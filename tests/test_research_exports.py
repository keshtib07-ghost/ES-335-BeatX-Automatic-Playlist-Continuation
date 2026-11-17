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
    def test_summary_scores_match_published_benchmark(self):
        class Scores(HTMLParser):
            active = False

            def __init__(self):
                super().__init__()
                self.values = []
                self.in_value = False

            def handle_starttag(self, tag, attrs):
                if tag == 'table' and dict(attrs).get('id') == 'summary-benchmark':
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
        parser.feed((ROOT / 'docs/research.html').read_text(encoding='utf-8'))
        benchmark = read_public_script(ROOT / 'docs/experiment.js', 'NEXT_TRACK_EXPERIMENT')
        expected = [f'{benchmark["all_queries"][method][metric]:.5f}'
                    for method in ('popularity', 'collaborative_filtering', 'selected_tag_ranker')
                    for metric in ('ndcg_at_20', 'recall_at_20')]
        self.assertEqual(parser.values, expected)

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
