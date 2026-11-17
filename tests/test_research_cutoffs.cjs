'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {scoresFromHitRanks} = require('../docs/research_additions.js');
const context = {window: {}};
vm.runInNewContext(fs.readFileSync(require.resolve('../docs/seed_experiment.js'), 'utf8'), context);
const cases = context.window.NEXT_TRACK_SEED_STUDY.test.cases;
for (const item of Object.values(cases)) {
  if (!item) continue;
  const cf = scoresFromHitRanks(item.plain_hit_ranks, item.withheld_tracks, 20);
  const tagged = scoresFromHitRanks(item.tagged_hit_ranks, item.withheld_tracks, 20);
  assert(Math.abs(tagged.ndcg - cf.ndcg - item.ndcg_delta) < 1e-12);
  for (const ranks of [item.plain_hit_ranks, item.tagged_hit_ranks]) {
    let prior = {recall: 0, hit_rate: 0};
    for (let k = 1; k <= 20; k++) {
      const score = scoresFromHitRanks(ranks, item.withheld_tracks, k);
      assert(score.recall >= prior.recall && score.hit_rate >= prior.hit_rate);
      assert(Object.values(score).every((value) => value >= 0 && value <= 1));
      prior = score;
    }
  }
}
assert.equal(scoresFromHitRanks([1], 3, 20).precision, .05);
assert.equal(scoresFromHitRanks([], 3, 20).ndcg, 0);
console.log('K-dependent scores match the actual saved cases.');
