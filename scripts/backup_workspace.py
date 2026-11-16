"""Create and verify private archives of an existing trained workspace.

Standalone standard-library utility. It never uploads or modifies source files.
"""

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
from datetime import datetime, timezone
from pathlib import Path


SKIP_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
             '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache'}
SECRET_NAMES = {'.env', 'credentials.json', 'token.json', 'tokens.json', 'secrets.json'}
ASSET_LIMIT = 2 * 1024**3


def excluded(path):
    name = path.name.lower()
    return (name in SECRET_NAMES or name.startswith('.env.') or name.startswith('client_secret')
            or path.suffix.lower() in {'.pem', '.key', '.p12', '.pfx'})


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(block)
    return value.hexdigest()


def fingerprint(path):
    value = path.lstat()
    if not stat.S_ISREG(value.st_mode):
        raise ValueError(f'Not a regular file: {path.name}')
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)


def collect(root):
    groups = {'runs': [], 'inputs': [], 'source': []}
    skipped = []
    def fail(error):
        raise error

    for folder, directories, names in os.walk(root, followlinks=False, onerror=fail):
        directory = Path(folder)
        keep = []
        for name in sorted(directories):
            path = directory / name
            if name in SKIP_DIRS or path.is_symlink():
                skipped.append(path.relative_to(root).as_posix() + '/')
            else:
                keep.append(name)
        directories[:] = keep
        for name in sorted(names):
            path = directory / name
            relative = path.relative_to(root)
            if path.is_symlink() or excluded(path):
                skipped.append(relative.as_posix())
                continue
            mark = fingerprint(path)
            if (name.endswith(('-wal', '-journal')) and mark[2] > 0
                    and name.rsplit('-', 1)[0].endswith(('.sqlite', '.sqlite3', '.db'))):
                raise ValueError(f'Close database-writing jobs before backup: {relative.as_posix()}')
            group = 'runs' if relative.parts[0] == 'runs' else 'inputs' if relative.parts[0] == 'private-data' else 'source'
            groups[group].append((relative.as_posix(), mark))
    return groups, skipped


class HashingReader:
    def __init__(self, stream):
        self.stream = stream
        self.hash = hashlib.sha256()

    def read(self, count=-1):
        block = self.stream.read(count)
        self.hash.update(block)
        return block


def archive_group(root, target, entries):
    records = []
    with target.open('xb') as raw, tarfile.open(fileobj=raw, mode='w:gz', compresslevel=1) as archive:
        for relative, mark in entries:
            source = root / relative
            if fingerprint(source) != mark:
                raise ValueError(f'File changed before backup: {relative}')
            with source.open('rb') as stream:
                opened = os.fstat(stream.fileno())
                if (opened.st_dev, opened.st_ino) != mark[:2]:
                    raise ValueError(f'File replaced before backup: {relative}')
                reader = HashingReader(stream)
                info = tarfile.TarInfo(relative)
                info.size = mark[2]
                info.mode = stat.S_IMODE(opened.st_mode)
                info.mtime = int(opened.st_mtime)
                archive.addfile(info, reader)
            if fingerprint(source) != mark:
                raise ValueError(f'File changed while backing up: {relative}')
            records.append({'path': relative, 'bytes': mark[2], 'sha256': reader.hash.hexdigest()})
    if target.stat().st_size >= ASSET_LIMIT:
        raise ValueError(f'{target.name} exceeds the release asset limit; keep this local backup and request a split transfer.')
    return {'name': target.name, 'bytes': target.stat().st_size, 'sha256': digest(target), 'files': records}


def verify_archive(directory, record):
    name = record['name']
    if Path(name).name != name:
        raise ValueError('Invalid archive name in manifest')
    path = directory / name
    if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
        raise ValueError(f'Archive checksum mismatch: {name}')
    expected = {item['path']: item for item in record['files']}
    if len(expected) != len(record['files']):
        raise ValueError('Duplicate manifest paths')
    seen = set()
    with tarfile.open(path, mode='r|gz') as archive:
        for member in archive:
            relative = Path(member.name)
            if (not member.isfile() or relative.is_absolute() or '..' in relative.parts
                    or member.name in seen or member.name not in expected):
                raise ValueError(f'Unexpected archive member: {member.name}')
            row = expected[member.name]
            value = hashlib.sha256()
            with archive.extractfile(member) as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b''):
                    value.update(block)
            if member.size != row['bytes'] or value.hexdigest() != row['sha256']:
                raise ValueError(f'File checksum mismatch: {member.name}')
            seen.add(member.name)
    if seen != set(expected):
        raise ValueError('Archive has missing files')


def verify(directory):
    manifest = json.loads((directory / 'manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema') != 'beatx-private-backup-v1':
        raise ValueError('Unsupported backup manifest')
    for record in manifest['archives']:
        verify_archive(directory, record)
    return manifest


def source_commit(root):
    try:
        result = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=root,
                                check=True, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return None


def create(root, output):
    root, output = root.resolve(), output.resolve()
    if not root.is_dir() or output.is_relative_to(root):
        raise ValueError('Use an existing source folder and an output directory outside it.')
    if output.exists():
        raise ValueError('The output directory already exists. Choose a new directory.')
    groups, skipped = collect(root)
    entries = [item for group in groups.values() for item in group]
    total = sum(mark[2] for _, mark in entries)
    parent = output.parent
    parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(parent).free < total * 1.05 + 64 * 1024**2:
        raise ValueError('Insufficient free disk space for a conservative backup estimate.')
    output.mkdir()
    manifest = {'schema': 'beatx-private-backup-v1', 'created_utc': datetime.now(timezone.utc).isoformat(),
                'source_commit': source_commit(root), 'source_files': len(entries), 'source_bytes': total,
                'private': True, 'skipped': skipped, 'archives': []}
    for group, items in groups.items():
        if not items:
            continue
        print(f'Archiving {group}: {len(items)} files', flush=True)
        record = archive_group(root, output / f'beatx-{group}.tar.gz', items)
        verify_archive(output, record)
        manifest['archives'].append(record)
    # Check that the archived set remained stable across the entire operation.
    current, current_skipped = collect(root)
    if current != groups or current_skipped != skipped:
        raise ValueError('Source files changed during backup. Keep this incomplete copy and rerun in a new output directory after jobs finish.')
    with (output / 'manifest.json').open('x', encoding='utf-8') as stream:
        json.dump(manifest, stream, indent=2)
        stream.write('\n')
    return manifest


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    commands = cli.add_subparsers(dest='command', required=True)
    make = commands.add_parser('create')
    make.add_argument('--root', type=Path, required=True)
    make.add_argument('--output', type=Path, required=True)
    check = commands.add_parser('verify')
    check.add_argument('--backup', type=Path, required=True)
    args = cli.parse_args()
    try:
        result = create(args.root, args.output) if args.command == 'create' else verify(args.backup)
    except (OSError, ValueError, EOFError, tarfile.TarError) as error:
        cli.exit(1, f'Backup failed: {error}\nNo source files were changed. An output without manifest.json is incomplete.\n')
    print(f'Verified {result["source_files"]} archived files.', flush=True)
    for record in result['archives']:
        print(f'{record["name"]}: {record["bytes"] / 1024**2:.1f} MiB', flush=True)
    if args.command == 'create':
        print(f'Backup saved in {args.output.resolve()}', flush=True)
        print('Keep these archives private. Nothing has been uploaded.', flush=True)


if __name__ == '__main__':
    main()
