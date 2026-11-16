import sqlite3
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError

import numpy as np

from playlist_model.profile_sources import (MetadataClient, MetadataUnavailable, acoustic_fields, choose_recording,
                                            listenbrainz_title_match, lookup_by_name, lookup_track)
from playlist_model.profile_tags import (CONTEXT_GROUPS, CONTEXT_TAGS, contextual_scores, predicted_context,
                                         recording_era, requested_eras, weak_context)
from scripts.track_profiles import enrich


ID = 'f36d9818-019b-4379-ad13-5080feb9ad8a'
OTHER_ID = '604a1fc9-0ae4-4897-9459-84e44070e76c'


def recording(identifier=ID, **overrides):
    return {'id': identifier, 'title': 'Example Song', 'artist-credit': [{'name': 'Example Artist'}],
            'length': 180_000, 'first-release-date': '1999', **overrides}


class TrackProfileTests(unittest.TestCase):
    def test_taxonomy_supports_multiple_contexts_and_avoids_negated_cues(self):
        self.assertEqual(weak_context('90s Rainy Road Trip'), {'rainy', 'drive'})
        self.assertEqual(weak_context('Romantic & Chill'), {'romantic', 'chill'})
        self.assertEqual(weak_context('DJ Set & Rave'), {'dj_club', 'rave', 'party'})
        self.assertEqual(weak_context('No sad songs, just relax'), {'relax'})
        self.assertEqual(weak_context('Happy birthday'), set())
        self.assertEqual(weak_context('Favourites'), set())
        self.assertEqual(requested_eras("80s / 1990s / '00s and 10s"), {'80s', '90s', '00s', '10s'})
        self.assertEqual(recording_era(1999), '90s')
        self.assertEqual(recording_era(2025), 'other')
        self.assertIsNone(recording_era(None))

    def test_title_model_retains_explicit_cues_and_honours_negation(self):
        class Tagger:
            def predict(self, titles):
                return np.array([[tag == 'sad' for tag in CONTEXT_TAGS] for _ in titles])

        labels = predicted_context(Tagger(), ['No sad, just a DJ set'])[0]
        self.assertEqual({tag for tag, enabled in zip(CONTEXT_TAGS, labels) if enabled}, {'dj_club', 'party'})

    def test_tag_score_is_continuous_and_unknown_columns_are_missing(self):
        tag = CONTEXT_TAGS.index('rainy')
        votes, priors = np.zeros(len(CONTEXT_TAGS)), np.zeros(len(CONTEXT_TAGS))
        totals = np.zeros(len(CONTEXT_GROUPS))
        votes[tag], priors[tag], totals[2] = 5, .05, 20
        scores = contextual_scores(votes, totals, priors)
        self.assertAlmostEqual(scores[tag], 3.)
        self.assertTrue(np.isnan(scores[CONTEXT_TAGS.index('gym')]))

    def test_recording_matching_preserves_ambiguity_and_versions(self):
        fields = ('Example Song', 'Example Artist', 'Album', 181_000)
        match, item, _ = choose_recording(*fields, [recording()])
        self.assertEqual((match, item['id']), ('metadata_match', ID))
        status, match, candidates = choose_recording(*fields, [recording(), recording(OTHER_ID)])
        self.assertEqual((status, match, candidates), ('multiple_recording_matches', None, [ID, OTHER_ID]))
        self.assertEqual(choose_recording(*fields, [recording(disambiguation='live')])[0],
                         'duration_or_version_unverified')
        self.assertEqual(choose_recording(*fields, [recording(length=175_000)])[0],
                         'duration_or_version_unverified')

    def test_acoustic_measurements_and_cache(self):
        payload = {'rhythm': {'bpm': 128.}, 'lowlevel': {'spectral_energy': {'mean': 2.0},
                   'spectral_energyband_low': {'mean': .5}, 'spectral_energyband_high': {'mean': .25}}}

        class Client:
            audio_requests = 0

            def get(self, url, *, missing_ok=False):
                if missing_ok:
                    self.audio_requests += 1
                    return payload
                return {'count': 1, 'recordings': [recording()]}

        client = Client()
        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE acoustic_cache (mbid TEXT PRIMARY KEY, payload TEXT)')
            args = client, connection, 'Example Song', 'Example Artist', 'Album', 180_000
            first = lookup_track(*args)
            self.assertEqual((first['era'], first['bpm'], first['bass_share'], first['treble_share']),
                             ('90s', 128., .25, .125))
            self.assertEqual(lookup_track(*args), first)
            self.assertEqual(client.audio_requests, 1)
        self.assertIsNone(acoustic_fields({'rhythm': {'bpm': 0}})['bpm'])

    def test_client_retries_transient_http_error(self):
        url = 'https://musicbrainz.org/ws/2/recording/'
        busy = HTTPError(url, 503, 'unavailable', {'Retry-After': '3'}, None)
        with patch('playlist_model.profile_sources.urlopen', side_effect=[busy, BytesIO(b'{"count":0}')]) as opener, \
                patch('playlist_model.profile_sources.time.sleep') as sleep:
            self.assertEqual(MetadataClient('test').get(url), {'count': 0})
        self.assertEqual(opener.call_count, 2)
        self.assertGreater(sleep.call_args_list[1].args[0], 2.9)

    def test_listenbrainz_records_date_and_checks_album_and_duration(self):
        class Client:
            def __init__(self, album, length):
                self.album, self.length, self.calls = album, length, []

            def get(self, url, *, missing_ok=False):
                self.calls.append(url)
                if 'acrr-lookup' in url:
                    return [{'recording_mbid': ID, 'recording_name': 'Example Song',
                             'artist_credit_name': 'Example Artist', 'release_name': self.album}]
                if 'api.listenbrainz.org' in url:
                    return {ID: {'recording': {'name': 'Example Song', 'length': self.length,
                                                'first_release_date': '1999-06-01'}}}
                return {'rhythm': {'bpm': 128.}}

        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE acoustic_cache (mbid TEXT PRIMARY KEY, payload TEXT)')
            for album, length, expected, calls in (('Album', 180_000, 'metadata_match', 3),
                                                    ('Live album', 180_000, 'title_artist_or_album_not_exact', 1),
                                                    ('Album', 184_000, 'duration_or_version_unverified', 2)):
                client = Client(album, length)
                profile = lookup_track(client, connection, 'Example Song', 'Example Artist', 'Album', 180_000, 'listenbrainz')
                self.assertEqual(profile['match_status'], expected)
                self.assertEqual(len(client.calls), calls)
                self.assertEqual(profile['recording_source'], 'listenbrainz')
                if expected == 'metadata_match':
                    self.assertEqual((profile['release_date'], profile['era'], profile['bpm']), ('1999-06-01', '90s', 128.))

    def test_title_search_allows_album_difference_and_rejects_ambiguous_recordings(self):
        class Client:
            def __init__(self, lengths):
                self.lengths = lengths

            def get(self, url):
                if 'recording-search' in url:
                    return [{'recording_mbid': identifier, 'recording_name': 'Example Song',
                             'artist_credit_name': 'Example Artist', 'release_name': 'Original Album'}
                            for identifier in self.lengths]
                return {identifier: {'recording': {'name': 'Example Song', 'length': duration,
                                                   'first_release_date': '1999-06-01'}}
                        for identifier, duration in self.lengths.items()}

        args = ('Example Song', 'Example Artist', 'Deluxe Edition', 180_000)
        status, selected, _ = listenbrainz_title_match(Client({ID: 180_100, OTHER_ID: 210_000}), *args)
        self.assertEqual((status, selected['id']), ('metadata_match', ID))
        status, selected, _ = listenbrainz_title_match(Client({ID: 180_100, OTHER_ID: 181_000}), *args)
        self.assertEqual((status, selected), ('multiple_recording_matches', None))
        status, selected, _ = listenbrainz_title_match(Client({ID: 180_100, OTHER_ID: None}), *args)
        self.assertEqual((status, selected), ('duration_or_version_unverified', None))
        status, selected, _ = listenbrainz_title_match(Client({ID: 180_100}), 'Example Song', 'Example Artist',
                                                      'Live Album', 180_000)
        self.assertEqual((status, selected), ('duration_or_version_unverified', None))

    def test_name_search_checks_joint_credit_and_marks_missing_duration(self):
        class Client:
            def get(self, url, *, missing_ok=False):
                if missing_ok:
                    return {'rhythm': {'bpm': 122}}
                if 'recording-search' in url:
                    return [{'recording_mbid': ID, 'recording_name': 'Chanson d’été',
                             'artist_credit_name': 'Élodie & Another Singer', 'release_name': 'Original Album'}]
                return {ID: {'recording': {'name': 'Chanson d’été', 'length': 180_000},
                             'release': {'year': 2002}}}

        with sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE acoustic_cache (mbid TEXT PRIMARY KEY, payload TEXT)')
            args = Client(), connection, "Chanson d'ete", 'Elodie', ''
            preview = lookup_by_name(*args, None)
            profile = lookup_track(*args, 180_100, 'listenbrainz-credits')
            self.assertEqual(preview['match_status'], 'candidate_without_duration')
            self.assertEqual(profile['match_status'], 'metadata_match')
            self.assertEqual(profile['known_release_year'], 2002)
            self.assertIsNone(profile['release_date'])
            self.assertEqual(profile['bpm'], 122)
            for length in (175_000, 185_000):
                self.assertEqual(lookup_track(*args, length, 'listenbrainz-credits')['mbid'], ID)
            for length in (174_999, 185_001):
                self.assertIsNone(lookup_track(*args, length, 'listenbrainz-credits')['mbid'])
            self.assertIsNone(lookup_track(*args, 180_100, 'listenbrainz-search')['mbid'])
            collaborator = lookup_by_name(Client(), connection, 'Chanson d’été', 'Another Singer', '', 180_000)
            self.assertIsNone(collaborator['mbid'])

    def test_provider_switch_retries_previous_unmatched_row(self):
        spotify_id = 'a' * 22
        with TemporaryDirectory() as temp, sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE catalogue (track_index, spotify_id, track_name, artist_name, album_name, duration_ms)')
            connection.execute('INSERT INTO catalogue VALUES (?,?,?,?,?,?)',
                               (0, spotify_id, 'Example Song', 'Example Artist', 'Album', 180_000))
            data, output = SimpleNamespace(connection=connection, identity={'split': 'fixture'}), Path(temp)
            def lookup(client, db, title, artist, album, length, source):
                return {'mbid': None, 'candidate_mbids': [], 'acoustic_status': 'not_checked',
                        'match_status': 'no_recording_found', 'release_date': None, 'release_year': None, 'era': None,
                        'bpm': None, 'bass_share': None, 'treble_share': None, 'acoustic_version': None,
                        'recording_source': source}

            with patch('scripts.track_profiles.choose_pilot', return_value=[(0, 'top_decile', 20)]), \
                    patch('scripts.track_profiles.lookup_track', side_effect=lookup) as lookup_mock:
                enrich(data, output, None, 1, 'test')
                report = enrich(data, output, None, 1, 'test', source='listenbrainz')
                enrich(data, output, None, 1, 'test', source='listenbrainz')
            self.assertEqual(report['recording_source_counts'], {'listenbrainz': 1})
            self.assertEqual(lookup_mock.call_count, 2)

    def test_pilot_resumes_after_recording_and_audio_interruptions(self):
        class Client:
            def __init__(self, unavailable):
                self.unavailable = unavailable
                self.calls = []

            def get(self, url, *, missing_ok=False):
                self.calls.append(url)
                if 'acousticbrainz.org' in url:
                    if self.unavailable:
                        raise MetadataUnavailable('Audio temporarily unavailable')
                    return {'rhythm': {'bpm': 128.}}
                if 'Second+Song' in url:
                    if self.unavailable:
                        raise MetadataUnavailable('Recording search temporarily unavailable')
                    return {'count': 0}
                return {'count': 1, 'recordings': [recording()]}

        first, second = Client(True), Client(False)
        with TemporaryDirectory() as temp, sqlite3.connect(':memory:') as connection:
            connection.execute('CREATE TABLE catalogue (track_index, spotify_id, track_name, artist_name, album_name, duration_ms)')
            connection.executemany('INSERT INTO catalogue VALUES (?,?,?,?,?,?)', (
                (0, 'a' * 22, 'Example Song', 'Example Artist', 'Album', 180_000),
                (1, 'b' * 22, 'Second Song', 'Example Artist', 'Album', 180_000)))
            data, output = SimpleNamespace(connection=connection, identity={'split': 'fixture'}), Path(temp)
            with patch('scripts.track_profiles.choose_pilot', return_value=[(0, 'top_decile', 20), (1, 'remaining_catalogue', 2)]), \
                    patch('scripts.track_profiles.MetadataClient', side_effect=[first, second]):
                partial = enrich(data, output, None, 2, 'test')
                result = enrich(data, output, None, 2, 'test')
        self.assertEqual(partial['run_progress']['recording_lookups_remaining'], 1)
        self.assertEqual(partial['run_progress']['audio_lookups_pending'], 1)
        self.assertEqual(partial['coverage_by_field']['release_date'], 1)
        self.assertEqual(result['run_progress']['recording_lookups_remaining'], 0)
        self.assertEqual(result['coverage_by_field']['bpm'], 1)
        self.assertEqual(len(second.calls), 2)
        self.assertIn('acousticbrainz.org', second.calls[0])


if __name__ == '__main__':
    unittest.main()
