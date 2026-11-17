"""Export reproducible research downloads from the existing public result scripts.

This does not train, tune or evaluate a model. No private MPD data is read.
"""

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
SOURCES = {
    'benchmark': ('experiment.js', 'NEXT_TRACK_EXPERIMENT'),
    'seed_study': ('seed_experiment.js', 'NEXT_TRACK_SEED_STUDY'),
    'sequence': ('sequence_experiment.js', 'NEXT_TRACK_SEQUENCE'),
}


def read_public_script(path, variable):
    """Parse the single JSON assignment without executing arbitrary JavaScript."""
    pattern = rf'\s*window\.{re.escape(variable)}\s*=\s*(\{{.*\}})\s*;\s*'
    match = re.fullmatch(pattern, path.read_text(encoding='utf-8'), flags=re.DOTALL)
    if not match:
        raise ValueError(f'{path}: expected one JSON assignment for {variable}')
    def reject_constant(token):
        raise ValueError(f'Nonfinite JSON constant: {token}')

    return json.loads(match[1], parse_constant=reject_constant)


def csv_text(headers, rows):
    output = io.StringIO(newline='')
    writer = csv.writer(output, lineterminator='\n')
    writer.writerow(headers)
    writer.writerows(rows)
    return output.getvalue()


def build_exports(source_dir):
    reports = {key: read_public_script(source_dir / filename, variable)
               for key, (filename, variable) in SOURCES.items()}
    benchmark, study = reports['benchmark'], reports['seed_study']
    source_hashes = {filename: hashlib.sha256((source_dir / filename).read_bytes()).hexdigest()
                     for filename, _ in SOURCES.values()}
    provenance = {
        'schema_version': 1,
        'generator': 'scripts/export_research_bundle.py',
        'source_sha256': source_hashes,
        'scope': 'Existing public aggregate exports; no new experiment or private-data verification.',
        'uncertainty': 'Published paired group-bootstrap intervals; not individual-model intervals.',
        'identity': 'Exact Spotify track IDs; no verified recording crosswalk in the measured run.',
        'model_scope': {
            'ranking_charts': 'Original CF and 12-tag title benchmark; not the unified Studio ranker.',
            'sequence_chart': 'Separate directed training-transition order-recovery study.',
            'teaching_tools': 'Invented counts and rankings; not evaluation results.',
            'unified_studio': 'Implementation documented separately; evaluation outputs are not published in this bundle.',
        },
        'protocols': {
            'benchmark': 'Three seeds; 5000 test queries; every remaining track is a reference.',
            'seed_study': study['reference_protocol'],
            'sequence': 'Same 20 known tracks, first fixed; original directed adjacency recovery.',
        },
        'not_evaluated_in_ranking_benchmark': [
            'Unified Studio ranker', 'Expanded song profiles', 'BPM', 'Bass', 'Treble', 'Release era', 'ALS', 'BPR',
        ],
        'missing_public_evidence': [
            'Full-million validation weight curve', 'Raw EDA distributions',
            'Private model-array checksums', 'Human listener study',
            'Unified evaluation and tuning outputs (unified-evaluation.json, unified-tuning.json)',
        ],
    }
    outputs = {}
    benchmark_rows = []
    for cohort in ('all_queries', 'title_tagged_queries'):
        queries = benchmark['sample']['eligible_queries_evaluated' if cohort == 'all_queries'
                                      else 'title_tagged_queries']
        for method, metrics in benchmark[cohort].items():
            for metric, value in metrics.items():
                benchmark_rows.append([cohort, queries, 3, method, metric, value])
    outputs['benchmark.csv'] = csv_text(['cohort', 'queries', 'seeds', 'method', 'metric', 'value'], benchmark_rows)
    score_rows, marginal_rows = [], []
    for partition in ('validation', 'test'):
        data = study[partition]
        for budget in study['seed_budgets']:
            current = data['budgets'][str(budget)]
            for cohort in ('all_queries', 'title_tagged_queries'):
                queries = data['queries' if cohort == 'all_queries' else 'title_tagged_queries']
                for method, metrics in current[cohort].items():
                    for metric, value in metrics.items():
                        score_rows.append([partition, cohort, queries, budget, method, metric, value])
            if 'marginal_seed_gain' in current:
                gain = current['marginal_seed_gain']
                marginal_rows.append([partition, gain['from_seeds'], budget, gain['ndcg_delta'],
                                      gain['ndcg_per_added_seed'], *gain['paired_ndcg_95_ci']])
    outputs['seed_scores.csv'] = csv_text(['partition', 'cohort', 'queries', 'seeds', 'method', 'metric', 'value'], score_rows)
    outputs['marginal_gains.csv'] = csv_text(['partition', 'from_seeds', 'to_seeds', 'ndcg_delta',
                                           'ndcg_per_added_seed', 'paired_total_delta_ci_low',
                                           'paired_total_delta_ci_high'], marginal_rows)
    outputs['provenance.json'] = json.dumps(provenance, indent=2, ensure_ascii=False, allow_nan=False) + '\n'
    outputs['research_bundle.json'] = json.dumps({'provenance': provenance, **reports}, indent=2,
                                                ensure_ascii=False, allow_nan=False) + '\n'
    return outputs


def export(source_dir, destination, check=False):
    outputs = build_exports(source_dir)
    if check:
        stale = [name for name, content in outputs.items()
                 if not (destination / name).is_file() or (destination / name).read_text(encoding='utf-8') != content]
        if stale:
            raise ValueError('Research downloads need regeneration: ' + ', '.join(stale))
    else:
        destination.mkdir(parents=True, exist_ok=True)
        for name, content in outputs.items():
            (destination / name).write_text(content, encoding='utf-8', newline='\n')
    return len(outputs)


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source-dir', type=Path, default=ROOT / 'docs')
    cli.add_argument('--output', type=Path, default=ROOT / 'docs/data/research')
    cli.add_argument('--check', action='store_true', help='Fail if checked-in downloads differ from their sources')
    args = cli.parse_args()
    total = export(args.source_dir, args.output, args.check)
    print(f'{"Verified" if args.check else "Exported"} {total} research downloads from public aggregates.')
