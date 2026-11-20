import json
import os
import random
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from subprocess import run
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from mini_dbms.bptree import BPlusTree
from mini_dbms.database import Database
from mini_dbms.server import PoolServer
from mini_dbms.sql import parse


class SqlTests(unittest.TestCase):
    def test_parse_comments_korean_and_escaped_quotes(self):
        rows = parse("-- demo\nINSERT INTO products (name, price) VALUES ('한글 O''Brien;', 4); "
                     "SELECT name FROM products WHERE id = 1 LIMIT 1;")
        self.assertEqual(rows[0]['values'], {'name': "한글 O'Brien;", 'price': 4})
        self.assertEqual(rows[1]['where'], ('id', 1))

    def test_reject_invalid_syntax(self):
        for sql in ('', 'DELETE FROM products', 'SELECT * FROM ../products',
                    'SELECT * FROM products WHERE id = 1LIMIT 2',
                    "SELECT * FROM products WHERE name = 'unfinished",
                    'SELECT * FROM products LIMIT -1',
                    "INSERT INTO products (name, name) VALUES ('a', 'b')"):
            with self.subTest(sql=sql), self.assertRaises(ValueError):
                parse(sql)


class TreeTests(unittest.TestCase):
    def test_lookup_and_order_after_leaf_and_internal_splits(self):
        for order in (3, 4, 8, 64):
            tree = BPlusTree(order)
            keys = list(range(500))
            random.Random(7).shuffle(keys)
            for key in keys:
                tree.insert(key, key * 8)
            self.assertGreaterEqual(tree.stats()['height'], 2)
            self.assertEqual(list(tree.items()), [(key, key * 8) for key in sorted(keys)])
            for key in keys:
                self.assertEqual(tree.lookup(key)[0], key * 8)
            tree.insert(17, 99999)
            self.assertEqual(tree.size, 500)
            self.assertEqual(tree.lookup(17)[0], 99999)
            self.assertIsNone(tree.lookup(500)[0])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.directory = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_cli_uses_the_same_file_across_processes(self):
        env = {**os.environ, 'PYTHONIOENCODING': 'utf-8'}
        project = Path(__file__).resolve().parents[1]
        insert = run([sys.executable, '-m', 'mini_dbms.cli', 'examples/demo.sql', '--data', str(self.directory)],
                     cwd=project, capture_output=True, encoding='utf-8', env=env, check=True)
        self.assertEqual(json.loads(insert.stdout)[2]['rows'][0]['name'], '빵')
        reopened = run([sys.executable, '-m', 'mini_dbms.cli', 'examples/read.sql', '--data', str(self.directory)],
                       cwd=project, capture_output=True, encoding='utf-8', env=env, check=True)
        self.assertEqual([row['name'] for row in json.loads(reopened.stdout)[0]['rows']], ['우유', '빵'])

    def test_lookup_finds_utf8_offsets_and_default_select_returns_all_rows(self):
        with Database(self.directory) as db:
            db.execute("INSERT INTO products (name, price) VALUES ('우유 🚀', 1)")
            db.tables['products'].bulk({'name': f'p{i}', 'price': i} for i in range(150))
            self.assertEqual(len(db.execute('SELECT id FROM products')[0]['rows']), 151)
            self.assertEqual(db.execute('SELECT * FROM products LIMIT 0')[0]['rows'], [])
        with Database(self.directory) as db:
            query = 'SELECT * FROM products WHERE id = 151'
            indexed = db.execute(query)[0]
            scan = db.execute(query, use_index=False)[0]
            self.assertEqual(indexed['rows'], scan['rows'])
            self.assertEqual(indexed['rows'], [{'id': 151, 'name': 'p149', 'price': 149}])
            self.assertEqual((indexed['plan'], indexed['rows_examined']), ('B+TREE', 1))
            self.assertEqual((scan['plan'], scan['rows_examined']), ('FULL_SCAN', 151))
            self.assertEqual(db.execute('SELECT * FROM products WHERE id = 999')[0]['rows'], [])
            self.assertEqual(db.execute("INSERT INTO products (name, price) VALUES ('새 행', 3)")[0]['row']['id'], 152)

    def test_reject_wrong_columns_and_types(self):
        with Database(self.directory) as db:
            for sql in ("INSERT INTO products (id, name, price) VALUES (1, 'a', 4)",
                        "INSERT INTO products (name, price) VALUES ('a', '4')",
                        "SELECT * FROM products WHERE id = '1'",
                        'SELECT missing FROM products', 'SELECT * FROM unknown'):
                with self.subTest(sql=sql), self.assertRaises(ValueError):
                    db.execute(sql)

    def test_recover_partial_tail_but_report_corrupt_complete_record(self):
        with Database(self.directory) as db:
            db.execute("INSERT INTO products (name, price) VALUES ('a', 1)")
        path = self.directory / 'products.jsonl'
        committed = path.read_bytes()
        path.write_bytes(committed + b'{"id":2')
        with Database(self.directory) as db:
            self.assertEqual(db.stats()['products']['entries'], 1)
        self.assertEqual(path.read_bytes(), committed)
        broken = committed + b'broken complete row\n'
        path.write_bytes(broken)
        with self.assertRaisesRegex(ValueError, 'invalid row at byte'):
            Database(self.directory)
        self.assertEqual(path.read_bytes(), broken)

    def test_io_error_rolls_back_the_row_and_index(self):
        with Database(self.directory) as db:
            db.execute("INSERT INTO products (name, price) VALUES ('a', 1)")
            with patch('mini_dbms.database.os.fsync', side_effect=[OSError('write failure'), None]):
                with self.assertRaisesRegex(OSError, 'write failure'):
                    db.execute("INSERT INTO products (name, price) VALUES ('failed', 2)")
            self.assertEqual(db.execute('SELECT id FROM products')[0]['rows'], [{'id': 1}])
            self.assertEqual(db.execute('SELECT id FROM products WHERE id = 2')[0]['rows'], [])
            self.assertEqual(db.execute("INSERT INTO products (name, price) VALUES ('b', 3)")[0]['row']['id'], 2)

    def test_two_instances_cannot_own_one_database(self):
        with Database(self.directory):
            with self.assertRaises(RuntimeError):
                Database(self.directory)

    def test_a_scan_reads_only_rows_committed_when_it_began(self):
        scan_started = threading.Event()
        resume_scan = threading.Event()
        decode = json.loads

        def pause_first_read(line):
            if not scan_started.is_set():
                scan_started.set()
                if not resume_scan.wait(timeout=3):
                    raise TimeoutError('Scan did not resume')
            return decode(line)

        with Database(self.directory) as db:
            db.execute("INSERT INTO products (name, price) VALUES ('a', 1)")
            with patch('mini_dbms.database.json.loads', side_effect=pause_first_read):
                with ThreadPoolExecutor(max_workers=1) as reader:
                    scan = reader.submit(db.execute, 'SELECT id FROM products')
                    try:
                        self.assertTrue(scan_started.wait(timeout=3))
                        db.execute("INSERT INTO products (name, price) VALUES ('b', 2)")
                    finally:
                        resume_scan.set()
                    self.assertEqual(scan.result(timeout=3)[0]['rows'], [{'id': 1}])
            self.assertEqual(db.execute('SELECT id FROM products')[0]['rows'], [{'id': 1}, {'id': 2}])


class ApiTests(unittest.TestCase):
    def setUp(self):
        directory = self.enterContext(tempfile.TemporaryDirectory())
        self.db = self.enterContext(Database(directory))
        self.server = self.enterContext(PoolServer(('127.0.0.1', 0), self.db, workers=4))
        worker = threading.Thread(target=self.server.serve_forever)
        worker.start()
        self.addCleanup(worker.join)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def request(self, path, body=None):
        data = json.dumps(body).encode('utf-8') if body is not None else None
        request = Request(self.url + path, data=data, headers={'Content-Type': 'application/json'})
        try:
            with urlopen(request, timeout=5) as response:
                return response.status, json.load(response)
        except HTTPError as error:
            with error:
                return error.code, json.load(error)

    def test_api_can_run_sql_and_expose_the_plan(self):
        self.assertEqual(self.request('/api/health')[0], 200)
        _, write = self.request('/api/sql', {'sql': "INSERT INTO scores (name, score) VALUES ('민수', 5);"})
        self.assertEqual(write['results'][0]['row'], {'id': 1, 'name': '민수', 'score': 5})
        sql = 'SELECT * FROM scores WHERE id = 1'
        _, indexed = self.request('/api/sql', {'sql': sql})
        _, scan = self.request('/api/sql', {'sql': sql, 'use_index': False})
        self.assertEqual(indexed['results'][0]['plan'], 'B+TREE')
        self.assertEqual(scan['results'][0]['plan'], 'FULL_SCAN')
        self.assertEqual(self.request('/api/stats')[1]['tables']['scores']['entries'], 1)
        self.assertEqual(self.request('/api/sql', {'sql': 'DROP TABLE scores'})[0], 400)
        self.assertEqual(self.request('/api/sql', {'sql': sql, 'use_index': 'no'})[0], 400)
        self.assertEqual(self.request('/missing')[0], 404)

    def test_workers_process_concurrent_requests(self):
        both_entered = threading.Barrier(2)
        execute = self.db.execute

        def wait_for_second_request(*args, **kwargs):
            both_entered.wait(timeout=3)
            return execute(*args, **kwargs)

        with patch.object(self.db, 'execute', side_effect=wait_for_second_request):
            with ThreadPoolExecutor(max_workers=2) as clients:
                responses = list(clients.map(lambda _: self.request(
                    '/api/sql', {'sql': 'SELECT * FROM products'},
                ), range(2)))
        self.assertEqual([code for code, _ in responses], [200, 200])
        self.assertEqual(len({body['worker'] for _, body in responses}), 2)

    def test_concurrent_inserts_create_unique_ids_and_readable_rows(self):
        def insert(i):
            status, response = self.request('/api/sql', {
                'sql': f"INSERT INTO products (name, price) VALUES ('p{i}', {i})",
            })
            self.assertEqual(status, 200)
            return i, response['results'][0]['row']['id']

        with ThreadPoolExecutor(max_workers=6) as clients:
            writes = dict(clients.map(insert, range(24)))
        self.assertEqual(sorted(writes.values()), list(range(1, 25)))
        for price, row_id in writes.items():
            _, response = self.request('/api/sql', {'sql': f'SELECT * FROM products WHERE id = {row_id}'})
            self.assertEqual(response['results'][0]['rows'][0]['price'], price)
