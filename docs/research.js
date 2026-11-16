'use strict';

const experiment = window.NEXT_TRACK_EXPERIMENT;
const methods = [['popularity', 'Popularity'], ['collaborative_filtering', 'Collaborative filtering'], ['selected_tag_ranker', 'CF + title tags']];
const metrics = {
  ndcg_at_20: ['NDCG@20 rewards reference tracks found near the top of the first 20 results.', (value) => value.toFixed(4)],
  recall_at_20: ['Recall@20 is the share of withheld tracks recovered in the first 20 results.', (value) => `${(100 * value).toFixed(2)}%`],
  precision_at_20: ['Precision@20 is the share of the first 20 results that are in the withheld playlist.', (value) => `${(100 * value).toFixed(2)}%`],
  hit_rate_at_20: ['Hit rate@20 is the fraction of playlists with at least one withheld track in the first 20 results.', (value) => `${(100 * value).toFixed(2)}%`],
};
let cohort = 'all_queries';
let metric = 'ndcg_at_20';

function showResults() {
  const score = experiment[cohort];
  const [, format] = metrics[metric];
  const tagged = cohort === 'title_tagged_queries';
  const count = tagged ? experiment.sample.title_tagged_queries : experiment.sample.eligible_queries_evaluated;
  select('query-count').textContent = `${count.toLocaleString('en-US')} held-out queries`;
  select('metric-description').textContent = metrics[metric][0];
  const maximum = Math.max(...['all_queries', 'title_tagged_queries'].flatMap((scope) =>
    methods.map(([key]) => experiment[scope][key]?.[metric] ?? 0)));
  const axisMax = Math.max(.05, Math.ceil(maximum * 20) / 20);
  select('chart-scale').textContent = `Bar scale ${format(0)} – ${format(axisMax)}`;
  select('chart').replaceChildren(...methods.map(([key, name]) => {
    const value = score[key][metric];
    const row = node('div', undefined, 'chart-row');
    row.setAttribute('role', 'row');
    const label = node('span', name, 'chart-label');
    const visual = node('span', undefined, 'bar-track');
    const bar = node('i', undefined, 'bar');
    const cell = node('span', format(value), 'chart-value');
    label.setAttribute('role', 'rowheader');
    visual.setAttribute('aria-hidden', 'true');
    cell.setAttribute('role', 'cell');
    bar.style.width = `${100 * value / axisMax}%`;
    visual.append(bar);
    row.append(label, visual, cell);
    return row;
  }));
  const gain = score.selected_tag_ranker[metric] - score.collaborative_filtering[metric];
  const detail = select('evidence');
  if (metric === 'ndcg_at_20') {
    const interval = experiment[tagged ? 'tag_ranker_minus_cf_ndcg_95_ci_tagged' : 'tag_ranker_minus_cf_ndcg_95_ci_all'];
    const message = interval ? ` · paired 95% interval ${interval[0].toFixed(4)} to ${interval[1].toFixed(4)}` : '';
    detail.replaceChildren(node('strong', `${gain >= 0 ? '+' : ''}${gain.toFixed(4)} NDCG@20`), document.createTextNode(` vs. plain CF${message}`));
  } else {
    detail.replaceChildren(node('strong', `${gain >= 0 ? '+' : ''}${(100 * gain).toFixed(2)} percentage points`), document.createTextNode(' vs. plain CF'));
  }
}

for (const button of document.querySelectorAll('[data-cohort], [data-metric]')) {
  if (button.dataset.cohort === 'title_tagged_queries' && !experiment.sample.title_tagged_queries) button.disabled = true;
  button.addEventListener('click', () => {
    const group = button.dataset.cohort ? 'cohort' : 'metric';
    if (group === 'cohort') cohort = button.dataset.cohort;
    else metric = button.dataset.metric;
    for (const peer of document.querySelectorAll(`[data-${group}]`)) peer.setAttribute('aria-pressed', String(peer === button));
    showResults();
  });
}
showResults();

