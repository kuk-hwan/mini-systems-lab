"""A local HTTP interface for the standalone Mini Redis cache."""
import argparse
import json
import logging
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit

from cache import MiniRedis


class CacheServer(ThreadingHTTPServer):
    # Let outstanding writes finish before saving the shutdown snapshot.
    daemon_threads = False

    def __init__(self, address, cache, snapshot=None):
        self.cache = cache
        self.snapshot = snapshot
        super().__init__(address, CacheHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class CacheHandler(BaseHTTPRequestHandler):
    def _read_value(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Send a JSON body with Content-Length')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 65536:
            raise ValueError('Expected a JSON body up to 64 KiB')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('Incomplete request body')
        body = json.loads(data)
        if not isinstance(body, dict) or 'value' not in body:
            raise ValueError('Expected a JSON object with a value field')
        return body['value'], body.get('ttl')

    def _route(self):
        path = urlsplit(self.path).path
        cache = self.server.cache
        if self.command == 'GET' and path == '/api/health':
            return 200, {'status': 'ok', 'engine': 'Mini Redis'}
        if self.command == 'GET' and path == '/api/metrics':
            return 200, {'cache': cache.stats()}
        if self.command == 'POST' and path == '/api/cache/snapshot':
            if self.server.snapshot is None:
                return 409, {'error': 'Start the server with --snapshot to enable persistence'}
            cache.snapshot(self.server.snapshot)
            return 200, {'saved': True}

        prefix = '/api/kv/'
        if path.startswith(prefix):
            key = unquote(path[len(prefix):], errors='strict')
            if not key or len(key.encode('utf-8')) > 1024:
                raise ValueError('key must be a nonempty UTF-8 string up to 1024 bytes')
            if self.command == 'PUT':
                value, ttl = self._read_value()
                cache.set(key, value, ttl)
                return 200, {'stored': True, 'ttl': ttl}
            if self.command == 'GET':
                return 200, cache.get(key)
            if self.command == 'DELETE':
                return 200, {'deleted': cache.delete(key)}
        return 404, {'error': 'API route not found'}

    def _handle(self):
        try:
            code, result = self._route()
        except (ValueError, OverflowError, RecursionError) as error:
            code, result = 400, {'error': str(error)}
        except TimeoutError:
            code, result = 408, {'error': 'Request timed out'}
        except OSError:
            logging.exception('Cache operation failed')
            code, result = 500, {'error': 'Cache operation failed'}
        encoded = json.dumps(result, allow_nan=False).encode('utf-8')
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)

    do_GET = do_PUT = do_DELETE = do_POST = _handle


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8787)
    parser.add_argument('--snapshot', type=Path, help='Optional path to persist the cache')
    args = parser.parse_args()

    cache = MiniRedis()
    if args.snapshot is not None:
        cache.restore(args.snapshot)
    with CacheServer(('127.0.0.1', args.port), cache, args.snapshot) as server:
        print(f'Mini Redis: http://127.0.0.1:{server.server_port}', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
    if args.snapshot is not None:
        cache.snapshot(args.snapshot)


if __name__ == '__main__':
    main()
