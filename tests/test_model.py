import csv
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from playlist_model.data import Playlist, playlist_query, read_dataset
from playlist_model.ranker import PlaylistRanker
from playlist_model.tagger import TAG_COLUMN, TAGS, era_hint, grouped_recording_evidence, label_matrix, weak_tags


def spotify_id(index):
    return f'{index:022d}'


class DataTests(unittest.TestCase):
    def test_verified_aliases_merge_before_grouped_split(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            playlists = []
            for pid in range(1020, 1300):
                items = (1, 2, 3, 4, 1) if pid == 1020 else ((5, 2, 3, 4) if pid == 1021 else (pid, 2))
                tracks = [{'track_uri': f'spotify:track:{spotify_id(i)}', 'track_name': str(i)} for i in items]
                playlists.append({'pid': pid, 'name': 'gym', 'tracks': tracks})
            (directory / 'mpd.slice.1000-1999.json').write_text(json.dumps({'playlists': playlists}))
            metadata = directory / 'metadata.csv'
            with metadata.open('w', newline='') as handle:
                writer = csv.writer(handle)
                writer.writerow(['track_id', 'recording_id', 'release_year', 'bpm'])
                writer.writerows([[spotify_id(1), 'x', 1996, 124], [spotify_id(5), 'x', 2012, 125]])
            records, catalog, aliases, statistics, _ = read_dataset(directory, metadata)
            self.assertEqual((records[0].fingerprint, records[0].split), (records[1].fingerprint, records[1].split))
            self.assertEqual(aliases[spotify_id(1)], aliases[spotify_id(5)])
            self.assertEqual(catalog[aliases[spotify_id(1)]].year, 1996)
            self.assertEqual(statistics['repeat_track_ids_in_playlist'], 1)
            seeds, targets = playlist_query(records[0], catalog)
            self.assertEqual((len(seeds), len(targets)), (3, 1))
            self.assertFalse(set(seeds) & targets)


class EvidenceTests(unittest.TestCase):
    def test_title_taxonomy_and_abstention(self):
        self.assertEqual(weak_tags('Rainy Night Study'), {'rainy', 'study'})
        self.assertEqual(weak_tags('No chill'), set())
        self.assertEqual(weak_tags('My Favourites'), set())
        self.assertEqual(weak_tags('Slow Hands'), set())
        self.assertEqual(era_hint("90's rainy night"), 1990)
        self.assertEqual(era_hint('1990s rainy night'), 1990)
        self.assertIsNone(era_hint('2090s'))

    def test_same_trackset_only_votes_once_and_unknown_axis_is_neutral(self):
        playlists = [Playlist(1, 'Gym', (0, 1), 'a', 'train'), Playlist(2, 'Gym', (0, 1), 'a', 'train'),
                     Playlist(3, 'Rainy Study', (0, 2), 'b', 'train'), Playlist(4, 'Favorites', (0,), 'c', 'train')]
        prediction = label_matrix([weak_tags(playlist.title) for playlist in playlists])
        votes, eligible, _, _ = grouped_recording_evidence(playlists, prediction, 3)
        self.assertEqual(votes[0, TAG_COLUMN['gym']], 1)
        self.assertEqual(eligible[0, TAG_COLUMN['gym']], 2)
        self.assertEqual(eligible[0, TAG_COLUMN['rainy']], 1)
        self.assertEqual(eligible[0, TAG_COLUMN['sad']], 0)


class RankingTests(unittest.TestCase):
    def test_tag_rerank_uses_identical_candidates_and_does_not_return_a_seed(self):
        playlists = [Playlist(1, '', (0, 1, 2), 'a', 'train'), Playlist(2, '', (0, 1), 'b', 'train'),
                     Playlist(3, '', (0, 2), 'c', 'train'), Playlist(4, '', (2, 3), 'd', 'train')]
        ranker = PlaylistRanker(5, playlists)
        items, scores = ranker.candidates([0], k=3)
        plain = ranker.recommend_from(items, scores, k=3)
        lifts = np.ones((5, len(TAGS)))
        lifts[2, TAG_COLUMN['gym']] = 10.
        hybrid = ranker.recommend_from(items, scores, [TAG_COLUMN['gym']], lifts, 1., k=3)
        self.assertEqual(plain[0], 1)
        self.assertEqual(hybrid[0], 2)
        self.assertEqual(set(plain), set(hybrid))
        self.assertNotIn(0, plain)
        empty, _ = ranker.candidates([4], np.zeros(5, dtype=bool), k=3)
        self.assertEqual(len(empty), 0)


if __name__ == '__main__':
    unittest.main()
