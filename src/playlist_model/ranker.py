import numpy as np
from scipy.sparse import csr_matrix

from .tagger import TAG_COLUMN, TAGS, era_hint


def ordered(items, scores, limit):
    if not len(items):
        return items, scores
    order = np.lexsort((items, -scores))[:limit]
    return items[order], scores[order]


class PlaylistRanker:
    def __init__(self, track_count, playlists, neighbours=200, shrinkage=10.):
        rows = np.repeat(np.arange(len(playlists)), [len(p.tracks) for p in playlists])
        columns = np.fromiter((index for p in playlists for index in p.tracks), dtype=np.int32)
        self.matrix = csr_matrix((np.ones(len(columns), dtype=np.uint8), (rows, columns)),
                                 shape=(len(playlists), track_count))
        self.by_track = self.matrix.tocsc()
        self.counts = np.diff(self.by_track.indptr)
        active = np.flatnonzero(self.counts).astype(np.int32)
        self.popular, _ = ordered(active, self.counts[active], len(active))
        self.neighbours = neighbours
        self.shrinkage = shrinkage
        self.cache = {}

    def similar(self, seed):
        if seed not in self.cache:
            lo, hi = self.by_track.indptr[seed:seed + 2]
            rows = self.by_track.indices[lo:hi]
            pool, supports = np.unique(self.matrix[rows].indices, return_counts=True)
            mask = pool != seed
            pool, supports = pool[mask], supports[mask].astype(np.float64)
            scores = supports / np.sqrt(float(self.counts[seed]) * self.counts[pool])
            scores *= supports / (supports + self.shrinkage)
            self.cache[seed] = ordered(pool, scores, self.neighbours)
        return self.cache[seed]

    def candidates(self, seeds, allowed=None, k=20):
        seeds = np.unique(seeds)
        rows = [self.similar(int(seed)) for seed in seeds]
        ids = np.concatenate([row[0] for row in rows])
        weights = np.concatenate([row[1] for row in rows])
        items, inverse = np.unique(ids, return_inverse=True)
        totals = np.bincount(inverse, weights=weights, minlength=len(items))
        keep = ~np.isin(items, seeds)
        if allowed is not None:
            keep &= allowed[items]
        items, totals = items[keep], totals[keep]
        if len(items) < k:
            exclude = np.concatenate((items, seeds))
            fallback = self.popularity(exclude, allowed, k - len(items))
            items = np.concatenate((items, fallback))
            totals = np.concatenate((totals, np.zeros(len(fallback))))
        return items, totals

    def popularity(self, excluded_seeds, allowed=None, k=20):
        denied = set(map(int, excluded_seeds))
        selected = []
        for item in self.popular:
            if int(item) not in denied and (allowed is None or allowed[item]):
                selected.append(item)
                if len(selected) >= k:
                    break
        return np.asarray(selected, dtype=np.int32)

    def recommend_from(self, items, scores, tag_columns=(), lifts=None, strength=0., k=20):
        if len(tag_columns) and strength:
            # Keep the candidate pool identical to plain CF in the ablation.
            tag_evidence = np.maximum(np.log(np.maximum(lifts[np.ix_(items, tag_columns)], .01)), 0).mean(axis=1)
            scores = scores * (1 + strength * tag_evidence)
        ranks, _ = ordered(items, scores, k)
        # CF-positive candidates come first. Zero-score fills retain popularity order.
        if len(items) and np.count_nonzero(scores > 0) < k:
            ranks = np.concatenate((ranks[np.isin(ranks, items[scores > 0])], items[scores == 0]))[:k]
        return ranks


def recommend(bundle, title, seed_identifiers, explicit_tags=None, era=None, bpm_range=None, k=20):
    tagger = bundle['tagger']
    catalog, aliases = bundle['tracks'], bundle['aliases']
    ranker = bundle['ranker']
    unknown = [track for track in seed_identifiers if track not in aliases]
    if unknown:
        raise ValueError(f'Unknown seed track IDs: {", ".join(unknown)}')
    seeds = np.asarray(list(dict.fromkeys(aliases[track] for track in seed_identifiers)))
    predicted = [TAGS[i] for i in np.flatnonzero(tagger.predict([title])[0])]
    tags = predicted if explicit_tags is None else explicit_tags
    columns = [TAG_COLUMN[tag] for tag in tags]
    wanted_era = era if era is not None else era_hint(title)
    allowed, notices = None, []
    if wanted_era is not None:
        ages = np.asarray([track.year or 0 for track in catalog])
        decade = (ages >= wanted_era) & (ages < wanted_era + 10)
        if era is not None or np.any(decade[ranker.popular]):
            allowed = decade
        else:
            notices.append('Title suggests an era, but the training catalogue has no verified matches for it.')
    if bpm_range:
        low, high = bpm_range
        if not 20 <= low <= high <= 350:
            raise ValueError('Require 20 <= minimum BPM <= maximum BPM <= 350')
        tempos = np.asarray([track.bpm or 0 for track in catalog])
        in_range = (tempos >= low) & (tempos <= high)
        allowed = in_range & allowed if allowed is not None else in_range
    if allowed is not None and not np.any(allowed[ranker.popular]):
        notices.append('No training-catalogue recordings have verified metadata that satisfies the requested filters.')
    items, scores = ranker.candidates(seeds, allowed, k)
    ranking = ranker.recommend_from(items, scores, columns, bundle['lifts'], bundle['strength'], k)
    if not ranker.counts[seeds].any():
        notices.append('These seeds were absent from training; the recommendation uses catalogue popularity.')
    if len(seeds) < len(seed_identifiers):
        notices.append('Duplicate seeds or verified alternate releases were counted once.')
    results = []
    counts, opportunities = bundle['tally'], bundle['opportunities']
    for item in ranking:
        track = catalog[item]
        evidence = {tag: {'support': int(counts[item, col]), 'eligible': int(opportunities[item, col]),
                          'lift': round(float(bundle['lifts'][item, col]), 3)}
                    for tag, col in zip(tags, columns) if counts[item, col]}
        visible_tags = [tag for tag, col in zip(tags, columns)
                        if counts[item, col] >= 5 and opportunities[item, col] >= 1
                        and counts[item, col] / opportunities[item, col] >= .4 and bundle['lifts'][item, col] > 1]
        results.append({'title': track.title, 'artist': track.artist, 'spotify_id': track.spotify_id,
                        'release_year': track.year, 'bpm': track.bpm, 'shown_tags': visible_tags,
                        'evidence': evidence})
    return {'title': title, 'predicted_tags': predicted, 'applied_tags': tags, 'requested_era': wanted_era,
            'notices': notices, 'recommendations': results}
