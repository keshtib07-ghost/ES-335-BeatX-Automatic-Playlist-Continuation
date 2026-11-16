"""Read-only inventory of an existing BeatX workspace. Does not upload files."""

import argparse
import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


EXCLUDED_DIRS = {'.git', '.venv', 'venv', 'node_modules', '__pycache__',
                 '.pytest_cache', '.mypy_cache', '.ruff_cache', '.cache'}
MODEL_SUFFIXES = {'.joblib', '.pkl', '.pickle', '.npy', '.npz', '.u64', '.u32',
                  '.pt', '.pth', '.onnx', '.safetensors', '.bin'}
SOURCE_SUFFIXES = {'.py', '.js', '.cjs', '.mjs', '.html', '.css', '.md',
                   '.ipynb', '.toml', '.yaml', '.yml', '.sh'}
SECRET_NAMES = {'credentials.json', 'token.json', 'tokens.json', 'secrets.json'}


def sensitive(path):
    name = path.name.casefold()
    return (name == '.env' or name.startswith('.env.') or name in SECRET_NAMES
            or name.startswith('client_secret') or path.suffix.casefold() in {'.pem', '.key', '.p12', '.pfx'})


def category(path):
    suffix = path.suffix.casefold()
    if suffix in MODEL_SUFFIXES:
        return 'trained_artifacts'
    if suffix in {'.sqlite', '.sqlite3', '.db'}:
        return 'databases'
    if suffix in SOURCE_SUFFIXES or path.name.startswith('requirements'):
        return 'source_and_documentation'
    if suffix == '.json' and 'runs' in path.parts:
        return 'run_metadata'
    if suffix in {'.csv', '.parquet', '.jsonl'}:
        return 'tables'
    if suffix in {'.zip', '.gz', '.tar', '.bz2', '.7z', '.mp3', '.wav', '.flac', '.ogg'}:
        return 'archives_and_audio'
    return 'other'


def git_state(root):
    try:
        result = subprocess.run(
            ['git', '--no-optional-locks', 'status', '--porcelain=v1', '-z', '--untracked-files=all'],
            cwd=root, capture_output=True, timeout=30, check=True)
        fields = result.stdout.decode('utf-8', errors='replace').split('\0')
        changes, index = [], 0
        while index < len(fields):
            value = fields[index]
            index += 1
            if not value:
                continue
            status, name = value[:2], value[3:]
            if 'R' in status or 'C' in status:
                index += 1  # Rename/copy entries have a second NUL-separated path.
            if not sensitive(Path(name)):
                changes.append({'status': status, 'path': name})
        return {'available': True, 'changes': changes}
    except (OSError, subprocess.SubprocessError):
        return {'available': False, 'changes': []}


def inventory(root, *, excluded_files=(), max_files=200000):
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError('The project folder does not exist.')
    excluded_files = {Path(path).resolve() for path in excluded_files}
    files, skipped, errors = [], Counter(), []
    folders = defaultdict(lambda: {'files': 0, 'bytes': 0})
    categories = defaultdict(lambda: {'files': 0, 'bytes': 0})
    truncated = False

    def on_error(error):
        errors.append({'path': str(Path(error.filename).relative_to(root)), 'reason': 'unreadable_directory'})

    for directory, dirs, names in os.walk(root, followlinks=False, onerror=on_error):
        parent = Path(directory)
        keep = []
        for name in sorted(dirs):
            path = parent / name
            if name in EXCLUDED_DIRS:
                skipped['environment_or_cache_directories'] += 1
            elif path.is_symlink():
                skipped['symlink_directories'] += 1
            else:
                keep.append(name)
        dirs[:] = keep
        for name in sorted(names):
            path = parent / name
            if path.is_symlink():
                skipped['symlink_files'] += 1
                continue
            if sensitive(path):
                skipped['credential_named_files'] += 1
                continue
            if path.resolve() in excluded_files:
                continue
            if len(files) >= max_files:
                truncated = True
                break
            relative = path.relative_to(root)
            try:
                size = path.stat().st_size
            except OSError:
                errors.append({'path': relative.as_posix(), 'reason': 'unreadable_file'})
                continue
            kind = category(relative)
            files.append({'path': relative.as_posix(), 'bytes': size, 'category': kind})
            folder = relative.parts[0] if len(relative.parts) > 1 else '.'
            for group in (folders[folder], categories[kind]):
                group['files'] += 1
                group['bytes'] += size
        if truncated:
            break
    required = ['mpd.sqlite3', 'split.sqlite3', 'model/frozen_settings.json',
                'model/index/summary.json', 'model/tags/title_tagger.joblib']
    present = {item['path'] for item in files}
    missing = ['runs/million/' + name for name in required if 'runs/million/' + name not in present]
    return {
        'schema': 'beatx-local-inventory-v1',
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'read_only': True,
        'file_contents_included': False,
        'truncated': truncated,
        'total_files': len(files),
        'total_bytes': sum(item['bytes'] for item in files),
        'folders': dict(sorted(folders.items())),
        'categories': dict(sorted(categories.items())),
        'default_deployment_probe': {'scope': 'file presence only; not a model-integrity check',
                                     'missing': missing},
        'git': git_state(root),
        'skipped': dict(skipped),
        'errors': errors,
        'files': files,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--root', type=Path, default=Path.cwd())
    cli.add_argument('--output', type=Path, default=Path('/tmp/beatx-local-inventory.json'))
    cli.add_argument('--max-files', type=int, default=200000)
    args = cli.parse_args()
    if args.max_files < 1:
        cli.error('--max-files must be positive')
    root, output = args.root.resolve(), args.output.resolve()
    if output.is_relative_to(root) and output.name != 'beatx-local-inventory.json':
        cli.error('Save outside the project folder, or use the generated filename beatx-local-inventory.json')
    try:
        result = inventory(root, excluded_files=(output,), max_files=args.max_files)
        # Exclusive creation avoids overwriting any existing file.
        with output.open('x', encoding='utf-8') as target:
            json.dump(result, target, indent=2, ensure_ascii=False)
            target.write('\n')
    except FileExistsError:
        cli.error('The output already exists. Choose another --output filename outside the project folder.')
    except (OSError, ValueError) as error:
        cli.error(str(error))
    print(f'Created {output}')
    print(f'Inspected {result["total_files"]:,} files ({result["total_bytes"] / 1024**3:.2f} GiB).')
    print('No training files were changed or uploaded. The report contains paths and sizes, not file contents.')
    if result['truncated'] or result['errors']:
        print('The scan is incomplete; check the report before planning a transfer.')


if __name__ == '__main__':
    main()
