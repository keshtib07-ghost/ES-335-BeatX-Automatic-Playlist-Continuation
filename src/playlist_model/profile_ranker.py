"""Apply local song profiles to the collaborative-filtering candidate pool."""

import json
import sqlite3
from contextlib import closing

import joblib
import numpy as np

from .million import read_json, read_only
from .profile_tags import (ASSOCIATION_SMOOTHING, CONTEXT_AXIS, CONTEXT_GROUPS, CONTEXT_TAGS, DECADES,
                           EXPANDED_CUES_VERSION, PROFILE_VERSIONS, contextual_scores, predicted_context,
                           recording_era, requested_eras)


COLUMNS = {tag: index for index, tag in enumerate(CONTEXT_TAGS)}
FILTER_BACKFILL = 5_000
CONTEXT_BACKFILL = 50_000


def parse_filters(raw):
    if not isinstance(raw, dict):
        raise ValueError('Filters must be an object.')
    tags, eras = raw.get('tags', []), raw.get('eras', [])
    for values, choices in ((tags, COLUMNS), (eras, DECADES.values())):
        if not isinstance(values, list) or any(not isinstance(value, str) or value not in choices for value in values):
            raise ValueError('Unknown tag or era selection.')
    bpm = [raw.get('min_bpm'), raw.get('max_bpm')]
    if any(value is not None and (type(value) is not int or not 30 <= value <= 300) for value in bpm):
        raise ValueError('BPM must be between 30 and 300.')
    if None not in bpm and bpm[0] > bpm[1]:
        raise ValueError('Minimum BPM must be at most maximum BPM.')
    return {'tags': set(tags), 'eras': set(eras), 'bpm': bpm}


def reconcile_context(explicit, title, seeds):
    """Agree within a category and combine separate categories."""
    resolved = []
    conflicts = []
    for group in CONTEXT_GROUPS.values():
        group = set(group)
        signals = [values & group for values in (explicit, title, seeds)]
        agreed = set()
        winner = None
        for source, labels in zip(('selected filters', 'title', 'seeds'), signals):
            if not labels:
                continue
            if not agreed:
                agreed, winner = labels, source
            elif overlap := agreed & labels:
                agreed = overlap
            else:
                conflicts.append((winner, source))
        if agreed:
            resolved.append(agreed)
    return resolved, conflicts


class ProfileRanker:
    def __init__(self, path, data, catalogue_profiles=None):
        self.path = path
        self.split = data.identity['split']
        self.catalogue_profiles = catalogue_profiles
        if catalogue_profiles:
            with closing(sqlite3.connect(read_only(catalogue_profiles), uri=True)) as db:
                report = json.loads(db.execute("SELECT value FROM metadata WHERE key='report'").fetchone()[0])
                if report['mpd_archive_signature'] != self.split['archive_signature']:
                    raise ValueError('Bulk catalogue profiles belong to a different MPD archive.')
        tags = path / 'tags'
        identity = read_json(tags / 'summary.json')['identity']
        if (identity['split'] != self.split or identity['taxonomy_version'] not in PROFILE_VERSIONS
                or identity['tag_groups'] != {key: list(labels) for key, labels in CONTEXT_GROUPS.items()}):
            raise ValueError('Song profiles do not belong to this split and taxonomy.')
        self.expanded = identity['taxonomy_version'] == EXPANDED_CUES_VERSION
        self.tagger = joblib.load(tags / 'title_tagger.joblib')
        self.votes = np.load(tags / 'track_tag_votes.npy', mmap_mode='r')
        self.totals = np.load(tags / 'track_axis_totals.npy', mmap_mode='r')
        self.priors = np.load(tags / 'tag_priors.npy')

    def metadata(self, catalogue):
        path = self.path / 'enrichment.sqlite3'
        records = {}
        if not path.is_file():
            return records
        with closing(sqlite3.connect(read_only(path), uri=True)) as db:
            identity = json.loads(db.execute("SELECT value FROM identity WHERE key='run'").fetchone()[0])
            if identity['split'] != self.split:
                raise ValueError('Song metadata belongs to a different split.')
            for identifier, payload in db.execute('SELECT spotify_id, profile FROM lookups'):
                index = catalogue.execute('SELECT track_index FROM catalogue WHERE spotify_id=?', (identifier,)).fetchone()
                if index is not None:
                    records[index[0]] = json.loads(payload)
        return records

    def add_bulk_metadata(self, catalogue, indices, records):
        if not self.catalogue_profiles:
            return
        for start in range(0, len(indices), 500):
            batch = [int(index) for index in indices[start:start + 500]]
            placeholders = ','.join('?' for _ in batch)
            rows = catalogue.execute(f'''
                SELECT c.track_index, p.spotify_catalogue_release_date, p.musicbrainz_release_date,
                       p.bpm, p.bpm_source
                FROM main.catalogue c JOIN bulk_profiles.profiles p USING (spotify_id)
                WHERE c.track_index IN ({placeholders})
            ''', batch)
            for index, edition_date, recording_date, bpm, source in rows:
                if not (edition_date or recording_date or bpm is not None):
                    continue
                profile = records.setdefault(index, {})
                profile.update(catalogue_release_date=edition_date, bulk_recording_release_date=recording_date)
                if bpm is not None and (source in ('spotify_csv_id', 'spotify_parquet_id') or profile.get('bpm') is None):
                    profile.update(bpm=bpm, bpm_source=source)
                if (profile.get('match_status') != 'verified_recording' or not profile.get('release_date')) and edition_date:
                    profile.update(era=recording_era(int(edition_date[:4])), era_source='catalogue_edition')

    @staticmethod
    def filter_era(profile):
        if profile.get('era_source') == 'catalogue_edition' or profile.get('match_status') == 'verified_recording':
            return profile.get('era')
        return None

    def cue_lift(self, pool, columns):
        votes = self.votes[np.ix_(pool, columns)]
        counts = self.totals[np.ix_(pool, CONTEXT_AXIS[columns])]
        priors = self.priors[columns]
        rates = (votes + ASSOCIATION_SMOOTHING * priors) / (counts + ASSOCIATION_SMOOTHING)
        lift = np.divide(rates, priors, out=np.ones_like(rates), where=priors > 0)
        return np.where(votes > 0, lift, 1.0)

    def context_matrix(self, pool, groups):
        if not groups:
            return np.empty((len(pool), 0), dtype=float)
        columns = sorted({COLUMNS[tag] for group in groups for tag in group})
        lifts = self.cue_lift(pool, columns)
        index = {column: position for position, column in enumerate(columns)}
        return np.column_stack([
            lifts[:, [index[COLUMNS[tag]] for tag in group]].max(axis=1) for group in groups
        ])

    def track_tags(self, index, limit=4):
        votes = self.votes[index]
        lift = contextual_scores(votes, self.totals[index], self.priors)
        columns = np.flatnonzero((votes > 0) & (lift > 1))
        top = columns[np.argsort(-lift[columns], kind='stable')[:limit]]
        return [CONTEXT_TAGS[column] for column in top]

    def seed_context(self, seeds):
        support = [set(self.track_tags(index, limit=None)) for index in seeds]
        support = [tags for tags in support if tags]
        return {tag for tag in CONTEXT_TAGS
                if support and 2 * sum(tag in tags for tags in support) >= len(support)}

    def recommend(self, ranker, seeds, title, filters, catalogue):
        constraints = parse_filters(filters)
        inferred = predicted_context(self.tagger, [title], expanded=self.expanded)[0]
        title_tags = {CONTEXT_TAGS[i] for i in np.flatnonzero(inferred)}
        seed_tags = self.seed_context(seeds)
        explicit = constraints['tags']
        groups, conflicts = reconcile_context(explicit, title_tags, seed_tags)
        explicit_groups = [group for tags in CONTEXT_GROUPS.values() if (group := set(tags) & explicit)]
        title_groups = [group for group in groups if group & title_tags]
        metadata = self.metadata(catalogue)
        eras = constraints['eras']
        hinted_eras = requested_eras(title) if not eras else set()
        minimum, maximum = constraints['bpm']
        tempo_filter = minimum is not None or maximum is not None

        def keep_metadata(pool, scores):
            self.add_bulk_metadata(catalogue, pool, metadata)
            if not (eras or tempo_filter):
                return pool, scores
            keep = []
            for index in pool:
                profile = metadata.get(index, {})
                bpm = profile.get('bpm')
                keep.append((not eras or self.filter_era(profile) in eras) and
                            (not tempo_filter or (bpm is not None and (minimum or 0) <= bpm <= (maximum or 300))))
            keep = np.array(keep, dtype=bool)
            return pool[keep], scores[keep]

        warm_seeds = seeds[ranker.counts[seeds] > 0]
        if len(warm_seeds):
            candidates, scores, _ = ranker.candidates(warm_seeds, k=20)
            keep = ~np.isin(candidates, seeds)
            candidates, scores = candidates[keep], scores[keep]
        else:
            candidates = np.empty(0, dtype=np.int32)
            scores = np.empty(0)
        candidates, scores = keep_metadata(candidates, scores)
        source_matches = self.context_matrix(candidates, groups) > 1
        if len(candidates) < 20 or (groups and np.count_nonzero(source_matches.all(axis=1)) < 20):
            needs_context = bool(groups)
            limit = CONTEXT_BACKFILL if needs_context and not len(warm_seeds) else FILTER_BACKFILL
            if not (groups or eras or tempo_filter):
                limit = 20
            popular = ranker.popularity(np.concatenate((seeds, candidates)), limit)
            # Avoid loading bulk data for a large context-only pool. Fetch the
            # selected results below unless era or tempo affects eligibility.
            if eras or tempo_filter or hinted_eras:
                popular, _ = keep_metadata(popular, np.zeros(len(popular)))
            candidates = np.concatenate((candidates, popular))
            scores = np.concatenate((scores, np.zeros(len(popular))))

        if explicit_groups:
            allowed = (self.context_matrix(candidates, explicit_groups) > 1).all(axis=1)
            candidates, scores = candidates[allowed], scores[allowed]
        lift = self.context_matrix(candidates, groups)
        matches = lift > 1
        title_hits = (self.context_matrix(candidates, title_groups) > 1).sum(axis=1)
        full_match = matches.all(axis=1) if groups else np.zeros(len(candidates), dtype=bool)
        context_strength = np.clip(np.log(np.maximum(lift, 1)), 0, 2).sum(axis=1)
        era_hint = np.asarray([self.filter_era(metadata.get(index, {})) in hinted_eras for index in candidates])
        if len(scores) and scores.max() > 0:
            scores = scores / scores.max()
        # Exact context agreement comes first, then the title's context.
        # Stable candidate order breaks ties in favour of training popularity.
        order = np.lexsort((-context_strength, -scores, -era_hint.astype(int), -matches.sum(axis=1),
                            -title_hits, -full_match.astype(int)))
        verified = {index: profile for index, profile in metadata.items()
                    if profile.get('match_status') == 'verified_recording'}
        seen = {verified[index]['mbid'] for index in seeds if index in verified}
        result = []
        for index in candidates[order]:
            recording = verified.get(index, {}).get('mbid')
            if recording and recording in seen:
                continue
            if recording:
                seen.add(recording)
            result.append(index)
            if len(result) == 20:
                break
        result = np.asarray(result, dtype=np.int32)
        self.add_bulk_metadata(catalogue, result, metadata)
        notes = [f'{winner.capitalize()} took priority over conflicting {other} tags.'
                 for winner, other in sorted(set(conflicts))]
        if not len(warm_seeds):
            if matches.any() or era_hint.any():
                notes.append('No seed co-occurrence evidence. Used title or selected context with training popularity.')
            else:
                notes.append('No usable seed or context evidence. Used training popularity.')
        if groups and np.count_nonzero(full_match) < len(result):
            notes.append('Some suggestions match only part of the inferred context.')
        if eras:
            notes.append('Era uses reviewed recording dates when available. Catalogue edition dates can be later reissues.')
        if tempo_filter:
            notes.append('BPM filters require a known tempo.')
        if (eras or tempo_filter or explicit_groups) and len(result) < 20:
            notes.append('Fewer than 20 songs in the candidate pool matched the selected filters.')
        labels = set().union(*groups)
        return result, sorted(labels | eras | hinted_eras), metadata, ' '.join(notes)
