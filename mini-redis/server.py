"""A local HTTP interface for the standalone Mini Redis cache."""
import argparse
import json
import logging
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlsplit

from cache import MiniRedis
from quiz import Quiz
from quiz_page import QuizPages, WEB


QUIZ_PATH = re.compile(r'/quiz/([0-9a-f]{32})(?:/(answer|hint|next|result))?')


class CacheServer(ThreadingHTTPServer):
    # Let outstanding writes finish before saving the shutdown snapshot.
    daemon_threads = False

    def __init__(self, address, cache, snapshot=None):
        self.cache = cache
        self.snapshot = snapshot
        self.quiz = Quiz(cache.clock)
        self.quiz_pages = QuizPages(self.quiz)
        super().__init__(address, CacheHandler)

    def get_request(self):
        connection, address = super().get_request()
        connection.settimeout(5)
        return connection, address


class CacheHandler(BaseHTTPRequestHandler):
    def _read_body(self, max_length):
        if self.headers.get('Transfer-Encoding'):
            raise ValueError('Send a body with Content-Length')
        length = int(self.headers.get('Content-Length', '0'))
        if not 0 < length <= max_length:
            raise ValueError(f'Expected a body up to {max_length} bytes')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('Incomplete request body')
        return data

    def _read_object(self):
        body = json.loads(self._read_body(65536))
        if not isinstance(body, dict):
            raise ValueError('Expected a JSON object')
        return body

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

        if self.command == 'POST' and path == '/api/quiz/rounds':
            return 200, self.server.quiz.start(self._read_object().get('index'))
        parts = path.split('/')
        if len(parts) == 6 and parts[:4] == ['', 'api', 'quiz', 'rounds']:
            token, action = parts[4:]
            if len(token) != 32 or any(char not in '0123456789abcdef' for char in token):
                raise ValueError('Invalid round token')
            if self.command == 'GET' and action == 'hint':
                return 200, self.server.quiz.hint(token)
            if self.command == 'POST' and action == 'answer':
                body = self._read_object()
                if 'choice' not in body:
                    raise ValueError('Expected a choice field')
                return 200, self.server.quiz.answer(token, body['choice'])

        prefix = '/api/kv/'
        if path.startswith(prefix):
            key = unquote(path[len(prefix):], errors='strict')
            if not key or len(key.encode('utf-8')) > 1024:
                raise ValueError('key must be a nonempty UTF-8 string up to 1024 bytes')
            if self.command == 'PUT':
                body = self._read_object()
                if 'value' not in body:
                    raise ValueError('Expected a value field')
                ttl = body.get('ttl')
                cache.set(key, body['value'], ttl)
                return 200, {'stored': True, 'ttl': ttl}
            if self.command == 'GET':
                return 200, cache.get(key)
            if self.command == 'DELETE':
                return 200, {'deleted': cache.delete(key)}
        return 404, {'error': 'API route not found'}

    def _handle(self):
        path = urlsplit(self.path).path
        if self.command == 'GET' and path == '/quiz.css':
            self._respond(200, (WEB / 'quiz.css').read_bytes(), 'text/css; charset=utf-8')
            return
        if path in ('/', '/quiz', '/quiz/start') or QUIZ_PATH.fullmatch(path):
            self._handle_quiz_page(path)
            return
        try:
            code, result = self._route()
        except (ValueError, OverflowError, RecursionError) as error:
            code, result = 400, {'error': str(error)}
        except TimeoutError:
            code, result = 408, {'error': 'Request timed out'}
        except LookupError as error:
            code, result = 404, {'error': str(error)}
        except OSError:
            logging.exception('Cache operation failed')
            code, result = 500, {'error': 'Cache operation failed'}
        encoded = json.dumps(result, allow_nan=False).encode('utf-8')
        self._respond(code, encoded, 'application/json; charset=utf-8')

    def _handle_quiz_page(self, path):
        pages = self.server.quiz_pages
        try:
            match = QUIZ_PATH.fullmatch(path)
            if self.command == 'GET' and path in ('/', '/quiz'):
                return self._html(200, pages.intro())
            if self.command == 'POST' and path == '/quiz/start':
                return self._redirect(pages.start())
            if match:
                token, action = match.groups()
                if self.command == 'GET' and action in (None, 'result'):
                    return self._html(200, pages.play(token, show_results=action == 'result'))
                if self.command == 'POST' and action in ('answer', 'hint', 'next'):
                    choice = None
                    if action == 'answer':
                        data = parse_qs(self._read_body(1024).decode('ascii'), max_num_fields=4)
                        values = data.get('choice', [])
                        if len(values) != 1:
                            raise ValueError('Choose one answer')
                        choice = int(values[0])
                    return self._redirect(pages.act(token, action, choice))
        except LookupError:
            return self._html(404, pages.intro('이 문제 세션은 종료됐어요. 새 퀴즈를 시작해 주세요.'))
        except (ValueError, TimeoutError):
            return self._html(400, pages.intro('요청을 처리하지 못했어요. 새 퀴즈를 시작해 주세요.'))
        return self._html(404, pages.intro('요청한 퀴즈 화면을 찾을 수 없어요.'))

    def _html(self, code, page):
        self._respond(code, page.encode('utf-8'), 'text/html; charset=utf-8')

    def _redirect(self, path):
        self._respond(303, b'', 'text/html; charset=utf-8', location=path)

    def _respond(self, code, encoded, media_type, location=None):
        self.send_response(code)
        self.send_header('Content-Type', media_type)
        self.send_header('Content-Length', str(len(encoded)))
        self.send_header('Cache-Control', 'no-store')
        if location is not None:
            self.send_header('Location', location)
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
