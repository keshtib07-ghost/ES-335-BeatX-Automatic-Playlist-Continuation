"""Report local model deployment files and sizes without uploading anything."""

import argparse
import json
from pathlib import Path


def report(root):
    required = [root / 'mpd.sqlite3', root / 'split.sqlite3', root / 'model' / 'frozen_settings.json']
    required += [root / 'model' / 'index' / name for name in (
        'summary.json', 'playlist_indices.npy', 'playlist_offsets.npy', 'track_playlists.npy',
        'track_offsets.npy', 'train_pids.npy')]
    required += [root / 'model' / 'tags' / name for name in (
        'summary.json', 'title_tagger.joblib', 'track_tag_votes.npy', 'track_axis_totals.npy', 'tag_priors.npy')]
    optional = [root / name for name in ('profiles-v2-expanded', 'profiles-v2', 'sequence')]
    optional.append(root / 'catalogue-enrichment' / 'catalogue_enrichment.sqlite3')
    files = [{'path': str(path.relative_to(root)), 'bytes': path.stat().st_size if path.is_file() else None}
             for path in required]
    extras = []
    for path in optional:
        if path.exists():
            size = sum(item.stat().st_size for item in path.rglob('*') if item.is_file()) if path.is_dir() else path.stat().st_size
            extras.append({'path': str(path.relative_to(root)), 'bytes': size})
    return {'required': files, 'optional': extras,
            'missing': [item['path'] for item in files if item['bytes'] is None],
            'required_bytes': sum(item['bytes'] or 0 for item in files),
            'optional_bytes': sum(item['bytes'] for item in extras)}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--data', type=Path, default=Path('runs/million'))
    args = cli.parse_args()
    result = report(args.data)
    print(json.dumps(result, indent=2))
    return 1 if result['missing'] else 0


if __name__ == '__main__':
    raise SystemExit(main())
