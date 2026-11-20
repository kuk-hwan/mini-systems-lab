"""Serve the same SQL engine over HTTP with a bounded pool of workers."""

import argparse
import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlsplit

from .database import Database


class SqlHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        started = time.perf_counter()
        try:
            status, result = self._route()
        except TimeoutError:
            status, result = 408, {'error': 'Request timed out'}
        except (ValueError, UnicodeError) as error:
            status, result = 400, {'error': str(error)}
        except OSError:
            logging.exception('SQL request failed')
            status, result = 500, {'error': 'Table I/O failed'}
        data = {
            **result,
            'worker': threading.current_thread().name,
            'request_ms': round((time.perf_counter() - started) * 1000, 4),
        }
        encoded = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(encoded)

    def _route(self):
        path = urlsplit(self.path).path
        db = self.server.db
        if self.command == 'GET' and path == '/api/health':
            return 200, {'status': 'ok'}
        if self.command == 'GET' and path == '/api/stats':
            return 200, {'tables': db.stats()}
        if self.command == 'POST' and path == '/api/sql':
            if self.headers.get_content_type() != 'application/json':
                return 415, {'error': 'Send Content-Type: application/json'}
            body = self._read_json()
            use_index = body.get('use_index', True)
            if type(use_index) is not bool:
                raise ValueError('use_index must be a boolean')
            return 200, {'results': db.execute(body.get('sql'), use_index=use_index)}
        return 404, {'error': 'API route not found'}

    def _read_json(self):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Send a request body with Content-Length')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= 65536:
            raise ValueError('Expected a request body of 1 to 65536 bytes')
        payload = self.rfile.read(length)
        if len(payload) != length:
            raise ValueError('Incomplete request body')
        try:
            body = json.loads(payload)
        except RecursionError as error:
            raise ValueError('JSON body is nested too deeply') from error
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        return body

    def log_message(self, *_):
        pass


class PoolServer(HTTPServer):
    def __init__(self, address, db, workers=8, queue_size=32):
        if workers < 1 or queue_size < 0:
            raise ValueError('Expected at least one worker and a nonnegative queue size')
        self.db = db
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='mini-db')
        self.slots = threading.BoundedSemaphore(workers + queue_size)
        super().__init__(address, SqlHandler)

    def process_request(self, request, client_address):
        request.settimeout(5)
        if not self.slots.acquire(blocking=False):
            try:
                request.sendall(b'HTTP/1.0 503 Service Unavailable\r\nContent-Length: 0\r\n\r\n')
            finally:
                self.shutdown_request(request)
            return
        try:
            self.pool.submit(self._serve, request, client_address)
        except RuntimeError:
            self.slots.release()
            raise

    def _serve(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception:
            self.handle_error(request, client_address)
        finally:
            self.shutdown_request(request)
            self.slots.release()

    def server_close(self):
        super().server_close()
        self.pool.shutdown(wait=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8796)
    parser.add_argument('--data', default='.data/db')
    parser.add_argument('--workers', type=int, default=8)
    args = parser.parse_args()
    try:
        with Database(args.data) as db, PoolServer((args.host, args.port), db, workers=args.workers) as server:
            print(f'Mini DBMS: http://{args.host}:{server.server_port} | workers: {args.workers}', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'Mini DBMS: {error}\n')


if __name__ == '__main__':
    main()
