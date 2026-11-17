'use strict';

const modelApi = new BeatXModelAPI(window.BEATX_CONFIG?.modelApiBase || '');
let modelStatus = null;
let realMode = false;
let selected = [];
let timer;
let searchGeneration = 0;
let recommendGeneration = 0;
let nextOffset = 0;
let lastResult = null;
let playlistSeeds = [];
let playbackMode = false;
const maxSeeds = 20;
const filterUI = setupFilters();
let spotify;
let savingSpotify = false;
const artworkLoader = new SpotifyArtwork();

function artwork(track) {
  const wrapper = node('span', '♪', 'track-art');
  wrapper.setAttribute('aria-hidden', 'true');
  const showImage = (url) => {
    if (!url) return;
    const img = node('img');
    img.alt = '';
    img.loading = 'lazy';
    img.decoding = 'async';
    img.width = img.height = 48;
    img.addEventListener('error', () => { wrapper.textContent = '♪'; }, {once: true});
    wrapper.replaceChildren(img);
    img.src = url;
  };
  const cover = spotifyImageUrl(track.image);
  if (cover) showImage(cover);
  else artworkLoader.cover(track.id).then(showImage);
  return wrapper;
}

function orderedTracks() {
  const tracks = [...(lastResult?.tracks || [])];
  if (playbackMode) tracks.sort((a, b) => a.playback_position - b.playback_position);
  return tracks;
}

function trackRow(track) {
  const li = node('li', undefined, 'track');
  const info = node('div', undefined, 'track-info');
  info.append(node('strong', track.title), node('small', track.artist));
  if (track.album) info.append(node('small', track.album, 'track-album'));
  const profile = track.profile;
  const details = [];
  if (profile?.tags?.length) details.push(profile.tags.map((tag) => filterLabels[tag] || tag).join(', '));
  if (profile?.era) {
    const edition = profile.era_source === 'catalogue_edition' ? ' (catalogue edition)' :
      profile.match_status === 'verified_recording' ? '' : ' (provisional)';
    details.push(`${profile.era}${edition}`);
  }
  if (profile?.bpm) details.push(`${Math.round(profile.bpm)} BPM`);
  if (details.length > 0) {
    const disclosure = node('details');
    disclosure.append(node('summary', 'Song details'), node('small', details.join(' · ')));
    info.append(disclosure);
  }
  const actions = node('div', undefined, 'track-actions');
  if (Number.isFinite(track.duration_ms)) {
    const seconds = Math.floor(track.duration_ms / 1000);
    actions.append(node('span', `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, '0')}`));
  }
  if (spotifyTrackId(track.id)) {
    const link = node('a', 'Spotify ↗');
    link.href = `https://open.spotify.com/track/${track.id}`;
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.setAttribute('aria-label', `Open ${track.title} in Spotify`);
    actions.append(link);
  }
  li.append(artwork(track), info, actions);
  return li;
}

function spotifyDraft() {
  return {title: select('generated-title').textContent, ids: orderedTracks().map((track) => track.id),
    result: lastResult, playbackMode, seedTracks: [...playlistSeeds], realMode, modelId: modelStatus?.model_id || 'local',
    filters: filterUI.read()};
}

function restoreStudioDraft(draft) {
  if (!realMode || draft?.realMode !== true || draft.modelId !== (modelStatus?.model_id || 'local') ||
      !draft.result || !Array.isArray(draft.seedTracks)) return false;
  selected = [...draft.seedTracks];
  playlistSeeds = [...draft.seedTracks];
  lastResult = draft.result;
  playbackMode = Boolean(draft.playbackMode);
  select('playlist-title').value = draft.title;
  select('generated-title').textContent = draft.title;
  filterUI.restore(draft.filters || {});
  showSeeds();
  showContext(lastResult);
  renderPlaylist();
  return true;
}

// Moving between pages keeps the current playlist in this tab's session.
window.addEventListener('pagehide', () => {
  try { sessionStorage.setItem('beatx.studio.draft', JSON.stringify(spotifyDraft())); } catch {}
});

function showSpotifyLink(url) {
  const link = select('spotify-playlist-link');
  link.hidden = !url;
  select('save-spotify').hidden = Boolean(url);
  if (url) link.href = url;
  else link.removeAttribute('href');
}

function configureSpotify(clientId) {
  if (!spotifyClientId(clientId)) return;
  spotify = new SpotifyStudio(clientId);
}

function ensureSpotify() {
  if (spotify) return true;
  select('spotify-redirect-uri').textContent = spotifyRedirectUri();
  select('spotify-setup').showModal();
  return false;
}

async function saveSpotify(draft = spotifyDraft()) {
  if (!realMode || draft?.realMode !== true || savingSpotify || !draft.ids.length || !ensureSpotify()) return;
  const status = select('spotify-status');
  showSpotifyLink(null);
  savingSpotify = true;
  select('save-spotify').disabled = true;
  try {
    if (!spotify.connected) {
      await spotify.authorize(draft, true);
      return;
    }
    status.textContent = 'Creating your Spotify playlist…';
    await spotify.save(draft);
    if (spotify.playlistKey(draft) === spotify.playlistKey(spotifyDraft())) {
      const seedNote = draft.seedTracks?.length ? ' Seed songs come first.' : '';
      status.textContent = `Saved ${spotifyPlaylistIds(draft).length} tracks to Spotify.${seedNote}`;
    }
  } catch (error) {
    status.textContent = `${error.message} Use Save to Spotify to retry.`;
  } finally {
    savingSpotify = false;
    renderPlaylist();
  }
}

select('save-spotify').addEventListener('click', () => saveSpotify());
select('close-spotify-setup').addEventListener('click', () => select('spotify-setup').close());
select('spotify-setup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const clientId = select('spotify-client-id').value.trim();
  if (!spotifyClientId(clientId)) return;
  configureSpotify(clientId);
  try { localStorage.setItem('beatx.spotify.clientId', clientId.toLowerCase()); } catch {}
  select('spotify-setup').close();
  await saveSpotify();
});

function showSeeds() {
  select('seed-count').textContent = `${selected.length} / ${maxSeeds}`;
  select('seed-chips').replaceChildren(...selected.map((track) => {
    const button = node('button', undefined, 'chip seed-chip');
    button.append(artwork(track), document.createTextNode(`${track.title} ×`));
    button.type = 'button';
    button.setAttribute('aria-label', `Remove ${track.title}`);
    button.addEventListener('click', () => {
      selected = selected.filter((candidate) => candidate.id !== track.id);
      showSeeds();
      select('track-search').focus();
      searchTracks();
    });
    return button;
  }));
}

async function searchTracks(append = false) {
  const query = select('track-search').value.trim();
  const generation = ++searchGeneration;
  const list = select('track-matches');
  const more = select('search-more');
  more.hidden = true;
  if (!append) {
    nextOffset = 0;
    list.replaceChildren();
  }
  if (!realMode || selected.length >= maxSeeds || query.length < 2) return;
  try {
    const result = await modelApi.search(query, nextOffset);
    let matches = result.tracks;
    const hasMore = result.more;
    if (generation !== searchGeneration) return;
    nextOffset += matches.length;
    matches = matches.filter((candidate) => !selected.some((track) => track.id === candidate.id));
    if (!matches.length && !append) list.append(node('p', hasMore ? 'More tracks are available on the next page.' : 'No additional matches in this catalogue.', 'small'));
    for (const track of matches) {
      const button = node('button', undefined, 'track-match');
      const info = node('span');
      info.append(node('strong', track.title), node('small', track.artist));
      button.append(artwork(track), info);
      button.type = 'button';
      button.addEventListener('click', () => {
        if (selected.length >= maxSeeds) return;
        selected.push(track);
        select('track-search').value = '';
        showSeeds();
        searchTracks();
        select(selected.length === maxSeeds ? 'get-recs' : 'track-search').focus();
      });
      list.append(button);
    }
    more.hidden = !hasMore;
  } catch (error) {
    if (generation === searchGeneration) list.append(node('p', 'Track search is unavailable.', 'small'));
  }
}

function renderPlaylist() {
  if (!lastResult) return;
  const list = orderedTracks();
  select('track-list').replaceChildren(...list.map(trackRow));
  select('generated-cover').replaceChildren(...list.slice(0, 4).map(artwork));
  select('spotify-tools').hidden = !list.length;
  select('save-spotify').disabled = savingSpotify || !list.length || !list.every((track) => spotifyTrackId(track.id));
  showSpotifyLink(spotify?.savedPlaylist(spotifyDraft()) || null);
  select('relevance-order').setAttribute('aria-pressed', String(!playbackMode));
  select('playback-order').setAttribute('aria-pressed', String(playbackMode));
  select('playback-order').disabled = lastResult.transition_evidence === null;
  const support = realMode ? ` · ${lastResult.known_seeds}/${lastResult.seed_count} seeds seen in training` : '';
  const transitions = playbackMode ? ` · ${lastResult.transition_evidence}/${list.length} transitions supported,${lastResult.has_seed_anchor ? ', including the last known seed' : ''}` : '';
  const seeds = playlistSeeds.length ? `${playlistSeeds.length} seed${playlistSeeds.length === 1 ? '' : 's'} + ` : '';
  select('generation-evidence').textContent = `${seeds}${list.length} additions${support}${transitions}`;
}

function showContext(result) {
  const tags = result.tags.map((tag) => filterLabels[tag] || tag);
  select('inferred-tags').textContent = tags.length ? `Applied context · ${tags.join(', ')}` : 'No context applied.';
  select('filter-note').textContent = result.filter_note || '';
  select('filter-note').hidden = !result.filter_note;
}

async function recommend(event) {
  event?.preventDefault();
  const generation = ++recommendGeneration;
  const button = select('get-recs');
  const status = select('demo-status');
  status.textContent = '';
  if (!realMode) {
    status.textContent = 'Connect the trained model before generating a playlist.';
    return;
  }
  button.disabled = true;
  try {
    const title = select('playlist-title').value;
    const seedTracks = [...selected];
    const result = await modelApi.recommend({
      title, seeds: seedTracks.map((track) => track.id), method: 'unified', filters: filterUI.read()
    });
    if (generation !== recommendGeneration) return;
    select('generated-title').textContent = title.trim() || 'Your playlist';
    showContext(result);
    showSpotifyLink(null);
    select('spotify-status').textContent = '';
    lastResult = result;
    playlistSeeds = seedTracks;
    playbackMode = false;
    renderPlaylist();
  } catch (error) {
    if (generation === recommendGeneration) status.textContent = error.message || 'Recommendation failed.';
  } finally {
    if (generation === recommendGeneration) button.disabled = !realMode;
  }
}

select('track-search').addEventListener('input', () => {
  searchGeneration += 1;
  clearTimeout(timer);
  timer = setTimeout(searchTracks, 220);
});
select('search-more').addEventListener('click', () => searchTracks(true));
select('relevance-order').addEventListener('click', () => { playbackMode = false; renderPlaylist(); });
select('playback-order').addEventListener('click', () => { playbackMode = true; renderPlaylist(); });
select('demo-form').addEventListener('submit', recommend);
function setModelControls(ready) {
  for (const id of ['get-recs', 'track-search']) {
    select(id).disabled = !ready;
  }
  select('search-more').hidden = true;
}

async function initializeStudio() {
  let authorizationError = '';
  realMode = false;
  setModelControls(false);
  select('retry-model').disabled = true;
  select('mode-label').textContent = 'Connecting to model';
  select('demo-mode').textContent = 'Connecting to the trained playlist recommender…';
  try {
    modelStatus = await modelApi.status();
    if (modelStatus.unified_model !== true) throw new Error('Update the model server to enable the unified recommender.');
    realMode = true;
    select('mode-label').textContent = 'Trained model connected';
    const support = Number.isInteger(modelStatus.training_playlists)
      ? ' Trained on ' + modelStatus.training_playlists.toLocaleString() + ' playlists.' : '';
    select('demo-mode').textContent = 'Use a title, seed tracks, or filters to generate a playlist.' + support;
    select('demo-status').textContent = '';
    select('retry-model').hidden = true;
    setModelControls(true);
  } catch (error) {
    modelStatus = null;
    select('mode-label').textContent = 'Model disconnected';
    select('demo-mode').textContent = 'The trained recommender is not connected yet. Playlist generation will become available when its server is running.';
    select('demo-status').textContent = error.message;
    select('retry-model').hidden = false;
  } finally {
    select('retry-model').disabled = false;
  }

  let savedClientId;
  try { savedClientId = localStorage.getItem('beatx.spotify.clientId'); } catch {}
  const query = new URL(location.href).searchParams;
  const pending = (query.has('code') || query.has('error')) ? storedJson(sessionStorage, spotifyStorage.auth) : null;
  configureSpotify(pending?.clientId || modelStatus?.spotify_client_id || window.BEATX_CONFIG?.spotifyClientId || savedClientId);
  showSeeds();
  if (spotify) {
    try {
      const session = await spotify.completeAuthorization(location.href);
      if (session) {
        const draft = session.draft;
        select('spotify-status').textContent = 'Spotify connected.';
        if (restoreStudioDraft(draft)) {
          if (session.saveAfter) await saveSpotify(draft);
          return;
        }
      }
    } catch (error) {
      authorizationError = error.message;
    }
  }
  const savedDraft = storedJson(sessionStorage, 'beatx.studio.draft');
  if (restoreStudioDraft(savedDraft)) {
    if (authorizationError) select('spotify-status').textContent = authorizationError;
    return;
  }
  select('inferred-tags').textContent = realMode ? 'Add a title, seed tracks, or filters to get started.' : 'Waiting for the trained model.';
  if (authorizationError) select('spotify-status').textContent = authorizationError;
}

select('retry-model').addEventListener('click', initializeStudio);
initializeStudio();
