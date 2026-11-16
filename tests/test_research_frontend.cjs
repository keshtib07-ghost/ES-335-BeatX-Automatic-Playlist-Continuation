'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');
const { chooseBudget, toyScores, rankingMetrics } = require('../docs/research.js');

// Moving identical hits changes rank-sensitive NDCG, not set-based recovery.
const refs = ['R1', 'R2', 'R3'];
const early = rankingMetrics(['R1', 'R2', 'X1', 'X2', 'X3'], refs, 5);
const late = rankingMetrics(['X1', 'X2', 'X3', 'R1', 'R2'], refs, 5);
const none = rankingMetrics(['X1', 'X2', 'X3', 'X4', 'X5'], refs, 5);
assert.equal(early.recall, 2 / 3);
assert.equal(early.precision, 2 / 5);
assert.equal(early.hitRate, 1);
assert.equal(late.recall, early.recall);
assert(early.ndcg > late.ndcg && late.ndcg > 0);
assert.equal(none.ndcg, 0);
assert.equal(none.hitRate, 0);
assert.equal(rankingMetrics(['R1', 'R2', 'R3'], refs, 5).ndcg, 1);

// Unknown context and zero weight must reproduce plain CF, with no negative-lift penalty.
const plain = toyScores(10, 0, true);
const unknown = toyScores(10, 2, false);
assert.deepEqual(plain.map((r) => [r.name, r.final]), unknown.map((r) => [r.name, r.final]));
assert.equal(plain[0].name, 'Track A');
const contextual = toyScores(10, 1, true);
assert.equal(contextual[0].name, 'Track B');
assert.equal(contextual.find((r) => r.name === 'Track A').bonus, 0);
assert(toyScores(50, 0, false).every((r) => r.cf < plain.find((p) => p.name === r.name).cf));

// Select on validation only, using actual budgets rather than a test-peak heuristic.
const context = { window: {} };
vm.runInNewContext(fs.readFileSync(path.join(__dirname, '../docs/seed_experiment.js'), 'utf8'), context);
const study = context.window.NEXT_TRACK_SEED_STUDY;
const values = study.seed_budgets.map((n) => study.validation.budgets[n].all_queries.learned_title.ndcg_at_20);
assert.equal(chooseBudget(study.seed_budgets, values, .95).budget, study.chosen_seed_budget);
assert.equal(chooseBudget([1, 2, 5], [.1, .4, .5], .8).budget, 2);
assert.equal(chooseBudget([1, 2, 5], [.1, .4, .5], 1).budget, 5);

// Check the report's substantive marginal-gain and case claims against the saved data.
for (const partition of ['validation', 'test']) {
  let previous = null, previousPerSeed = Infinity;
  for (const n of study.seed_budgets) {
    const b = study[partition].budgets[n], score = b.all_queries.learned_title.ndcg_at_20;
    assert.equal(b.tag_effect.improved + b.tag_effect.worsened + b.tag_effect.unchanged, study[partition].queries);
    if (previous) {
      const gain = b.marginal_seed_gain;
      assert(Math.abs(gain.ndcg_delta - (score - previous.score)) < 1e-12);
      assert(Math.abs(gain.ndcg_per_added_seed - gain.ndcg_delta / (n - previous.n)) < 1e-12);
      assert(gain.ndcg_per_added_seed < previousPerSeed);
      previousPerSeed = gain.ndcg_per_added_seed;
    }
    previous = { n, score };
  }
}
assert.equal(study.test.cases.first_zero_hit.withheld_in_cf_candidates, 0);
assert.equal(study.test.cases.first_zero_hit.withheld_seen_in_training, 4);
console.log('Research arithmetic, abstention, validation selection and saved-report claims passed.');
