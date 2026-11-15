"""Keep track selection fixed and optimize the playback order with observed transitions."""

import math

import numpy as np


def edge_key(left, right):
    return (int(left) << 32) | int(right)


class Transitions:
    def __init__(self, directory, counts):
        pairs, support = directory / 'pairs.u64', directory / 'support.u32'
        if pairs.stat().st_size % 8 or support.stat().st_size * 2 != pairs.stat().st_size:
            raise ValueError('Invalid sequence index size')
        self.pairs = np.memmap(pairs, mode='r', dtype='<u8') if pairs.stat().st_size else np.empty(0, dtype='<u8')
        self.support = np.memmap(support, mode='r', dtype='<u4') if len(self.pairs) else np.empty(0, dtype='<u4')
        self.counts = counts

    def strength(self, left, destinations):
        destinations = np.asarray(destinations, dtype=np.int64)
        if not len(self.pairs) or not self.counts[left]:
            return np.zeros(len(destinations))
        keys = np.uint64(int(left) << 32) | destinations.astype(np.uint64)
        locations = np.searchsorted(self.pairs, keys).clip(0, len(self.pairs) - 1)
        supports = np.where(self.pairs[locations] == keys, self.support[locations], 0).astype(float)
        normalizer = np.sqrt(np.maximum(1, self.counts[destinations]) * float(self.counts[left]))
        return supports / normalizer * (supports / (supports + 5.))

    def order(self, relevance, anchor=None):
        remaining = list(map(int, relevance))
        result = []
        learned = 0
        while remaining:
            if anchor is None:
                position = 0
            else:
                links = self.strength(anchor, remaining)
                position = int(links.argmax())
                learned += int(links[position] > 0)
            anchor = remaining.pop(position)
            result.append(anchor)
        return result, learned


def adjacency_recall(reference, ranking):
    if len(reference) < 2:
        return 0.
    true_pairs = set(zip(reference, reference[1:]))
    return sum((a, b) in true_pairs for a, b in zip(ranking, ranking[1:])) / (len(reference) - 1)
