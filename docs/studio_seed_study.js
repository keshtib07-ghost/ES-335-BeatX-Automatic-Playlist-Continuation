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
  function seedAnswer(report) {
    const first = report.test.budgets[1].cutoffs[20].unified;
    const last = report.test.budgets[20].cutoffs[20].unified;
    const limit = report.chosen_seed_budget === 20
      ? 'Twenty is the largest count tested, so the study does not establish an earlier stopping point or a universal optimum.'
      : 'This validation rule applies to the tested model and cohort; it is not a universal minimum.';
    return `Test NDCG@20 rises from ${first.ndcg.toFixed(5)} with one seed to ${last.ndcg.toFixed(5)} with 20. Validation selected ${report.chosen_seed_budget} seeds under the 95% rule. ${limit}`;
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {seedView, seedAnswer};
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
  const answer = seedAnswer(report);
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
  function table(target, headers, rows, caption) {
    const result = node('table'), head = node('thead'), row = node('tr'), body = node('tbody');
    if (caption) result.append(node('caption', caption));
    headers.forEach(label => {const cell = node('th', label); cell.scope = 'col'; row.append(cell);});
    head.append(row); result.append(head);
    rows.forEach(values => {const line = node('tr'); values.forEach((value, i) => {
      const cell = node(i ? 'td' : 'th', value); if (!i) cell.scope = 'row'; line.append(cell);
    }); body.append(line);});
    result.append(body); target.replaceChildren(result);
  }
  function renderDiagnostics(partition) {
    if (!$('final-seed-marginal-chart')) return;
    const section = report[partition];
    const gains = report.seed_budgets.slice(1).map(n => ({to: n, ...section.budgets[n].marginal_seed_gain}));
    const maximum = Math.max(...gains.map(row => Math.abs(row.ndcg_per_added_seed)), .00001);
    $('final-seed-marginal-chart').replaceChildren();
    gains.forEach(gain => {
      const line = node('div'); line.className = 'research-bar-row';
      const track = node('span'), fill = node('span'); track.className = 'track'; fill.className = 'fill';
      fill.style.width = `${100 * Math.abs(gain.ndcg_per_added_seed) / maximum}%`;
      track.setAttribute('aria-hidden', 'true'); track.append(fill);
      line.append(node('span', `${gain.from_seeds} → ${gain.to} seeds`), track, node('strong', gain.ndcg_per_added_seed.toFixed(5)));
      $('final-seed-marginal-chart').append(line);
    });
    table($('final-seed-marginal-table'), ['Seeds', 'Total ΔNDCG', 'Δ per extra seed', 'Paired 95% interval for total Δ'],
      gains.map(row => [`${row.from_seeds} → ${row.to}`, row.ndcg_delta.toFixed(5), row.ndcg_per_added_seed.toFixed(5),
        `[${row.paired_ndcg_95_ci.map(v => v.toFixed(5)).join(', ')}]`]), `${partition}; NDCG@20`);
    const differences = report.seed_budgets.map(n => ({n,
      value: section.budgets[n].cutoffs[20].unified.ndcg - section.budgets[n].cutoffs[20].cf.ndcg,
      interval: section.budgets[n].paired_final_minus_cf_ndcg_at_20_95_ci}));
    const chart = svg('svg', {viewBox: '0 0 760 290', role: 'img', 'aria-label': `${partition}: final pipeline minus CF NDCG@20 at each seed count, with paired 95% intervals`});
    chart.append(svg('title', {}, 'Final pipeline minus CF'));
    let minimum = Math.min(0, ...differences.map(row => row.interval[0]));
    let maximumCI = Math.max(0, ...differences.map(row => row.interval[1]));
    const padding = Math.max(.00001, (maximumCI - minimum) * .12); minimum -= padding; maximumCI += padding;
    const x = v => 85 + (v - minimum) / (maximumCI - minimum) * 635;
    chart.append(svg('line', {x1: x(0), x2: x(0), y1: 20, y2: 225, stroke: '#b0bec9', 'stroke-dasharray': '4 4'}));
    for (let i = 0; i <= 4; i++) {const value = minimum + (maximumCI - minimum) * i / 4;
      chart.append(svg('text', {x: x(value), y: 252, 'text-anchor': 'middle'}, value.toFixed(4)));}
    differences.forEach((row, i) => {
      const y = 38 + 35 * i;
      chart.append(svg('text', {x: 4, y: y + 4}, `${row.n} seeds`));
      chart.append(svg('line', {x1: x(row.interval[0]), x2: x(row.interval[1]), y1: y, y2: y, stroke: '#84b8ff', 'stroke-width': 3}));
      for (const end of row.interval) chart.append(svg('line', {x1: x(end), x2: x(end), y1: y - 6, y2: y + 6, stroke: '#84b8ff'}));
      const dot = svg('circle', {cx: x(row.value), cy: y, r: 4, fill: '#cefb70'});
      dot.append(svg('title', {}, `${row.n} seeds: ${row.value.toFixed(5)}; interval ${row.interval.map(v => v.toFixed(5)).join(' to ')}`)); chart.append(dot);
    });
    chart.append(svg('text', {x: 400, y: 285, 'text-anchor': 'middle'}, 'ΔNDCG@20: final pipeline minus CF'));
    $('final-seed-difference-chart').replaceChildren(chart);
    table($('final-seed-difference-table'), ['Seeds', 'Mean ΔNDCG@20', 'Paired 95% interval'],
      differences.map(row => [row.n, row.value.toFixed(5), `[${row.interval.map(v => v.toFixed(5)).join(', ')}]`]), partition);
    const lastGain = gains.at(-1), lastDifference = differences.at(-1);
    if ($('final-seed-marginal-analysis')) $('final-seed-marginal-analysis').textContent = `${partition}: going from 10 to 20 seeds adds ${lastGain.ndcg_delta.toFixed(5)} NDCG@20 in total, or ${lastGain.ndcg_per_added_seed.toFixed(5)} per extra seed. The total gain's paired 95% interval is [${lastGain.paired_ndcg_95_ci.map(v => v.toFixed(5)).join(', ')}].`;
    if ($('final-seed-difference-analysis')) {
      const above = differences.filter(row => row.interval[0] > 0).length;
      $('final-seed-difference-analysis').textContent = `${partition}: ${above} of the six pointwise intervals lie above zero. At 20 seeds the final-minus-CF difference is ${lastDifference.value.toFixed(5)}, with interval [${lastDifference.interval.map(v => v.toFixed(5)).join(', ')}]. The extra gain is small and depends on seed count.`;
    }
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
    const maximum = Math.min(1, Math.max(.00001, ...rows.flatMap(row => row.values)) * 1.12);
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
    table.append(node('caption', `${report[partition].queries.toLocaleString()} ${partition} playlists; ${LABELS[metric]} at K = ${k}`));
    ['Seeds', ...rows.map(row => row.label)].forEach(label => {const th = node('th', label); th.scope = 'col'; head.append(th);});
    const thead = node('thead'); thead.append(head); table.append(thead);
    const body = node('tbody');
    budgets.forEach((n, i) => {const tr = node('tr'), th = node('th', n); th.scope = 'row'; tr.append(th);
      rows.forEach(row => tr.append(node('td', row.values[i].toFixed(5)))); body.append(tr);});
    table.append(body); $('final-seed-table').replaceChildren(table);
    $('final-seed-analysis').textContent = answer;
    if ($('final-seed-metric-note')) $('final-seed-metric-note').textContent = {
      ndcg: 'NDCG rewards hidden songs ranked near the top. Higher means better recovery and ordering of those hits.',
      recall: 'Recall is the fraction of hidden songs recovered. The hidden set stays unchanged across seed counts.',
      precision: 'Precision is the fraction of K recommendation slots that recover hidden songs. Empty slots earn no credit.',
      hit_rate: 'Hit rate is the fraction of playlists with at least one recovered song. One hit and many hits count equally.',
      artist_diversity: 'Artist variety measures distinct known artists within a list. It does not measure acoustic variety or listener preference.',
      catalogue_coverage: 'Catalogue coverage measures distinct songs recommended across this fixed-size sample, relative to the training catalogue.'
    }[metric];
    if ($('final-seed-tempo-note')) {
      const count = report[partition].budgets[20].tempo_eligible;
      $('final-seed-tempo-note').hidden = !['tempo', 'all'].includes(comparison);
      $('final-seed-tempo-note').textContent = `The BPM window needs at least two known seed tempos. At one seed the BPM arm uses the ordinary final pipeline, so those curves coincide. At 20 seeds, ${count} of ${report[partition].queries} requests have enough tempo evidence. No hidden song determines the tempo target.`;
    }
    renderDiagnostics(partition);
  }
  for (const id of ['final-seed-partition', 'final-seed-metric', 'final-seed-k', 'final-seed-comparison']) $(id).addEventListener('change', render);
  render();
}());
