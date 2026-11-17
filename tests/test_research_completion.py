"""Check metric denominators, unseen references and the published audit scope."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest

from scripts.complete_research import METHODS, CUTOFFS, choose_path, metrics_at_k, public_report, sample_rows
from scripts.research_eda import histogram, pilot_eda


class CompletionTests(unittest.TestCase):
    def test_cutoffs_keep_unseen_references_and_penalize_empty_slots(self):
        refs = {1, 2, 99}
        self.assertEqual(metrics_at_k([1, 8, 2], refs, 1), [1 / 3, 1., 1., 1.])
        score = metrics_at_k([1, 8, 2], refs, 20)
        self.assertEqual(score[0], 2 / 3)
        self.assertEqual(score[2], 2 / 20)
        self.assertEqual(metrics_at_k([], refs, 20), [0, 0, 0, 0])
        with self.assertRaises(ValueError):
            metrics_at_k([1, 1], refs, 20)

    def test_sample_is_grouped_and_excludes_ineligible_playlists(self):
        rows = [(0, '', b'', 10, b'old'), (1, '', b'', 5, b'short'),
                (2, '', b'', 12, b'a'), (3, '', b'', 12, b'a'), (4, '', b'', 8, b'b')]
        data = SimpleNamespace(rows=lambda *args: rows)
        selected = sample_rows(data, {b'old'}, 5, 100)
        self.assertEqual({row[-1] for row in selected}, {b'a', b'b'})
        self.assertEqual(len(selected), 2)
        self.assertEqual(selected, sample_rows(data, {b'old'}, 5, 100))

    def test_public_report_uses_query_means_without_publishing_identifiers(self):
        records = []
        for pid, refs in ((12345, {1}), (67890, {1, 2, 3, 4})):
            scores = {method: {str(k): metrics_at_k([1], refs, k) for k in CUTOFFS} for method in METHODS}
            records.append({'pid': pid, 'group': str(pid), 'scores': scores,
                'known_seeds': 5, 'context': [], 'reference_count': len(refs), 'unseen_references': 0,
                'candidate_recall': 1 / len(refs), 'result_count': 1, 'note': '',
                'hit_ranks': {method: [1] for method in METHODS}})
        report = public_report(records, {'seeds': 5})
        self.assertEqual(report['cohorts']['all_queries']['cutoffs']['20']['cf']['recall'], .625)
        self.assertNotIn('12345', json.dumps(report))
        self.assertEqual(report['unified_failures']['short_outputs'], 2)

    def test_full_title_artifacts_take_priority(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'model').mkdir()
            (root / 'model-full-titles').mkdir()
            self.assertEqual(choose_path(root, ('model-full-titles', 'model')).name, 'model-full-titles')

    def test_histogram_does_not_drop_boundary_values(self):
        result = histogram([0, 1, 9, 10, 20, 999], (0, 10, 20))
        self.assertEqual(result['counts'], [3, 1, 2])
        self.assertEqual(sum(result['counts']), result['total'])

    def test_eda_deduplicates_membership_and_verifies_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'slice.json'
            source.write_text(json.dumps({'playlists': [{'name': 'study', 'tracks': [
                {'track_uri': 'spotify:track:' + 'a' * 22},
                {'track_uri': 'spotify:track:' + 'a' * 22},
                {'track_uri': 'spotify:track:' + 'b' * 22}]}]}))
            payload = source.read_bytes()
            blob = hashlib.sha1(f'blob {len(payload)}\0'.encode() + payload).hexdigest()
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({'repository': 'fixture', 'commit': 'fixed',
                'slices': [{'filename': source.name, 'git_blob_sha1': blob}]}))
            result = pilot_eda(root, manifest)
            self.assertEqual(result['all_playlists']['memberships'], 2)
            self.assertEqual(result['repeat_occurrences_removed'], 1)
            source.write_text('{}')
            with self.assertRaisesRegex(ValueError, 'Unverified'):
                pilot_eda(root, manifest)


if __name__ == '__main__':
    unittest.main()
