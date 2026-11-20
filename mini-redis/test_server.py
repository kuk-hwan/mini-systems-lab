import http.client
import json
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import quote

from cache import MiniRedis
from server import CacheServer


class CacheApiTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.cache = MiniRedis(lambda: self.now)
        data = self.enterContext(tempfile.TemporaryDirectory())
        self.snapshot = Path(data) / 'cache.json'
        self.server = self.enterContext(CacheServer(('127.0.0.1', 0), self.cache, self.snapshot))
        worker = threading.Thread(target=self.server.serve_forever)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.server.shutdown)

    def request(self, method, path, body=None):
        content = None if body is None else json.dumps(body)
        status, _, payload = self.request_raw(method, path, content, 'application/json')
        return status, json.loads(payload)

    def request_raw(self, method, path, body=None, content_type='application/x-www-form-urlencoded'):
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            connection.request(method, path, body=body, headers={'Content-Type': content_type})
            response = connection.getresponse()
            return response.status, dict(response.getheaders()), response.read().decode('utf-8')
        finally:
            connection.close()

    def test_put_get_expiry_delete_and_metrics(self):
        path = '/api/kv/' + quote('상품:1', safe='')
        self.assertEqual(self.request('GET', path), (200, {'found': False, 'value': None}))
        self.assertEqual(self.request('PUT', path, {'value': ['상품 A'], 'ttl': 5})[0], 200)
        self.assertEqual(self.request('GET', path), (200, {'found': True, 'value': ['상품 A']}))
        self.now += 5
        self.assertEqual(self.request('GET', path), (200, {'found': False, 'value': None}))
        self.assertEqual(self.request('PUT', path, {'value': None})[0], 200)
        self.assertEqual(self.request('GET', path), (200, {'found': True, 'value': None}))
        self.assertEqual(self.request('DELETE', path), (200, {'deleted': True}))
        status, metrics = self.request('GET', '/api/metrics')
        self.assertEqual(status, 200)
        self.assertEqual(metrics['cache']['keys'], 0)
        self.assertEqual(metrics['cache']['expired'], 1)

    def test_reject_invalid_write_and_restore_saved_snapshot(self):
        path = '/api/kv/products'
        self.assertEqual(self.request('PUT', path, {'ttl': 60})[0], 400)
        self.assertEqual(self.request('PUT', path, {'value': []})[0], 200)
        self.assertEqual(self.request('POST', '/api/cache/snapshot'), (200, {'saved': True}))
        restored = MiniRedis()
        restored.restore(self.snapshot)
        self.assertEqual(restored.get('products'), {'found': True, 'value': []})

    def test_quiz_hint_expires_before_answer_deadline(self):
        status, round_data = self.request('POST', '/api/quiz/rounds', {'index': 0})
        self.assertEqual(status, 200)
        self.assertNotIn('answer', round_data)
        self.assertNotIn('hint', round_data)
        path = '/api/quiz/rounds/' + round_data['token']
        status, hint = self.request('GET', path + '/hint')
        self.assertEqual((status, hint['status']), (200, 'HIT'))
        self.assertEqual(self.request('GET', '/api/kv/' + round_data['key'])[1]['found'], False)
        self.now += round_data['hint_seconds']
        self.assertEqual(self.request('GET', path + '/hint'), (200, {'status': 'MISS', 'value': None}))
        status, result = self.request('POST', path + '/answer', {'choice': 0})
        self.assertEqual((status, result['correct'], result['timed_out']), (200, True, False))
        self.assertEqual(self.request('POST', path + '/answer', {'choice': 1}), (200, result))

    def test_quiz_rejects_invalid_input_and_grades_late_choice_as_timeout(self):
        self.assertEqual(self.request('POST', '/api/quiz/rounds', {'index': -1})[0], 400)
        _, round_data = self.request('POST', '/api/quiz/rounds', {'index': 0})
        path = '/api/quiz/rounds/' + round_data['token']
        self.assertEqual(self.request('POST', path + '/answer', {'choice': None})[0], 400)
        self.now += round_data['round_seconds']
        status, result = self.request('POST', path + '/answer', {'choice': 0})
        self.assertEqual((status, result['correct'], result['timed_out']), (200, False, True))

    def test_python_quiz_forms_complete_and_keep_the_score(self):
        status, _, page = self.request_raw('GET', '/quiz')
        self.assertEqual(status, 200)
        self.assertIn('퀴즈 시작', page)
        self.assertNotIn('<script', page)
        status, headers, _ = self.request_raw('POST', '/quiz/start')
        self.assertEqual(status, 303)
        path = headers['Location']
        for i, choice in enumerate((0, 1, 2, 0, 2), 1):
            _, _, page = self.request_raw('GET', path)
            self.assertIn(f'문제 {i} / 5', page)
            self.assertIn('http-equiv="refresh"', page)
            if i == 1:
                self.assertEqual(self.request_raw('POST', path + '/hint')[0], 303)
                self.assertIn('GET · HIT', self.request_raw('GET', path)[2])
                self.now += 10
                self.assertEqual(self.request_raw('POST', path + '/hint')[0], 303)
                self.assertIn('GET · MISS', self.request_raw('GET', path)[2])
            status, _, _ = self.request_raw('POST', path + '/answer', f'choice={choice}')
            self.assertEqual(status, 303)
            status, _, page = self.request_raw('GET', path)
            self.assertIn('정답이에요.', page)
            self.assertIn(f'{i} / 5 완료', page)
            self.assertNotIn('http-equiv="refresh"', page)
            status, headers, _ = self.request_raw('POST', path + '/next')
            self.assertEqual(status, 303)
            # Repeated form submissions return the same next page.
            self.assertEqual(self.request_raw('POST', path + '/next')[1]['Location'], headers['Location'])
            path = headers['Location']
        _, _, page = self.request_raw('GET', path)
        self.assertIn('오늘의 결과', page)
        self.assertIn('<p class="score">5 / 5</p>', page)

    def test_python_quiz_renders_timeout_on_refresh(self):
        _, headers, _ = self.request_raw('POST', '/quiz/start')
        path = headers['Location']
        self.now += 25
        status, _, page = self.request_raw('GET', path)
        self.assertEqual(status, 200)
        self.assertIn('시간이 끝났어요.', page)
        self.assertIn('1 / 5 완료', page)
        self.assertNotIn('http-equiv="refresh"', page)
