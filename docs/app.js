'use strict';

const select = (id) => document.getElementById(id);
function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = content;
  if (className) element.className = className;
  return element;
}

const experiment = window.NEXT_TRACK_EXPERIMENT;
const methods = [['popularity', 'Popularity'], ['collaborative_filtering', 'Collaborative filtering'], ['selected_tag_ranker', 'CF + title tags']];
const metrics = {
  ndcg_at_20: ['NDCG@20 rewards reference tracks found near the top of the first 20 results.', (value) => value.toFixed(4)],
  recall_at_20: ['Recall@20 is the share of withheld tracks recovered in the first 20 results.', (value) => `${(100 * value).toFixed(2)}%`],
  precision_at_20: ['Precision@20 is the share of the first 20 results that are in the withheld playlist.', (value) => `${(100 * value).toFixed(2)}%`],
  hit_rate_at_20: ['Hit rate@20 is the fraction of playlists with at least one withheld track in the first 20 results.', (value) => `${(100 * value).toFixed(2)}%`],
};
let cohort = 'all_queries';
let metric = 'ndcg_at_20';

function showResults() {
  const score = experiment[cohort];
  const [, format] = metrics[metric];
  const tagged = cohort === 'title_tagged_queries';
  const count = tagged ? experiment.sample.title_tagged_queries : experiment.sample.eligible_queries_evaluated;
  select('query-count').textContent = `${count.toLocaleString('en-US')} held-out queries`;
  select('metric-description').textContent = metrics[metric][0];
  const maximum = Math.max(...['all_queries', 'title_tagged_queries'].flatMap((scope) =>
    methods.map(([key]) => experiment[scope][key]?.[metric] ?? 0)));
  const axisMax = Math.max(.05, Math.ceil(maximum * 20) / 20);
  select('chart-scale').textContent = `Bar scale ${format(0)} – ${format(axisMax)}`;
  select('chart').replaceChildren(...methods.map(([key, name]) => {
    const value = score[key][metric];
    const row = node('div', undefined, 'chart-row');
    row.setAttribute('role', 'row');
    const label = node('span', name, 'chart-label');
    const visual = node('span', undefined, 'bar-track');
    const bar = node('i', undefined, 'bar');
    const cell = node('span', format(value), 'chart-value');
    label.setAttribute('role', 'rowheader');
    visual.setAttribute('aria-hidden', 'true');
    cell.setAttribute('role', 'cell');
    bar.style.width = `${100 * value / axisMax}%`;
    visual.append(bar);
    row.append(label, visual, cell);
    return row;
  }));
  const gain = score.selected_tag_ranker[metric] - score.collaborative_filtering[metric];
  const detail = select('evidence');
  if (metric === 'ndcg_at_20') {
    const interval = experiment[tagged ? 'tag_ranker_minus_cf_ndcg_95_ci_tagged' : 'tag_ranker_minus_cf_ndcg_95_ci_all'];
    const message = interval ? ` · paired 95% interval ${interval[0].toFixed(4)} to ${interval[1].toFixed(4)}` : '';
    detail.replaceChildren(node('strong', `${gain >= 0 ? '+' : ''}${gain.toFixed(4)} NDCG@20`), document.createTextNode(` vs. plain CF${message}`));
  } else {
    detail.replaceChildren(node('strong', `${gain >= 0 ? '+' : ''}${(100 * gain).toFixed(2)} percentage points`), document.createTextNode(' vs. plain CF'));
  }
}

for (const button of document.querySelectorAll('[data-cohort], [data-metric]')) {
  if (button.dataset.cohort === 'title_tagged_queries' && !experiment.sample.title_tagged_queries) button.disabled = true;
  button.addEventListener('click', () => {
    const group = button.dataset.cohort ? 'cohort' : 'metric';
    if (group === 'cohort') cohort = button.dataset.cohort;
    else metric = button.dataset.metric;
    for (const peer of document.querySelectorAll(`[data-${group}]`)) peer.setAttribute('aria-pressed', String(peer === button));
    showResults();
  });
}
showResults();

const fictional = [
  ['Windowlight', 'Glass Station', 'study chill rainy'], ['Low Clouds', 'Evening Static', 'study rainy'],
  ['Paper Lanterns', 'Field Notes', 'study chill'], ['Blue Margin', 'Field Notes', 'study chill'],
  ['After the Rain', 'Evening Static', 'rainy chill'], ['Quiet Hours', 'Glass Station', 'study sleep'],
  ['Corners of the Library', 'Field Notes', 'study rainy'], ['Soft Landing', 'Glass Station', 'chill sleep'],
  ['Empty Platform', 'Evening Static', 'rainy sad'], ['First Draft', 'Field Notes', 'study'],
  ['Kitchen Window', 'Glass Station', 'chill'], ['Porch in June', 'Glass Station', 'summer chill'],
  ['Night Trainer', 'Turnline', 'gym upbeat'], ['Second Lap', 'Turnline', 'gym upbeat'],
  ['Hold the Pace', 'Turnline', 'gym dance'], ['Floor Signal', 'North Exit', 'dance rave'],
  ['Lights Until Dawn', 'North Exit', 'rave party'], ['South Stairwell', 'North Exit', 'party dance'],
  ['Last Train Home', 'Evening Static', 'sad rainy'], ['Sundial', 'Field Notes', 'summer upbeat'],
  ['Zero Visibility', 'Evening Static', 'winter rainy'], ['Daybreak Repeat', 'North Exit', 'summer dance party'],
  ['On the Run Again', 'Turnline', 'upbeat gym'], ['Snow Overhead', 'Glass Station', 'winter sleep'],
  ['Small Hours', 'Field Notes', 'sleep study'], ['Drift Lines', 'Evening Static', 'sad winter'],
].map(([title, artist, labels], index) => ({id: `demo-${index}`, title, artist, tags: labels.split(' ')}));

const demoRules = {study: /study|focus|homework/, chill: /chill|relax|calm/, rainy: /rain|storm/, sleep: /sleep|bedtime/,
  gym: /gym|workout|running/, upbeat: /upbeat|hype/, dance: /dance/, party: /party/, rave: /rave/,
  sad: /sad|heartbreak/, summer: /summer/, winter: /winter|snow/};
let realMode = false;
let selected = fictional.slice(0, 3);
let timer;
let searchGeneration = 0;
let recommendGeneration = 0;

function showSeeds() {
  select('seed-count').textContent = `${selected.length} / 3`;
  select('seed-chips').replaceChildren(...selected.map((track) => {
    const button = node('button', `${track.title} ×`, 'chip');
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

async function searchTracks() {
  const query = select('track-search').value.trim();
  const generation = ++searchGeneration;
  const list = select('track-matches');
  list.replaceChildren();
  if (selected.length === 3 || (realMode && query.length < 2)) return;
  try {
    let matches;
    if (realMode) {
      const response = await fetch(`/api/search?q=${encodeURIComponent(query)}`);
      if (!response.ok) throw new Error('Search failed');
      matches = (await response.json()).tracks;
    } else {
      matches = fictional.filter((track) => `${track.title} ${track.artist}`.toLowerCase().includes(query.toLowerCase()));
    }
    if (generation !== searchGeneration) return;
    matches = matches.filter((candidate) => !selected.some((track) => track.id === candidate.id)).slice(0, 7);
    if (!matches.length) list.append(node('p', 'No matching tracks.', 'small'));
    for (const track of matches) {
      const button = node('button', `${track.title} · ${track.artist}`);
      button.type = 'button';
      button.addEventListener('click', () => {
        if (selected.length >= 3) return;
        selected.push(track);
        select('track-search').value = '';
        showSeeds();
        searchTracks();
        select(selected.length === 3 ? 'get-recs' : 'track-search').focus();
      });
      list.append(button);
    }
  } catch (error) {
    if (generation === searchGeneration) list.append(node('p', 'Track search is unavailable.', 'small'));
  }
}

function demoRecommendation(title, seeds) {
  const inferred = Object.entries(demoRules).filter(([, rule]) => rule.test(title.toLowerCase())).map(([label]) => label);
  const seedTags = seeds.flatMap((track) => track.tags);
  const value = (track) => track.tags.reduce((sum, tag) => sum + seedTags.filter((t) => t === tag).length, 0)
    + 2 * track.tags.filter((tag) => inferred.includes(tag)).length;
  const tracks = fictional.filter((track) => !seeds.some((seed) => seed.id === track.id))
    .sort((a, b) => value(b) - value(a)).slice(0, 20);
  return {tags: inferred, tracks, cold: 0};
}

async function recommend(event) {
  event?.preventDefault();
  const generation = ++recommendGeneration;
  const button = select('get-recs');
  const status = select('demo-status');
  status.textContent = '';
  if (selected.length !== 3) {
    status.textContent = 'Select three distinct tracks first.';
    return;
  }
  button.disabled = true;
  try {
    const title = select('playlist-title').value;
    let result;
    if (realMode) {
      const response = await fetch('/api/recommend', {method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({title, seeds: selected.map((track) => track.id)})});
      result = await response.json();
      if (!response.ok) throw new Error(result.error || 'Recommendation failed.');
    } else result = demoRecommendation(title, selected);
    if (generation !== recommendGeneration) return;
    select('inferred-tags').textContent = result.tags.length ? `Title tags · ${result.tags.join(', ')}` : 'No title tags inferred.';
    select('track-list').replaceChildren(...result.tracks.map((track) => {
      const li = node('li', undefined, 'track');
      const info = node('div');
      info.append(node('strong', track.title), node('small', track.artist));
      li.append(info);
      return li;
    }));
    status.textContent = result.cold ? `${result.cold} seed track(s) were unseen during training.` : `${result.tracks.length} suggestions`;
  } catch (error) {
    if (generation === recommendGeneration) status.textContent = error.message || 'Recommendation failed.';
  } finally {
    if (generation === recommendGeneration) button.disabled = false;
  }
}

select('track-search').addEventListener('input', () => {
  searchGeneration += 1;
  clearTimeout(timer);
  timer = setTimeout(searchTracks, 220);
});
select('demo-form').addEventListener('submit', recommend);
showSeeds();
recommend();

const owner = location.hostname.match(/^([\w-]+)\.github\.io$/);
const repo = location.pathname.split('/').filter(Boolean)[0];
if (owner && repo && /^[\w.-]+$/.test(repo) && !/\.html$/.test(repo)) {
  select('source-link').href = `https://github.com/${owner[1]}/${repo}#readme`;
  select('source-link').hidden = false;
}
if (['localhost', '127.0.0.1'].includes(location.hostname)) {
  fetch('/api/status').then((response) => response.ok ? response.json() : null).then((status) => {
    if (!status?.trained_model) return;
    realMode = true;
    selected = [];
    select('mode-label').textContent = 'Local trained model';
    select('demo-mode').textContent = 'Search your local MPD catalogue and get predictions from the trained model. This data stays on your machine.';
    select('inferred-tags').textContent = 'Add three tracks to get started.';
    select('demo-status').textContent = '';
    select('track-list').replaceChildren();
    showSeeds();
  }).catch(() => {});
}
