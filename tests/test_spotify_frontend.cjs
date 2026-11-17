const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {webcrypto} = require('node:crypto');
const path = require('node:path');

const source = fs.readFileSync(path.join(__dirname, '../docs/spotify.js'), 'utf8');
const clientId = 'a'.repeat(32);
const redirect = 'https://example.github.io/beatx/';
const playlistId = 'P'.repeat(22);
const draft = {title: 'Rainy Study', ids: ['A'.repeat(22), 'B'.repeat(22)], seedTracks: [{id: 'C'.repeat(22)}]};

function fixture(request = async () => { throw new Error('Unexpected network request'); }) {
  const values = new Map();
  const store = {getItem: (key) => values.get(key) ?? null,
    setItem: (key, value) => values.set(key, value), removeItem: (key) => values.delete(key)};
  const navigation = {};
  const context = vm.createContext({URL, URLSearchParams, AbortSignal, TextEncoder, btoa, crypto: webcrypto,
    location: {href: redirect, assign: (url) => { navigation.destination = url; }},
    history: {replaceState: (_, __, url) => { navigation.cleaned = url; }},
    sessionStorage: store, fetch: request});
  vm.runInContext(source + '\nthis.api = {SpotifyStudio, SpotifyArtwork, spotifyRedirectUri, spotifyImageUrl, spotifyStorage, spotifyPlaylistIds};', context);
  return {api: context.api, store, navigation, browserGlobal: vm.runInContext('globalThis', context)};
}

function ok(body, status = 200) { return {ok: true, status, json: async () => body}; }

function connected(app) { app.accessToken = 'unit-test-token'; app.expires = Date.now() + 60000; }

test('album artwork loads through public oEmbed without an access token and deduplicates requests', async () => {
  const requests = [];
  const f = fixture(async (url, options) => {
    requests.push({url, options});
    return ok({thumbnail_url: 'https://image-cdn-fa.spotifycdn.com/image/example'});
  });
  const art = new f.api.SpotifyArtwork();
  const first = art.cover(draft.ids[0]);
  assert.equal(first, art.cover(draft.ids[0]));
  assert.equal(await first, 'https://image-cdn-fa.spotifycdn.com/image/example');
  assert.equal(await art.cover(draft.ids[0]), await first);
  assert.equal(await art.cover('fictional-track'), null);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].options.headers, undefined);
  assert.equal(new URL(requests[0].url).searchParams.get('url'), 'https://open.spotify.com/track/' + draft.ids[0]);
  assert.equal(f.api.spotifyImageUrl('https://spotifycdn.com.evil.test/image'), null);
});

test('artwork provider failures fall back without breaking recommendations', async () => {
  const f = fixture(async () => { throw new Error('Offline'); });
  assert.equal(await new f.api.SpotifyArtwork().cover(draft.ids[0]), null);
});

test('OAuth redirect retains the GitHub Pages repository path', () => {
  const {api} = fixture();
  assert.equal(api.spotifyRedirectUri('https://example.github.io/beatx/index.html?code=test#demo'), redirect);
  assert.equal(api.spotifyRedirectUri('http://127.0.0.1:8000/index.html'), 'http://127.0.0.1:8000/');
});

test('Spotify authorization uses PKCE and retains the playlist draft', async () => {
  const f = fixture();
  const app = new f.api.SpotifyStudio(clientId);
  await app.authorize(draft, true);
  const url = new URL(f.navigation.destination);
  const saved = JSON.parse(f.store.getItem(f.api.spotifyStorage.auth));
  assert.equal(url.origin, 'https://accounts.spotify.com');
  assert.equal(url.searchParams.get('redirect_uri'), redirect);
  assert.equal(url.searchParams.get('scope'), 'playlist-modify-private');
  assert.equal(url.searchParams.get('code_challenge_method'), 'S256');
  assert.equal(url.searchParams.get('state'), saved.state);
  const digest = Buffer.from(await webcrypto.subtle.digest('SHA-256', new TextEncoder().encode(saved.verifier)));
  assert.equal(url.searchParams.get('code_challenge'), digest.toString('base64url'));
  assert.deepEqual(saved.draft, draft);
  assert.equal(saved.saveAfter, true);
});

test('an unmatched OAuth callback never exchanges the code', async () => {
  const f = fixture();
  const app = new f.api.SpotifyStudio(clientId);
  await app.authorize(draft, false);
  await assert.rejects(app.completeAuthorization(redirect + '?code=unit-test-code&state=wrong'), /did not match/);
  assert.equal(f.navigation.cleaned, redirect);
  assert.equal(f.store.getItem(f.api.spotifyStorage.auth), null);
});

test('a valid OAuth return restores the draft and session across page navigation', async () => {
  let exchanges = 0;
  const f = fixture(async (url, options) => {
    exchanges += 1;
    assert.equal(url, 'https://accounts.spotify.com/api/token');
    assert.equal(options.body.get('redirect_uri'), redirect);
    return ok({access_token: 'unit-test-token', expires_in: 3600});
  });
  const app = new f.api.SpotifyStudio(clientId);
  await app.authorize(draft, true);
  const saved = JSON.parse(f.store.getItem(f.api.spotifyStorage.auth));
  const session = await app.completeAuthorization(redirect + '?code=unit-test-code&state=' + saved.state);
  assert.equal(exchanges, 1);
  assert.deepEqual(JSON.parse(JSON.stringify(session.draft)), draft);
  assert.equal(session.saveAfter, true);
  assert.equal(new f.api.SpotifyStudio(clientId).connected, true);
});

test('playlist creation returns a link only after all tracks are saved and retries reuse the playlist', async () => {
  const calls = [];
  let fail = true;
  const f = fixture(async (url, options) => {
    calls.push({url, method: options.method, body: JSON.parse(options.body)});
    if (options.method === 'POST') return ok({id: playlistId});
    if (fail) { fail = false; return {ok: false, status: 503}; }
    return ok({}, 204);
  });
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  await assert.rejects(app.save(draft), /503/);
  assert.equal(app.savedPlaylist(draft), null);
  const link = await app.save(draft);
  assert.equal(link, 'https://open.spotify.com/playlist/' + playlistId);
  assert.equal(await app.save(draft), link);
  assert.equal(calls.filter(call => call.method === 'POST').length, 1);
  assert.equal(calls.length, 3);
  assert.deepEqual(calls[0].body, {name: draft.title, description: 'Generated with BeatX', public: false});
  assert.equal(calls[1].url, `https://api.spotify.com/v1/playlists/${playlistId}/items`);
  const expectedUris = [...draft.seedTracks.map(track => track.id), ...draft.ids].map(id => 'spotify:track:' + id);
  assert.deepEqual(calls[1].body.uris, expectedUris);
  assert.deepEqual(calls[2].body.uris, expectedUris);
  assert.equal(app.savedPlaylist({...draft, ids: [...draft.ids].reverse()}), null);
});

test('three seed songs stay first and twenty additions produce a 23-track Spotify playlist', async () => {
  const calls = [];
  const f = fixture(async (url, options) => {
    calls.push({url, body: JSON.parse(options.body)});
    return options.method === 'POST' ? ok({id: playlistId}) : ok({}, 204);
  });
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  const seeds = ['Z', 'Y', 'X'].map(letter => ({id: letter.repeat(22)}));
  const additions = Array.from({length: 20}, (_, i) => String(i).padStart(22, '0'));
  await app.save({...draft, seedTracks: seeds, ids: additions});
  assert.equal(calls.length, 2);
  assert.deepEqual(calls[1].body.uris,
    [...seeds.map(track => track.id), ...additions].map(id => 'spotify:track:' + id));
  assert.equal(calls[1].body.uris.length, 23);
});

test('overlapping and repeated seeds are saved once at their first position', async () => {
  const writes = [];
  const f = fixture(async (_, options) => {
    if (options.method === 'POST') return ok({id: playlistId});
    writes.push(JSON.parse(options.body));
    return ok({}, 204);
  });
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  await app.save({...draft, seedTracks: [draft.seedTracks[0], {id: draft.ids[1]}, draft.seedTracks[0]]});
  assert.deepEqual(writes[0].uris,
    [draft.seedTracks[0].id, draft.ids[1], draft.ids[0]].map(id => 'spotify:track:' + id));
});

test('a playlist without seeds still saves its recommendations in order', async () => {
  let uris;
  const f = fixture(async (_, options) => {
    if (options.method === 'POST') return ok({id: playlistId});
    uris = JSON.parse(options.body).uris;
    return ok({}, 204);
  });
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  await app.save({...draft, seedTracks: []});
  assert.deepEqual(uris, draft.ids.map(id => 'spotify:track:' + id));
});

test('twenty seeds plus twenty additions are not truncated to twenty tracks', async () => {
  let uris;
  const f = fixture(async (_, options) => {
    if (options.method === 'POST') return ok({id: playlistId});
    uris = JSON.parse(options.body).uris;
    return ok({}, 204);
  });
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  const ids = Array.from({length: 40}, (_, i) => String(i).padStart(22, '0'));
  await app.save({...draft, seedTracks: ids.slice(0, 20).map(id => ({id})), ids: ids.slice(20)});
  assert.deepEqual(uris, ids.map(id => 'spotify:track:' + id));
});

test('saved playlist identity includes seed songs and their order and ignores old additions-only saves', async () => {
  const f = fixture(async (_, options) => options.method === 'POST' ? ok({id: playlistId}) : ok({}, 204));
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  const seeded = {...draft, seedTracks: [...draft.seedTracks, {id: 'D'.repeat(22)}]};
  f.store.setItem(f.api.spotifyStorage.playlist, JSON.stringify({
    key: JSON.stringify([clientId, draft.title, draft.ids]), id: playlistId, complete: true,
  }));
  assert.equal(app.savedPlaylist(seeded), null);
  await app.save(seeded);
  assert.equal(app.savedPlaylist(seeded), 'https://open.spotify.com/playlist/' + playlistId);
  assert.equal(app.savedPlaylist({...seeded, seedTracks: [...seeded.seedTracks].reverse()}), null);
  assert.equal(app.savedPlaylist({...seeded, seedTracks: draft.seedTracks}), null);
});

test('saving after the OAuth round trip writes restored seed songs before the recommendations', async () => {
  let uris;
  const f = fixture(async (url, options) => {
    if (url === 'https://accounts.spotify.com/api/token') return ok({access_token: 'unit-test-token', expires_in: 3600});
    if (options.method === 'POST') return ok({id: playlistId});
    uris = JSON.parse(options.body).uris;
    return ok({}, 204);
  });
  await new f.api.SpotifyStudio(clientId).authorize(draft, true);
  const saved = JSON.parse(f.store.getItem(f.api.spotifyStorage.auth));
  const returned = new f.api.SpotifyStudio(clientId);
  const session = await returned.completeAuthorization(redirect + '?code=unit-test-code&state=' + saved.state);
  await returned.save(session.draft);
  assert.deepEqual(uris,
    [...draft.seedTracks.map(track => track.id), ...draft.ids].map(id => 'spotify:track:' + id));
});

test('expired authorization is cleared after Spotify rejects the session', async () => {
  const f = fixture(async () => ({ok: false, status: 401}));
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  f.store.setItem(f.api.spotifyStorage.token, 'old session');
  await assert.rejects(app.save(draft), /401/);
  assert.equal(app.connected, false);
  assert.equal(f.store.getItem(f.api.spotifyStorage.token), null);
});

test('invalid or repeated track IDs never create a Spotify playlist', async () => {
  const f = fixture();
  const app = new f.api.SpotifyStudio(clientId);
  connected(app);
  await assert.rejects(app.save({...draft, ids: ['demo-1']}), /valid Spotify songs/);
  await assert.rejects(app.save({...draft, ids: [draft.ids[0], draft.ids[0]]}), /valid Spotify songs/);
  for (const seedTracks of [null, 'invalid', [{}], [null], [{id: 'demo-1'}], Array(21).fill(draft.seedTracks[0])]) {
    await assert.rejects(app.save({...draft, seedTracks}), /valid Spotify songs/);
  }
});


test('default fetch preserves Window for artwork, OAuth exchange, and playlist writes', async () => {
  const calls = [];
  const f = fixture(function browserFetch(url, options) {
    assert.equal(this, f.browserGlobal, 'Native browser fetch must be called on Window');
    calls.push({url, method: options?.method || 'GET'});
    if (url.startsWith('https://open.spotify.com/oembed?')) {
      return Promise.resolve(ok({thumbnail_url: 'https://i.scdn.co/image/test-cover'}));
    }
    if (url === 'https://accounts.spotify.com/api/token') {
      return Promise.resolve(ok({access_token: 'unit-test-token', expires_in: 3600}));
    }
    return Promise.resolve(options.method === 'POST' ? ok({id: playlistId}) : ok({}, 204));
  });
  const art = new f.api.SpotifyArtwork();
  assert.equal(await art.cover(draft.ids[0]), 'https://i.scdn.co/image/test-cover');
  const app = new f.api.SpotifyStudio(clientId);
  await app.authorize(draft, true);
  const saved = JSON.parse(f.store.getItem(f.api.spotifyStorage.auth));
  await app.completeAuthorization(redirect + '?code=unit-test-code&state=' + saved.state);
  assert.equal(await app.save(draft), 'https://open.spotify.com/playlist/' + playlistId);
  assert.deepEqual(calls.map(call => call.method), ['GET', 'POST', 'POST', 'PUT']);
});
