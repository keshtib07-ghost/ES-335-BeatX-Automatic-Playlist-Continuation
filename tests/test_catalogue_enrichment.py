import json
import sqlite3
import tarfile
import unittest
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from scripts.enrich_catalogue import OUTPUT_DB, run
from scripts.prepare_million import SCHEMA


def tar_data(path, files):
    with tarfile.open(path, 'w') as archive:
        for name, data in files.items():
            payload = b'\n'.join(json.dumps(row).encode() for row in data)
            entry = tarfile.TarInfo(name)
            entry.size = len(payload)
            archive.addfile(entry, BytesIO(payload))


def recording(mbid, title, length=180_000, track_id=None, version=''):
    relations = [{'url': {'resource': f'https://open.spotify.com/track/{track_id}'}}] if track_id else []
    return {'id': mbid, 'title': title, 'length': length, 'artist-credit': [{'name': 'Café'}],
            'disambiguation': version, 'relations': relations}


class CatalogueEnrichmentTests(unittest.TestCase):
    def test_full_join_checks_exact_id_before_metadata_and_caches_audio(self):
        with TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'mpd.sqlite3'
            want = [letter * 22 for letter in 'ABCDEF']
            titles = ['Use ID', 'At Boundary', 'Ambiguous', 'Wrong Version', 'Outside']
            titles.append('No Match')
            with sqlite3.connect(source) as db:
                db.executescript(SCHEMA)
                db.execute('INSERT INTO run_info VALUES (?, ?)', ('identity', '{"archive_signature":"test"}'))
                db.executemany('INSERT INTO catalogue VALUES (?, ?, ?, ?, ?, ?)',
                               ((i, identifier, title, 'Cafe', 'Album', 185_000)
                                for i, (identifier, title) in enumerate(zip(want, titles))))

            exact = '00000000-0000-0000-0000-000000000001'
            by_name = '00000000-0000-0000-0000-000000000002'
            alternative = '00000000-0000-0000-0000-000000000003'
            spotify_csv = root / 'spotify.csv'
            spotify_csv.write_text(f'id,release_date,tempo\n{want[0]},2001,114\n{want[1]},1998,121\n')
            recordings = root / 'recordings.tar'
            tar_data(recordings, {'mbdump/recording': [
                recording(exact, 'Other Name', track_id=want[0]),
                recording(alternative, 'Use ID'),
                recording(by_name, 'At Boundary'),
                recording(by_name, 'Ambiguous'),
                recording(alternative, 'Ambiguous'),
                recording(alternative, 'Wrong Version', version='live'),
                recording(alternative, 'Outside', length=179_999),
            ]})
            releases = root / 'releases.tar'
            tar_data(releases, {'mbdump/release': [
                {'title': 'An Early Release', 'date': '1997-12',
                 'media': [{'tracks': [{'recording': recording(by_name, 'At Boundary'), 'length': 180_000}]}]},
            ]})
            audio = {
                'rhythm': {'bpm': 120}, 'lowlevel': {'spectral_energy': {'mean': 2.0},
                                                    'spectral_energyband_low': {'mean': 0.5},
                                                    'spectral_energyband_high': {'mean': 0.25}},
            }
            archive = root / 'acoustic.tar'
            tar_data(archive, {f'lowlevel/00/0/{exact}-0.json': [audio]})
            args = SimpleNamespace(source=source, output=root / 'results', spotify_csv=spotify_csv,
                                   spotify_parquet=None, musicbrainz=recordings, musicbrainz_releases=releases,
                                   acoustic_archive=[archive], acoustic_online_limit=25, contact='test')
            with patch('scripts.enrich_catalogue.MetadataClient') as client:
                client.return_value.get.return_value = {by_name: {'0': audio}}
                first = run(args)
                second = run(args)
                self.assertEqual(client.return_value.get.call_count, 1)
            self.assertEqual(first['tracks'], len(want))
            self.assertEqual(first['musicbrainz_matches'],
                             {'spotify_link': 1, 'name_artist_duration': 1, 'ambiguous': 1, 'unmatched': 3})
            self.assertEqual(first['acoustic_web_ids_checked'], 1)
            self.assertEqual(second['acoustic_web_ids_checked'], 0)
            self.assertEqual(second['all_four_fields'], 2)
            with sqlite3.connect(args.output / OUTPUT_DB) as db:
                rows = db.execute('SELECT recording_mbid, bpm, bass_share, treble_share, musicbrainz_release_date '
                                  'FROM profiles ORDER BY spotify_id').fetchall()
            self.assertEqual(rows[0], (exact, 114, 0.25, 0.125, None))
            self.assertEqual(rows[1], (by_name, 121, 0.25, 0.125, '1997-12'))
            self.assertEqual(rows[2], (None, None, None, None, None))
