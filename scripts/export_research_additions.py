"""Bundle measured additions for static hosting, without missing-file requests."""

import argparse
import hashlib
import json
from pathlib import Path
import re


def export(directory, target):
    def read(name):
        path = directory / name
        return json.loads(path.read_text()) if path.is_file() else None
    report = {'eda': read('eda_full.json') or read('eda_pilot.json'),
              'studio_audit': read('studio_audit.json'),
              'studio_evaluation': read('studio_evaluation.json'),
              'studio_seed_study': read('studio_seed_study.json')}
    payload = 'window.BEATX_RESEARCH_ADDITIONS = ' + json.dumps(report, indent=2, allow_nan=False) + ';\n'
    target.write_text(payload)
    assets = (target.name, 'research_additions.js', 'studio_seed_study.js',
              'research.js', 'research-summary.js', 'research.css',
              'experiment.js', 'seed_experiment.js', 'sequence_experiment.js')
    versions = {name: hashlib.sha256((target.parent / name).read_bytes()).hexdigest()[:12]
                for name in assets if (target.parent / name).is_file()}
    for name in ('research.html', 'research-deep-dive.html'):
        page = target.parent / name
        if page.is_file():
            text = page.read_text()
            for asset, version in versions.items():
                text = re.sub(r'((?:src|href)=")' + re.escape(asset) + r'(?:\?[^"]*)?(")',
                              lambda match: match[1] + asset + '?v=' + version + match[2], text)
            page.write_text(text)
    return report


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory', type=Path, default=Path('docs/data/research'))
    cli.add_argument('--output', type=Path, default=Path('docs/research_extra_data.js'))
    args = cli.parse_args()
    export(args.directory, args.output)
