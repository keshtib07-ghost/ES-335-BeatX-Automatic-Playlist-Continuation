"""Production WSGI API for the existing frozen MPD recommender."""

import hashlib
import json
import logging
import os
from http import HTTPStatus
from pathlib import Path
from threading import Lock
from urllib.parse import parse_qs, urlsplit

from scripts.serve_million_demo import Demo
from playlist_model.million import read_json


LOG = logging.getLogger(__name__)
DEFAULT_ORIGIN = 'https://keshtib07-ghost.github.io'
METHODS = ('popularity', 'cf', 'keyword_title', 'learned_title')


class ModelAPI:
    def __init__(self, demo, status, allowed_origins):
        self.demo = demo
        self.status = status
        self.allowed_origins = frozenset(allowed_origins)
        # Large NumPy candidate pools run one at a time per worker.
        self.inference_lock = Lock()

    def __call__(self, environ, start_response):
        path = environ.get('PATH_INFO', '')
        method = environ.get('REQUEST_METHOD', 'GET')
        origin = environ.get('HTTP_ORIGIN', '')
        headers = [('Cache-Control', 'no-store'), ('Vary', 'Origin')]

        def respond(value, code=200, extra=()):
            body = b'' if code == 204 else json.dumps(value, ensure_ascii=False).encode('utf-8')
            start_response(f'{code} {HTTPStatus(code).phrase}', [
                ('Content-Type', 'application/json; charset=utf-8'),
                ('Content-Length', str(len(body))), *headers, *extra
            ])
            return [body]

        if origin and origin not in self.allowed_origins:
            return respond({'error': 'This website origin is not enabled.'}, 403)
        if origin:
            headers.append(('Access-Control-Allow-Origin', origin))
        if path not in ('/healthz', '/api/status', '/api/search', '/api/recommend'):
            return respond({'error': 'Unknown route.'}, 404)
        allowed = 'POST' if path == '/api/recommend' else 'GET'
        if method == 'OPTIONS':
            requested = environ.get('HTTP_ACCESS_CONTROL_REQUEST_METHOD', '')
            requested_headers = {item.strip().lower() for item in
                                 environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS', '').split(',') if item.strip()}
            if requested != allowed or requested_headers - {'content-type'}:
                return respond({'error': 'Unsupported preflight request.'}, 400)
            return respond(None, 204, [('Access-Control-Allow-Methods', allowed),
                                       ('Access-Control-Allow-Headers', 'Content-Type'),
                                       ('Access-Control-Max-Age', '600')])
        if method != allowed:
            return respond({'error': 'Method not allowed.'}, 405, [('Allow', allowed)])
        try:
            if path in ('/healthz', '/api/status'):
                return respond(self.status)
            if path == '/api/search':
                query = parse_qs(environ.get('QUERY_STRING', ''), max_num_fields=10)
                return respond(self.demo.search(query.get('q', [''])[0], int(query.get('offset', ['0'])[0])))
            if environ.get('CONTENT_TYPE', '').split(';', 1)[0].strip().lower() != 'application/json':
                return respond({'error': 'Send a JSON request.'}, 415)
            length = int(environ.get('CONTENT_LENGTH') or 0)
            if not 0 < length <= 4096:
                return respond({'error': 'Send a request of 1–4096 bytes.'}, 413)
            raw = environ['wsgi.input'].read(length)
            if len(raw) != length:
                raise ValueError('Incomplete request body.')
            body = json.loads(raw)
            with self.inference_lock:
                result = self.demo.recommend(body)
            return respond(result)
        except (ValueError, UnicodeError) as error:
            return respond({'error': str(error)}, 400)
        except Exception:
            LOG.exception('Model request failed')
            return respond({'error': 'The model could not complete this request. Try again.'}, 500)


def create_app():
    data = Path(os.environ.get('BEATX_DATA_DIR', 'runs/million'))
    source, split, run = data / 'mpd.sqlite3', data / 'split.sqlite3', data / 'model'
    required = [source, split, run / 'frozen_settings.json']
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError('Mount the trained model data before starting the API. Missing: ' + ', '.join(missing))

    expanded = data / 'profiles-v2-expanded'
    profiles = expanded if (expanded / 'tags').is_dir() else data / 'profiles-v2'
    bulk = data / 'catalogue-enrichment' / 'catalogue_enrichment.sqlite3'
    client_id = os.environ.get('BEATX_SPOTIFY_CLIENT_ID')
    demo = Demo(source, split, run, False, data / 'sequence', profiles,
                client_id, bulk if bulk.is_file() else None)
    origins = [item.strip() for item in os.environ.get('BEATX_ALLOWED_ORIGINS', DEFAULT_ORIGIN).split(',') if item.strip()]
    for origin in origins:
        url = urlsplit(origin)
        if (url.scheme not in ('https', 'http') or not url.netloc or url.path or url.query or url.fragment
                or url.username or url.password):
            raise ValueError('BEATX_ALLOWED_ORIGINS must contain origins without paths.')
    index = read_json(run / 'index' / 'summary.json')
    methods = list(METHODS) + (['song_profiles'] if demo.profiles is not None else [])
    status = {
        'trained_model': True,
        'model_id': hashlib.sha256((run / 'frozen_settings.json').read_bytes()).hexdigest(),
        'training_playlists': index['training_playlists'],
        'training_recordings': index['training_recordings'],
        'methods': methods,
        'sequence_model': demo.sequence is not None,
        'song_profiles': demo.profiles is not None,
        'bulk_catalogue_profiles': bool(demo.profiles and demo.profiles.catalogue_profiles),
        'spotify_client_id': client_id,
    }
    return ModelAPI(demo, status, origins)
