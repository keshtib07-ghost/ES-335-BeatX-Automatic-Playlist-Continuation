"""Fetch the manifest's 20 exact public-mirror slices for local research."""

import argparse
import hashlib
import json
import shutil
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen


def git_blob_sha1(path):
    fingerprint = hashlib.sha1(f'blob {path.stat().st_size}\0'.encode())
    with path.open('rb') as file:
        for block in iter(lambda: file.read(1024 * 1024), b''):
            fingerprint.update(block)
    return fingerprint.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='private-data')
    parser.add_argument('--manifest', default='artifacts/source_manifest.json')
    args = parser.parse_args()
    source = json.loads(Path(args.manifest).read_text(encoding='utf-8'))
    destination = Path(args.output)
    destination.mkdir(parents=True, exist_ok=True)
    project = source['repository'].removeprefix('https://github.com/')
    base = f'https://raw.githubusercontent.com/{project}/{source["commit"]}/data1'

    def download(item):
        filename, expected = item['filename'], item['git_blob_sha1']
        target = destination / filename
        if target.is_file() and git_blob_sha1(target) == expected:
            return filename
        temporary = target.with_suffix('.partial')
        for attempt in range(3):
            try:
                with urlopen(f'{base}/{filename}', timeout=60) as response, temporary.open('wb') as output:
                    shutil.copyfileobj(response, output)
                if git_blob_sha1(temporary) != expected:
                    raise ValueError(f'Checksum mismatch for {filename}')
                temporary.replace(target)
                return filename
            except (OSError, ValueError):
                temporary.unlink(missing_ok=True)
                if attempt == 2:
                    raise

    with ThreadPoolExecutor(max_workers=4) as pool:
        for filename in pool.map(download, source['slices']):
            print(f'Verified {filename}', flush=True)


if __name__ == '__main__':
    main()
