import http.client
import json
import sqlite3
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from urllib.parse import quote

from cache import MiniRedis
from server import CacheServer
from quiz_results import RECENT_TTL


class CacheApiTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.cache = MiniRedis(lambda: self.now)
        data = self.enterContext(tempfile.TemporaryDirectory())
        self.snapshot = Path(data) / 'cache.json'
        self.results_path = Path(data) / 'scores.sqlite3'
        self.server = self.enterContext(CacheServer(
            ('127.0.0.1', 0), self.cache, self.snapshot, results_path=self.results_path,
        ))
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

    def complete_quiz(self, choices):
        _, headers, _ = self.request_raw('POST', '/quiz/start')
        path = headers['Location']
        for choice in choices:
            self.assertEqual(self.request_raw('POST', path + '/answer', f'choice={choice}')[0], 303)
            status, headers, _ = self.request_raw('POST', path + '/next')
            self.assertEqual(status, 303)
            path = headers['Location']
        return path

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
        _, unread_round = self.request('POST', '/api/quiz/rounds', {'index': 1})
        unread_path = '/api/quiz/rounds/' + unread_round['token'] + '/hint'
        self.now += round_data['hint_seconds']
        self.assertEqual(self.request('GET', path + '/hint'), (409, {'status': 'LIMIT', 'value': None}))
        self.assertEqual(self.request('GET', unread_path), (200, {'status': 'MISS', 'value': None}))
        self.assertEqual(self.request('GET', unread_path), (409, {'status': 'LIMIT', 'value': None}))
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

    def test_hint_shows_redis_ttl_and_accepts_only_one_lookup(self):
        _, headers, _ = self.request_raw('POST', '/quiz/start')
        path = headers['Location']
        self.now += 8
        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.request_raw('POST', path + '/hint')[0], range(2)))
        self.assertEqual(statuses, [303, 303])
        _, _, page = self.request_raw('GET', path)
        self.assertIn('aria-label="캐시에 남은 힌트 시간" aria-valuemin="0" aria-valuemax="10" aria-valuenow="2"', page)
        self.assertIn('이번 문제 조회 <strong>1회</strong>', page)
        self.assertIn('class="hint-button" type="submit" disabled>힌트 조회 완료', page)
        self.assertEqual(page.count('GET · HIT'), 1)

        with ThreadPoolExecutor(max_workers=2) as pool:
            statuses = list(pool.map(lambda _: self.request_raw('POST', path + '/extend')[0], range(2)))
        self.assertEqual(statuses, [303, 303])
        _, _, page = self.request_raw('GET', path)
        self.assertIn('aria-valuemax="15" aria-valuenow="7"', page)
        self.assertIn('aria-valuemax="25" aria-valuenow="17"', page)
        self.assertEqual(page.count('<b>EXPIRE</b>'), 1)
        self.assertIn('연장 사용 완료', page)
        self.assertIn('이번 문제 조회 <strong>1회</strong>', page)

        self.now += 7
        self.assertEqual(self.request_raw('POST', path + '/hint')[0], 303)
        _, _, page = self.request_raw('GET', path)
        self.assertNotIn('GET · MISS', page)
        self.assertIn('TTL 만료', page)
        self.assertIn('이번 문제 조회 <strong>1회</strong>', page)
        self.assertEqual(self.request_raw('POST', path + '/answer', 'choice=0')[0], 303)
        _, headers, _ = self.request_raw('POST', path + '/next')
        self.assertIn('이번 문제 조회 <strong>0회</strong>', self.request_raw('GET', headers['Location'])[2])

    def test_expired_hint_cannot_be_extended(self):
        _, headers, _ = self.request_raw('POST', '/quiz/start')
        path = headers['Location']
        self.now += 10
        self.assertEqual(self.request_raw('POST', path + '/extend')[0], 303)
        _, _, page = self.request_raw('GET', path)
        self.assertIn('TTL 만료', page)
        self.assertNotIn('<b>EXPIRE</b>', page)
        self.assertIn('이번 문제 조회 <strong>0회</strong>', page)

        for _ in range(2):
            self.assertEqual(self.request_raw('POST', path + '/hint')[0], 303)
        _, _, page = self.request_raw('GET', path)
        self.assertEqual(page.count('GET · MISS'), 1)
        self.assertIn('class="hint-button" type="submit" disabled>힌트 조회 완료', page)
        self.assertIn('이번 문제 조회 <strong>1회</strong>', page)

    def test_recent_scores_miss_hit_expire_and_invalidate_on_new_score(self):
        first = self.complete_quiz((0, 1, 2, 0, 2))
        queries = []
        self.server.results.db.set_trace_callback(queries.append)

        def read_result(path, expected):
            queries.clear()
            _, _, page = self.request_raw('GET', path)
            self.assertIn(f'GET · {expected}', page)
            used_db = any('SELECT score' in statement for statement in queries)
            self.assertEqual(used_db, expected == 'MISS')
            return page

        self.assertIn('<strong>5 / 5</strong>', read_result(first, 'MISS'))
        self.assertIn('결과 목록 다시 조회', read_result(first, 'HIT'))
        last_question = first.removesuffix('/result')
        self.assertEqual(self.request_raw('POST', last_question + '/next')[0], 303)
        read_result(first, 'HIT')
        self.now += RECENT_TTL
        read_result(first, 'MISS')

        second = self.complete_quiz((1, 0, 0, 1, 0))
        page = read_result(second, 'MISS')
        self.assertLess(page.index('<strong>0 / 5</strong>'), page.index('<strong>5 / 5</strong>'))
        read_result(second, 'HIT')
        with closing(sqlite3.connect(self.results_path)) as db:
            self.assertEqual(db.execute('SELECT score FROM quiz_results ORDER BY id').fetchall(), [(5,), (0,)])
