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
  const LABELS = {...METRICS, artist_diversity: 'Artist variety', catalogue_coverage: 'Catalogue coverage'};
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
    const chart = svg('svg', {viewBox: '0 0 760 310', role: 'img', 'aria-label': `${LABELS[metric]} by K. The exact selected values follow in the table.`});
    chart.append(svg('title', {}, `${LABELS[metric]} as K changes`));
    const left = 64, right = 730, top = 26, bottom = 255;
    const maximum = metric === 'catalogue_coverage' ? Math.max(.00001, ...series.flatMap((row) => row.values)) * 1.12 : 1;
    const x = (k) => left + (k - 1) / 19 * (right - left);
    const y = (v) => bottom - v / maximum * (bottom - top);
    [0, .25, .5, .75, 1].map((fraction) => fraction * maximum).forEach((v) => {
      chart.append(svg('line', {x1: left, x2: right, y1: y(v), y2: y(v), class: 'grid'}));
      chart.append(svg('text', {x: left - 9, y: y(v) + 4, 'text-anchor': 'end'}, metric === 'catalogue_coverage' ? percent(v) : v.toFixed(2)));
    });
    [1, 5, 10, 15, 20].forEach((k) => chart.append(svg('text', {x: x(k), y: bottom + 22, 'text-anchor': 'middle'}, k)));
    chart.append(svg('line', {x1: x(selectedK), x2: x(selectedK), y1: top, y2: bottom, stroke: '#fff', 'stroke-dasharray': '4 4'}));
    series.forEach((row) => {
      chart.append(svg('polyline', {points: row.values.map((v, i) => `${x(i + 1)},${y(v)}`).join(' '), fill: 'none', stroke: row.color, 'stroke-width': 2.5}));
      const dot = svg('circle', {cx: x(selectedK), cy: y(row.values[selectedK - 1]), r: 5, fill: row.color});
      dot.append(svg('title', {}, `${row.label} at K=${selectedK}: ${fixed(row.values[selectedK - 1])}`)); chart.append(dot);
    });
    chart.append(svg('text', {x: left, y: 16}, LABELS[metric]));
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
    }), `One saved playlist with ${item.seeds} seeds and ${item.withheld_tracks} hidden songs`);
    $('cutoff-note').textContent = `The hidden set stays at ${item.withheld_tracks} songs for every K. Increasing K checks more of the same recommendation list. These scores are calculated from the saved hit positions.`;
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
    $('eda-support-note').textContent = `Ranges count playlist memberships per song. Bar lengths use ${log ? 'log10(count + 1)' : 'raw counts'}; labels show actual song counts. The most frequent 1% account for ${percent(head)} of ${full ? 'training' : 'pilot'} memberships. ${full ? 'This song histogram stays on training data when the playlist-shape selector changes split.' : ''}`;
    const stats = full ? [['Playlists', eda.playlists], ['Training tracks', support.total],
      ['Training songs seen once', support.counts[support.labels.indexOf('1–1')]],
      ['Exact-copy groups', Object.values(eda.partitions).reduce((total, row) => total + row.duplicate_group_size.total, 0)]] :
      [['Pilot playlists', eda.playlists], ['Distinct tracks', part.distinct_tracks], ['Median length', part.playlist_length_quantiles.median], ['Repeated occurrences removed', eda.repeat_occurrences_removed]];
    $('eda-stats').replaceChildren();
    stats.forEach(([label, value]) => {const card = element('article'); card.append(element('strong', number(value)), element('span', label)); $('eda-stats').append(card);});
    $('eda-quality').textContent = full ? `The most frequent 1% of training songs account for ${percent(head)} of training memberships. Nearly half of training songs appear in just one playlist. This helps explain why popularity alone is limited and why rare songs have weak co-occurrence evidence. Split plots are descriptive; they do not choose model settings.` :
      `This pilot contains ${number(part.singleton_tracks)} songs seen in just one playlist. Exact set grouping finds ${part.extra_exact_group_members} extra copies. ${part.non_ascii_titles} titles contain non-ASCII characters; this is not a language label.`;
    $('eda-download').href = full ? 'data/research/eda_full.json' : 'data/research/eda_pilot.json';
  }
  const CASE_NAMES = {title_only_study: 'Title only: study', title_only_gym: 'Title only: gym', no_context: 'No usable context', unknown_seed: 'Unknown seed', mixed_seeds: 'Known + unknown seed', known_study: 'Known seeds: study', conflicting_title: 'Same seeds: gym title', explicit_gym: 'Explicit gym filter', explicit_conflict: 'Selected study vs gym title', restrictive_tempo: 'Tempo 299–300 BPM', duplicate_seeds: 'Duplicate seed input'};
  function renderAudit() {
    const report = data.studio_audit;
    if (!report) { $('studio-audit-status').textContent = 'No live-audit export is available.'; return; }
    $('studio-audit-status').textContent = `${report.cases.length} fixed requests checked on ${report.measured_utc.slice(0, 10)}. ${report.all_contract_checks_passed ? 'Every response met the expected API checks.' : 'A response failed an API check; see the table.'} These requests test specific difficult inputs. They do not estimate how often a user will encounter a problem.`;
    bars($('studio-audit-chart'), report.cases.filter((row) => row.http_status === 200).map((row) => ({label: CASE_NAMES[row.case], value: row.results, color: row.results ? '#84b8ff' : '#f4a8c4'})));
    table($('studio-audit-table'), ['Request', 'Results', 'Known seeds', 'Artist variety', 'What happened'], report.cases.map((row) => [
      CASE_NAMES[row.case], row.results, row.known_seeds === null ? 'Input rejected' : `${row.known_seeds}/${row.request.seeds.length}`,
      row.artist_diversity === null ? 'No list' : percent(row.artist_diversity), row.note || 'Generated from seed evidence.']
    ), 'Live Studio behavior. Artist variety = distinct known artists / known-artist result slots.');
  }
  const MODEL_LABELS = {popularity: 'Popularity baseline', cf: 'CF baseline', standard_title: 'Earlier title method', unified_no_title: 'Final pipeline without title', unified: 'Final pipeline', unified_seed_bpm: 'Final pipeline + BPM filter'};
  const COLORS = ['#aab7c2', '#84b8ff', '#f4a8c4', '#c5a8fa', '#cefb70', '#ffd47c'];
  function renderContextEffects() {
    if (!$('final-context-chart') || !data.studio_evaluation) return;
    const seeds = $('final-context-seeds')?.value || '20';
    const study = data.studio_seed_study;
    const scores = study ? study.test.budgets[seeds].cutoffs['20'] : data.studio_evaluation.cohorts.all_queries.cutoffs['20'];
    bars($('final-context-chart'), ['cf', 'unified_no_title', 'unified'].map(name => ({
      label: MODEL_LABELS[name], value: scores[name].ndcg,
      text: scores[name].ndcg.toFixed(5), color: COLORS[data.studio_evaluation.methods.indexOf(name)]
    })));
    if ($('final-context-note')) {
      const delta = scores.unified.ndcg - scores.unified_no_title.ndcg;
      $('final-context-note').textContent = `${study ? `Seed-count study: ${study.test.queries} test playlists; ${seeds} seeds` : 'Five-seed continuation test'}; K = 20. Title minus blank-title NDCG: ${delta >= 0 ? '+' : ''}${delta.toFixed(5)}. This is a descriptive ablation; no paired interval for that title-only difference was published.`;
    }
  }
  function renderEvaluation() {
    const report = data.studio_evaluation;
    if (!report) return;
    const cohort = report.cohorts[$('studio-evaluation-cohort').value], metric = $('studio-evaluation-metric').value;
    const evaluationMetrics = LABELS;
    if (!cohort.queries) { $('studio-evaluation-chart').textContent = 'No eligible queries in this subset.'; $('studio-evaluation-table').replaceChildren(); return; }
    const k = Number($('studio-evaluation-k').value);
    $('studio-evaluation-results').hidden = false;
    $('studio-evaluation-status').textContent = `${number(cohort.queries)} held-out queries; ${report.freeze.seeds} seeds each. Frozen settings were recorded before test scoring.`;
    const comparisons = {main: ['popularity', 'cf', 'unified'], context: ['cf', 'standard_title', 'unified_no_title', 'unified'], tempo: ['unified', 'unified_seed_bpm'], all: report.methods};
    const methods = comparisons[$('studio-evaluation-comparison')?.value || 'main'];
    const rows = methods.map((name) => ({label: MODEL_LABELS[name], color: COLORS[report.methods.indexOf(name)], values: report.cutoffs.map((n) => cohort.cutoffs[n][name][metric])}));
    curves($('studio-evaluation-chart'), rows, metric, k);
    table($('studio-evaluation-table'), ['Method', ...Object.values(evaluationMetrics).map((m) => `${m}@${k}`)], methods.map((name) => [MODEL_LABELS[name], ...Object.keys(evaluationMetrics).map((m) => fixed(cohort.cutoffs[k][name][m]))]));
    const ci = report.paired_unified_minus_cf_ndcg_at_20_95_ci;
    $('studio-evaluation-note').textContent = `All-query paired 95% interval for Studio minus CF NDCG@20: [${ci.map(fixed).join(', ')}]. Across all queries, ${report.unified_failures.zero_hit_queries} had no recovered song and ${report.unified_failures.short_outputs} returned fewer than 20 songs. These counts and the interval describe the full cohort, including when the graph shows a subset.`;
  }
  function renderStudioCase() {
    const report = data.studio_evaluation;
    if (!report) return;
    const name = $('studio-case').value, item = report.cases[name];
    if (!item) return;
    table($('studio-case-facts'), ['Known seeds', 'Hidden songs', 'Training-unseen references', 'CF candidate recall', 'Change in NDCG@20'], [[
      `${item.known_seeds}/${report.freeze.seeds}`, item.reference_count, item.unseen_references,
      percent(item.candidate_recall), item.ndcg_delta.toFixed(5)
    ]]);
    $('studio-case-ranks').replaceChildren();
    [['Plain CF', item.hit_ranks.cf], ['Studio', item.hit_ranks.unified]].forEach(([label, hits]) => {
      const line = element('div', undefined, 'research-rank-line');
      line.append(element('p', `${label}: ${hits.length} recovered songs`));
      const cells = element('div', undefined, 'research-rank-cells');
      for (let rank = 1; rank <= 20; rank++) {
        const cell = element('span', String(rank), hits.includes(rank) ? 'hit' : '');
        cell.setAttribute('aria-label', `Rank ${rank}: ${hits.includes(rank) ? 'held-out hit' : 'no recovery credit'}`);
        cells.append(cell);
      }
      line.append(cells); $('studio-case-ranks').append(line);
    });
    $('studio-case-reason').textContent = {
      largest_gain: 'Studio recovers 16 hidden songs versus CF’s 13. Only three of five seeds are training-known, and 22 hidden songs are absent from training. The saved ranks show a useful reranking gain; they do not verify the meaning of the inferred tags.',
      largest_loss: 'Both methods recover the same two songs. Studio moves the first hit from rank 1 to rank 2, so NDCG falls even though Recall stays at 1. This is a ranking loss rather than missing candidates.',
      first_zero_hit: 'All six hidden songs exist in the CF candidate pool. CF places one at rank 19; Studio places none in its first 20. Retrieval found the references, but the final ranking missed them.'
    }[name];
  }
  function renderStudioDiagnostics() {
    const report = data.studio_evaluation;
    if (!report) return;
    const all = report.cohorts.all_queries;
    bars($('studio-recovery-chart'), [
      {label: 'At least one recovered song', value: all.queries - report.unified_failures.zero_hit_queries, color: '#cefb70'},
      {label: 'No recovered song', value: report.unified_failures.zero_hit_queries, color: '#f4a8c4'}
    ]);
    bars($('studio-cold-chart'), ['all_seeds_known', 'some_seeds_unseen'].map((key) => {
      const cohort = report.cohorts[key];
      return {label: `${key === 'all_seeds_known' ? 'All seeds known' : 'Some seeds unseen'} (${cohort.queries} queries)`,
        value: cohort.cutoffs['20'].unified.ndcg,
        text: cohort.cutoffs['20'].unified.ndcg.toFixed(5), color: '#84b8ff'};
    }));
    const tempo = report.cohorts.seed_tempo_available;
    table($('studio-tempo-table'), ['Method', 'Recall@20', 'NDCG@20', 'Artist variety'], ['unified', 'unified_seed_bpm'].map((method) => {
      const value = tempo.cutoffs['20'][method];
      return [MODEL_LABELS[method], value.recall.toFixed(5), value.ndcg.toFixed(5), percent(value.artist_diversity)];
    }), `Same ${tempo.queries} queries with at least two known seed tempos`);
    renderStudioCase();
  }
  try {
    renderCutoff(); renderEDA(); renderAudit(); renderEvaluation(); renderStudioDiagnostics(); renderContextEffects();
    ['cutoff-case', 'cutoff-metric'].forEach((id) => $(id).addEventListener('change', renderCutoff));
    $('cutoff-k').addEventListener('input', renderCutoff);
    ['eda-dimension', 'eda-partition', 'eda-scale'].forEach((id) => $(id).addEventListener('change', renderEDA));
    ['studio-evaluation-metric', 'studio-evaluation-k', 'studio-evaluation-cohort', 'studio-evaluation-comparison'].forEach((id) => $(id)?.addEventListener('change', renderEvaluation));
    $('studio-case').addEventListener('change', renderStudioCase);
    $('final-context-seeds')?.addEventListener('change', renderContextEffects);
  } catch (error) {
    const status = $('research-status'); status.hidden = false;
    status.textContent = 'A chart could not load. The saved reports remain available below.';
    console.error(error);
  }
}());
