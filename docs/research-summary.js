/* Preserve links to report sections now that Research opens its summary. */
(function () {
  'use strict';
  const reportSections = new Set([
    'overview', 'known-seeds', 'unknown-seeds', 'questions', 'features',
    'training-scope', 'evaluation', 'method', 'studio-pipeline', 'metrics',
    'seed-study', 'results', 'findings', 'limitations', 'what-tags-mean',
    'method-status', 'conclusion', 'rubric', 'viva', 'reproduce', 'playback'
  ]);
  function openReportSection() {
    let section;
    try { section = decodeURIComponent(location.hash.slice(1)); }
    catch { return; }
    if (reportSections.has(section)) {
      location.replace(new URL(`research-deep-dive.html${location.hash}`, location.href).href);
    }
  }
  openReportSection();
  window.addEventListener('hashchange', openReportSection);
}());
