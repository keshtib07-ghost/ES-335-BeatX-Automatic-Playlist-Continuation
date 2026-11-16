import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import backup_workspace as backup


class WorkspaceBackupTests(unittest.TestCase):
    def fixture(self, parent):
        root = parent / 'old-project'
        root.mkdir()
        items = {
            'runs/million/model/index/playlist_indices.npy': b'trained-index',
            'runs/million/mpd.sqlite3': b'database-bytes',
            'private-data/features.csv': b'id,bpm\na,120\n',
            'export_song_batch.py': b'print("local script")\n',
            'songs_batch_01.csv': b'id,title\na,Local export\n',
        }
        for name, data in items.items():
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        return root, items

    def test_private_backup_verifies_all_groups_and_preserves_originals(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, items = self.fixture(parent)
            output = parent / 'backup'
            result = backup.create(root, output)
            self.assertEqual(backup.verify(output), result)
            self.assertEqual({row['name'] for row in result['archives']},
                             {'beatx-runs.tar.gz', 'beatx-inputs.tar.gz', 'beatx-source.tar.gz'})
            files = {row['path']: row for archive in result['archives'] for row in archive['files']}
            self.assertEqual(set(files), set(items))
            for name, value in items.items():
                self.assertEqual(files[name]['sha256'], hashlib.sha256(value).hexdigest())
                self.assertEqual((root / name).read_bytes(), value)

    def test_excludes_environment_credentials_and_external_symlinks(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, _ = self.fixture(parent)
            (root / '.env').write_text('CLIENT_SECRET=private', encoding='utf-8')
            (root / '.venv').mkdir()
            (root / '.venv/package.py').write_text('dependency', encoding='utf-8')
            (root / 'external').symlink_to(parent, target_is_directory=True)
            result = backup.create(root, parent / 'backup')
            skipped = set(result['skipped'])
            self.assertTrue({'.env', '.venv/', 'external/'}.issubset(skipped))
            self.assertNotIn('CLIENT_SECRET', json.dumps(result))

    def test_refuses_to_overwrite_or_write_inside_source(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, items = self.fixture(parent)
            with self.assertRaisesRegex(ValueError, 'outside'):
                backup.create(root, root / 'backup')
            existing = parent / 'existing'
            existing.mkdir()
            (existing / 'keep').write_text('preserve', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'already exists'):
                backup.create(root, existing)
            self.assertEqual((existing / 'keep').read_text(encoding='utf-8'), 'preserve')

    def test_corrupted_download_fails_checksum_verification(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, _ = self.fixture(parent)
            output = parent / 'backup'
            result = backup.create(root, output)
            archive = output / result['archives'][0]['name']
            data = bytearray(archive.read_bytes())
            data[-1] ^= 1
            archive.write_bytes(data)
            with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
                backup.verify(output)

    def test_active_sqlite_wal_prevents_inconsistent_backup(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, _ = self.fixture(parent)
            (root / 'runs/million/mpd.sqlite3-wal').write_bytes(b'pending database writes')
            with self.assertRaisesRegex(ValueError, 'database-writing jobs'):
                backup.create(root, parent / 'backup')
            self.assertFalse((parent / 'backup').exists())

    def test_files_changed_mid_backup_do_not_produce_a_complete_manifest(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, _ = self.fixture(parent)
            original = backup.archive_group

            def changing(source, target, entries):
                result = original(source, target, entries)
                (root / 'export_song_batch.py').write_bytes(b'changed during backup')
                return result

            with patch.object(backup, 'archive_group', side_effect=changing):
                with self.assertRaisesRegex(ValueError, 'changed'):
                    backup.create(root, parent / 'backup')
            self.assertFalse((parent / 'backup/manifest.json').exists())

    def test_oversized_asset_is_not_marked_complete(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp)
            root, _ = self.fixture(parent)
            with patch.object(backup, 'ASSET_LIMIT', 32):
                with self.assertRaisesRegex(ValueError, 'asset limit'):
                    backup.create(root, parent / 'backup')
            self.assertFalse((parent / 'backup/manifest.json').exists())


if __name__ == '__main__':
    unittest.main()
