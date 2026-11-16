import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from scripts.serve_model_api import ModelAPI, create_app
from scripts.deployment_files import report


ORIGIN = 'https://keshtib07-ghost.github.io'


class ModelAPITests(unittest.TestCase):
    def setUp(self):
        self.ranking = {'tags': ['chill'], 'tracks': [{'id': 'a' * 22, 'title': 'Model result'}], 'method': 'cf'}
        self.demo = SimpleNamespace(search=Mock(return_value={'tracks': [], 'more': False}),
                                    recommend=Mock(return_value=self.ranking))
        self.app = ModelAPI(self.demo, {'trained_model': True, 'model_id': 'frozen-run'}, [ORIGIN])

    def call(self, path, method='GET', body=None, origin=ORIGIN, **overrides):
        raw = json.dumps(body).encode() if body is not None else b''
        environ = {'PATH_INFO': path, 'REQUEST_METHOD': method, 'HTTP_ORIGIN': origin,
                   'CONTENT_TYPE': 'application/json', 'CONTENT_LENGTH': str(len(raw)),
                   'QUERY_STRING': '', 'wsgi.input': io.BytesIO(raw), **overrides}
        received = {}

        def start_response(status, headers):
            received.update(status=int(status.split()[0]), headers=dict(headers))

        response = b''.join(self.app(environ, start_response))
        received['body'] = json.loads(response) if response else None
        return received

    def test_cross_origin_preflight_allows_the_website(self):
        response = self.call('/api/recommend', 'OPTIONS',
                             HTTP_ACCESS_CONTROL_REQUEST_METHOD='POST',
                             HTTP_ACCESS_CONTROL_REQUEST_HEADERS='content-type')
        self.assertEqual(response['status'], 204)
        self.assertEqual(response['headers']['Access-Control-Allow-Origin'], ORIGIN)
        self.assertEqual(response['headers']['Access-Control-Allow-Methods'], 'POST')
        self.demo.recommend.assert_not_called()

    def test_unknown_origin_is_rejected(self):
        response = self.call('/api/status', origin='https://unconfigured.example')
        self.assertEqual(response['status'], 403)
        self.assertNotIn('Access-Control-Allow-Origin', response['headers'])

    def test_health_reports_loaded_model_without_an_origin(self):
        response = self.call('/healthz', origin='')
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['body']['model_id'], 'frozen-run')

    def test_live_request_uses_existing_model_and_preserves_inputs(self):
        request = {'seeds': ['b' * 22], 'title': 'Rainy evening', 'method': 'cf',
                   'context': '', 'filters': {}}
        response = self.call('/api/recommend', 'POST', request)
        self.assertEqual(response['status'], 200)
        self.assertEqual(response['body'], self.ranking)
        self.demo.recommend.assert_called_once_with(request)

    def test_search_preserves_unicode_and_pagination(self):
        self.call('/api/search', QUERY_STRING='q=Bj%C3%B6rk&offset=12')
        self.demo.search.assert_called_once_with('Björk', 12)

    def test_bad_requests_do_not_call_the_model(self):
        for overrides, expected in (
            ({'CONTENT_LENGTH': '5000'}, 413),
            ({'CONTENT_TYPE': 'text/plain'}, 415),
            ({'CONTENT_LENGTH': '3', 'wsgi.input': io.BytesIO(b'bad')}, 400),
        ):
            with self.subTest(overrides=overrides):
                self.assertEqual(self.call('/api/recommend', 'POST', **overrides)['status'], expected)
        self.demo.recommend.assert_not_called()

    def test_model_failure_returns_an_error_instead_of_sample_tracks(self):
        self.demo.recommend.side_effect = RuntimeError('private model path')
        with self.assertLogs('scripts.serve_model_api', level='ERROR'):
            response = self.call('/api/recommend', 'POST', {'seeds': ['b' * 22]})
        self.assertEqual(response['status'], 500)
        self.assertNotIn('tracks', response['body'])
        self.assertNotIn('private model path', json.dumps(response['body']))

    def test_startup_requires_trained_artifacts(self):
        with tempfile.TemporaryDirectory() as temp, patch.dict('os.environ', {'BEATX_DATA_DIR': temp}):
            with self.assertRaisesRegex(RuntimeError, 'Mount the trained model data'):
                create_app()

    def test_artifact_report_does_not_treat_missing_files_as_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            result = report(Path(temp))
            self.assertIn('model/frozen_settings.json', result['missing'])
            self.assertEqual(result['required_bytes'], 0)


if __name__ == '__main__':
    unittest.main()
