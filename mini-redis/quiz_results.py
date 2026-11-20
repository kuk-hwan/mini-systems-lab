"""Store completed quiz scores in SQLite and cache the recent list."""

import sqlite3
from pathlib import Path


RECENT_KEY = 'quiz:results:recent'
RECENT_TTL = 30
RECENT_LIMIT = 5


class QuizResults:
    def __init__(self, cache, path=None):
        self.cache = cache
        if path is not None:
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path if path is not None else ':memory:', check_same_thread=False)
        try:
            with self.db:
                self.db.execute('''
                    CREATE TABLE IF NOT EXISTS quiz_results (
                        id INTEGER PRIMARY KEY,
                        round_token TEXT NOT NULL UNIQUE,
                        score INTEGER NOT NULL,
                        total INTEGER NOT NULL,
                        completed_at REAL NOT NULL
                    )
                ''')
        except sqlite3.Error:
            self.db.close()
            raise

    def save(self, token, results, completed_at):
        score = sum(result['correct'] for result in results)
        # Keep the DB commit and cache invalidation in the same lock as recent().
        with self.cache.lock:
            with self.db:
                write = self.db.execute('''
                    INSERT INTO quiz_results (round_token, score, total, completed_at)
                    VALUES (?, ?, ?, ?) ON CONFLICT(round_token) DO NOTHING
                ''', (token, score, len(results), completed_at))
            if write.rowcount:
                self.cache.delete(RECENT_KEY)

    def recent(self):
        with self.cache.lock:
            cached = self.cache.get(RECENT_KEY)
            if cached['found']:
                return 'HIT', cached['value']
            rows = self.db.execute('''
                SELECT score, total, completed_at FROM quiz_results
                ORDER BY id DESC LIMIT ?
            ''', (RECENT_LIMIT,)).fetchall()
            results = [
                {'score': score, 'total': total, 'completed_at': completed_at}
                for score, total, completed_at in rows
            ]
            self.cache.set(RECENT_KEY, results, RECENT_TTL)
            return 'MISS', results

    def close(self):
        self.db.close()
