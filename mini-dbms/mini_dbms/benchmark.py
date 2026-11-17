"""Compare indexed and sequential SQL reads over the same records."""

import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

from .database import Database
from .sql import parse


def measure(directory, count, repeats):
    with Database(directory) as db:
        def records():
            for number in range(1, count + 1):
                sql = f"INSERT INTO products (name, price) VALUES ('product-{number}', {number})"
                yield parse(sql)[0]['values']

        table = db.tables['products']
        started = time.perf_counter()
        inserted = table.bulk(records())
        insert_ms = (time.perf_counter() - started) * 1000
        id_query = f'SELECT * FROM products WHERE id = {count}'
        variants = {
            'indexed_id': (id_query, True),
            'scan_name': (f"SELECT * FROM products WHERE name = 'product-{count}'", True),
            'scan_id': (id_query, False),
        }

        def run(label):
            sql, use_index = variants[label]
            start = time.perf_counter()
            result = db.execute(sql, use_index=use_index)[0]
            return result, (time.perf_counter() - start) * 1000

        # Warm all paths, and rotate the order of subsequent measurements.
        expected = [{'id': count, 'name': f'product-{count}', 'price': count}]
        for label in variants:
            result, _ = run(label)
            if result['rows'] != expected:
                raise RuntimeError(f'{label} returned the wrong record')
        labels = tuple(variants)
        plans = {}
        samples = {label: [] for label in variants}
        for iteration in range(repeats):
            offset = iteration % len(labels)
            for label in labels[offset:] + labels[:offset]:
                plans[label], elapsed = run(label)
                samples[label].append(elapsed)

        return {
            'rows': inserted,
            'python': platform.python_version(),
            'platform': platform.system(),
            'insert_ms': round(insert_ms, 3),
            'insert_batch_size': 10_000,
            'repeats': repeats,
            'file_bytes': table.committed_end,
            'index': table.index.stats(),
            'queries': {
                label: {
                    'sql': variants[label][0],
                    'plan': plans[label]['plan'],
                    'rows_examined': plans[label]['rows_examined'],
                    'index_nodes_visited': plans[label]['index_nodes_visited'],
                    'median_ms': round(statistics.median(samples[label]), 4),
                    'samples_ms': [round(sample, 4) for sample in samples[label]],
                }
                for label in variants
            },
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rows', default=1_000_000, type=int)
    parser.add_argument('--repeats', default=5, type=int)
    parser.add_argument('--output', type=Path, help='Optional JSON report path')
    args = parser.parse_args()
    if args.rows <= 0 or args.repeats <= 0:
        parser.error('--rows and --repeats must be positive')
    with tempfile.TemporaryDirectory(prefix='mini-dbms-bench-') as directory:
        report = measure(directory, args.rows, args.repeats)
    encoded = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded + '\n', encoding='utf-8')
    print(encoded)


if __name__ == '__main__':
    main()
