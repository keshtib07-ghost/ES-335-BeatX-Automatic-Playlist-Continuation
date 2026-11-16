import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.local_inventory import git_state, inventory


class LocalInventoryTests(unittest.TestCase):
    def test_inventory_preserves_model_and_reports_its_size(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            model = root / 'runs/million/model/tags/title_tagger.joblib'
            model.parent.mkdir(parents=True)
            model.write_bytes(b'trained-model-bytes')
            secret = root / '.env'
            secret.write_text('CLIENT_SECRET=do-not-copy', encoding='utf-8')
            (root / 'scripts').mkdir()
            (root / 'scripts/local.py').write_text('print("local edit")', encoding='utf-8')
            with patch('scripts.local_inventory.git_state', return_value={'available': False, 'changes': []}):
                result = inventory(root)
            rows = {item['path']: item for item in result['files']}
            self.assertEqual(rows[model.relative_to(root).as_posix()]['bytes'], len(b'trained-model-bytes'))
            self.assertEqual(model.read_bytes(), b'trained-model-bytes')
            self.assertNotIn('.env', rows)
            self.assertNotIn('do-not-copy', json.dumps(result))
            self.assertFalse(result['file_contents_included'])
            self.assertTrue(result['read_only'])

    def test_ignores_environments_and_does_not_follow_links(self):
        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as external:
            root = Path(temp)
            (root / '.venv').mkdir()
            (root / '.venv/package.py').write_text('unused', encoding='utf-8')
            (Path(external) / 'outside.npy').write_bytes(b'outside')
            (root / 'external').symlink_to(external, target_is_directory=True)
            with patch('scripts.local_inventory.git_state', return_value={'available': False, 'changes': []}):
                result = inventory(root)
            self.assertEqual(result['total_files'], 0)
            self.assertEqual(result['skipped']['symlink_directories'], 1)

    def test_reports_partial_scan(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / 'one.py').write_text('one', encoding='utf-8')
            (root / 'two.py').write_text('two', encoding='utf-8')
            with patch('scripts.local_inventory.git_state', return_value={'available': False, 'changes': []}):
                result = inventory(root, max_files=1)
            self.assertTrue(result['truncated'])
            self.assertEqual(result['total_files'], 1)

    def test_git_rename_does_not_corrupt_next_status(self):
        completed = subprocess.CompletedProcess([], 0, stdout=b'R  new.py\0old.py\0?? other.py\0')
        with patch('scripts.local_inventory.subprocess.run', return_value=completed):
            result = git_state(Path('.'))
        self.assertEqual(result['changes'], [{'status': 'R ', 'path': 'new.py'},
                                             {'status': '??', 'path': 'other.py'}])

    def test_cli_refuses_to_overwrite_a_file(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            target = root / 'existing.json'
            target.write_text('keep this', encoding='utf-8')
            script = Path(__file__).resolve().parents[1] / 'scripts/local_inventory.py'
            result = subprocess.run([sys.executable, str(script), '--root', temp,
                                     '--output', str(target)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(target.read_text(encoding='utf-8'), 'keep this')


if __name__ == '__main__':
    unittest.main()
