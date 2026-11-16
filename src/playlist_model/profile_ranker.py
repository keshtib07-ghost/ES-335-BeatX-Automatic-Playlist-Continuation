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

    def context_bonus(self, pool, tags):
        columns = sorted(COLUMNS[tag] for tag in tags)
        if not columns:
            return np.zeros(len(pool))
        axes = CONTEXT_AXIS[columns]
        votes = self.votes[np.ix_(pool, columns)]
        counts = self.totals[np.ix_(pool, axes)]
        priors = self.priors[columns]
        rates = (votes + ASSOCIATION_SMOOTHING * priors) / (counts + ASSOCIATION_SMOOTHING)
        lift = np.divide(rates, priors, out=np.ones_like(rates), where=priors > 0)
        lift = np.clip(np.log(np.maximum(lift, .01)), 0, 2.0)
        return np.mean([lift[:, axes == axis].max(axis=1) for axis in set(axes)], axis=0)

    def track_tags(self, index):
        votes = self.votes[index]
        lift = contextual_scores(votes, self.totals[index], self.priors)
        columns = np.flatnonzero((votes > 0) & (lift > 1))
        top = columns[np.argsort(-lift[columns], kind='stable')[:4]]
        return [CONTEXT_TAGS[column] for column in top]

    def recommend(self, ranker, seeds, title, filters, catalogue):
        constraints = parse_filters(filters)
        inferred = predicted_context(self.tagger, [title], expanded=self.expanded)[0]
        labels = constraints['tags'] or {CONTEXT_TAGS[i] for i in np.flatnonzero(inferred)}
        metadata = self.metadata(catalogue)
        eras = constraints['eras']
        hinted_eras = requested_eras(title) if not eras else set()
        space, scores, fallback = ranker.candidates(seeds, k=60)
        candidates = np.concatenate((space, fallback))
        values = np.concatenate((scores, np.zeros(len(fallback))))
        self.add_bulk_metadata(catalogue, candidates, metadata)
        minimum, maximum = constraints['bpm']
        tempo_filter = minimum is not None or maximum is not None

        def fits(index):
            profile = metadata.get(index, {})
            if eras and self.filter_era(profile) not in eras:
                return False
            bpm = profile.get('bpm')
            return not tempo_filter or (bpm is not None and (minimum or 0) <= bpm <= (maximum or float('inf')))

        if eras or tempo_filter:
            keep = np.fromiter((fits(index) for index in candidates), dtype=bool, count=len(candidates))
            candidates, values = candidates[keep], values[keep]
            if len(candidates) < 20:
                popular = ranker.popularity(np.concatenate((seeds, candidates)), FILTER_BACKFILL)
                self.add_bulk_metadata(catalogue, popular, metadata)
                backfill = [index for index in popular if fits(index)][:20]
                candidates = np.concatenate((candidates, np.asarray(backfill, dtype=np.int32)))
                values = np.concatenate((values, np.zeros(len(backfill))))

        bonus = self.context_bonus(candidates, labels)
        bonus += np.asarray([.2 if self.filter_era(metadata.get(index, {})) in hinted_eras else 0.
                             for index in candidates])
        verified = {index: profile for index, profile in metadata.items()
                    if profile.get('match_status') == 'verified_recording'}
        order = np.argsort(-(values * (1 + bonus)), kind='stable')
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
        notes = []
        if eras:
            notes.append('Era uses reviewed recording dates when available. Catalogue edition dates can be later reissues.')
        if tempo_filter:
            notes.append('BPM filters require a known tempo.')
        if (eras or tempo_filter) and len(result) < 20:
            notes.append('The available candidates did not fill all 20 positions.')
        return np.array(result, dtype=np.int32), sorted(labels | eras | hinted_eras), metadata, ' '.join(notes)
