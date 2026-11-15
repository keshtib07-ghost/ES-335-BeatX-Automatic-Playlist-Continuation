"""Serve the static site and real trained-model demo on local loopback."""

import argparse
import json
import sqlite3
from contextlib import contextmanager, closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

from playlist_model.data import track_id
from playlist_model.million import TAGS, open_dataset, rank_candidates, read_json, read_only
from playlist_model.million_eval import load_training


class Demo:
    def __init__(self, source, split, run, allow_partial):
        self.source, self.split = source, split
        frozen = read_json(run / 'frozen_settings.json')
        with open_dataset(source, split, allow_partial) as data:
            self.ranker, self.tags, signatures = load_training(data, run)
            if frozen['identity'] != data.identity or signatures != frozen['training_summary_sha256']:
                raise ValueError('The trained model and frozen settings do not match')
        self.weight = frozen['selected_tag_weight']

    @contextmanager
    def catalogue(self):
        with closing(sqlite3.connect(read_only(self.source), uri=True)) as connection:
            connection.execute('ATTACH DATABASE ? AS splits', (read_only(self.split),))
            connection.execute('PRAGMA query_only=ON')
            yield connection

    def search(self, query):
        words = query.casefold().split()
        if len(query) < 2 or not words:
            return []
        if len(query) > 120 or len(words) > 10:
            raise ValueError('Use a shorter track or artist search.')
        where = ' AND '.join(['instr(lower(c.track_name || \' \' || c.artist_name), ?) > 0'] * len(words))
        with self.catalogue() as db:
            hits = list(db.execute(f'''
                SELECT COALESCE(a.recording_index, c.track_index), c.spotify_id, c.track_name, c.artist_name
                FROM catalogue AS c LEFT JOIN splits.recording_aliases AS a USING (track_index)
                WHERE {where} LIMIT 180
            ''', words))
        hits.sort(key=lambda row: (-int(self.ranker.counts[row[0]]), row[2]))
        distinct = {}
        for canonical, identifier, title, artist in hits:
            distinct.setdefault(canonical, {'id': identifier, 'title': title, 'artist': artist})
        return list(distinct.values())[:24]

    def recommend(self, body):
        if not isinstance(body, dict):
            raise ValueError('Expected a request object.')
        title, seeds = body.get('title'), body.get('seeds')
        if not isinstance(title, str) or len(title) > 180 or not isinstance(seeds, list) or len(seeds) != 3:
            raise ValueError('Enter a title of up to 180 characters and select three tracks.')
        if not all(isinstance(item, str) for item in seeds):
            raise ValueError('Select three valid Spotify track IDs.')
        identifiers = list(map(track_id, seeds))
        if None in identifiers or len(set(identifiers)) != 3:
            raise ValueError('Select three distinct Spotify track IDs.')
        with self.catalogue() as db:
            rows = dict(db.execute('''
                SELECT c.spotify_id, COALESCE(a.recording_index, c.track_index)
                FROM catalogue AS c LEFT JOIN splits.recording_aliases AS a USING (track_index)
                WHERE c.spotify_id IN (?, ?, ?)
            ''', identifiers))
            if len(rows) != 3:
                raise ValueError('A selected track is absent from your local catalogue.')
            ids = np.array([rows[identifier] for identifier in identifiers], dtype=np.int32)
            if len(set(ids)) != 3:
                raise ValueError('Two selected tracks represent one recording. Pick another seed.')
            labels = np.flatnonzero(self.tags.tagger.predict([title])[0])
            candidates, scores, fallback = self.ranker.candidates(ids)
            bonus = self.tags.bonus(candidates, labels)
            ranked = rank_candidates(candidates, scores, fallback, bonus, self.weight)
            tracks = []
            for index in ranked:
                identifier, name, artist = db.execute('''
                    SELECT spotify_id, track_name, artist_name FROM catalogue WHERE track_index=?
                ''', (int(index),)).fetchone()
                tracks.append({'id': identifier, 'title': name, 'artist': artist})
        return {'tags': [TAGS[i] for i in labels], 'tracks': tracks,
                'cold': int(np.sum(self.ranker.counts[ids] == 0))}


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, demo, directory, **kwargs):
        self.demo = demo
        super().__init__(*args, directory=str(directory), **kwargs)

    def respond(self, value, status=200):
        body = json.dumps(value, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlsplit(self.path)
        if url.path == '/api/status':
            self.respond({'trained_model': True})
        elif url.path == '/api/search':
            try:
                query = parse_qs(url.query).get('q', [''])[0]
                self.respond({'tracks': self.demo.search(query)})
            except ValueError as error:
                self.respond({'error': str(error)}, 400)
        else:
            super().do_GET()

    def do_POST(self):
        if urlsplit(self.path).path != '/api/recommend':
            self.respond({'error': 'Unknown route.'}, 404)
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 4096 or self.headers.get_content_type() != 'application/json':
                raise ValueError('Send a small JSON request.')
            result = self.demo.recommend(json.loads(self.rfile.read(length)))
            self.respond(result)
        except (ValueError, UnicodeError) as error:
            self.respond({'error': str(error)}, 400)


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('--source', type=Path, default=Path('runs/million/mpd.sqlite3'))
    cli.add_argument('--split', type=Path, default=Path('runs/million/split.sqlite3'))
    cli.add_argument('--run', type=Path, default=Path('runs/million/model'))
    cli.add_argument('--port', type=int, default=8000)
    cli.add_argument('--allow-partial-source', action='store_true', help='Allow a verified pilot-sized database')
    args = cli.parse_args()
    try:
        demo = Demo(args.source, args.split, args.run, args.allow_partial_source)
        handler = partial(Handler, demo=demo, directory=Path(__file__).resolve().parent.parent / 'docs')
        with ThreadingHTTPServer(('127.0.0.1', args.port), handler) as server:
            print(f'Local trained demo: http://127.0.0.1:{server.server_address[1]}/', flush=True)
            server.serve_forever()
    except KeyboardInterrupt:
        pass
    except (OSError, ValueError, sqlite3.Error) as error:
        cli.exit(2, f'Error: {error}\n')


if __name__ == '__main__':
    main()
