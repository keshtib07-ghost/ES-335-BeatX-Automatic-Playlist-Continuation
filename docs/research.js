/* Public aggregates are the sole source of measured values on this page. */
(function () {
  'use strict';
  const METHODS = [
    { key: 'popularity', label: 'Popularity', color: '#aab7c2', dash: '3 5' },
    { key: 'cf', label: 'Plain CF', color: '#84b8ff', dash: '' },
    { key: 'keyword_title', label: 'CF + keyword title', color: '#f4a8c4', dash: '7 4' },
    { key: 'learned_title', label: 'CF + learned title', color: '#cefb70', dash: '' }
  ];
  const METRICS = {
    ndcg_at_20: ['NDCG@20', 'Rewards recovering hidden songs near the top. A perfect ranking scores 1. Higher is better.'],
    recall_at_20: ['Recall@20', 'Fraction of hidden songs recovered in the first 20 recommendations. Higher is better.'],
    precision_at_20: ['Precision@20', 'Fraction of the first 20 recommendations that match hidden songs. Higher is better.'],
    hit_rate_at_20: ['Hit rate@20', 'Fraction of playlists with at least one hidden song recovered. Higher is better.'],
    artist_diversity: ['Artist diversity', 'Distinct artists divided by songs with known artists, averaged across playlists. This measures artist variety.'],
    catalogue_coverage: ['Catalogue coverage', 'Fraction of the training catalogue recommended at least once across the sample. Compare samples of the same size.'],
    popular_track_share: ['Top 1% share', 'Share of recommendations from the most frequent 1% of training songs. Lower means fewer popular songs, which does not by itself mean better recommendations.']
  };
  const pct = (x, places = 2) => `${(100 * x).toFixed(places)}%`;
  const num = (x, places = 4) => Number(x).toFixed(places);
  const signed = (x, places = 5) => `${x >= 0 ? '+' : '−'}${Math.abs(x).toFixed(places)}`;
  const count = (x) => Number(x).toLocaleString('en-US');
  const format = (metric, value) => ['catalogue_coverage', 'artist_diversity', 'popular_track_share', 'hit_rate_at_20'].includes(metric) ? pct(value) : num(value);

  function chooseBudget(budgets, values, fraction) {
    const peak = Math.max(...values);
    return { budget: budgets[values.findIndex((value) => value >= peak * fraction - 1e-12)], peak, target: peak * fraction };
  }
  function toyScores(shrinkage, weight, supported) {
    return [
      { name: 'Track A', frequency: 60, co: 12, lift: 0.7 },
      { name: 'Track B', frequency: 50, co: 10, lift: 2 },
      { name: 'Track C', frequency: 40, co: 4, lift: 1 }
    ].map((row) => {
      const cosine = row.co / Math.sqrt(100 * row.frequency);
      const shrink = row.co / (row.co + shrinkage);
      const cf = cosine * shrink;
      const bonus = supported ? Math.max(Math.log(row.lift), 0) : 0;
      return { ...row, cosine, shrink, cf, bonus, final: cf * (1 + weight * bonus) };
    }).sort((a, b) => b.final - a.final || a.name.localeCompare(b.name));
  }
  function rankingMetrics(ranking, references, k) {
    const hits = ranking.slice(0, k).map((track) => references.includes(track));
    const recovered = hits.filter(Boolean).length;
    const dcg = hits.reduce((sum, hit, i) => sum + (hit ? 1 / Math.log2(i + 2) : 0), 0);
    const idcg = Array.from({ length: Math.min(k, references.length) }, (_, i) => 1 / Math.log2(i + 2)).reduce((a, b) => a + b, 0);
    return { hits, recovered, dcg, idcg, recall: recovered / references.length, precision: recovered / k, hitRate: Number(recovered > 0), ndcg: idcg ? dcg / idcg : 0 };
  }
  // Export the actual educational arithmetic for small, independent correctness tests.
  if (typeof module !== 'undefined' && module.exports) module.exports = { chooseBudget, toyScores, rankingMetrics };
  if (typeof document === 'undefined') return;

  const $ = (id) => document.getElementById(id);
  const el = (tag, text, className) => {
    const node = document.createElement(tag);
    if (text !== undefined) node.textContent = text;
    if (className) node.className = className;
    return node;
  };
  function table(target, headers, rows, caption) {
    const node = el('table');
    if (caption) node.append(el('caption', caption));
    const head = el('thead'), tr = el('tr');
    headers.forEach((h) => { const th = el('th', h); th.scope = 'col'; tr.append(th); });
    head.append(tr); node.append(head);
    const body = el('tbody');
    rows.forEach((row) => {
      const r = el('tr');
      row.forEach((cell, i) => { const td = el(i === 0 ? 'th' : 'td', String(cell)); if (i === 0) td.scope = 'row'; r.append(td); });
      body.append(r);
    });
    node.append(body); target.replaceChildren(node);
  }
  function bars(target, rows, maximum = null) {
    const max = maximum || Math.max(...rows.map((r) => Math.abs(r.value))) * 1.1 || 1;
    target.replaceChildren();
    rows.forEach((row) => {
      const line = el('div', undefined, 'research-bar-row');
      const track = el('span', undefined, 'track');
      track.setAttribute('aria-hidden', 'true');
      const fill = el('span', undefined, 'fill');
      fill.style.width = `${Math.min(100, Math.abs(row.value) / max * 100)}%`;
      fill.style.setProperty('--bar-color', row.color || '#cefb70');
      track.append(fill); line.append(el('span', row.label), track, el('strong', row.formatted || num(row.value)));
      target.append(line);
    });
    target.append(el('p', `Bar scale: 0 to ${num(max)}. Exact values are shown beside each bar.`, 'research-caption'));
  }
  const NS = 'http://www.w3.org/2000/svg';
  function svgNode(tag, attrs, text) {
    const node = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([k, v]) => node.setAttribute(k, String(v)));
    if (text !== undefined) node.textContent = text;
    return node;
  }
  function svgRoot(title, description, height = 330, width = 760) {
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, role: 'img', 'aria-label': `${title}. ${description}` });
    svg.append(svgNode('title', {}, title), svgNode('desc', {}, description));
    return svg;
  }
  function linePlot(target, budgets, series, metric) {
    const svg = svgRoot(`${METRICS[metric][0]} by visible seed count`, 'Exact values follow in the expandable data table. Curves use actual seed counts on the horizontal axis.');
    const left = 70, right = 735, top = 22, bottom = 277;
    const maxValue = Math.max(...series.flatMap((s) => s.values));
    const max = maxValue > 0.9 ? 1 : Math.max(maxValue * 1.13, 0.00001);
    const x = (n) => left + (n - budgets[0]) / (budgets.at(-1) - budgets[0]) * (right - left);
    const y = (v) => bottom - v / max * (bottom - top);
    for (let i = 0; i <= 4; i++) {
      const value = max * i / 4, yy = y(value);
      svg.append(svgNode('line', { x1: left, x2: right, y1: yy, y2: yy, class: 'grid' }));
      svg.append(svgNode('text', { x: left - 10, y: yy + 4, 'text-anchor': 'end' }, metric === 'catalogue_coverage' ? pct(value, 2) : num(value, 2)));
    }
    budgets.forEach((n) => {
      svg.append(svgNode('line', { x1: x(n), x2: x(n), y1: bottom, y2: bottom + 5, class: 'grid' }));
      svg.append(svgNode('text', { x: x(n), y: bottom + 22, 'text-anchor': 'middle' }, n));
    });
    svg.append(svgNode('text', { x: left, y: 12, class: 'axis-title' }, METRICS[metric][0]));
    svg.append(svgNode('text', { x: (left + right) / 2, y: 323, 'text-anchor': 'middle', class: 'axis-title' }, 'Visible seed songs (actual counts)'));
    series.forEach((s) => {
      const points = s.values.map((v, i) => `${x(budgets[i])},${y(v)}`).join(' ');
      svg.append(svgNode('polyline', { points, fill: 'none', stroke: s.color, 'stroke-width': 2.5, 'stroke-dasharray': s.dash || '' }));
      s.values.forEach((v, i) => {
        const point = svgNode('circle', { cx: x(budgets[i]), cy: y(v), r: 3.5, fill: s.color });
        point.append(svgNode('title', {}, `${s.label}, ${budgets[i]} seeds: ${format(metric, v)}`)); svg.append(point);
      });
    });
    target.replaceChildren(svg);
  }
  function composition(target, segments, label) {
    const bar = el('div', undefined, 'research-stacked');
    bar.setAttribute('role', 'img'); bar.setAttribute('aria-label', label);
    segments.forEach((s) => { const segment = el('span'); segment.style.flex = String(s.value); segment.style.background = s.color; segment.title = s.label; bar.append(segment); });
    target.replaceChildren(bar);
  }
  function pressed(attribute, selected) {
    document.querySelectorAll(`[${attribute}]`).forEach((button) => button.setAttribute('aria-pressed', String(button.getAttribute(attribute) === selected)));
  }
  function renderScoreLab() {
    const alpha = Number($('shrinkage').value), weight = Number($('tag-weight').value), known = $('context-known').checked;
    $('shrinkage-value').value = alpha; $('tag-weight-value').value = num(weight, 2);
    const scores = toyScores(alpha, weight, known);
    table($('score-lab'), ['Rank / track', 'Frequency', 'Co-occurrence', 'Cosine', 'Shrink factor', 'CF score', 'Lift', 'Positive log lift', 'Final score'], scores.map((s, i) => [`${i + 1}. ${s.name}`, s.frequency, s.co, num(s.cosine), num(s.shrink), num(s.cf), s.lift, num(s.bonus), num(s.final)]));
    $('score-lab-note').textContent = `${scores[0].name} ranks first. ${!known || weight === 0 ? 'Context adds no boost. The order follows CF scores.' : 'Context boosts Track B. Track A receives no context boost or penalty.'} Increasing α gives less weight to pairs seen together only a few times. With several seeds, the real model adds their CF scores before applying context.`;
  }
  function renderMetricLab(example = 'early') {
    const options = { early: ['R1', 'R2', 'X1', 'X2', 'X3'], late: ['X1', 'X2', 'X3', 'R1', 'R2'], none: ['X1', 'X2', 'X3', 'X4', 'X5'] };
    const ranking = options[example], result = rankingMetrics(ranking, ['R1', 'R2', 'R3'], 5);
    pressed('data-example', example); $('metric-ranking').replaceChildren();
    ranking.forEach((track, i) => { const node = el('li', track, result.hits[i] ? 'hit' : ''); node.append(el('small', result.hits[i] ? `hit · gain ${num(1 / Math.log2(i + 2), 3)}` : 'no credit')); $('metric-ranking').append(node); });
    $('metric-values').replaceChildren();
    [['Recall@5', result.recall], ['Precision@5', result.precision], ['Hit rate@5', result.hitRate], ['NDCG@5', result.ndcg]].forEach(([label, value]) => { const card = el('article'); card.append(el('strong', num(value)), el('span', label)); $('metric-values').append(card); });
    $('metric-calculation').textContent = `${result.recovered} of 3 hidden songs recovered: Recall = ${num(result.recall)}. Discounted gain (DCG) = ${num(result.dcg)}. The ideal gain for 3 hits is ${num(result.idcg)}, so NDCG = ${num(result.ndcg)}. Moving the same hits changes NDCG; the other scores stay the same.`;
  }

  const experiment = window.NEXT_TRACK_EXPERIMENT, study = window.NEXT_TRACK_SEED_STUDY, sequence = window.NEXT_TRACK_SEQUENCE;
  function fail(message) { $('research-status').hidden = false; $('research-status').textContent = message; }
  function setupScrollableViews() {
    // Fixed scientific axes and wide data tables remain readable on phones.
    // Explain the local scrolling and make it available from the keyboard.
    const regions = document.querySelectorAll('.research-plot, .table-wrap, .research-formula');
    regions.forEach((region, i) => {
      if (!region.hasAttribute('tabindex')) region.tabIndex = 0;
      region.classList.add('research-scroll-region');
      const hint = el('p', 'Swipe or scroll sideways for the full view. Keyboard: focus this area and use the arrow keys.', 'research-scroll-hint');
      hint.id = `research-scroll-hint-${i}`;
      region.insertAdjacentElement('afterend', hint);
      region.setAttribute('aria-describedby', [region.getAttribute('aria-describedby'), hint.id].filter(Boolean).join(' '));
      const refresh = () => { hint.hidden = region.scrollWidth <= region.clientWidth + 1; };
      refresh();
      if (typeof ResizeObserver !== 'undefined') {
        const observer = new ResizeObserver(refresh);
        observer.observe(region);
        [...region.children].forEach((child) => observer.observe(child));
      }
      if (typeof MutationObserver !== 'undefined') {
        new MutationObserver(refresh).observe(region, { childList: true, subtree: true });
      }
    });
  }
  if (!experiment || !study || !sequence) {
    fail('An experiment export could not be loaded. The written report and linked downloads remain available. Reload the page or inspect the three experiment scripts.');
    return;
  }
  const budgets = study.seed_budgets;
  function renderSeedStudy() {
    const partition = $('seed-partition').value, metric = $('seed-metric').value, data = study[partition];
    const series = METHODS.map((m) => ({ ...m, values: budgets.map((n) => data.budgets[n].all_queries[m.key][metric]) }));
    linePlot($('seed-curve'), budgets, series, metric);
    $('seed-description').textContent = `${count(data.queries)} ${partition} playlists; ${count(data.title_tagged_queries)} titles received tags. ${METRICS[metric][1]} All four methods are shown; keyword and learned-title curves can overlap.`;
    table($('seed-table'), ['Seeds', ...METHODS.map((m) => m.label)], budgets.map((n) => [n, ...METHODS.map((m) => format(metric, data.budgets[n].all_queries[m.key][metric]))]), `Experiment B · ${partition} · ${METRICS[metric][0]}`);
    const marginals = budgets.slice(1).map((n) => ({ n, ...data.budgets[n].marginal_seed_gain }));
    bars($('marginal-chart'), marginals.map((m) => ({ label: `${m.from_seeds} → ${m.n} seeds`, value: m.ndcg_per_added_seed, formatted: signed(m.ndcg_per_added_seed), color: '#cefb70' })));
    table($('marginal-table'), ['Seeds', 'Total ΔNDCG', '95% paired CI for total Δ', 'Δ per added seed'], marginals.map((m) => [`${m.from_seeds} → ${m.n}`, signed(m.ndcg_delta), `[${signed(m.paired_ndcg_95_ci[0])}, ${signed(m.paired_ndcg_95_ci[1])}]`, signed(m.ndcg_per_added_seed)]));
    $('marginal-note').textContent = `Gain in NDCG per extra seed on ${partition}. The table’s confidence intervals describe the total change between seed counts. This panel always uses NDCG, even when you select another metric for the curve.`;
    const low = data.budgets[1].all_queries.learned_title.ndcg_at_20, high = data.budgets[20].all_queries.learned_title.ndcg_at_20;
    $('seed-conclusion').textContent = `With learned title tags, ${partition} NDCG rises from ${num(low)} at 1 seed to ${num(high)} at 20. Each extra seed adds less on average, but going from 10 to 20 still helps. The validation rule selects ${study.chosen_seed_budget}. We did not test larger seed counts.`;
  }
  function renderSeedRule() {
    const fraction = Number($('seed-threshold').value) / 100;
    const values = budgets.map((n) => study.validation.budgets[n].all_queries.learned_title.ndcg_at_20);
    const choice = chooseBudget(budgets, values, fraction);
    $('seed-threshold-value').value = pct(fraction, 0);
    const large = el('strong', `${choice.budget} seeds`);
    $('seed-rule').replaceChildren(large, el('span', `Smallest tested count reaching ${num(choice.target)} NDCG (${pct(fraction, 0)} of the best validation score, ${num(choice.peak)}). The published 95% rule selects ${study.chosen_seed_budget} seeds.`));
  }
  let cohort = 'all_queries', metric = 'ndcg_at_20';
  const { eligible_queries_evaluated: benchmarkQueries, title_tagged_queries: taggedQueries } = experiment.sample;
  function renderBenchmark() {
    const names = [['popularity', 'Popularity', '#aab7c2'], ['collaborative_filtering', 'Collaborative filtering', '#84b8ff'], ['selected_tag_ranker', 'CF + learned title', '#cefb70']];
    const scores = experiment[cohort], cf = scores.collaborative_filtering[metric], hybrid = scores.selected_tag_ranker[metric];
    bars($('benchmark-chart'), names.map(([key, label, color]) => ({ label, color, value: scores[key][metric], formatted: format(metric, scores[key][metric]) })), 1);
    const queryLabel = cohort === 'all_queries' ? `${count(benchmarkQueries)} test playlists` : `${count(taggedQueries)} test playlists whose titles received tags`;
    $('benchmark-description').textContent = `${queryLabel} · ${METRICS[metric][1]} Each method receives the same three seeds and is scored against the same hidden songs.`;
    $('benchmark-delta').textContent = `Title minus CF: ${signed(hybrid - cf)} ${METRICS[metric][0]} (${signed(100 * (hybrid / cf - 1), 2)}% relative). ${metric === 'ndcg_at_20' ? 'The confidence interval for this difference is shown below.' : 'The saved benchmark has a confidence interval for NDCG only.'}`;
    pressed('data-cohort', cohort); pressed('data-metric', metric);
  }
  function renderIntervals() {
    const rows = [
      { label: `All ${count(benchmarkQueries)} queries`, key: 'all_queries', ci: experiment.tag_ranker_minus_cf_ndcg_95_ci_all, color: '#84b8ff' },
      { label: `${count(taggedQueries)} tagged queries`, key: 'title_tagged_queries', ci: experiment.tag_ranker_minus_cf_ndcg_95_ci_tagged, color: '#cefb70' }
    ].map((r) => ({ ...r, delta: experiment[r.key].selected_tag_ranker.ndcg_at_20 - experiment[r.key].collaborative_filtering.ndcg_at_20 }));
    const svg = svgRoot('Title minus CF: paired NDCG intervals', 'Two paired 95% confidence intervals. Exact bounds follow in the table.', 205, 480);
    const x = (v) => 120 + (v + 0.001) / 0.019 * 345;
    svg.append(svgNode('line', { x1: x(0), x2: x(0), y1: 15, y2: 145, stroke: '#b0bec9', 'stroke-dasharray': '3 4' }));
    [0, 0.005, 0.01, 0.015].forEach((v) => { svg.append(svgNode('text', { x: x(v), y: 172, 'text-anchor': 'middle' }, num(v, 3))); });
    rows.forEach((r, i) => {
      const y = 48 + i * 66;
      svg.append(svgNode('text', { x: 0, y: y + 4 }, i ? 'Tagged queries' : 'All queries'));
      svg.append(svgNode('line', { x1: x(r.ci[0]), x2: x(r.ci[1]), y1: y, y2: y, stroke: r.color, 'stroke-width': 3 }));
      r.ci.forEach((v) => svg.append(svgNode('line', { x1: x(v), x2: x(v), y1: y - 7, y2: y + 7, stroke: r.color, 'stroke-width': 2 })));
      svg.append(svgNode('circle', { cx: x(r.delta), cy: y, r: 5, fill: r.color }));
    });
    svg.append(svgNode('text', { x: 290, y: 201, 'text-anchor': 'middle', class: 'axis-title' }, 'Absolute ΔNDCG@20 (title − CF)'));
    $('interval-chart').replaceChildren(svg);
    table($('interval-table'), ['Cohort', 'Mean Δ', 'Paired 95% CI'], rows.map((r) => [r.label, signed(r.delta), `[${signed(r.ci[0])}, ${signed(r.ci[1])}]`]));
  }
  function renderAblation() {
    const n = Number($('ablation-budget').value), b = study.test.budgets[n];
    table($('ablation-table'), ['Method', 'All-query NDCG', 'Tagged-query NDCG', 'All-query Recall', 'Artist diversity'], METHODS.map((m) => [m.label, num(b.all_queries[m.key].ndcg_at_20, 6), num(b.title_tagged_queries[m.key].ndcg_at_20, 6), num(b.all_queries[m.key].recall_at_20), pct(b.all_queries[m.key].artist_diversity)]), `1,500 test playlists; 194 titles received tags · ${n} seeds`);
    const delta = b.all_queries.learned_title.ndcg_at_20 - b.all_queries.keyword_title.ndcg_at_20;
    $('ablation-note').textContent = `Classifier minus keyword-rule NDCG: ${signed(delta, 6)} across all playlists. The scores are close. Without a confidence interval for this difference, we cannot conclude that the classifier improves on the rules.`;
  }
  function renderTradeoff() {
    const method = METHODS.find((m) => m.key === $('tradeoff-method').value);
    const points = budgets.map((n) => ({ n, ...study.test.budgets[n].all_queries[method.key] }));
    const svg = svgRoot('NDCG versus catalogue coverage', 'Each point is a tested seed budget for the selected method. Exact values follow in the table.', 325);
    // Fixed axes make ranker changes comparable; the grey baseline remains visible near zero coverage.
    const left = 75, right = 730, top = 20, bottom = 265, xMax = 0.36, yMax = 0.01;
    const x = (v) => left + v / xMax * (right - left), y = (v) => bottom - v / yMax * (bottom - top);
    [0, 0.0025, 0.005, 0.0075, 0.01].forEach((v) => { svg.append(svgNode('line', { x1: left, x2: right, y1: y(v), y2: y(v), class: 'grid' }), svgNode('text', { x: left - 10, y: y(v) + 4, 'text-anchor': 'end' }, pct(v))); });
    [0, 0.1, 0.2, 0.3].forEach((v) => svg.append(svgNode('text', { x: x(v), y: bottom + 23, 'text-anchor': 'middle' }, num(v, 1))));
    svg.append(svgNode('text', { x: left, y: 12, class: 'axis-title' }, 'Catalogue coverage'), svgNode('text', { x: 410, y: 318, 'text-anchor': 'middle', class: 'axis-title' }, 'NDCG@20 →'));
    svg.append(svgNode('polyline', { points: points.map((p) => `${x(p.ndcg_at_20)},${y(p.catalogue_coverage)}`).join(' '), fill: 'none', stroke: method.color, 'stroke-width': 2 }));
    points.forEach((p, i) => {
      const dot = svgNode('circle', { cx: x(p.ndcg_at_20), cy: y(p.catalogue_coverage), r: 5, fill: method.color });
      dot.append(svgNode('title', {}, `${p.n} seeds: NDCG ${num(p.ndcg_at_20)}, coverage ${pct(p.catalogue_coverage, 3)}`)); svg.append(dot);
      // Popularity's near-identical points are deliberately labeled through the table rather than overlapping text.
      if (method.key !== 'popularity') svg.append(svgNode('text', { x: x(p.ndcg_at_20) + 8, y: y(p.catalogue_coverage) + (i % 2 ? 18 : -9), class: 'point-label' }, p.n));
    });
    $('tradeoff-chart').replaceChildren(svg);
    table($('tradeoff-table'), ['Seeds', 'NDCG@20', 'Unique tracks', 'Coverage', 'Artist diversity', 'Top 1% share'], points.map((p) => [p.n, num(p.ndcg_at_20), count(p.unique_recommended_tracks), pct(p.catalogue_coverage, 3), pct(p.artist_diversity), pct(p.popular_track_share)]), method.label);
  }
  function renderEffect() {
    const n = $('effect-budget').value, effect = study.test.budgets[n].tag_effect;
    composition($('effect-bar'), [
      { value: effect.improved, color: '#cefb70', label: 'Improved' },
      { value: effect.worsened, color: '#f4a8c4', label: 'Worsened' },
      { value: effect.unchanged, color: '#52606a', label: 'Unchanged' }
    ], `${n} seeds: ${effect.improved} improved, ${effect.worsened} worsened, ${effect.unchanged} unchanged out of 1500 queries.`);
    $('effect-counts').replaceChildren();
    [['Improved', effect.improved, '#cefb70'], ['Worsened', effect.worsened, '#f4a8c4'], ['Unchanged', effect.unchanged, '#b0bec9']].forEach(([label, value, color]) => {
      const node = el('div'); const strong = el('strong', count(value)); strong.style.color = color; node.append(strong, el('span', `${label} · ${pct(value / study.test.queries, 1)}`)); $('effect-counts').append(node);
    });
    const ci = effect.paired_ndcg_95_ci_tagged;
    $('effect-interval').textContent = `For the 194 playlists with tagged titles, the 95% confidence interval for title minus CF NDCG is [${signed(ci[0])}, ${signed(ci[1])}]. ${ci[0] <= 0 && ci[1] >= 0 ? 'It includes zero, so this comparison does not establish an average improvement.' : 'It excludes zero for this sample.'} This is from the seed-count study, which uses a different sample from the three-seed benchmark.`;
  }
  function renderCase() {
    const key = $('case-select').value, data = study.test.cases[key];
    const summary = $('case-summary'); summary.replaceChildren();
    if (!data) { summary.textContent = 'No published case for this selection.'; $('case-ranks').replaceChildren(); return; }
    [['Known seeds', `${data.known_seeds}/${data.seeds}`], ['Hidden songs', data.withheld_tracks], ['Hidden songs seen in training', data.withheld_seen_in_training], ['Hidden songs in shortlist', data.withheld_in_cf_candidates], ['Inferred tags', data.inferred_tag_count], ['ΔNDCG', signed(data.ndcg_delta)]].forEach(([label, value]) => { const node = el('span'); node.append(`${label}: `, el('strong', String(value))); summary.append(node); });
    $('case-ranks').replaceChildren();
    [['Plain CF', data.plain_hit_ranks], ['CF + learned title', data.tagged_hit_ranks]].forEach(([label, ranks]) => {
      const line = el('div', undefined, 'research-rank-line'); line.append(el('p', `${label} · ${ranks.length} hits`));
      const cells = el('div', undefined, 'research-rank-cells');
      for (let r = 1; r <= 20; r++) { const cell = el('span', String(r), ranks.includes(r) ? 'hit' : ''); cell.title = `Rank ${r}: ${ranks.includes(r) ? 'held-out hit' : 'no recovery credit'}`; cell.setAttribute('aria-label', cell.title); cells.append(cell); }
      line.append(cells); $('case-ranks').append(line);
    });
    $('case-reason').textContent = {
      largest_gain: 'The shortlist contains 23 of the 25 hidden songs. Title reranking brings more into the first 20 and moves recovered songs higher. The saved results show the ranking improvement, but do not tell us whether the inferred tags correctly describe the title.',
      largest_loss: 'The shortlist contains 33 of the 34 hidden songs. Title reranking recovers fewer of them and moves hits lower. The problem occurs during ranking. To identify a specific tag error, we would need the original title and each song’s score details.',
      first_zero_hit: 'All four hidden songs appeared in training, but none reaches the shortlist. The title receives no tags. Changing the order cannot recover a song missing from the list; the model needs a better way to find candidates.'
    }[key];
  }
  function renderSequence() {
    const data = sequence.evaluation;
    bars($('sequence-chart'), [
      { label: 'Seeded shuffle', value: data.random_adjacency_recall, formatted: pct(data.random_adjacency_recall), color: '#aab7c2' },
      { label: 'Training-transition order', value: data.ordered_adjacency_recall, formatted: pct(data.ordered_adjacency_recall), color: '#cefb70' }
    ], 1);
    $('sequence-note').textContent = `${data.eligible_test_sequences} of ${data.sampled_playlists} sampled test playlists were eligible. Directed adjacency recall improves by ${num(100 * (data.ordered_adjacency_recall - data.random_adjacency_recall), 2)} percentage points. ${pct(data.ordered_transitions_with_training_evidence)} of ordered transitions have training evidence. This scores next-song pairs among a fixed set of songs. Recommendation Recall@20 scores recovered hidden songs, so the two percentages are not comparable.`;
  }
  try {
    METHODS.forEach((m) => { const label = el('span'), swatch = el('i'); swatch.style.setProperty('--legend-color', m.color); label.append(swatch, m.label); $('seed-legend').append(label); });
    renderScoreLab(); renderMetricLab(); renderSeedStudy(); renderSeedRule(); renderBenchmark(); renderIntervals(); renderAblation(); renderTradeoff(); renderEffect(); renderCase(); renderSequence();
    const untaggedQueries = benchmarkQueries - taggedQueries;
    composition($('title-coverage'), [
      { value: taggedQueries, color: '#cefb70', label: `${count(taggedQueries)} tagged` },
      { value: untaggedQueries, color: '#52606a', label: `${count(untaggedQueries)} untagged` }
    ], `${pct(taggedQueries / benchmarkQueries, 2)} of titles receive an inferred tag. Untagged queries use plain CF.`);
    setupScrollableViews();
    ['shrinkage', 'tag-weight', 'context-known'].forEach((id) => $(id).addEventListener('input', renderScoreLab));
    document.querySelectorAll('[data-example]').forEach((b) => b.addEventListener('click', () => renderMetricLab(b.dataset.example)));
    ['seed-partition', 'seed-metric'].forEach((id) => $(id).addEventListener('change', renderSeedStudy));
    $('seed-threshold').addEventListener('input', renderSeedRule);
    document.querySelectorAll('[data-cohort]').forEach((b) => b.addEventListener('click', () => { cohort = b.dataset.cohort; renderBenchmark(); }));
    document.querySelectorAll('[data-metric]').forEach((b) => b.addEventListener('click', () => { metric = b.dataset.metric; renderBenchmark(); }));
    $('ablation-budget').addEventListener('change', renderAblation);
    $('tradeoff-method').addEventListener('change', renderTradeoff);
    $('effect-budget').addEventListener('change', renderEffect);
    $('case-select').addEventListener('change', renderCase);
  } catch (error) { fail('A research view could not be rendered. Download the linked public results or reload the page.'); console.error(error); }
}());
