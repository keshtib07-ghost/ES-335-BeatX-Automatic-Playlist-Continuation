'use strict';

const select = (id) => document.getElementById(id);
function node(tag, content, className) {
  const element = document.createElement(tag);
  if (content !== undefined) element.textContent = content;
  if (className) element.className = className;
  return element;
}

// Keep old research bookmarks working after the page split.
if (document.body.dataset.page === 'studio' &&
    ['#seed-study', '#results', '#features', '#method', '#reproduce', '#findings'].includes(location.hash)) {
  location.replace(new URL(`research.html${location.hash}`, location.href).href);
}
const sourceLink = document.getElementById('source-link');
if (sourceLink) {
  const owner = location.hostname.match(/^([\w-]+)\.github\.io$/);
  const repository = location.pathname.split('/').filter(Boolean)[0];
  if (owner && repository && /^[\w.-]+$/.test(repository)) {
    sourceLink.href = `https://github.com/${owner[1]}/${repository}#readme`;
    sourceLink.hidden = false;
  }
}
