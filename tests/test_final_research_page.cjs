'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const {seedView} = require('../docs/studio_seed_study.js');
const docs = path.join(__dirname, '../docs');

class Element {
  constructor(tag = 'div') {
    this.tagName = tag.toUpperCase(); this.children = []; this.attributes = {}; this.listeners = {};
    this.style = {setProperty() {}}; this.classList = {add() {}}; this.value = ''; this.hidden = false;
    this._text = ''; this.dataset = {};
  }
  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this._text = ''; this.children = [...nodes]; }
  set textContent(text) { this._text = String(text); this.children = []; }
  get textContent() { return this._text + this.children.map(child => typeof child === 'string' ? child : child.textContent).join(''); }
  setAttribute(name, value) { this.attributes[name] = String(value); }
  getAttribute(name) { return this.attributes[name] ?? null; }
  hasAttribute(name) { return name in this.attributes; }
  addEventListener(name, fn) { this.listeners[name] = fn; }
}

function pageFixture() {
  const html = fs.readFileSync(path.join(docs, 'research-deep-dive.html'), 'utf8');
  const elements = new Map();
  for (const match of html.matchAll(/<([a-z0-9]+)\b([^>]*\bid="([^"]+)"[^>]*)>/g)) {
    const element = new Element(match[1]);
    element.hidden = /\bhidden\b/.test(match[2]);
    element.value = /\bvalue="([^"]*)"/.exec(match[2])?.[1] || '';
    element.checked = /\bchecked\b/.test(match[2]);
    elements.set(match[3], element);
  }
  for (const match of html.matchAll(/<select\b[^>]*\bid="([^"]+)"[^>]*>(.*?)<\/select>/gs)) {
    const options = [...match[2].matchAll(/<option([^>]*)>(.*?)<\/option>/gs)];
    const selected = options.find(option => /\bselected\b/.test(option[1])) || options[0];
    elements.get(match[1]).value = /\bvalue="([^"]*)"/.exec(selected[1])?.[1] || selected[2];
  }
  const errors = [];
  const context = vm.createContext({window: {addEventListener() {}}, location: {hash: ''},
    requestAnimationFrame: fn => fn(), console: {error: e => errors.push(String(e))},
    document: {getElementById: id => elements.get(id) || null, querySelectorAll: () => [],
      createElement: tag => new Element(tag), createElementNS: (_, tag) => new Element(tag)}});
  for (const file of ['experiment.js', 'seed_experiment.js', 'sequence_experiment.js',
    'research.js', 'research_extra_data.js', 'research_additions.js', 'studio_seed_study.js']) {
    vm.runInContext(fs.readFileSync(path.join(docs, file), 'utf8'), context);
  }
  return {elements, errors, context, html};
}

test('final results render first and retain all earlier graph controls', () => {
  const f = pageFixture();
  assert.deepEqual(f.errors, []);
  assert.equal(f.elements.get('research-status').hidden, true);
  assert.equal(f.elements.get('studio-evaluation-results').hidden, false);
  const chart = f.elements.get('studio-evaluation-chart');
  assert.equal(chart.children[0].tagName, 'SVG');
  assert.match(chart.textContent, /Final pipeline/);
  assert.match(f.elements.get('seed-description').textContent, /1,500 test playlists/);
  assert.match(f.elements.get('final-seed-status').textContent, /1,000 test playlists/);
  assert.equal(f.elements.get('final-seed-pending').hidden, true);
  assert.equal(f.elements.get('final-seed-results').hidden, false);
  assert(f.html.indexOf('id="studio-evaluation"') < f.html.indexOf('id="development-history"'));
  assert(f.html.indexOf('id="feature-decisions"') < f.html.indexOf('id="earlier-seed-study"'));
  for (const id of ['seed-curve', 'benchmark-chart', 'tradeoff-chart', 'eda-shape-chart',
    'studio-recovery-chart', 'studio-cold-chart', 'final-context-chart',
    'final-seed-chart', 'final-seed-marginal-chart', 'final-seed-difference-chart']) {
    assert(f.elements.get(id).children.length, `${id} must retain its rendered evidence`);
  }
});

test('final seed controls render the uploaded scores at each metric and K', () => {
  const f = pageFixture();
  const study = f.context.window.BEATX_RESEARCH_ADDITIONS.studio_seed_study;
  const metric = f.elements.get('final-seed-metric'); metric.value = 'recall'; metric.listeners.change();
  const k = f.elements.get('final-seed-k'); k.value = '5'; k.listeners.change();
  const table = f.elements.get('final-seed-table').children[0];
  const rows = table.children.find(child => child.tagName === 'TBODY').children;
  assert.equal(rows.length, 6);
  assert.equal(rows[5].children[3].textContent, study.test.budgets[20].cutoffs[5].unified.recall.toFixed(5));
  const split = f.elements.get('final-seed-partition'); split.value = 'validation'; split.listeners.change();
  assert.match(f.elements.get('final-seed-difference-analysis').textContent, /^validation:/);
  assert.match(f.elements.get('final-seed-marginal-analysis').textContent,
    new RegExp(study.validation.budgets[20].marginal_seed_gain.ndcg_delta.toFixed(5).replace('.', '\\.')));
  assert.deepEqual(f.errors, []);
});

test('BPM fallback and title ablation are explained using the selected seed count', () => {
  const f = pageFixture();
  const comparison = f.elements.get('final-seed-comparison'); comparison.value = 'tempo'; comparison.listeners.change();
  assert.equal(f.elements.get('final-seed-tempo-note').hidden, false);
  assert.match(f.elements.get('final-seed-tempo-note').textContent, /994 of 1000/);
  const context = f.elements.get('final-context-seeds'); context.value = '10'; context.listeners.change();
  assert.match(f.elements.get('final-context-note').textContent, /-0\.00008/);
  assert.match(f.elements.get('final-context-note').textContent, /10 seeds/);
  assert.deepEqual(f.errors, []);
});

test('final result selectors use the exact saved cohort and K', () => {
  const f = pageFixture();
  const select = f.elements.get('studio-evaluation-comparison'); select.value = 'tempo'; select.listeners.change();
  const k = f.elements.get('studio-evaluation-k'); k.value = '5'; k.listeners.change();
  const table = f.elements.get('studio-evaluation-table').children[0];
  const rows = table.children.find(child => child.tagName === 'TBODY').children;
  assert.equal(rows.length, 2);
  const report = f.context.window.BEATX_RESEARCH_ADDITIONS.studio_evaluation;
  assert.equal(rows[0].children[1].textContent, report.cohorts.all_queries.cutoffs['5'].unified.recall.toFixed(4));
  assert.match(rows[1].children[0].textContent, /BPM filter/);
  assert.deepEqual(f.errors, []);
});

test('final seed plot accepts only final-pipeline results and does not borrow legacy curves', () => {
  const old = {}; vm.runInNewContext(fs.readFileSync(path.join(docs, 'seed_experiment.js'), 'utf8'), {window: old});
  assert.equal(seedView(old.NEXT_TRACK_SEED_STUDY, 'test', 'ndcg', 20, 'main'), null);
  const methods = ['popularity', 'cf', 'unified'];
  const report = {kind: 'frozen_final_pipeline_seed_study', seed_budgets: [1, 5, 20], methods,
    test: {budgets: Object.fromEntries([1, 5, 20].map(n => [n, {cutoffs: {
      20: Object.fromEntries(methods.map((method, i) => [method, {ndcg: n / 100 + i / 1000}]))
    }}]))}};
  const rows = seedView(report, 'test', 'ndcg', 20, 'main');
  assert.deepEqual(rows[2].values, [.012, .052000000000000005, .202]);
  assert.equal(rows[2].label, 'Final pipeline');
});
