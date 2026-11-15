"""Serve the static site and real trained-model demo on local loopback."""

import argparse
import json
import sqlite3
import unicodedata
from contextlib import contextmanager, closing
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import numpy as np

from playlist_model.data import track_id
from playlist_model.million import TAGS, open_dataset, rank_candidates, read_json, read_only
from playlist_model.million_eval import load_training
from playlist_model.sequence import Transitions
from playlist_model.tagger import TAG_COLUMN, weak_tags


PAGE_SIZE = 12
METHODS = ('popularity', 'cf', 'keyword_title', 'learned_title')


def spotify_reference(value):
    if raw := track_id(value.strip()):
        return raw
    url = urlsplit(value.strip())
    fields = url.path.strip('/').split('/')
    if url.scheme == 'https' and url.hostname == 'open.spotify.com' and len(fields) >= 2 and fields[-2] == 'track':
        return track_id(fields[-1])
    return None


class Demo:
    def __init__(self, source, split, run, allow_partial, sequence=None):
        self.source, self.split = source, split
        frozen = read_json(run / 'frozen_settings.json')
        with open_dataset(source, split, allow_partial) as data:
            self.ranker, self.tags, signatures = load_training(data, run)
            if frozen['identity'] != data.identity or signatures != frozen['training_summary_sha256']:
                raise ValueError('The trained model and frozen settings do not match')
            self.sequence = None
            if sequence and sequence.exists():
                if read_json(sequence / 'summary.json')['identity'] != data.identity:
                    raise ValueError('Sequence model belongs to a different split')
                self.sequence = Transitions(sequence, self.ranker.counts)
            self.has_aliases = data.aliases is not None
        self.weight = frozen['selected_tag_weight']

    @contextmanager
    def catalogue(self):
        with closing(sqlite3.connect(read_only(self.source), uri=True)) as connection:
            connection.execute('ATTACH DATABASE ? AS splits', (read_only(self.split),))
            connection.execute('PRAGMA query_only=ON')
            yield connection

    def search(self, query, offset=0):
        def fold(value):
            return unicodedata.normalize('NFKC', value or '').casefold()

        words = fold(query).split()
        if len(query) < 2 or not words:
            return {'tracks': [], 'more': False}
        if len(query) > 120 or len(words) > 10:
            raise ValueError('Use a shorter track or artist search.')
        if not 0 <= offset <= 2_500_000:
            raise ValueError('Invalid track-search offset.')
        with self.catalogue() as db:
            db.create_function('training_support', 1, lambda index: int(self.ranker.counts[index]))
            if identifier := spotify_reference(query):
                hits = db.execute('''
                    SELECT c.spotify_id, c.track_name, c.artist_name,
                           training_support(COALESCE(a.recording_index, c.track_index))
                    FROM catalogue AS c LEFT JOIN splits.recording_aliases AS a USING (track_index)
                    WHERE c.spotify_id=?
                ''', (identifier,)).fetchall() if offset == 0 else []
            else:
                func = 'lower' if query.isascii() else 'fold_text'
                if func == 'fold_text':
                    db.create_function(func, 1, fold)
                where = ' AND '.join([f"instr({func}(c.track_name || ' ' || c.artist_name), ?) > 0"] * len(words))
                canonical = 'COALESCE(a.recording_index, c.track_index)' if self.has_aliases else 'c.track_index'
                alias_join = 'LEFT JOIN splits.recording_aliases AS a USING (track_index)' if self.has_aliases else ''
                group = 'GROUP BY recording' if self.has_aliases else ''
                hits = db.execute(f'''
                    SELECT spotify_id, title, artist, training_support(recording) FROM (
                        SELECT c.spotify_id, c.track_name AS title, c.artist_name AS artist,
                               {canonical} AS recording, {func}(c.track_name)=? AS exact
                        FROM catalogue AS c {alias_join} WHERE {where}
                    ) {group}
                    ORDER BY exact DESC, training_support(recording) DESC, title, spotify_id LIMIT ? OFFSET ?
                ''', (fold(query).strip(), *words, PAGE_SIZE + 1, offset)).fetchall()
        return {'tracks': [{'id': identifier, 'title': title, 'artist': artist, 'training_support': support}
                           for identifier, title, artist, support in hits[:PAGE_SIZE]], 'more': len(hits) > PAGE_SIZE}

    def recommend(self, body):
        if not isinstance(body, dict):
            raise ValueError('Expected a request object.')
        title, seeds = body.get('title'), body.get('seeds')
        method, override = body.get('method', 'learned_title'), body.get('context', '')
        if not isinstance(title, str) or len(title) > 180 or not isinstance(seeds, list) or not 1 <= len(seeds) <= 20:
            raise ValueError('Enter a title of up to 180 characters and select 1–20 tracks.')
        if not isinstance(method, str) or method not in METHODS or not isinstance(override, str) or (override and override not in TAG_COLUMN):
            raise ValueError('Unknown recommendation method or context.')
        if not all(isinstance(item, str) for item in seeds):
            raise ValueError('Select valid Spotify track IDs.')
        identifiers = list(map(track_id, seeds))
        if None in identifiers or len(set(identifiers)) != len(seeds):
            raise ValueError('Select distinct Spotify track IDs.')
        markers = ','.join('?' for _ in identifiers)
        with self.catalogue() as db:
            rows = dict(db.execute(f'''
                SELECT c.spotify_id, COALESCE(a.recording_index, c.track_index)
                FROM catalogue AS c LEFT JOIN splits.recording_aliases AS a USING (track_index)
                WHERE c.spotify_id IN ({markers})
            ''', identifiers))
            if len(rows) != len(seeds):
                raise ValueError('A selected track is absent from your local catalogue.')
            ids = np.array([rows[identifier] for identifier in identifiers], dtype=np.int32)
            if len(set(ids)) != len(seeds):
                raise ValueError('Two selected tracks represent one recording. Pick another seed.')
            labels = []
            if method in ('keyword_title', 'learned_title'):
                if override:
                    labels = [TAG_COLUMN[override]]
                elif method == 'keyword_title':
                    labels = sorted(TAG_COLUMN[tag] for tag in weak_tags(title))
                else:
                    labels = np.flatnonzero(self.tags.tagger.predict([title])[0])
            if method == 'popularity':
                ranked = self.ranker.popularity(ids, 20)
            else:
                candidates, scores, fallback = self.ranker.candidates(ids)
                bonus = self.tags.bonus(candidates, labels)
                ranked = rank_candidates(candidates, scores, fallback, bonus, self.weight)
            playback, learned = self.sequence.order(ranked, anchor=int(ids[-1])) if self.sequence else (None, None)
            tracks = []
            for index in ranked:
                identifier, name, artist = db.execute('''
                    SELECT spotify_id, track_name, artist_name FROM catalogue WHERE track_index=?
                ''', (int(index),)).fetchone()
                tracks.append({'id': identifier, 'title': name, 'artist': artist, 'rank': len(tracks) + 1,
                               'playback_position': playback.index(int(index)) + 1 if playback is not None else None})
        return {'tags': [TAGS[i] for i in labels], 'tracks': tracks, 'method': method,
                'known_seeds': int(np.count_nonzero(self.ranker.counts[ids])), 'seed_count': len(ids),
                'transition_evidence': learned}


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
            self.respond({'trained_model': True, 'sequence_model': self.demo.sequence is not None})
        elif url.path == '/api/search':
            try:
                query = parse_qs(url.query)
                self.respond(self.demo.search(query.get('q', [''])[0], int(query.get('offset', ['0'])[0])))
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
    cli.add_argument('--sequence', type=Path, default=Path('runs/million/sequence'))
    cli.add_argument('--port', type=int, default=8000)
    cli.add_argument('--allow-partial-source', action='store_true', help='Allow a verified pilot-sized database')
    args = cli.parse_args()
    try:
        demo = Demo(args.source, args.split, args.run, args.allow_partial_source, args.sequence)
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
