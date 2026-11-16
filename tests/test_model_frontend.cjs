'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');

function client(request, base = 'https://model.example') {
  const context = vm.createContext({URL, AbortSignal, fetch: request});
  vm.runInContext(fs.readFileSync('docs/model_api.js', 'utf8') + '\nthis.API = BeatXModelAPI;', context);
  return {api: new context.API(base), window: vm.runInContext('globalThis', context)};
}
const ok = value => ({ok: true, json: async () => value});

test('trained model status is checked at the configured public endpoint', async () => {
  let url;
  const f = client(async function(input) {
    assert.equal(this, f.window);
    url = input;
    return ok({trained_model: true, model_id: 'frozen-run'});
  });
  assert.equal((await f.api.status()).model_id, 'frozen-run');
  assert.equal(url, 'https://model.example/api/status');
});

test('search forwards the song query and page offset', async () => {
  let url;
  const f = client(async input => {url = input; return ok({tracks: [], more: false});});
  await f.api.search('Björk', 12);
  assert.equal(url, 'https://model.example/api/search?q=Bj%C3%B6rk&offset=12');
});

test('recommendation sends seed tracks to the model and returns its ranking', async () => {
  const input = {title: 'Rainy Night', seeds: ['a'.repeat(22)], method: 'cf', context: '', filters: {}};
  const expected = {tags: [], tracks: [{id: 'b'.repeat(22)}]};
  let called;
  const f = client(async (url, options) => {called = {url, options}; return ok(expected);});
  assert.deepEqual(await f.api.recommend(input), expected);
  assert.equal(called.url, 'https://model.example/api/recommend');
  assert.equal(called.options.method, 'POST');
  assert.deepEqual(JSON.parse(called.options.body), input);
});

test('missing or failing backend cannot return an illustrative playlist', async () => {
  const missing = client(async () => ({ok: false, json: async () => {throw Error('HTML 404');}}));
  await assert.rejects(missing.api.status(), /not connected/);
  const down = client(async () => {throw Error('offline');});
  await assert.rejects(down.api.recommend({seeds: []}), /unavailable/);
  const notReady = client(async () => ok({trained_model: false}));
  await assert.rejects(notReady.api.status(), /not ready/);
});

test('invalid model outputs and backend errors stay visible', async () => {
  const malformed = client(async () => ok({tracks: 'invalid'}));
  await assert.rejects(malformed.api.recommend({}), /invalid playlist/);
  const invalid = client(async () => ({ok: false, json: async () => ({error: 'Unknown seed track'})}));
  await assert.rejects(invalid.api.recommend({}), /Unknown seed track/);
});

test('production API configuration requires HTTPS', () => {
  assert.throws(() => client(async () => {}, 'http://model.example'), /HTTPS/);
  assert.throws(() => client(async () => {}, 'https://user:password@model.example'), /HTTPS/);
  assert.doesNotThrow(() => client(async () => {}, 'http://127.0.0.1:8080'));
  assert.doesNotThrow(() => client(async () => {}, ''));
});
