'use strict';

class BeatXModelAPI {
  constructor(baseUrl = '', request = (input, init) => globalThis.fetch(input, init)) {
    const base = String(baseUrl).trim().replace(/\/+$/, '');
    if (base) {
      const url = new URL(base);
      const loopback = ['localhost', '127.0.0.1', '[::1]'].includes(url.hostname);
      if ((url.protocol !== 'https:' && !(url.protocol === 'http:' && loopback)) ||
          url.username || url.password || url.search || url.hash) {
        throw new Error('Use an HTTPS model API address.');
      }
    }
    this.baseUrl = base;
    this.request = request;
  }

  async json(path, init = {}) {
    let response;
    try {
      response = await this.request(this.baseUrl + path, {...init, signal: AbortSignal.timeout(60000)});
    } catch {
      throw new Error('The trained model is unavailable. Check the connection and try again.');
    }
    let payload;
    try {
      payload = await response.json();
    } catch {
      throw new Error('The trained model API is not connected to this website.');
    }
    if (!response.ok) throw new Error(payload.error || 'The trained model request failed.');
    return payload;
  }

  async status() {
    const status = await this.json('/api/status');
    if (status.trained_model !== true) throw new Error('The trained model is not ready.');
    return status;
  }

  search(query, offset = 0) {
    return this.json('/api/search?q=' + encodeURIComponent(query) + '&offset=' + offset);
  }

  async recommend(input) {
    const result = await this.json('/api/recommend', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(input)
    });
    if (!Array.isArray(result.tracks) || !Array.isArray(result.tags)) {
      throw new Error('The trained model returned an invalid playlist.');
    }
    return result;
  }
}
