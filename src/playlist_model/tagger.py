import csv
import re
import unicodedata
from collections import defaultdict

import numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import FeatureUnion


TAG_GROUPS = {
    'mood': ('sad', 'chill', 'upbeat'),
    'activity': ('gym', 'study', 'sleep', 'dance', 'party', 'rave'),
    'weather': ('rainy', 'summer', 'winter'),
}
TAGS = tuple(tag for tags in TAG_GROUPS.values() for tag in tags)
TAG_COLUMN = {tag: index for index, tag in enumerate(TAGS)}
CUES = {
    'sad': r'sad|sadness|heartbreak(?:ed)?|heartbroken|crying|breakup',
    'chill': r'chill(?:out|ing)?|relax(?:ing|ation)?|laid back|calm(?:ing)?',
    'upbeat': r'upbeat|feel good|good vibes|hype',
    'gym': r'gym|work\s*out[s]?|weightlifting|lifting weights|cardio|running|exercise',
    'study': r'stud(?:y|ying)|focus(?:ing)?|homework|revision|concentration',
    'sleep': r'sleep(?:ing)?|bedtime|lullab(?:y|ies)|fall asleep',
    'dance': r'danc(?:e|ing)|dancefloor|dance floor',
    'party': r'part(?:y|ies)|pre[- ]?game|celebration',
    'rave': r'raves?|raving',
    'rainy': r'rainy|rainy days?|rain sounds|rainy weather|days? of rain',
    'summer': r'summer(?:time)?|summer nights?|summer vacation',
    'winter': r'winter(?:time)?|cold weather|snow days?|winter nights?',
}
PATTERNS = {tag: re.compile(rf'\b(?:{words})\b') for tag, words in CUES.items()}
NEGATION = re.compile(r'\b(?:no|not|without|never)\s+(?:\w+\s+)?$')
ERA = re.compile(r"\b(?:(19[789]0|20[012]0)|(70|80|90|00|10|20))'?s\b")


def normalize(title):
    return ' '.join(unicodedata.normalize('NFKC', title).casefold().replace('’', "'").split())


def weak_tags(title):
    text = normalize(title)
    return {tag for tag, pattern in PATTERNS.items()
            if any(not NEGATION.search(text[max(0, match.start() - 25):match.start()])
                   for match in pattern.finditer(text))}


def era_hint(title):
    match = ERA.search(normalize(title))
    if not match:
        return None
    if match[1]:
        return int(match[1])
    decade = int(match[2])
    return (1900 if decade >= 70 else 2000) + decade


def read_annotations(path):
    annotations = {}
    if path:
        with open(path, encoding='utf-8-sig', newline='') as handle:
            for row in csv.DictReader(handle):
                pid = int(row['pid'])
                tag_text = row['tags'].strip().casefold()
                if tag_text == 'skip':
                    continue
                tags = {tag.strip() for tag in tag_text.split(',') if tag.strip()} - {'unknown'}
                if pid in annotations or tags - set(TAGS):
                    raise ValueError(f'Bad or repeated annotation for playlist {pid}')
                annotations[pid] = tags
    return annotations


def label_matrix(label_sets):
    return np.asarray([[tag in labels for tag in TAGS] for labels in label_sets], dtype=bool)


def classification_metrics(truth, prediction):
    truth, prediction = np.asarray(truth, bool), np.asarray(prediction, bool)
    if not len(truth):
        return {'titles': 0, 'macro_f1_supported': None, 'per_tag': {}}
    by_tag, scores = {}, []
    for i, tag in enumerate(TAGS):
        tp = int(np.count_nonzero(truth[:, i] & prediction[:, i]))
        positives = int(truth[:, i].sum())
        predicted = int(prediction[:, i].sum())
        precision = tp / predicted if predicted else 0.0
        recall = tp / positives if positives else 0.0
        f1 = 2 * tp / (positives + predicted) if positives + predicted else 0.0
        by_tag[tag] = dict(precision=precision, recall=recall, f1=f1, support=positives, predicted=predicted)
        if positives:
            scores.append(f1)
    return {'titles': len(truth), 'macro_f1_supported': float(np.mean(scores)) if scores else None,
            'per_tag': by_tag}


class TitleTagger:
    def __init__(self):
        self.features = FeatureUnion([
            ('words', TfidfVectorizer(ngram_range=(1, 2), min_df=2, max_features=25_000, sublinear_tf=True)),
            ('characters', TfidfVectorizer(analyzer='char_wb', ngram_range=(3, 5), min_df=2,
                                          max_features=35_000, sublinear_tf=True)),
        ])
        self.models = []
        self.thresholds = np.full(len(TAGS), .5)

    def fit(self, titles, labels):
        features = self.features.fit_transform([normalize(title) for title in titles])
        for index, tag in enumerate(TAGS):
            target = labels[:, index]
            model = None
            if 2 <= target.sum() <= len(target) - 2:
                model = LogisticRegression(C=3, class_weight='balanced', max_iter=400)
                model.fit(features, target)
            self.models.append(model)
        return self

    def scores(self, titles):
        titles = list(titles)
        features = self.features.transform([normalize(title) for title in titles])
        scores = np.zeros((len(titles), len(TAGS)))
        for index, model in enumerate(self.models):
            if model is not None:
                scores[:, index] = model.predict_proba(features)[:, 1]
        return scores

    def select_thresholds(self, titles, labels, reviewed=None):
        scores = self.scores(titles)
        sources = {}
        for index, tag in enumerate(TAGS):
            mask = reviewed if reviewed is not None and int(labels[reviewed, index].sum()) >= 5 else slice(None)
            sources[tag] = 'reviewed' if not isinstance(mask, slice) else 'all available validation labels'
            truth, column = labels[mask, index], scores[mask, index]
            options = []
            for cutoff in (.50, .60, .70, .80, .90, .95):
                predicted = column >= cutoff
                tp, count = int((predicted & truth).sum()), int(predicted.sum())
                if count >= 3 and tp / count >= .65:
                    options.append((2 * tp / (count + int(truth.sum())), cutoff))
            self.thresholds[index] = max(options)[1] if options else .90
        return sources

    def predict(self, titles):
        return self.scores(titles) >= self.thresholds


def label_training_titles(playlists, annotations):
    return label_matrix([annotations[p.pid] if p.pid in annotations else weak_tags(p.title) for p in playlists])


def grouped_recording_evidence(playlists, predictions, track_count, smoothing=20.):
    groups = defaultdict(list)
    for index, playlist in enumerate(playlists):
        groups[playlist.fingerprint].append(index)
    tally = np.zeros((track_count, len(TAGS)), dtype=np.int32)
    opportunities = np.zeros_like(tally)
    prior_counts = np.zeros(len(TAGS), dtype=np.int64)
    prior_totals = np.zeros(len(TAGS), dtype=np.int64)
    for members in groups.values():
        labels = predictions[members].any(axis=0)
        indices = np.asarray(playlists[members[0]].tracks)
        for tags in TAG_GROUPS.values():
            columns = [TAG_COLUMN[tag] for tag in tags]
            if labels[columns].any():
                opportunities[np.ix_(indices, columns)] += 1
                prior_totals[columns] += 1
        marked = np.flatnonzero(labels)
        tally[np.ix_(indices, marked)] += 1
        prior_counts += labels
    prior = np.divide(prior_counts, prior_totals, out=np.zeros(len(TAGS)), where=prior_totals > 0)
    rates = (tally + smoothing * prior) / (opportunities + smoothing)
    lifts = np.divide(rates, prior, out=np.ones_like(rates), where=prior > 0).astype(np.float32)
    return tally, opportunities, lifts, prior
