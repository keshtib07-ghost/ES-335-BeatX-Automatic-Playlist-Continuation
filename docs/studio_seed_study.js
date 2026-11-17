/* Final-pipeline seed curves read measured aggregates only. */
(function () {
  'use strict';
  const LABELS = {ndcg: 'NDCG', recall: 'Recall', precision: 'Precision', hit_rate: 'Hit rate',
    artist_diversity: 'Artist variety', catalogue_coverage: 'Catalogue coverage'};
  const NAMES = {popularity: 'Popularity baseline', cf: 'CF baseline', standard_title: 'Earlier title method',
    unified_no_title: 'Final pipeline without title', unified: 'Final pipeline', unified_seed_bpm: 'Final pipeline + BPM filter'};
  const COLORS = {popularity: '#aab7c2', cf: '#84b8ff', standard_title: '#f4a8c4',
    unified_no_title: '#c5a8fa', unified: '#cefb70', unified_seed_bpm: '#ffd47c'};
  function seedView(report, partition, metric, k, comparison) {
    if (report?.kind !== 'frozen_final_pipeline_seed_study') return null;
    const methods = {main: ['popularity', 'cf', 'unified'], context: ['unified_no_title', 'unified'],
      tempo: ['unified', 'unified_seed_bpm'], all: report.methods}[comparison];
    return methods.map(name => ({name, label: NAMES[name], color: COLORS[name],
      values: report.seed_budgets.map(n => report[partition].budgets[n].cutoffs[k][name][metric])}));
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {seedView};
  if (typeof document === 'undefined') return;
  const $ = id => document.getElementById(id);
  const report = window.BEATX_RESEARCH_ADDITIONS?.studio_seed_study;
  const status = $('final-seed-status');
  function openAnchor() {
    let target;
    try { target = $(decodeURIComponent(location.hash.slice(1))); } catch { return; }
    if (!target) return;
    for (let parent = target.parentElement; parent; parent = parent.parentElement) {
      if (parent.tagName === 'DETAILS') parent.open = true;
    }
    if (location.hash) requestAnimationFrame(() => target.scrollIntoView({block: 'start'}));
  }
  openAnchor();
  window.addEventListener('hashchange', openAnchor);
  if (!report || report.kind !== 'frozen_final_pipeline_seed_study') return;
  const answer = `Validation selected ${report.chosen_seed_budget} seeds using the fixed 95% rule. This is the smallest tested count near the best validation NDCG@20; it is not a universal minimum.`;
  for (const id of ['final-seed-answer', 'summary-final-seed-answer']) if ($(id)) $(id).textContent = answer;
  for (const id of ['final-seed-coverage', 'summary-seed-coverage']) if ($(id)) $(id).textContent = 'Measured at six seed counts';
  if (!status) return;
  function node(tag, text) {
    const result = document.createElement(tag);
    if (text !== undefined) result.textContent = text;
    return result;
  }
  const NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, text) {
    const result = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([k, v]) => result.setAttribute(k, String(v)));
    if (text !== undefined) result.textContent = text;
    return result;
  }
  function render() {
    const partition = $('final-seed-partition').value, metric = $('final-seed-metric').value;
    const k = Number($('final-seed-k').value), comparison = $('final-seed-comparison').value;
    const rows = seedView(report, partition, metric, k, comparison), budgets = report.seed_budgets;
    status.textContent = `${report[partition].queries.toLocaleString()} ${partition} playlists, with the same hidden songs at every seed count. These curves use the frozen final pipeline.`;
    $('final-seed-results').hidden = false;
    $('final-seed-pending').hidden = true;
    $('final-seed-downloads').hidden = false;
    const chart = svg('svg', {viewBox: '0 0 760 320', role: 'img', 'aria-label': `${LABELS[metric]} at K=${k} by number of seed songs. Exact values follow.`});
    chart.append(svg('title', {}, `${LABELS[metric]} by seed count`));
    const left = 70, right = 730, top = 25, bottom = 260;
    const maximum = Math.max(.00001, ...rows.flatMap(row => row.values)) * 1.12;
    const x = n => left + (n - budgets[0]) / (budgets.at(-1) - budgets[0]) * (right - left);
    const y = v => bottom - v / maximum * (bottom - top);
    for (let i = 0; i <= 4; i++) {
      const v = maximum * i / 4;
      chart.append(svg('line', {x1: left, x2: right, y1: y(v), y2: y(v), class: 'grid'}));
      chart.append(svg('text', {x: left - 10, y: y(v) + 4, 'text-anchor': 'end'}, v.toFixed(metric === 'catalogue_coverage' ? 4 : 3)));
    }
    budgets.forEach(n => chart.append(svg('text', {x: x(n), y: bottom + 22, 'text-anchor': 'middle'}, n)));
    rows.forEach(row => {
      chart.append(svg('polyline', {points: row.values.map((v, i) => `${x(budgets[i])},${y(v)}`).join(' '),
        fill: 'none', stroke: row.color, 'stroke-width': 2.5}));
      row.values.forEach((v, i) => {
        const point = svg('circle', {cx: x(budgets[i]), cy: y(v), r: 4, fill: row.color});
        point.append(svg('title', {}, `${row.label}, ${budgets[i]} seeds: ${v.toFixed(5)}`)); chart.append(point);
      });
    });
    chart.append(svg('text', {x: left, y: 15}, `${LABELS[metric]}${['ndcg', 'recall', 'precision', 'hit_rate'].includes(metric) ? '@' + k : ''}`));
    chart.append(svg('text', {x: 400, y: 313, 'text-anchor': 'middle'}, 'Number of input seed songs'));
    $('final-seed-chart').replaceChildren(chart);
    const legend = node('div'); legend.className = 'research-legend';
    rows.forEach(row => {const label = node('span'), swatch = node('i'); swatch.style.setProperty('--legend-color', row.color); label.append(swatch, row.label); legend.append(label);});
    $('final-seed-chart').append(legend);
    const table = node('table'), head = node('tr');
    ['Seeds', ...rows.map(row => row.label)].forEach(label => {const th = node('th', label); th.scope = 'col'; head.append(th);});
    const thead = node('thead'); thead.append(head); table.append(thead);
    const body = node('tbody');
    budgets.forEach((n, i) => {const tr = node('tr'), th = node('th', n); th.scope = 'row'; tr.append(th);
      rows.forEach(row => tr.append(node('td', row.values[i].toFixed(5)))); body.append(tr);});
    table.append(body); $('final-seed-table').replaceChildren(table);
    $('final-seed-analysis').textContent = answer;
  }
  for (const id of ['final-seed-partition', 'final-seed-metric', 'final-seed-k', 'final-seed-comparison']) $(id).addEventListener('change', render);
  render();
}());
