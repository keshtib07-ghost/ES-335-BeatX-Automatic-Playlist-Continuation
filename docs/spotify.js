'use strict';

const spotifyTrackId = (value) => /^[A-Za-z0-9]{22}$/.test(value);

class SpotifyStudio {
  constructor(clientId, origin = location.origin, store = sessionStorage, request = fetch) {
    this.clientId = clientId;
    this.redirectUri = `${origin}/`;
    this.store = store;
    this.request = request;
    this.accessToken = null;
    this.expires = 0;
    this.art = new Map();
    this.artPending = new Map();
  }

  get connected() {
    return Boolean(this.accessToken && Date.now() < this.expires);
  }

  async authorize(draft, saveAfter) {
    const verifier = Array.from(crypto.getRandomValues(new Uint8Array(48)), (byte) => byte.toString(16).padStart(2, '0')).join('');
    const state = crypto.randomUUID();
    const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier));
    const challenge = btoa(String.fromCharCode(...new Uint8Array(digest))).replace(/=+$/, '').replace(/\+/g, '-').replace(/\//g, '_');
    this.store.setItem('nexttrack.spotify.auth', JSON.stringify({state, verifier, draft, saveAfter}));
    const parameters = new URLSearchParams({client_id: this.clientId, response_type: 'code', redirect_uri: this.redirectUri,
      scope: 'playlist-modify-private', state, code_challenge_method: 'S256', code_challenge: challenge});
    location.assign(`https://accounts.spotify.com/authorize?${parameters}`);
  }

  async completeAuthorization(pageUrl) {
    const url = new URL(pageUrl);
    const saved = JSON.parse(this.store.getItem('nexttrack.spotify.auth') || 'null');
    if (!saved || (!url.searchParams.has('code') && !url.searchParams.has('error'))) return null;
    this.store.removeItem('nexttrack.spotify.auth');
    const {code, error, state} = Object.fromEntries(url.searchParams);
    for (const key of ['code', 'error', 'state']) url.searchParams.delete(key);
    history.replaceState(null, '', url.href);
    if (state !== saved.state) throw new Error('Spotify authorization state did not match. Connect again.');
    if (error || !code) throw new Error('Spotify authorization was declined.');
    const body = new URLSearchParams({client_id: this.clientId, grant_type: 'authorization_code',
      code, redirect_uri: this.redirectUri, code_verifier: saved.verifier});
    const response = await this.request('https://accounts.spotify.com/api/token', {method: 'POST', body});
    if (!response.ok) throw new Error(`Spotify sign-in failed (${response.status}). Check the redirect URL.`);
    const token = await response.json();
    this.accessToken = token.access_token;
    this.expires = Date.now() + 1000 * token.expires_in;
    return {draft: saved.draft, saveAfter: saved.saveAfter};
  }

  async api(path, method = 'GET', body) {
    if (!this.connected) throw new Error('Connect your Spotify account to continue.');
    const headers = {Authorization: `Bearer ${this.accessToken}`};
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    const response = await this.request(`https://api.spotify.com/v1${path}`, {method, headers, body: JSON.stringify(body)});
    if (response.status === 401) this.accessToken = null;
    if (!response.ok) throw new Error(`Spotify could not complete the request (${response.status}).`);
    return response.status === 204 ? {} : response.json();
  }

  cover(id) {
    if (!this.connected || !spotifyTrackId(id)) return Promise.resolve(null);
    if (this.art.has(id)) return Promise.resolve(this.art.get(id));
    if (this.artPending.has(id)) return this.artPending.get(id);
    const lookup = this.api(`/tracks/${id}`).then((track) => {
      const image = track.album?.images?.at(-1)?.url;
      const cover = image && /^https:\/\/i\.scdn\.co\//.test(image) ? image : null;
      this.art.set(id, cover);
      return cover;
    }).catch(() => null).finally(() => this.artPending.delete(id));
    this.artPending.set(id, lookup);
    return lookup;
  }

  async save(draft) {
    const {title, ids} = draft;
    if (typeof title !== 'string' || !title.trim() || !Array.isArray(ids) || !ids.length || ids.length > 20
        || !ids.every(spotifyTrackId) || new Set(ids).size !== ids.length) throw new Error('Generate a real playlist before saving.');
    const requestKey = JSON.stringify([this.clientId, title, ids]);
    const previous = JSON.parse(this.store.getItem('nexttrack.spotify.playlist') || 'null');
    let playlist = previous?.key === requestKey ? previous : null;
    if (!playlist) {
      const created = await this.api('/me/playlists', 'POST', {name: title, public: false});
      if (!spotifyTrackId(created.id)) throw new Error('Spotify did not return a playlist ID.');
      playlist = {key: requestKey, id: created.id, complete: false};
      this.store.setItem('nexttrack.spotify.playlist', JSON.stringify(playlist));
    }
    if (!playlist.complete) {
      const uris = ids.map((id) => `spotify:track:${id}`);
      await this.api(`/playlists/${playlist.id}/items`, 'PUT', {uris});
      playlist.complete = true;
      this.store.setItem('nexttrack.spotify.playlist', JSON.stringify(playlist));
    }
    return `https://open.spotify.com/playlist/${playlist.id}`;
  }
}
