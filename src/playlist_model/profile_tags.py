"""Title context and recording-era labels for the expanded song profiles."""

import re

import numpy as np

from .tagger import CUES, NEGATION, label_matrix, normalize


TAXONOMY_VERSION = 'context-v2'
EXPANDED_CUES_VERSION = 'context-v2-expanded-cues-v1'
PROFILE_VERSIONS = {TAXONOMY_VERSION, EXPANDED_CUES_VERSION}
CONTEXT_GROUPS = {
    'mood': ('happy', 'chill', 'sad', 'upbeat', 'angry'),
    'theme': ('romantic', 'heartbreak'),
    'weather': ('rainy', 'summer', 'winter'),
    'party': ('party', 'dance', 'rave', 'dj_club'),
    'activity': ('study_focus', 'drive', 'relax', 'gym', 'sleep'),
}
CONTEXT_TAGS = tuple(tag for group in CONTEXT_GROUPS.values() for tag in group)
CONTEXT_AXIS = np.repeat(np.arange(len(CONTEXT_GROUPS)), [len(group) for group in CONTEXT_GROUPS.values()])
PARTY_CHILDREN = {'dance', 'rave', 'dj_club'}
CUE_WORDS = {
    'happy': r'happy(?!\s+birthday\b)|happiness|feel[ -]good|cheerful|good vibes',
    'chill': r'chill(?:out|ing)?|laid[ -]back|mellow',
    'sad': r'sad|sadness|crying|melanchol(?:y|ic)|feeling down',
    'upbeat': r'upbeat|high[ -]energy|hype|energetic',
    'angry': r'angry|anger|rage|furious',
    'romantic': r'romantic|romance|love songs?|love playlist|in love|date night|valentine(?:\'s)?',
    'heartbreak': r'heart[ -]?break(?:s|ing)?|heartbroken|break[ -]?ups?|broken heart',
    'rainy': CUES['rainy'] + r'|rainy night',
    'summer': CUES['summer'],
    'winter': CUES['winter'],
    'party': CUES['party'],
    'dance': CUES['dance'],
    'rave': CUES['rave'],
    'dj_club': r'dj(?:s| sets?| mixes)?|club (?:mix|music|hits|night|bangers)|clubbing|nightclub(?:s)?',
    'study_focus': CUES['study'],
    'drive': r'driv(?:e|es|ing)|road[ -]trips?|car (?:songs|jams|music|rides?)|in the car',
    'relax': r'relax(?:ing|ation)?|unwind|wind[ -]down|calm(?:ing)?',
    'gym': CUES['gym'],
    'sleep': CUES['sleep'],
}
PATTERNS = {tag: re.compile(rf'\b(?:{words})\b') for tag, words in CUE_WORDS.items()}
EXTRA_CUES = {
    'chill': r"chillin(?!'?\s+like a villain)|chillax(?:ing)?|laidback",
    'drive': r'roadtrip(?:s)?|(?:morning|evening|daily|work) commute|road music',
    'gym': r'work-out(?:s)?|cross[ -]?fit|leg day|treadmill',
    'upbeat': r'pump[ -]up',
    'party': r'turnt|turn[ -]up(?!\s+the\b)',
    'romantic': r'rom[aá]ntica|making love',
    'sleep': r'sleepy[ -]?time|nap[ -]time',
}
EXPANDED_PATTERNS = {tag: re.compile(rf'\b(?:{words}|{EXTRA_CUES[tag]})\b') if tag in EXTRA_CUES else PATTERNS[tag]
                     for tag, words in CUE_WORDS.items()}
DECADES = {1980: '80s', 1990: '90s', 2000: '00s', 2010: '10s'}
DECADE_CUE = re.compile(r"\b(1980|1990|2000|2010|80|90|00|10)'?s\b")
AMBIGUOUS_CUE = re.compile(r'\b(?:love|car|club|rain)\b')
ASSOCIATION_SMOOTHING = 20


def with_party_parent(tags):
    return tags | {'party'} if tags & PARTY_CHILDREN else tags


def title_context(title, *, expanded=False):
    text = normalize(title)
    found, excluded = set(), set()
    for tag, pattern in (EXPANDED_PATTERNS if expanded else PATTERNS).items():
        for match in pattern.finditer(text):
            labels = excluded if NEGATION.search(text[max(0, match.start() - 25):match.start()]) else found
            labels.add(tag)
    return found, excluded


def weak_context(title, *, expanded=False):
    found, excluded = title_context(title, expanded=expanded)
    return with_party_parent(found - excluded) - excluded


def predicted_context(tagger, titles, *, expanded=False):
    predictions = tagger.predict(titles)
    labels = []
    for title, prediction in zip(titles, predictions):
        found, excluded = title_context(title, expanded=expanded)
        learned = {CONTEXT_TAGS[index] for index in np.flatnonzero(prediction)}
        labels.append(with_party_parent((found | learned) - excluded) - excluded)
    return label_matrix(labels, CONTEXT_TAGS)


def requested_eras(title):
    text = normalize(title)
    labels = set()
    for match in DECADE_CUE.finditer(text):
        if not NEGATION.search(text[max(0, match.start() - 25):match.start()]):
            labels.add(match[1][-2:] + 's')
    return labels


def recording_era(year):
    if year is None:
        return None
    return DECADES.get(year // 10 * 10, 'other')


def contextual_scores(votes, category_totals, priors):
    """Return smoothed lift for tags with evidence and NaN for unknowns."""
    totals = category_totals[CONTEXT_AXIS]
    rates = (votes + ASSOCIATION_SMOOTHING * priors) / (totals + ASSOCIATION_SMOOTHING)
    return np.divide(rates, priors, out=np.full(priors.shape, np.nan), where=(priors > 0) & (totals > 0))
