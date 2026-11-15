'use strict';

const study = window.NEXT_TRACK_SEED_STUDY;
const sequenceStudy = window.NEXT_TRACK_SEQUENCE;
const studyMethods = [['popularity', 'Popularity'], ['cf', 'Plain CF'],
  ['keyword_title', 'CF + keywords'], ['learned_title', 'CF + learned tags']];
const studyMetrics = {
  ndcg_at_20: ['Rewards recovering reference songs near the top.', false],
  recall_at_20: ['Share of the fixed reference set recovered in the first 20 suggestions.', true],
  artist_diversity: ['Mean share of suggestions with a distinct artist among slots with known artist names.', true],
  catalogue_coverage: ['Distinct suggestions across the sample divided by the training catalogue. A fixed sample makes methods comparable.', true],
  popular_track_share: ['Mean share of a playlist’s suggestions from the most popular 1% of training tracks.', true],
};
const ratio = (number, digits = 2) => `${(100 * number).toFixed(digits)}%`;
const signed = (number) => `${number >= 0 ? '+' : ''}${number.toFixed(4)}`;

function studyRow(tag, labels) {
  const row = node('tr');
  for (const label of labels) row.append(node(tag, label));
  return row;
}

function renderStudy() {
  const metric = select('seed-metric').value;
  const format = studyMetrics[metric][1] ? (value) => ratio(value, 3) : (value) => value.toFixed(4);
  const table = select('seed-table');
  const thead = node('thead');
  thead.append(studyRow('th', ['Seeds', ...studyMethods.map(([, label]) => label)]));
  const body = node('tbody');
  const chart = [];
  const axisMax = Math.max(.000001, ...study.seed_budgets.flatMap((n) =>
    ['cf','learned_title'].map((key) => study.test.budgets[n].all_queries[key][metric])));
  for (const count of study.seed_budgets) {
    const values = study.test.budgets[count].all_queries;
    const row = studyRow('td', [String(count), ...studyMethods.map(([key]) => format(values[key][metric]))]);
    if (count === study.chosen_seed_budget) row.className = 'selected-budget';
    body.append(row);
    const group = node('div', undefined, 'seed-bar-group');
    const bars = node('div', undefined, 'seed-bar-pair');
    for (const key of ['cf','learned_title']) {
      const bar = node('i');
      bar.style.height = `${100 * values[key][metric] / axisMax}%`;
      bars.append(bar);
    }
    group.append(bars, node('span', String(count)));
    chart.push(group);
  }
  table.replaceChildren(thead, body);
  select('seed-curve').replaceChildren(...chart);
  select('seed-metric-description').textContent = studyMetrics[metric][0];
  const chosen = study.chosen_seed_budget;
  const first = study.test.budgets[study.seed_budgets[0]].all_queries.learned_title.ndcg_at_20;
  const last = study.test.budgets[study.seed_budgets.at(-1)].all_queries.learned_title.ndcg_at_20;
  select('seed-gain').textContent = `Validation selected ${chosen} seed${chosen === 1 ? '' : 's'} under the 95%-of-peak rule. On the fresh test sample, learned-tag NDCG@20 changes from ${first.toFixed(4)} at one seed to ${last.toFixed(4)} at twenty.`;
}

if (study) {
  select('seed-study-status').hidden = true;
  select('seed-study-content').hidden = false;
  select('seed-study-cohort').textContent = `${study.test.queries.toLocaleString()} fresh held-out playlists · same references at each budget`;
  select('seed-metric').addEventListener('change', renderStudy);
  renderStudy();
  const head = node('thead');
  head.append(studyRow('th', ['Seed change', 'Δ NDCG', 'Δ per added seed', 'Paired 95% interval']));
  const changes = node('tbody');
  for (const n of study.seed_budgets.slice(1)) {
    const row = study.test.budgets[n].marginal_seed_gain;
    if (row) changes.append(studyRow('td', [`${row.from_seeds} → ${n}`, signed(row.ndcg_delta),
      signed(row.ndcg_per_added_seed), row.paired_ndcg_95_ci.map(signed).join(' to ')]));
  }
  select('seed-marginal').replaceChildren(head, changes);
  const chosen = study.test.budgets[study.chosen_seed_budget];
  const effects = chosen.tag_effect;
  select('seed-audit').hidden = false;
  const tagged = chosen.title_tagged_queries;
  const taggedEffect = tagged.learned_title ? ` Among the ${study.test.title_tagged_queries} inferred-tag titles, mean NDCG changed by ${signed(tagged.learned_title.ndcg_at_20 - tagged.cf.ndcg_at_20)}.` : '';
  select('seed-audit-counts').textContent = `At ${study.chosen_seed_budget} seeds, reranking improved NDCG for ${effects.improved} queries, worsened it for ${effects.worsened}, and left ${effects.unchanged} unchanged.${taggedEffect} The cases below illustrate specific outcomes from this sample.`;
  const cases = [['largest_gain', 'Largest measured gain'], ['largest_loss', 'Largest measured loss'], ['first_zero_hit', 'A zero-hit query']];
  for (const [key, heading] of cases) {
    const value = study.test.cases[key];
    const card = node('article');
    card.append(node('h3', heading));
    if (value) {
      const before = value.plain_hit_ranks.join(', ') || 'none';
      const after = value.tagged_hit_ranks.join(', ') || 'none';
      card.append(node('p', `Hit ranks went from ${before} to ${after}. NDCG change ${signed(value.ndcg_delta)}.`),
        node('p', `${value.withheld_in_cf_candidates} of ${value.withheld_tracks} reference tracks reached the CF candidate pool.`));
    } else card.append(node('p', 'No case of this type occurred in the measured sample.'));
    select('seed-cases').append(card);
  }
}

if (sequenceStudy) {
  const result = sequenceStudy.evaluation;
  select('sequence-study-status').textContent = `Matched ${ratio(result.ordered_adjacency_recall)} of original directed adjacencies versus ${ratio(result.random_adjacency_recall)} for shuffled order, across ${result.eligible_test_sequences} held-out playlists. This measures recovery of original order with known tracks.`;
}
