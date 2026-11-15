"""Validation selection and final held-out evaluation for full MPD."""

import hashlib

import numpy as np

from .__main__ import paired_interval, scores_for, summary
from .million import TAGS, DiskRanker, TagEvidence, completed, make_seeds, rank_candidates, read_json, write_json


WEIGHTS = (0., .25, .5, 1., 2.)
VALIDATION_SEED = 337
TEST_SEED = 338
FIELDS = 'p.pid, p.title, p.track_indices, s.recording_count, s.group_hash'
INDEX_FILES = ('playlist_indices.npy', 'playlist_offsets.npy', 'track_playlists.npy', 'track_offsets.npy', 'train_pids.npy')
TAG_FILES = ('title_tagger.joblib', 'track_tag_votes.npy', 'track_axis_totals.npy', 'tag_priors.npy')


def load_training(data, run):
    index = completed(run / 'index', data.identity, INDEX_FILES)
    if not index or not (run / 'tags' / 'summary.json').is_file():
        raise ValueError('Finish index and tags before evaluating')
    tag_identity = read_json(run / 'tags' / 'summary.json')['identity']
    if any(tag_identity.get(key) != value for key, value in data.identity.items()):
        raise ValueError('Tagging output belongs to a different run')
    completed(run / 'tags', tag_identity, TAG_FILES)
    training_signature = {name: hashlib.sha256((run / name / 'summary.json').read_bytes()).hexdigest()
                          for name in ('index', 'tags')}
    return DiskRanker(run / 'index'), TagEvidence(run / 'tags'), training_signature


def measure(data, ranker, tags, part, limit, random_seed, weights):
    sample = data.sample(part, FIELDS, limit, random_seed, eligible=True)
    if not sample:
        raise ValueError(f'No eligible {part} playlists for three-seed evaluation')
    predicted = tags.tagger.predict([row[1] for row in sample])
    tagged = predicted.any(axis=1)
    measurements = {name: [] for name in ('popularity', 'collaborative_filtering')}
    for weight in weights:
        measurements[f'tag_weight_{weight:g}'] = []
    no_training_seeds = missing_reference = total_reference = 0
    for index, ((pid, _, payload, count, _), labels) in enumerate(zip(sample, predicted), start=1):
        seeds, targets = make_seeds(pid, data.recordings(payload, count))
        no_training_seeds += int(not ranker.counts[seeds].any())
        missing_reference += int(np.count_nonzero(ranker.counts[list(targets)] == 0))
        total_reference += len(targets)
        candidates, scores, fallback = ranker.candidates(seeds)
        bonus = tags.bonus(candidates, np.flatnonzero(labels))
        plain = rank_candidates(candidates, scores, fallback, bonus, 0.)
        measurements['popularity'].append(scores_for(ranker.popularity(seeds, 20), targets))
        measurements['collaborative_filtering'].append(scores_for(plain, targets))
        for weight in weights:
            result = rank_candidates(candidates, scores, fallback, bonus, weight)
            measurements[f'tag_weight_{weight:g}'].append(scores_for(result, targets))
        if index % 500 == 0 or index == len(sample):
            print(f'{part}: scored {index:,}/{len(sample):,} queries', flush=True)
    values = {name: np.asarray(rows) for name, rows in measurements.items()}
    query_info = {'eligible_queries_evaluated': len(sample), 'title_tagged_queries': int(tagged.sum()),
                  'all_seeds_unseen_in_training': no_training_seeds,
                  'unseen_reference_occurrences': missing_reference, 'all_reference_occurrences': total_reference,
                  'sample_seed': random_seed,
                  'sampled_pid_sha256': hashlib.sha256(','.join(str(row[0]) for row in sample).encode()).hexdigest()}
    return values, tagged, [row[-1].hex() for row in sample], query_info


def validate(data, run, limit):
    freeze_path = run / 'frozen_settings.json'
    if freeze_path.exists():
        raise ValueError('Validation choices are already frozen for this run')
    ranker, tags, fingerprints = load_training(data, run)
    scores, tagged, _, sample = measure(data, ranker, tags, 'validation', limit, VALIDATION_SEED, WEIGHTS)
    mask = tagged if tagged.any() else np.ones(len(tagged), dtype=bool)
    chosen = max(WEIGHTS, key=lambda weight: (scores[f'tag_weight_{weight:g}'][mask, 1].mean(), -weight))
    frozen = {'identity': data.identity, 'training_summary_sha256': fingerprints, 'query_limit_per_partition': limit,
              'visible_seeds': 3, 'recommendations': 20, 'test_seed': TEST_SEED,
              'selection_metric': 'NDCG@20 on title-tagged queries' if tagged.any() else 'NDCG@20 on all queries',
              'selected_tag_weight': chosen, 'validation_grid': list(WEIGHTS),
              'validation_query_sample': sample, 'tag_order': list(TAGS)}
    metrics = {'selected_tag_weight': chosen, 'sample': sample, 'all_queries': summary(scores, np.ones(len(tagged), bool)),
               'title_tagged_queries': summary(scores, tagged)}
    write_json(run / 'validation_metrics.json', metrics)
    write_json(freeze_path, frozen)
    return metrics


def test(data, run):
    freeze_path = run / 'frozen_settings.json'
    if not freeze_path.is_file():
        raise ValueError('Run validation and freeze the chosen settings before testing')
    frozen = read_json(freeze_path)
    output = run / 'test_metrics.json'
    if output.exists():
        raise ValueError('Test results already exist for this run')
    ranker, tags, fingerprints = load_training(data, run)
    if frozen['identity'] != data.identity or frozen['training_summary_sha256'] != fingerprints:
        raise ValueError('The frozen settings do not match this split and training output')
    chosen = frozen['selected_tag_weight']
    if chosen not in WEIGHTS or frozen['visible_seeds'] != 3 or frozen['recommendations'] != 20:
        raise ValueError('Unsupported validation settings in frozen run')
    scores, tagged, groups, sample = measure(data, ranker, tags, 'test', frozen['query_limit_per_partition'],
                                             frozen['test_seed'], (chosen,))
    scores['selected_tag_ranker'] = scores.pop(f'tag_weight_{chosen:g}')
    delta = scores['selected_tag_ranker'][:, 1] - scores['collaborative_filtering'][:, 1]
    all_rows = np.ones(len(tagged), bool)
    result = {'selected_tag_weight': chosen, 'sample': sample,
              'freeze_sha256': hashlib.sha256(freeze_path.read_bytes()).hexdigest(),
              'all_queries': summary(scores, all_rows), 'title_tagged_queries': summary(scores, tagged),
              'tag_ranker_minus_cf_ndcg_95_ci_all': paired_interval(delta, groups, all_rows),
              'tag_ranker_minus_cf_ndcg_95_ci_tagged': paired_interval(delta, groups, tagged)}
    write_json(output, result)
    return result
