"""Disposable match cache, keyed by the exact formal corpus and scoring code.

Draft-only writes may refresh the snapshot, but do not invalidate match results.
The source database is always read-only; cache failures fall back to scoring.
"""
from functools import lru_cache
from contextlib import closing
import hashlib
import json
from pathlib import Path
import sqlite3

from services.database_service import BASE_DIR, readonly_database_connection, resolve_database_path


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()


@lru_cache(maxsize=1)
def _scorer_version():
    directory = Path(__file__).parent
    return hashlib.sha256(b''.join((directory / name).read_bytes() for name in (
        'question_similarity_service.py', 'import_service.py', 'question_match_cache.py'))).hexdigest()


def _database_token(path):
    values = []
    for filename in (path, path + '-wal'):
        try:
            s = Path(filename).stat()
            values.append((s.st_mtime_ns, s.st_ctime_ns, s.st_size))
        except FileNotFoundError:
            values.append(None)
    return tuple(values)


@lru_cache(maxsize=4)
def _snapshot(path, token):
    with readonly_database_connection(path) as conn:
        rows = tuple(tuple(r) for r in conn.execute(
            "SELECT question_id, stem_tex, choices_json, question_type_id "
            "FROM question WHERE stem_tex != '' ORDER BY question_id"))
    return rows, _digest(rows)


def corpus_snapshot(db_path):
    path = resolve_database_path(db_path)
    return _snapshot(path, _database_token(path))


def match_cache_key(corpus_hash, stem, choices, kind, minimum_score, max_results):
    return _digest([_scorer_version(), corpus_hash, stem, choices, kind, minimum_score, max_results])


def _cache_path(db_path):
    identity = hashlib.sha256(resolve_database_path(db_path).encode()).hexdigest()[:24]
    return Path(BASE_DIR) / 'data' / 'cache' / ('question_matches_' + identity + '.sqlite3')


def load_matches(db_path, key):
    path = _cache_path(db_path)
    if not path.is_file():
        return None
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=0.2)) as conn:
            row = conn.execute('SELECT result FROM matches WHERE cache_key=?', (key,)).fetchone()
        result = json.loads(row[0]) if row else None
        return result if isinstance(result, list) else None
    except (OSError, sqlite3.Error, ValueError):
        return None


def store_matches(db_path, key, result):
    path = _cache_path(db_path)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(path, timeout=0.2)) as conn, conn:
            conn.execute('CREATE TABLE IF NOT EXISTS matches (cache_key TEXT PRIMARY KEY, result TEXT NOT NULL)')
            conn.execute('INSERT OR REPLACE INTO matches VALUES (?, ?)',
                         (key, json.dumps(result, ensure_ascii=False)))
    except (OSError, sqlite3.Error):
        pass
