"""Check scientific download fidelity, not presentation markup."""
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts.export_research_bundle import ROOT, build_exports, export, read_public_script


class ResearchExportTests(unittest.TestCase):
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
