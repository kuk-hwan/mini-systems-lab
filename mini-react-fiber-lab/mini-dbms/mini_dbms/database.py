"""Execute SQL against append-only table files and an in-memory ID index."""

import json
import os
import threading
import time
from itertools import islice
from pathlib import Path

from .bptree import BPlusTree
from .sql import parse


SCHEMAS = {
    'products': {'name': str, 'price': int},
    'scores': {'name': str, 'score': int},
}


class DirectoryLock:
    """Give one CLI or server process ownership of its in-memory index."""

    def __init__(self, directory):
        self.stream = (directory / '.engine.lock').open('a+b')
        try:
            if os.name == 'nt':
                import msvcrt
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            self.stream.close()
            raise RuntimeError('Data directory is in use. Stop the other process or choose --data.') from error

    def close(self):
        # Closing the file releases the process lock on both platforms.
        self.stream.close()


class Table:
    def __init__(self, path, schema):
        self.path = path
        self.schema = schema
        self.lock = threading.Lock()
        self.index = BPlusTree()
        self.next_id = 1
        self.committed_end = 0
        self.write_failed = False
        path.touch(exist_ok=True)
        self._rebuild()

    def _rebuild(self):
        with self.path.open('r+b') as stream:
            while line := stream.readline():
                offset = self.committed_end
                if not line.endswith(b'\n'):
                    stream.truncate(offset)
                    stream.flush()
                    os.fsync(stream.fileno())
                    break
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] != self.next_id:
                        raise ValueError('invalid row ID')
                    self.validate({key: value for key, value in row.items() if key != 'id'})
                except ValueError as error:
                    raise ValueError(f'{self.path.name}: invalid row at byte {offset}: {error}') from error
                self.index.insert(row['id'], offset)
                self.next_id += 1
                self.committed_end += len(line)

    def validate(self, values):
        if set(values) != set(self.schema):
            raise ValueError(f'Required columns: {", ".join(self.schema)}; id is automatic')
        for name, kind in self.schema.items():
            value = values[name]
            if type(value) is not kind:
                raise ValueError(f'{name} must be {kind.__name__}')
            if kind is str and not 1 <= len(value) <= 200:
                raise ValueError(f'{name} must contain 1 to 200 characters')
            if kind is int and not -(2**31) <= value < 2**31:
                raise ValueError(f'{name} must be a 32-bit integer')

    def append(self, values):
        return self._append_batch([values])[0]

    def bulk(self, values):
        """Benchmark loader; share the same file commit in batches of 10,000."""
        count = 0
        iterator = iter(values)
        while batch := list(islice(iterator, 10_000)):
            count += len(self._append_batch(batch))
        return count

    def _append_batch(self, batch):
        for values in batch:
            self.validate(values)
        with self.lock:
            if self.write_failed:
                raise OSError('Table writes are disabled after an I/O error; reopen the database')
            rows = [{'id': row_id, **values} for row_id, values in enumerate(batch, self.next_id)]
            encoded = [(json.dumps(row, ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
                       for row in rows]
            start = self.committed_end
            end = start
            offsets = []
            with self.path.open('r+b') as stream:
                stream.seek(start)
                try:
                    for line in encoded:
                        offsets.append(end)
                        stream.write(line)
                        end += len(line)
                    stream.flush()
                    os.fsync(stream.fileno())
                except OSError:
                    try:
                        stream.truncate(start)
                        stream.flush()
                        os.fsync(stream.fileno())
                    except OSError:
                        self.write_failed = True
                    raise
            for row, offset in zip(rows, offsets):
                self.index.insert(row['id'], offset)
            self.next_id += len(rows)
            self.committed_end = end
            return rows

    def select(self, columns, where, limit, *, use_index=True):
        allowed = {'id': int, **self.schema}
        if columns != ['*'] and any(column not in allowed for column in columns):
            raise ValueError('Unknown selected column')
        if where and (where[0] not in allowed or type(where[1]) is not allowed[where[0]]):
            raise ValueError('Unknown WHERE column or wrong literal type')
        indexed = use_index and where is not None and where[0] == 'id'
        plan = 'B+TREE' if indexed else 'FULL_SCAN'
        if limit == 0:
            return {'rows': [], 'plan': plan, 'rows_examined': 0, 'index_nodes_visited': 0}
        rows, examined, visited = [], 0, 0
        # Committed rows are immutable. Release the lock before the file read
        # so concurrent readers can scan the same table while new rows append.
        with self.lock:
            end = self.committed_end
            if indexed:
                offset, visited = self.index.lookup(where[1])
        if indexed:
            if offset is not None:
                with self.path.open('rb') as stream:
                    stream.seek(offset)
                    rows.append(json.loads(stream.readline()))
                    examined = 1
        else:
            with self.path.open('rb') as stream:
                remaining = end
                while remaining > 0:
                    line = stream.readline()
                    if not line:
                        raise OSError('Table file ended before the committed offset')
                    remaining -= len(line)
                    row = json.loads(line)
                    examined += 1
                    if where is None or row[where[0]] == where[1]:
                        rows.append(row)
                        if len(rows) == limit:
                            break
        if columns != ['*']:
            rows = [{key: row[key] for key in columns} for row in rows]
        return {
            'rows': rows, 'plan': plan,
            'rows_examined': examined, 'index_nodes_visited': visited,
        }


class Database:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.ownership = DirectoryLock(self.directory)
        try:
            self.tables = {
                name: Table(self.directory / f'{name}.jsonl', schema)
                for name, schema in SCHEMAS.items()
            }
        except Exception:
            self.close()
            raise

    def execute(self, sql, *, use_index=True):
        results = []
        for statement in parse(sql):
            started = time.perf_counter()
            table = self.tables.get(statement['table'])
            if table is None:
                raise ValueError(f'Unknown table: {statement["table"]}')
            if statement['op'] == 'INSERT':
                result = {'row': table.append(statement['values']), 'plan': 'APPEND+INDEX'}
            else:
                result = table.select(
                    statement['columns'], statement['where'], statement['limit'], use_index=use_index,
                )
            result['elapsed_ms'] = round((time.perf_counter() - started) * 1000, 4)
            results.append(result)
        return results

    def stats(self):
        output = {}
        for name, table in self.tables.items():
            with table.lock:
                output[name] = {**table.index.stats(), 'file_bytes': table.committed_end}
        return output

    def close(self):
        self.ownership.close()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()
