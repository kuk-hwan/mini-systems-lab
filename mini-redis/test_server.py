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
        connection = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        try:
            content = None if body is None else json.dumps(body)
            connection.request(method, path, body=content, headers={'Content-Type': 'application/json'})
            response = connection.getresponse()
            return response.status, json.load(response)
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
