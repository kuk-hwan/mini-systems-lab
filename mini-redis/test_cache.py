import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cache import HashTable, MiniRedis


class HashTests(unittest.TestCase):
    def test_collisions_resize_update_delete(self):
        table = HashTable(4)
        keys = [str(i) for i in range(500)]
        for i, key in enumerate(keys):
            table.set(key, i)
        self.assertGreater(len(table.buckets), 4)
        self.assertEqual(table.size, 500)
        for i, key in enumerate(keys):
            self.assertEqual(table.get(key), i)
        table.set('1', 99)
        self.assertEqual(table.get('1'), 99)
        self.assertEqual(table.size, 500)
        self.assertTrue(table.delete('1'))
        self.assertFalse(table.delete('1'))
        self.assertEqual(table.size, 499)

    def test_same_bucket_collision_preserves_neighbors(self):
        table = HashTable(32)
        keys = [str(i) for i in range(1000) if table.slot(str(i)) == 0][:3]
        for key in keys:
            table.set(key, key)
        table.delete(keys[1])
        self.assertEqual(table.get(keys[0]), keys[0])
        self.assertEqual(table.get(keys[2]), keys[2])

    def test_expiry_boundary_null_and_mutation_isolation(self):
        clock = [100.0]
        cache = MiniRedis(lambda: clock[0])
        value = {'items': [1]}
        cache.set('한글', value, 2)
        value['items'].append(2)
        read = cache.get('한글')
        self.assertEqual(read['value'], {'items': [1]})
        read['value']['items'].append(3)
        self.assertEqual(cache.get('한글')['value'], {'items': [1]})
        clock[0] = 102
        self.assertFalse(cache.get('한글')['found'])
        cache.set('null', None)
        self.assertEqual(cache.get('null'), {'found': True, 'value': None})
        cache.set('now', 1, 0)
        self.assertFalse(cache.get('now')['found'])

    def test_ttl_replacement_and_sweep(self):
        clock = [0]
        cache = MiniRedis(lambda: clock[0])
        cache.set('x', 1, 1)
        cache.set('x', 2)
        cache.set('y', 3, 1)
        clock[0] = 2
        self.assertEqual(cache.sweep(), 1)
        self.assertEqual(cache.get('x')['value'], 2)

    def test_invalid_ttl_and_key(self):
        cache = MiniRedis()
        for ttl in (-1, float('nan'), float('inf'), '1', True):
            with self.subTest(ttl=ttl), self.assertRaises(ValueError):
                cache.set('x', 1, ttl)
        with self.assertRaises(ValueError):
            cache.set('', 1)

    def test_snapshot_absolute_ttl(self):
        clock = [10]
        cache = MiniRedis(lambda: clock[0])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'snapshot.json'
            cache.set('permanent', {'v': 1})
            cache.set('expires', 1, 1)
            cache.snapshot(path)
            clock[0] = 12
            restored = MiniRedis(lambda: clock[0])
            restored.restore(path)
            self.assertFalse(restored.get('expires')['found'])
            self.assertEqual(restored.get('permanent')['value'], {'v': 1})

    def test_concurrent_writes(self):
        cache = MiniRedis()
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda i: cache.set(str(i), i), range(2000)))
        self.assertEqual(cache.stats()['keys'], 2000)
        for i in range(2000):
            self.assertEqual(cache.get(str(i))['value'], i)
