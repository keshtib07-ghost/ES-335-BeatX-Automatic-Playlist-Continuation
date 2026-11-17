"""Bundle measured additions for static hosting, without missing-file requests."""

import argparse
import json
from pathlib import Path


def export(directory, target):
    def read(name):
        path = directory / name
        return json.loads(path.read_text()) if path.is_file() else None
    report = {'eda': read('eda_full.json') or read('eda_pilot.json'),
              'studio_audit': read('studio_audit.json'),
              'studio_evaluation': read('studio_evaluation.json')}
    target.write_text('window.BEATX_RESEARCH_ADDITIONS = ' + json.dumps(report, indent=2, allow_nan=False) + ';\n')
    return report


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--directory', type=Path, default=Path('docs/data/research'))
    cli.add_argument('--output', type=Path, default=Path('docs/research_extra_data.js'))
    args = cli.parse_args()
    export(args.directory, args.output)
