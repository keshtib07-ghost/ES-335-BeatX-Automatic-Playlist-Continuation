'use strict';

const spotifyTrackId = (value) => typeof value === 'string' && /^[A-Za-z0-9]{22}$/.test(value);
const spotifyClientId = (value) => typeof value === 'string' && /^[a-fA-F0-9]{32}$/.test(value);
const spotifyRedirectUri = (pageUrl = location.href) => new URL('./', pageUrl).href;
const spotifyStorage = {auth: 'beatx.spotify.auth', token: 'beatx.spotify.token', playlist: 'beatx.spotify.playlist'};
// Keep native fetch on Window when called through a Spotify client instance.
const spotifyFetch = (input, init) => globalThis.fetch(input, init);

function storedJson(store, key) {
  try { return JSON.parse(store.getItem(key) || 'null'); } catch { return null; }
}

function spotifyImageUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === 'https:' &&
      (url.hostname === 'i.scdn.co' || url.hostname.endsWith('.spotifycdn.com')) ? url.href : null;
  } catch { return null; }
}

// Public oEmbed thumbnails do not need OAuth. Limit concurrent metadata lookups.
class SpotifyArtwork {
  constructor(request = spotifyFetch) {
    this.request = request;
    this.cache = new Map();
    this.pending = new Map();
    this.queue = [];
    this.active = 0;
  }

  cover(id) {
    if (!spotifyTrackId(id)) return Promise.resolve(null);
    if (this.cache.has(id)) return Promise.resolve(this.cache.get(id));
    if (this.pending.has(id)) return this.pending.get(id);
    const result = new Promise((resolve) => {
      this.queue.push({id, resolve});
      this.drain();
    });
    this.pending.set(id, result);
    return result;
  }

  drain() {
    while (this.active < 4 && this.queue.length) {
      const {id, resolve} = this.queue.shift();
      this.active += 1;
      const query = new URLSearchParams({url: `https://open.spotify.com/track/${id}`});
      Promise.resolve().then(() => this.request(`https://open.spotify.com/oembed?${query}`,
        {signal: AbortSignal.timeout(8000)}))
        .then((response) => response.ok ? response.json() : null)
        .then((data) => spotifyImageUrl(data?.thumbnail_url))
        .catch(() => null)
        .then((cover) => {
          this.cache.set(id, cover);
          this.pending.delete(id);
          this.active -= 1;
          resolve(cover);
          this.drain();
        });
    }
  }
}

class SpotifyStudio {
  constructor(clientId, redirectUri = spotifyRedirectUri(), store = sessionStorage, request = spotifyFetch) {
    if (!spotifyClientId(clientId)) throw new Error('Enter a valid Spotify Client ID.');
    this.clientId = clientId.toLowerCase();
    this.redirectUri = redirectUri;
    this.store = store;
    this.request = request;
    const saved = storedJson(store, spotifyStorage.token);
    this.accessToken = saved?.clientId === this.clientId ? saved.accessToken : null;
    this.expires = saved?.clientId === this.clientId ? saved.expires : 0;
  }

  get connected() {
    return Boolean(this.accessToken && Date.now() < this.expires);
  }

  async authorize(draft, saveAfter) {
    const redirect = new URL(this.redirectUri);
    if (redirect.protocol !== 'https:' &&
        !(redirect.protocol === 'http:' && ['127.0.0.1', '[::1]'].includes(redirect.hostname))) {
      throw new Error('Open BeatX over HTTPS, or use http://127.0.0.1 for the local demo.');
    }
    const verifier = Array.from(crypto.getRandomValues(new Uint8Array(48)),
      (byte) => byte.toString(16).padStart(2, '0')).join('');
    const state = crypto.randomUUID();
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest)))
      .replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
    this.store.setItem(spotifyStorage.auth, JSON.stringify({state, verifier, draft, saveAfter,
      clientId: this.clientId, redirectUri: this.redirectUri}));
    const parameters = new URLSearchParams({client_id: this.clientId, response_type: 'code',
      redirect_uri: this.redirectUri, scope: 'playlist-modify-private', state,
      code_challenge_method: 'S256', code_challenge: challenge});
    location.assign(`https://accounts.spotify.com/authorize?${parameters}`);
  }

  async completeAuthorization(pageUrl) {
    const url = new URL(pageUrl);
    if (!url.searchParams.has('code') && !url.searchParams.has('error')) return null;
    const saved = storedJson(this.store, spotifyStorage.auth);
    const {code, error, state} = Object.fromEntries(url.searchParams);
    for (const key of ['code', 'error', 'state']) url.searchParams.delete(key);
    history.replaceState(null, '', url.href);
    this.store.removeItem(spotifyStorage.auth);
    if (!saved || state !== saved.state || saved.clientId !== this.clientId ||
        saved.redirectUri !== this.redirectUri) {
      throw new Error('Spotify authorization did not match this session. Connect again.');
    }
    if (error || !code) throw new Error('Spotify authorization was declined.');
    const body = new URLSearchParams({client_id: this.clientId, grant_type: 'authorization_code',
      code, redirect_uri: this.redirectUri, code_verifier: saved.verifier});
    const response = await this.request('https://accounts.spotify.com/api/token',
      {method: 'POST', body, signal: AbortSignal.timeout(20000)});
    if (!response.ok) throw new Error(`Spotify sign-in failed (${response.status}). Check your app’s redirect address.`);
    const token = await response.json();
    if (!token.access_token || !(token.expires_in > 0)) throw new Error('Spotify did not return a valid session.');
    this.accessToken = token.access_token;
    this.expires = Date.now() + 1000 * token.expires_in;
    this.store.setItem(spotifyStorage.token, JSON.stringify({clientId: this.clientId,
      accessToken: this.accessToken, expires: this.expires}));
    return {draft: saved.draft, saveAfter: saved.saveAfter};
  }

  async api(path, method = 'GET', body) {
    if (!this.connected) throw new Error('Connect your Spotify account to continue.');
    const headers = {Authorization: `Bearer ${this.accessToken}`};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await this.request(`https://api.spotify.com/v1${path}`,
      {method, headers, body: JSON.stringify(body), signal: AbortSignal.timeout(20000)});
    if (response.status === 401 || response.status === 403) {
      this.accessToken = null;
      this.store.removeItem(spotifyStorage.token);
    }
    if (response.status === 403) throw new Error('Spotify denied access. Check that your account can use this Spotify app.');
    if (response.status === 429) throw new Error('Spotify is receiving too many requests. Wait before trying again.');
    if (!response.ok) throw new Error(`Spotify could not complete the request (${response.status}).`);
    return response.status === 204 ? {} : response.json();
  }

  playlistKey(draft) {
    return JSON.stringify([this.clientId, draft.title, draft.ids]);
  }

  savedPlaylist(draft) {
    const saved = storedJson(this.store, spotifyStorage.playlist);
    return saved?.key === this.playlistKey(draft) && saved.complete && spotifyTrackId(saved.id)
      ? `https://open.spotify.com/playlist/${saved.id}` : null;
  }

  async save(draft) {
    const {title, ids} = draft;
    if (typeof title !== 'string' || !title.trim() || !Array.isArray(ids) || !ids.length ||
        ids.length > 20 || !ids.every(spotifyTrackId) || new Set(ids).size !== ids.length) {
      throw new Error('Generate a playlist with valid Spotify songs before saving.');
    }
    const key = this.playlistKey(draft);
    const previous = storedJson(this.store, spotifyStorage.playlist);
    let playlist = previous?.key === key && spotifyTrackId(previous.id) ? previous : null;
    if (!playlist) {
      const created = await this.api('/me/playlists', 'POST', {
        name: title,
        description: 'Generated with BeatX',
        public: false,
      });
      if (!spotifyTrackId(created.id)) throw new Error('Spotify did not return a playlist ID.');
      playlist = {key, id: created.id, complete: false};
      this.store.setItem(spotifyStorage.playlist, JSON.stringify(playlist));
    }
    if (!playlist.complete) {
      await this.api(`/playlists/${playlist.id}/items`, 'PUT',
        {uris: ids.map((id) => `spotify:track:${id}`)});
      playlist.complete = true;
      this.store.setItem(spotifyStorage.playlist, JSON.stringify(playlist));
    }
    return this.savedPlaylist(draft);
  }
}
