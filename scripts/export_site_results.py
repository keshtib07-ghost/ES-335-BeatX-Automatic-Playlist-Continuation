"""Export only aggregate held-out results for the public GitHub Pages site."""

import argparse
import json
from pathlib import Path


def export(source, destination):
    report = json.loads(source.read_text(encoding='utf-8'))
    scopes = ('all_queries', 'title_tagged_queries')
    models = ('popularity', 'collaborative_filtering', 'selected_tag_ranker')
    metrics = ('recall_at_20', 'ndcg_at_20', 'precision_at_20', 'hit_rate_at_20')
    sample_fields = ('eligible_queries_evaluated', 'title_tagged_queries', 'all_seeds_unseen_in_training',
                     'unseen_reference_occurrences', 'all_reference_occurrences')
    public = {key: {model: {metric: report[key][model][metric] for metric in metrics}
                    for model in models} if report[key] else {} for key in scopes}
    public['sample'] = {key: report['sample'][key] for key in sample_fields}
    public['selected_tag_weight'] = report['selected_tag_weight']
    for key in ('tag_ranker_minus_cf_ndcg_95_ci_all', 'tag_ranker_minus_cf_ndcg_95_ci_tagged'):
        public[key] = report[key]
    destination.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(public, ensure_ascii=False, indent=2, allow_nan=False)
    destination.write_text(f'window.NEXT_TRACK_EXPERIMENT = {text};\n', encoding='utf-8')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--input', type=Path, default=Path('runs/million/model/test_metrics.json'))
    cli.add_argument('--output', type=Path, default=Path('docs/experiment.js'))
    options = cli.parse_args()
    export(options.input, options.output)
