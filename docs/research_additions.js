/* Every measured view below reads a saved report. No scores are invented. */
(function () {
  'use strict';
  function scoresFromHitRanks(hitRanks, referenceCount, k) {
    if (!Number.isInteger(k) || k < 1 || referenceCount < 1) throw new Error('Invalid metric inputs');
    const hits = hitRanks.filter((rank) => rank <= k);
    const dcg = hits.reduce((sum, rank) => sum + 1 / Math.log2(rank + 1), 0);
    const ideal = Array.from({length: Math.min(k, referenceCount)}, (_, i) => 1 / Math.log2(i + 2)).reduce((a, b) => a + b, 0);
    return {recall: hits.length / referenceCount, ndcg: dcg / ideal,
      precision: hits.length / k, hit_rate: Number(hits.length > 0)};
  }
  if (typeof module !== 'undefined' && module.exports) module.exports = {scoresFromHitRanks};
  if (typeof document === 'undefined') return;
  const data = window.BEATX_RESEARCH_ADDITIONS || {};
  const $ = (id) => document.getElementById(id);
  const number = (v) => Number(v).toLocaleString('en-US');
  const fixed = (v) => Number(v).toFixed(4);
  const percent = (v) => `${(100 * v).toFixed(2)}%`;
  const METRICS = {recall: 'Recall', ndcg: 'NDCG', precision: 'Precision', hit_rate: 'Hit rate'};
  function element(tag, text, cls) {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (cls) node.className = cls;
    return node;
  }
  function table(target, headers, rows, caption) {
    const result = element('table'), head = element('thead'), body = element('tbody');
    if (caption) result.append(element('caption', caption));
    const heading = element('tr');
    headers.forEach((name) => {const cell = element('th', name); cell.scope = 'col'; heading.append(cell);});
    head.append(heading);
    rows.forEach((row) => {
      const line = element('tr');
      row.forEach((value, i) => {const cell = element(i ? 'td' : 'th', String(value)); if (!i) cell.scope = 'row'; line.append(cell);});
      body.append(line);
    });
    result.append(head, body); target.replaceChildren(result);
  }
  function bars(target, rows, log = false) {
    const transform = (value) => log ? Math.log10(value + 1) : value;
    const maximum = Math.max(...rows.map((r) => transform(r.value)), 1);
    target.replaceChildren();
    rows.forEach((row) => {
      const line = element('div', undefined, 'research-bar-row');
      const track = element('span', undefined, 'track'), fill = element('span', undefined, 'fill');
      track.setAttribute('aria-hidden', 'true');
      fill.style.width = `${transform(row.value) / maximum * 100}%`;
      fill.style.setProperty('--bar-color', row.color || '#cefb70');
      track.append(fill); line.append(element('span', row.label), track, element('strong', row.text || number(row.value)));
      target.append(line);
    });
  }
  const NS = 'http://www.w3.org/2000/svg';
  function svg(tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => node.setAttribute(key, String(value)));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function curves(target, series, metric, selectedK) {
    const chart = svg('svg', {viewBox: '0 0 760 310', role: 'img', 'aria-label': `${(METRICS[metric] || metric)} by K. The exact selected values follow in the table.`});
    chart.append(svg('title', {}, `${(METRICS[metric] || metric)} as K changes`));
    const left = 64, right = 730, top = 26, bottom = 255;
    const x = (k) => left + (k - 1) / 19 * (right - left);
    const y = (v) => bottom - v * (bottom - top);
    [0, .25, .5, .75, 1].forEach((v) => {
      chart.append(svg('line', {x1: left, x2: right, y1: y(v), y2: y(v), class: 'grid'}));
      chart.append(svg('text', {x: left - 9, y: y(v) + 4, 'text-anchor': 'end'}, v.toFixed(2)));
    });
    [1, 5, 10, 15, 20].forEach((k) => chart.append(svg('text', {x: x(k), y: bottom + 22, 'text-anchor': 'middle'}, k)));
    chart.append(svg('line', {x1: x(selectedK), x2: x(selectedK), y1: top, y2: bottom, stroke: '#fff', 'stroke-dasharray': '4 4'}));
    series.forEach((row) => {
      chart.append(svg('polyline', {points: row.values.map((v, i) => `${x(i + 1)},${y(v)}`).join(' '), fill: 'none', stroke: row.color, 'stroke-width': 2.5}));
      const dot = svg('circle', {cx: x(selectedK), cy: y(row.values[selectedK - 1]), r: 5, fill: row.color});
      dot.append(svg('title', {}, `${row.label} at K=${selectedK}: ${fixed(row.values[selectedK - 1])}`)); chart.append(dot);
    });
    chart.append(svg('text', {x: left, y: 16}, METRICS[metric] || metric));
    chart.append(svg('text', {x: 400, y: 304, 'text-anchor': 'middle'}, 'K: number of recommendations inspected'));
    const legend = element('div', undefined, 'research-legend');
    series.forEach((row) => {
      const label = element('span'), swatch = element('i');
      swatch.style.setProperty('--legend-color', row.color);
      label.append(swatch, row.label); legend.append(label);
    });
    target.replaceChildren(chart, legend);
  }
  function renderCutoff() {
    const study = window.NEXT_TRACK_SEED_STUDY;
    const item = study.test.cases[$('cutoff-case').value];
    const k = Number($('cutoff-k').value), metric = $('cutoff-metric').value;
    $('cutoff-k-value').value = k;
    const methods = [
      {label: 'Plain CF', ranks: item.plain_hit_ranks, color: '#84b8ff'},
      {label: 'CF + title', ranks: item.tagged_hit_ranks, color: '#cefb70'}
    ];
    const series = methods.map((row) => ({...row, values: Array.from({length: 20}, (_, i) => scoresFromHitRanks(row.ranks, item.withheld_tracks, i + 1)[metric])}));
    curves($('cutoff-chart'), series, metric, k);
    table($('cutoff-table'), ['Method', `Recall@${k}`, `NDCG@${k}`, `Precision@${k}`, `Hit rate@${k}`], methods.map((row) => {
      const score = scoresFromHitRanks(row.ranks, item.withheld_tracks, k);
      return [row.label, ...['recall', 'ndcg', 'precision', 'hit_rate'].map((m) => fixed(score[m]))];
    }), `One saved ${item.seeds}-seed query; ${item.withheld_tracks} reference tracks`);
    $('cutoff-note').textContent = `The same ${item.withheld_tracks} hidden tracks remain the reference set at every K. Only the inspected ranking prefix changes. Values are calculated from the recorded hit positions.`;
  }
  function renderEDA() {
    const eda = data.eda;
    if (!eda) { $('eda-scope').textContent = 'No measured EDA export is available.'; return; }
    const full = eda.kind === 'full_staging_eda';
    $('eda-scope').textContent = eda.scope;
    $('eda-partition-label').hidden = !full;
    const part = full ? eda.partitions[$('eda-partition').value] : eda.all_playlists;
    const dimension = $('eda-dimension').value, distribution = part[dimension];
    const rows = distribution.labels.map((label, i) => ({label, value: distribution.counts[i]}));
    bars($('eda-shape-chart'), rows);
    table($('eda-shape-table'), ['Range', 'Count', 'Share'], rows.map((row) => [row.label, number(row.value), percent(row.value / distribution.total)]), `${number(distribution.total)} ${dimension === 'duplicate_group_size' ? 'groups' : 'playlists'}`);
    const support = full ? eda.training_track_support : part.track_support;
    const log = $('eda-scale').value === 'log';
    bars($('eda-support-chart'), support.labels.map((label, i) => ({label, value: support.counts[i]})), log);
    const head = full ? eda.top_one_percent_membership_share : part.top_one_percent_membership_share;
    $('eda-support-note').textContent = `X ranges count playlist memberships per song. Bar lengths use ${log ? 'log10(count + 1)' : 'raw counts'}; labels show actual song counts. The most frequent 1% of songs account for ${percent(head)} of memberships in this scope.`;
    const stats = full ? [['Playlists', eda.playlists], ['Training tracks', support.total]] :
      [['Pilot playlists', eda.playlists], ['Distinct tracks', part.distinct_tracks], ['Median length', part.playlist_length_quantiles.median], ['Repeated occurrences removed', eda.repeat_occurrences_removed]];
    $('eda-stats').replaceChildren();
    stats.forEach(([label, value]) => {const card = element('article'); card.append(element('strong', number(value)), element('span', label)); $('eda-stats').append(card);});
    $('eda-quality').textContent = full ? 'Each plot uses the existing split. No preprocessing choices are selected from these distributions.' :
      `This pilot contains ${number(part.singleton_tracks)} songs seen in just one playlist. Exact set grouping finds ${part.extra_exact_group_members} extra copies. ${part.non_ascii_titles} titles contain non-ASCII characters; this is not a language label.`;
    $('eda-download').href = full ? 'data/research/eda_full.json' : 'data/research/eda_pilot.json';
  }
  const CASE_NAMES = {title_only_study: 'Title only: study', title_only_gym: 'Title only: gym', no_context: 'No usable context', unknown_seed: 'Unknown seed', mixed_seeds: 'Known + unknown seed', known_study: 'Known seeds: study', conflicting_title: 'Same seeds: gym title', explicit_gym: 'Explicit gym filter', explicit_conflict: 'Selected study vs gym title', restrictive_tempo: 'Tempo 299–300 BPM', duplicate_seeds: 'Duplicate seed input'};
  function renderAudit() {
    const report = data.studio_audit;
    if (!report) { $('studio-audit-status').textContent = 'No live-audit export is available.'; return; }
    $('studio-audit-status').textContent = `${report.cases.length} fixed requests checked on ${report.measured_utc.slice(0, 10)}. ${report.all_contract_checks_passed ? 'All API contract checks passed.' : 'A contract check failed; inspect the table.'} These requests are deliberately chosen edge cases, not a random user sample.`;
    bars($('studio-audit-chart'), report.cases.filter((row) => row.http_status === 200).map((row) => ({label: CASE_NAMES[row.case], value: row.results, color: row.results ? '#84b8ff' : '#f4a8c4'})));
    table($('studio-audit-table'), ['Request', 'Results', 'Known seeds', 'Artist variety', 'What happened'], report.cases.map((row) => [
      CASE_NAMES[row.case], row.results, row.known_seeds === null ? 'Input rejected' : `${row.known_seeds}/${row.request.seeds.length}`,
      row.artist_diversity === null ? 'No list' : percent(row.artist_diversity), row.note || 'Generated from seed evidence.']
    ), 'Live Studio behavior. Artist variety = distinct known artists / known-artist result slots.');
  }
  const MODEL_LABELS = {popularity: 'Popularity', cf: 'Plain CF', standard_title: 'Standard title model', unified_no_title: 'Studio without title', unified: 'Studio', unified_seed_bpm: 'Studio + seed BPM'};
  const COLORS = ['#aab7c2', '#84b8ff', '#f4a8c4', '#c5a8fa', '#cefb70', '#ffd47c'];
  function renderEvaluation() {
    const report = data.studio_evaluation;
    if (!report) return;
    const cohort = report.cohorts[$('studio-evaluation-cohort').value], metric = $('studio-evaluation-metric').value;
    const evaluationMetrics = {...METRICS, artist_diversity: 'Artist variety', catalogue_coverage: 'Catalogue coverage'};
    if (!cohort.queries) { $('studio-evaluation-chart').textContent = 'No eligible queries in this subset.'; $('studio-evaluation-table').replaceChildren(); return; }
    const k = Number($('studio-evaluation-k').value);
    $('studio-evaluation-results').hidden = false;
    $('studio-evaluation-status').textContent = `${number(cohort.queries)} held-out queries; ${report.freeze.seeds} seeds each. Frozen settings were recorded before test scoring.`;
    const rows = report.methods.map((name, i) => ({label: MODEL_LABELS[name], color: COLORS[i], values: report.cutoffs.map((n) => cohort.cutoffs[n][name][metric])}));
    curves($('studio-evaluation-chart'), rows, metric, k);
    table($('studio-evaluation-table'), ['Method', ...Object.values(evaluationMetrics).map((m) => `${m}@${k}`)], report.methods.map((name) => [MODEL_LABELS[name], ...Object.keys(evaluationMetrics).map((m) => fixed(cohort.cutoffs[k][name][m]))]));
    const ci = report.paired_unified_minus_cf_ndcg_at_20_95_ci;
    $('studio-evaluation-note').textContent = `All-query paired 95% interval for Studio minus CF NDCG@20: [${ci.map(fixed).join(', ')}]. Across all queries, ${report.unified_failures.zero_hit_queries} had no recovered song and ${report.unified_failures.short_outputs} returned fewer than 20 songs. These counts and the interval describe the full cohort, including when the graph shows a subset.`;
  }
  try {
    renderCutoff(); renderEDA(); renderAudit(); renderEvaluation();
    ['cutoff-case', 'cutoff-metric'].forEach((id) => $(id).addEventListener('change', renderCutoff));
    $('cutoff-k').addEventListener('input', renderCutoff);
    ['eda-dimension', 'eda-partition', 'eda-scale'].forEach((id) => $(id).addEventListener('change', renderEDA));
    ['studio-evaluation-metric', 'studio-evaluation-k', 'studio-evaluation-cohort'].forEach((id) => $(id).addEventListener('change', renderEvaluation));
  } catch (error) {
    const status = $('research-status'); status.hidden = false;
    status.textContent = 'A chart could not load. The saved reports remain available below.';
    console.error(error);
  }
}());
