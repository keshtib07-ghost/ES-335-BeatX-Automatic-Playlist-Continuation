"""Check the completed reports and refresh their plain-language interpretation.

This reads saved evidence. It never reruns inference or selects model settings.
"""

import argparse
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
LABELS = {'popularity': 'Popularity baseline', 'cf': 'CF baseline', 'standard_title': 'Earlier title method',
          'unified_no_title': 'Final pipeline without title', 'unified': 'Final pipeline',
          'unified_seed_bpm': 'Final pipeline + BPM filter'}


def check(report, eda):
    if report['kind'] != 'frozen_studio_heldout_evaluation' or eda['kind'] != 'full_staging_eda':
        raise ValueError('Completed Studio and full-data reports are required')
    if report['freeze']['split'] != eda['identity']:
        raise ValueError('Evaluation and EDA refer to different data splits')
    if sum(v['playlists'] for v in eda['partitions'].values()) != eda['playlists']:
        raise ValueError('Split counts do not reconcile')
    for part in eda['partitions'].values():
        for field in ('playlist_length', 'title_length', 'duplicate_group_size'):
            histogram = part[field]
            if sum(histogram['counts']) != histogram['total']:
                raise ValueError(f'Invalid {field} distribution')
        if part['playlist_length']['total'] != part['playlists']:
            raise ValueError('Playlist length count differs from split size')
    if eda['training_track_support']['total'] != report['freeze']['training_catalogue_tracks']:
        raise ValueError('Training-catalogue denominators differ')
    for name, cohort in report['cohorts'].items():
        if not cohort['queries']:
            continue
        for method in report['methods']:
            previous = dict(recall=0., hit_rate=0., catalogue_coverage=0.)
            for k in report['cutoffs']:
                values = cohort['cutoffs'][str(k)][method]
                if any(not math.isfinite(v) or not 0 <= v <= 1 for v in values.values()):
                    raise ValueError(f'Invalid score in {name}/{method}/{k}')
                for metric in previous:
                    if values[metric] + 1e-12 < previous[metric]:
                        raise ValueError(f'{metric} falls as the ranking prefix grows')
                    previous[metric] = values[metric]
    cohort = report['cohorts']['all_queries']
    if cohort['queries'] != report['freeze']['queries']:
        raise ValueError('Frozen and measured query counts differ')
    expected_hit_rate = 1 - report['unified_failures']['zero_hit_queries'] / cohort['queries']
    if abs(expected_hit_rate - cohort['cutoffs']['20']['unified']['hit_rate']) > 1e-12:
        raise ValueError('Zero-hit count and Hit Rate disagree')
    for case in report['cases'].values():
        if case is None:
            continue
        ideal = sum(1 / math.log2(i + 2) for i in range(min(20, case['reference_count'])))
        scores = {}
        for method, ranks in case['hit_ranks'].items():
            if len(ranks) != len(set(ranks)) or any(not 1 <= n <= 20 for n in ranks):
                raise ValueError('Invalid saved hit positions')
            if len(ranks) > case['reference_count']:
                raise ValueError('More hits than references')
            scores[method] = sum(1 / math.log2(n + 1) for n in ranks) / ideal
        if abs(scores['unified'] - scores['cf'] - case['ndcg_delta']) > 1e-12:
            raise ValueError('Saved case scores do not match their hit positions')


def score_table(report, table_id, methods, cohort='all_queries', extra=False):
    data = report['cohorts'][cohort]
    metrics = ['ndcg', 'recall', 'precision', 'hit_rate']
    labels = ['NDCG@20', 'Recall@20', 'Precision@20', 'Hit Rate@20']
    if extra:
        metrics.append('artist_diversity')
        labels.append('Artist variety')
    cells = ''.join('<th scope="col">' + label + '</th>' for label in labels)
    rows = []
    for method in methods:
        values = data['cutoffs']['20'][method]
        rows.append('<tr><th scope="row">' + LABELS[method] + '</th>' +
                    ''.join(f'<td>{values[m]:.5f}</td>' for m in metrics) + '</tr>')
    return (f'<div class="table-wrap"><table id="{table_id}"><caption>'
            f'{data["queries"]:,} held-out queries; {report["freeze"]["seeds"]} seeds; K = 20.'
            '</caption><thead><tr><th scope="col">Method</th>' + cells +
            '</tr></thead><tbody>' + ''.join(rows) + '</tbody></table></div>')


def summary_block(report):
    values = report['cohorts']['all_queries']['cutoffs']['20']
    delta = values['unified']['ndcg'] - values['cf']['ndcg']
    low, high = report['paired_unified_minus_cf_ndcg_at_20_95_ci']
    return (f'<div class="research-card" id="summary-studio-results"><h3>Final pipeline evaluation</h3>'
            + score_table(report, 'summary-studio', ('popularity', 'cf', 'unified', 'unified_seed_bpm')) +
            f'<p>The final pipeline recovers at least one hidden song in {100 * values["unified"]["hit_rate"]:.1f}% of queries. '
            f'Its NDCG gain over CF is {delta:+.5f}. The paired 95% interval is '
            f'[{low:+.5f}, {high:+.5f}], which includes zero. This sample does not establish a clear improvement over CF.</p>'
            '<p>The BPM filter lowers recovery. It increases artist variety, but that is a different objective.</p>'
            '<a href="research-deep-dive.html#studio-evaluation">Explore every K and the tempo subset →</a></div>')


def refresh(root=ROOT):
    directory = root / 'docs/data/research'
    report = json.loads((directory / 'studio_evaluation.json').read_text())
    eda = json.loads((directory / 'eda_full.json').read_text())
    check(report, eda)
    p = root / 'docs/research.html'
    text = p.read_text()
    # The older table remains available with its original cohort and score.
    marker = '      <div class="research-card"><div class="table-wrap"><table id="summary-benchmark">'
    block = '<!-- final-studio-summary:start -->' + summary_block(report) + '<!-- final-studio-summary:end -->\n'
    pattern = r'<!-- final-studio-summary:start -->.*?<!-- final-studio-summary:end -->\s*'
    if re.search(pattern, text, flags=re.S):
        text = re.sub(pattern, lambda _: block, text, count=1, flags=re.S)
    else:
        if marker not in text:
            raise ValueError('The summary benchmark anchor changed; review the page before updating')
        text = text.replace(marker, block + marker, 1)
    if 'id="earlier-benchmark"' not in text:
        pattern = r'<div class="research-card"><div class="table-wrap"><table id="summary-benchmark">.*?</table></div><p>.*?</p></div>'
        text, count = re.subn(pattern, lambda match:
            '<details class="research-details" id="earlier-benchmark"><summary>Earlier three-seed benchmark</summary>' +
            match.group() + '</details>', text, count=1, flags=re.S)
        if count != 1:
            raise ValueError('The older benchmark card changed; check its placement manually')
    text = text.replace('Its scores need the trained-data run.', 'The completed Studio test measures that filter separately.')
    text = text.replace('Its relevance needs a separate evaluation.', 'The final Studio comparison above uses its own held-out cohort.')
    text = text.replace('Controlled comparisons would be needed to measure the ranking effects of the expanded profile logic, BPM, era, bass and treble.',
                        'The final Studio and BPM comparisons are complete. Era and spectral audio features still need separate tests.')
    p.write_text(text)
    p = root / 'docs/research-deep-dive.html'
    text = p.read_text()
    table = score_table(report, 'studio-static-scores', report['methods'], extra=True)
    text = re.sub(r'<!-- studio-static:start -->.*?<!-- studio-static:end -->\s*', '', text, flags=re.S)
    anchor = '<div id="studio-evaluation-results" hidden>'
    text = text.replace(anchor, '<!-- studio-static:start --><details class="research-details"><summary>Recorded scores at K = 20</summary>' +
                        table + '</details><!-- studio-static:end -->' + anchor, 1)
    text = text.replace('The final held-out scores are awaiting the trained-data run. The standard benchmark above is a different pipeline.',
                        'Completed: 1,000 held-out queries with five seeds. Change K or select a subset below. The earlier three-seed benchmark uses different queries.')
    p.write_text(text)
    print(f'Checked {report["cohorts"]["all_queries"]["queries"]:,} Studio queries and {eda["playlists"]:,} EDA rows.')


if __name__ == '__main__':
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--check-only', action='store_true')
    args = cli.parse_args()
    if args.check_only:
        directory = ROOT / 'docs/data/research'
        check(json.loads((directory / 'studio_evaluation.json').read_text()), json.loads((directory / 'eda_full.json').read_text()))
        print('Completed report consistency checks passed.')
    else:
        refresh()
