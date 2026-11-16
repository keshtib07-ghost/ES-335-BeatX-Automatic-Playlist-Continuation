"""Disk-backed training against the verified full-MPD split."""

import hashlib
import json
import os
import sqlite3
from contextlib import closing, contextmanager
from functools import lru_cache
from pathlib import Path
from tempfile import TemporaryDirectory

import joblib
import numpy as np
from scipy.sparse import csr_matrix

from .ranker import ordered
from .tagger import TAG_COLUMN, TAG_GROUPS, TAGS, TitleTagger, classification_metrics, label_matrix, weak_tags


VERSION = 'full-mpd-training-v1'
TAG_BLOCK = 2048
GROUP_COLUMNS = tuple(np.array([TAG_COLUMN[tag] for tag in group]) for group in TAG_GROUPS.values())
TAG_AXIS = np.array([axis for axis, columns in enumerate(GROUP_COLUMNS) for _ in columns])


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    temporary.replace(path)


def read_only(path):
    return Path(path).resolve().as_uri() + '?mode=ro'


class Dataset:
    def __init__(self, connection, allow_partial):
        self.connection = connection
        source = json.loads(connection.execute("SELECT value FROM run_info WHERE key='identity'").fetchone()[0])
        split = json.loads(connection.execute("SELECT value FROM splits.split_info WHERE key='identity'").fetchone()[0])
        if (source['archive_signature'] != split['archive_signature'] or split['version'] != 'mpd-grouped-split-v1'
                or source['version'] != 'mpd-staging-v1'):
            raise ValueError('Source and split databases must belong to the same staging run')
        self.sizes = dict(connection.execute('SELECT split, COUNT(*) FROM splits.assigned_splits GROUP BY split'))
        if sum(self.sizes.values()) != split['source_playlists'] or set(self.sizes) != {'train', 'validation', 'test'}:
            raise ValueError('Finish and verify the grouped split before training')
        if not allow_partial and (not split['source_is_full_mpd'] or split['source_playlists'] != 1_000_000):
            raise ValueError('Expected the complete one-million-playlist split')
        self.track_count = split['source_track_indices']
        self.aliases = None
        aliases = connection.execute('SELECT track_index, recording_index FROM splits.recording_aliases')
        if first := aliases.fetchone():
            self.aliases = np.arange(self.track_count, dtype=np.int32)
            self.aliases[first[0]] = first[1]
            for track_index, recording_index in aliases:
                self.aliases[track_index] = recording_index
        self.identity = {'version': VERSION, 'split': split, 'partition_sizes': self.sizes}

    def rows(self, partition, fields):
        return self.connection.execute(f'''
            SELECT {fields} FROM playlists AS p
            JOIN splits.assigned_splits AS s USING (pid)
            WHERE s.split=? ORDER BY p.pid
        ''', (partition,))

    def recordings(self, payload, expected):
        items = np.frombuffer(payload, dtype='<i4')
        if self.aliases is not None:
            items = np.unique(self.aliases[items])
        if len(items) != expected:
            raise ValueError('Playlist membership count disagrees with the split database')
        return items

    def sample(self, partition, fields, limit, salt, eligible=False):
        suffix = ' AND s.recording_count>3' if eligible else ''
        count = self.connection.execute(f'SELECT COUNT(*) FROM splits.assigned_splits AS s WHERE s.split=?{suffix}',
                                        (partition,)).fetchone()[0]
        cursor = self.connection.execute(f'''
            SELECT {fields} FROM playlists AS p JOIN splits.assigned_splits AS s USING (pid)
            WHERE s.split=?{suffix} ORDER BY p.pid
        ''', (partition,))
        if count <= limit:
            return list(cursor)
        positions = set(np.random.default_rng(salt).choice(count, limit, replace=False).tolist())
        return [row for index, row in enumerate(cursor) if index in positions]


@contextmanager
def open_dataset(source, split, allow_partial=False):
    with closing(sqlite3.connect(read_only(source), uri=True)) as connection:
        connection.execute('ATTACH DATABASE ? AS splits', (read_only(split),))
        connection.execute('PRAGMA query_only=ON')
        connection.execute('PRAGMA cache_size=-32768')
        yield Dataset(connection, allow_partial)


def completed(path, identity, files):
    if not path.exists():
        return None
    if any(not (path / name).is_file() for name in (*files, 'summary.json')):
        raise ValueError(f'Incomplete outputs in {path}. Use another run folder')
    result = read_json(path / 'summary.json')
    if result['identity'] != identity:
        raise ValueError(f'{path} uses a different split or settings. Use another run folder')
    return result


def build_index(data, run):
    target = run / 'index'
    files = ('playlist_indices.npy', 'playlist_offsets.npy', 'track_playlists.npy', 'track_offsets.npy', 'train_pids.npy')
    if prior := completed(target, data.identity, files):
        return prior
    run.mkdir(parents=True, exist_ok=True)
    count, memberships = data.connection.execute('''
        SELECT COUNT(*), COALESCE(SUM(recording_count),0) FROM splits.assigned_splits WHERE split='train'
    ''').fetchone()
    if not memberships or memberships > np.iinfo(np.int32).max:
        raise ValueError('Training membership count is outside the index format')
    print(f'Indexing {count:,} training playlists and {memberships:,} memberships', flush=True)
    with TemporaryDirectory(dir=run, prefix='.index-') as temp:
        path = Path(temp)
        indices = np.lib.format.open_memmap(path / files[0], mode='w+', dtype=np.int32, shape=(memberships,))
        offsets = np.lib.format.open_memmap(path / files[1], mode='w+', dtype=np.int32, shape=(count + 1,))
        pids = np.lib.format.open_memmap(path / files[4], mode='w+', dtype=np.int32, shape=(count,))
        offsets[0] = position = row_count = 0
        for row_count, (pid, payload, expected) in enumerate(data.rows(
                'train', 'p.pid, p.track_indices, s.recording_count'), start=1):
            items = data.recordings(payload, expected)
            indices[position:position + expected] = items
            position += expected
            offsets[row_count] = position
            pids[row_count - 1] = pid
            if row_count % 100_000 == 0:
                print(f'Indexed {row_count:,}/{count:,} training playlists', flush=True)
        if row_count != count or position != memberships:
            raise ValueError('Training row or membership counts disagree with the split')
        for array in (indices, offsets, pids):
            array.flush()
        print('Building the reverse track-to-playlist index', flush=True)
        matrix = csr_matrix((np.ones(memberships, dtype=np.uint8), indices, offsets),
                            shape=(count, data.track_count), copy=False)
        reverse = matrix.tocsc()
        np.save(path / files[2], reverse.indices)
        np.save(path / files[3], reverse.indptr)
        summary = {'identity': data.identity, 'training_playlists': count, 'training_memberships': memberships,
                   'training_recordings': int(np.count_nonzero(np.diff(reverse.indptr)))}
        del matrix, reverse, indices, offsets, pids
        write_json(path / 'summary.json', summary)
        os.replace(path, target)
    return summary


def fit_tags(data, run, title_limit, *, groups=TAG_GROUPS, rules=weak_tags, taxonomy_version=None, predict=None,
             cross_category_baseline=()):
    target = run / 'tags'
    files = ('title_tagger.joblib', 'track_tag_votes.npy', 'track_axis_totals.npy', 'tag_priors.npy')
    identity = {**data.identity, 'title_training_limit': title_limit, 'validation_title_limit': 5000}
    if taxonomy_version is not None:
        identity.update(taxonomy_version=taxonomy_version, tag_groups={key: list(value) for key, value in groups.items()},
                        cross_category_baseline=list(cross_category_baseline))
    if prior := completed(target, identity, files):
        return prior
    run.mkdir(parents=True, exist_ok=True)
    train_titles = [title for (title,) in data.sample('train', 'p.title', title_limit, salt=335)]
    val_titles = [title for (title,) in data.sample('validation', 'p.title', 5000, salt=336)]
    tags = tuple(tag for group in groups.values() for tag in group)
    group_columns = np.split(np.arange(len(tags)), np.cumsum([len(group) for group in groups.values()])[:-1])
    broader_axes = {i for i, name in enumerate(groups) if name in cross_category_baseline}
    tag_axis = np.repeat(np.arange(len(groups)), [len(group) for group in groups.values()])
    train_labels = label_matrix(map(rules, train_titles), tags)
    val_labels = label_matrix(map(rules, val_titles), tags)
    print(f'Training the TF-IDF title model on {len(train_titles):,} sampled training titles', flush=True)
    tagger = TitleTagger(tags).fit(train_titles, train_labels)
    tagger.select_thresholds(val_titles, val_labels)
    validation_agreement = classification_metrics(val_labels, tagger.predict(val_titles), tags)
    del train_titles, train_labels, val_titles, val_labels

    duplicates = {row[0] for row in data.connection.execute('''
        SELECT a.group_hash FROM splits.playlist_assignments AS a
        JOIN splits.playlist_groups AS g USING (group_hash)
        WHERE g.split='train' GROUP BY a.group_hash HAVING COUNT(*)>1
    ''')}
    deferred = {}
    prior_votes = np.zeros(len(tags), dtype=np.int64)
    prior_axes = np.zeros(len(groups), dtype=np.int64)
    predicted_titles = np.zeros(len(tags), dtype=np.int64)

    with TemporaryDirectory(dir=run, prefix='.tags-') as temp:
        path = Path(temp)
        votes = np.lib.format.open_memmap(path / files[1], mode='w+', dtype=np.int32,
                                          shape=(data.track_count, len(tags)))
        axes = np.lib.format.open_memmap(path / files[2], mode='w+', dtype=np.int32,
                                         shape=(data.track_count, len(groups)))
        votes[:] = 0
        axes[:] = 0

        def record_evidence(labels, payload, expected):
            if not expected:
                return
            items = data.recordings(payload, expected)
            for column in np.flatnonzero(labels):
                votes[items, column] += 1
                prior_votes[column] += 1
            for axis, columns in enumerate(group_columns):
                if axis in broader_axes or labels[columns].any():
                    axes[items, axis] += 1
                    prior_axes[axis] += 1

        rows = data.rows('train', 'p.title, p.track_indices, s.recording_count, s.group_hash')
        row_count = 0
        while batch := rows.fetchmany(TAG_BLOCK):
            titles = [row[0] for row in batch]
            predictions = tagger.predict(titles) if predict is None else predict(tagger, titles)
            predicted_titles += predictions.sum(axis=0)
            for (_, payload, expected, group), labels in zip(batch, predictions):
                if not labels.any():
                    continue
                if group in duplicates:
                    if group in deferred:
                        deferred[group][0][:] |= labels
                    else:
                        deferred[group] = (labels.copy(), payload, expected)
                else:
                    record_evidence(labels, payload, expected)
            row_count += len(batch)
            if row_count % 100_000 < TAG_BLOCK:
                print(f'Predicted tags for {row_count:,}/{data.sizes["train"]:,} training playlists', flush=True)
        for entry in deferred.values():
            record_evidence(*entry)
        if row_count != data.sizes['train']:
            raise ValueError('Title prediction row count disagrees with the training partition')
        denominators = prior_axes[tag_axis]
        priors = np.divide(prior_votes, denominators, out=np.zeros(len(tags)), where=denominators > 0)
        votes.flush()
        axes.flush()
        np.save(path / files[3], priors)
        joblib.dump(tagger, path / files[0], compress=3)
        summary = {'identity': identity, 'classifier_training_titles': min(data.sizes['train'], title_limit),
                   'title_label_source': 'weak title rules', 'train_playlists_scored_for_song_tags': row_count,
                   'validation_rule_agreement': validation_agreement,
                   'classifier_thresholds': dict(zip(tags, map(float, tagger.thresholds))),
                   'training_titles_by_tag': dict(zip(tags, map(int, predicted_titles))),
                   'song_tag_priors': dict(zip(tags, map(float, priors)))}
        del votes, axes
        write_json(path / 'summary.json', summary)
        os.replace(path, target)
    return summary


class DiskRanker:
    def __init__(self, index):
        self.items = np.load(index / 'playlist_indices.npy', mmap_mode='r')
        self.offsets = np.load(index / 'playlist_offsets.npy', mmap_mode='r')
        self.rows = np.load(index / 'track_playlists.npy', mmap_mode='r')
        self.track_offsets = np.load(index / 'track_offsets.npy', mmap_mode='r')
        self.counts = np.diff(self.track_offsets)
        ids = np.flatnonzero(self.counts).astype(np.int32)
        self.popular, _ = ordered(ids, self.counts[ids], len(ids))

    @lru_cache(maxsize=4096)
    def neighbours(self, seed):
        start, end = self.track_offsets[seed:seed + 2]
        rows = self.rows[start:end]
        left, right = self.offsets[rows], self.offsets[rows + 1]
        lengths = right - left
        local_starts = np.cumsum(lengths, dtype=np.int64) - lengths
        positions = np.repeat(left - local_starts, lengths) + np.arange(lengths.sum(), dtype=np.int64)
        pool, support = np.unique(self.items[positions], return_counts=True)
        keep = pool != seed
        pool, support = pool[keep], support[keep].astype(np.float64)
        scores = (support / np.sqrt(float(self.counts[seed]) * self.counts[pool])) * (support / (support + 10.))
        return ordered(pool, scores, 200)

    def popularity(self, exclude, k):
        pool = self.popular[:k + len(exclude)]
        return pool[~np.isin(pool, exclude)][:k]

    def candidates(self, seeds, k=20):
        neighbours = [self.neighbours(int(seed)) for seed in seeds]
        ids, inverse = np.unique(np.concatenate([row[0] for row in neighbours]), return_inverse=True)
        scores = np.bincount(inverse, weights=np.concatenate([row[1] for row in neighbours]), minlength=len(ids))
        keep = ~np.isin(ids, seeds)
        ids, scores = ids[keep], scores[keep]
        fallback = self.popularity(np.concatenate((ids, seeds)), k - len(ids)) if len(ids) < k else np.array([], np.int32)
        return ids, scores, fallback


class TagEvidence:
    def __init__(self, path):
        self.tagger = joblib.load(path / 'title_tagger.joblib')
        self.votes = np.load(path / 'track_tag_votes.npy', mmap_mode='r')
        self.axes = np.load(path / 'track_axis_totals.npy', mmap_mode='r')
        self.priors = np.load(path / 'tag_priors.npy')

    def bonus(self, items, labels):
        if not len(labels) or not len(items):
            return np.zeros(len(items))
        prior = self.priors[labels]
        rate = (self.votes[np.ix_(items, labels)] + 20 * prior) / (self.axes[np.ix_(items, TAG_AXIS[labels])] + 20)
        lift = np.divide(rate, prior, out=np.ones_like(rate), where=prior > 0)
        return np.maximum(np.log(np.maximum(lift, .01)), 0).mean(axis=1)


def rank_candidates(items, scores, fallback, bonus, weight, k=20):
    ranked, _ = ordered(items, scores * (1 + weight * bonus), k)
    return np.concatenate((ranked, fallback))[:k]


def make_seeds(pid, items):
    def score(item):
        return hashlib.blake2b(f'ES335-full-query-v1|{pid}|{item}'.encode(), digest_size=8).digest()
    perm = sorted(map(int, items), key=score)
    return np.asarray(perm[:3], dtype=np.int32), set(perm[3:])
