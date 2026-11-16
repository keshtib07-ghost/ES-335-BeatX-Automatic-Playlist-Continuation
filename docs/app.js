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
let playbackMode = false;
const maxSeeds = 20;
const filterUI = setupFilters();
const profileOption = node('option', 'CF + song profiles');
profileOption.value = 'song_profiles';
select('demo-method').prepend(profileOption);
select('demo-method').value = profileOption.value;
let spotify;
let savingSpotify = false;
let pendingSpotifySave = false;
const artworkLoader = new SpotifyArtwork();

function updateMethod() {
  const method = select('demo-method').value;
  const usesOldTags = ['learned_title', 'keyword_title'].includes(method);
  select('demo-context').disabled = !usesOldTags;
  select('demo-context').parentElement.hidden = !usesOldTags;
  filterUI.show(method === 'song_profiles');
}

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
    result: lastResult, playbackMode, seedTracks: selected, realMode, modelId: modelStatus?.model_id || 'local',
    method: select('demo-method').value, context: select('demo-context').value, filters: filterUI.read()};
}

function restoreStudioDraft(draft) {
  if (!realMode || draft?.realMode !== true || draft.modelId !== (modelStatus?.model_id || 'local') ||
      !draft.result || !Array.isArray(draft.seedTracks)) return false;
  selected = draft.seedTracks;
  lastResult = draft.result;
  playbackMode = Boolean(draft.playbackMode);
  select('playlist-title').value = draft.title;
  select('generated-title').textContent = draft.title;
  if ([...select('demo-method').options].some((option) => option.value === draft.method && !option.disabled)) {
    select('demo-method').value = draft.method;
  }
  select('demo-context').value = draft.context || '';
  filterUI.restore(draft.filters || {});
  updateMethod();
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
  select('copy-playlist-link').hidden = !url;
  if (url) link.href = url;
  else link.removeAttribute('href');
}

function configureSpotify(clientId) {
  if (!spotifyClientId(clientId)) return;
  spotify = new SpotifyStudio(clientId);
  select('connect-spotify').textContent = spotify.connected ? 'Reconnect Spotify' : 'Connect Spotify';
}

function ensureSpotify(saveAfter) {
  if (spotify) return true;
  pendingSpotifySave = saveAfter;
  select('spotify-redirect-uri').textContent = spotifyRedirectUri();
  select('spotify-setup').showModal();
  return false;
}

async function connectSpotify() {
  if (!ensureSpotify(false)) return;
  try {
    await spotify.authorize(spotifyDraft(), false);
  } catch (error) {
    select('spotify-status').textContent = error.message;
  }
}

async function saveSpotify(draft = spotifyDraft()) {
  if (!realMode || draft?.realMode !== true || savingSpotify || !draft.ids.length || !ensureSpotify(true)) return;
  const status = select('spotify-status');
  showSpotifyLink(null);
  savingSpotify = true;
  select('save-spotify').disabled = true;
  select('recommend-and-save').disabled = true;
  try {
    if (!spotify.connected) {
      await spotify.authorize(draft, true);
      return;
    }
    status.textContent = 'Creating your Spotify playlist…';
    const url = await spotify.save(draft);
    // Display only a completed playlist for the order currently on screen.
    if (spotify.playlistKey(draft) === spotify.playlistKey(spotifyDraft())) showSpotifyLink(url);
    status.textContent = `Saved ${draft.ids.length} recommended tracks to Spotify.`;
  } catch (error) {
    status.textContent = `${error.message} Use Create Spotify playlist to retry.`;
  } finally {
    savingSpotify = false;
    renderPlaylist();
    select('recommend-and-save').disabled = !realMode;
    select('connect-spotify').textContent = spotify.connected ? 'Reconnect Spotify' : 'Connect Spotify';
  }
}

select('connect-spotify').addEventListener('click', connectSpotify);
select('save-spotify').addEventListener('click', () => saveSpotify());
select('close-spotify-setup').addEventListener('click', () => select('spotify-setup').close());
select('spotify-setup-form').addEventListener('submit', async (event) => {
  event.preventDefault();
  const clientId = select('spotify-client-id').value.trim();
  if (!spotifyClientId(clientId)) return;
  configureSpotify(clientId);
  try { localStorage.setItem('beatx.spotify.clientId', clientId.toLowerCase()); } catch {}
  select('spotify-setup').close();
  if (pendingSpotifySave) await saveSpotify();
  else await connectSpotify();
});
select('copy-playlist-link').addEventListener('click', async () => {
  try {
    await navigator.clipboard.writeText(select('spotify-playlist-link').href);
    select('spotify-status').textContent = 'Spotify playlist link copied.';
  } catch {
    select('spotify-status').textContent = 'Open the Spotify link and copy its address.';
  }
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
  select('save-spotify').disabled = savingSpotify || !list.length || !list.every((track) => spotifyTrackId(track.id));
  showSpotifyLink(spotify?.savedPlaylist(spotifyDraft()) || null);
  select('relevance-order').setAttribute('aria-pressed', String(!playbackMode));
  select('playback-order').setAttribute('aria-pressed', String(playbackMode));
  select('playback-order').disabled = lastResult.transition_evidence === null;
  const support = realMode ? ` · ${lastResult.known_seeds}/${lastResult.seed_count} seeds seen in training` : '';
  const transitions = playbackMode ? ` · ${lastResult.transition_evidence}/${list.length} transitions supported, including the last seed` : '';
  select('generation-evidence').textContent = `${list.length} additions${support}${transitions}`;
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
  const saveButton = select('recommend-and-save');
  const saveWhenReady = event?.submitter === saveButton;
  const status = select('demo-status');
  status.textContent = '';
  if (!realMode) {
    status.textContent = 'Connect the trained model before generating a playlist.';
    return;
  }
  if (selected.length < 1 || selected.length > maxSeeds) {
    status.textContent = 'Select 1–20 distinct seed tracks first.';
    return;
  }
  button.disabled = true;
  saveButton.disabled = true;
  try {
    const title = select('playlist-title').value;
    const method = select('demo-method').value;
    const context = select('demo-context').value;
    const filters = filterUI.read();
    const seeds = [...selected];
    async function getRanking(approach) {
      return modelApi.recommend({title, seeds: seeds.map((track) => track.id), method: approach, context, filters});
    }
    const result = await getRanking(method);
    const baseline = select('compare-cf').checked && method !== 'cf' ? await getRanking('cf') : null;
    if (generation !== recommendGeneration) return;
    select('generated-title').textContent = title.trim() || 'Your playlist';
    showContext(result);
    showSpotifyLink(null);
    select('spotify-status').textContent = '';
    lastResult = result;
    playbackMode = false;
    renderPlaylist();
    select('demo-comparison').hidden = !baseline;
    if (baseline) {
      const common = new Set(baseline.tracks.map((track) => track.id));
      const overlap = result.tracks.filter((track) => common.has(track.id)).length;
      select('comparison-summary').textContent = `Plain CF ranking · ${overlap} of ${result.tracks.length} suggestions in common`;
      select('comparison-list').replaceChildren(...baseline.tracks.map(trackRow));
    }
    if (saveWhenReady && result.tracks.length) await saveSpotify();
  } catch (error) {
    if (generation === recommendGeneration) status.textContent = error.message || 'Recommendation failed.';
  } finally {
    if (generation === recommendGeneration) button.disabled = saveButton.disabled = !realMode;
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
select('demo-method').addEventListener('change', updateMethod);
select('demo-form').addEventListener('submit', recommend);
function setModelControls(ready) {
  for (const id of ['get-recs', 'recommend-and-save', 'track-search', 'demo-method', 'compare-cf']) {
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
    realMode = true;
    profileOption.disabled = !modelStatus.song_profiles;
    select('demo-method').value = modelStatus.song_profiles ? 'song_profiles' : 'learned_title';
    select('mode-label').textContent = 'Trained model connected';
    const support = Number.isInteger(modelStatus.training_playlists)
      ? ' Trained on ' + modelStatus.training_playlists.toLocaleString() + ' playlists.' : '';
    select('demo-mode').textContent = 'Search the model catalogue and generate recommendations from your seed songs.' + support;
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
  select('recommend-and-save').hidden = false;
  updateMethod();
  showSeeds();
  if (spotify) {
    try {
      const session = await spotify.completeAuthorization(location.href);
      if (session) {
        const draft = session.draft;
        select('spotify-status').textContent = 'Spotify connected.';
        select('connect-spotify').textContent = 'Reconnect Spotify';
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
  select('inferred-tags').textContent = realMode ? 'Add seed tracks to get started.' : 'Waiting for the trained model.';
  if (authorizationError) select('spotify-status').textContent = authorizationError;
}

select('retry-model').addEventListener('click', initializeStudio);
initializeStudio();
