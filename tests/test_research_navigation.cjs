'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const test = require('node:test');
const script = fs.readFileSync(path.join(__dirname, '../docs/research-summary.js'), 'utf8');

function route(hash) {
  let destination = null;
  let listener;
  const location = {
    hash,
    href: `https://example.github.io/project/research.html${hash}`,
    replace: (url) => { destination = url; }
  };
  vm.runInNewContext(script, { location, URL, window: { addEventListener: (name, fn) => {
    assert.equal(name, 'hashchange'); listener = fn;
  } } });
  return { destination: () => destination, location, listener };
}

test('Research opens the summary and its own anchors stay there', () => {
  for (const hash of ['', '#top', '#main', '#summary-model', '#summary-results', '#summary-next']) {
    assert.equal(route(hash).destination(), null);
  }
});

test('legacy research bookmarks keep the repository path and report section', () => {
  for (const section of ['overview', 'known-seeds', 'unknown-seeds', 'seed-study', 'results', 'reproduce', 'playback']) {
    assert.equal(route(`#${section}`).destination(),
      `https://example.github.io/project/research-deep-dive.html#${section}`);
  }
  const state = route('');
  state.location.hash = '#metrics'; state.listener();
  assert.equal(state.destination(), 'https://example.github.io/project/research-deep-dive.html#metrics');
});

test('unknown or malformed bookmarks do not redirect', () => {
  for (const hash of ['#unknown-section', '#%E0%A4%A', '#https://other.example/']) {
    assert.equal(route(hash).destination(), null);
  }
});
