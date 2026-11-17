'use strict';
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const path = require('node:path');

function studio(request) {
  const elements = new Map();
  const element = () => ({textContent: '', value: '', listeners: {},
    addEventListener(name, callback) { this.listeners[name] = callback; },
    setAttribute() {}, removeAttribute() {}, append() {}, replaceChildren() {}, focus() {}});
  const select = id => {
    if (!elements.has(id)) elements.set(id, element());
    return elements.get(id);
  };
  const values = new Map();
  const store = {getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value),
    removeItem: key => values.delete(key)};
  const context = vm.createContext({URL, AbortSignal, location: {href: 'https://example.test/'},
    sessionStorage: store, localStorage: store, window: {addEventListener() {}},
    document: {createTextNode: text => text}, select, node: element, filterLabels: {},
    setupFilters: () => ({read: () => ({}), restore() {}}),
    BeatXModelAPI: class {
      status() { return new Promise(() => {}); }
      recommend(input) { return request(input); }
    }});
  for (const file of ['spotify.js', 'app.js']) {
    vm.runInContext(fs.readFileSync(path.join(__dirname, '../docs', file), 'utf8'), context);
  }
  vm.runInContext(`
    realMode = true;
    modelStatus = {model_id: 'test-model'};
    this.studio = {recommend, spotifyDraft, restoreStudioDraft, saveSpotify,
      setSeeds(tracks) { selected = tracks; },
      addSeed(track) { selected.push(track); },
      connect() {
        configureSpotify('a'.repeat(32));
        spotify.accessToken = 'test-token';
        spotify.expires = Date.now() + 60000;
      }};
  `, context);
  return {app: context.studio, select, context};
}

const song = letter => ({id: letter.repeat(22), title: letter, artist: 'Test artist',
  image: 'https://i.scdn.co/image/test'});
const result = {tracks: [{...song('A'), playback_position: 2}, {...song('B'), playback_position: 1}],
  tags: [], known_seeds: 1, seed_count: 1, transition_evidence: 1};

test('Studio keeps the seeds used for generation when the selection changes during or after the request', async () => {
  let finish;
  let requested;
  const f = studio(input => {
    requested = input;
    return new Promise(resolve => { finish = resolve; });
  });
  f.select('playlist-title').value = 'Study';
  f.app.setSeeds([song('C')]);
  const pending = f.app.recommend();
  f.app.addSeed(song('D'));
  finish(result);
  await pending;
  assert.deepEqual(JSON.parse(JSON.stringify(requested.seeds)), [song('C').id]);
  assert.deepEqual(JSON.parse(JSON.stringify(f.app.spotifyDraft().seedTracks)), [song('C')]);
  assert.match(f.select('generation-evidence').textContent, /^1 seed \+ 2 additions/);
  f.app.addSeed(song('E'));
  assert.deepEqual(JSON.parse(JSON.stringify(f.app.spotifyDraft().seedTracks)), [song('C')]);
  f.select('playback-order').listeners.click();
  assert.deepEqual(JSON.parse(JSON.stringify(f.app.spotifyDraft().ids)), [song('B').id, song('A').id]);
  assert.deepEqual(JSON.parse(JSON.stringify(f.app.spotifyDraft().seedTracks)), [song('C')]);
});

test('Studio restores seed order and reports the total saved track count', async () => {
  const f = studio(async () => result);
  const uris = [];
  f.context.fetch = async (_, options) => {
    if (options.method === 'POST') return {ok: true, status: 200, json: async () => ({id: 'P'.repeat(22)})};
    uris.push(...JSON.parse(options.body).uris);
    return {ok: true, status: 204};
  };
  f.app.connect();
  const restored = {title: 'Study', ids: [song('B').id, song('A').id], result, playbackMode: true,
    seedTracks: [song('D'), song('C')], realMode: true, modelId: 'test-model'};
  assert.equal(f.app.restoreStudioDraft(restored), true);
  f.app.addSeed(song('E'));
  await f.app.saveSpotify();
  assert.deepEqual(uris, ['D', 'C', 'B', 'A'].map(letter => 'spotify:track:' + song(letter).id));
  assert.equal(f.select('spotify-status').textContent, 'Saved 4 tracks to Spotify. Seed songs come first.');
  assert.equal(f.select('spotify-playlist-link').hidden, false);
});
