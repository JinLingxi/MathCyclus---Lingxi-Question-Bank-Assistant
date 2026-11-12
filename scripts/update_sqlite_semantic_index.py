"""Refresh the derived SQLite semantic index using the configured embedding API."""
import argparse
from contextlib import closing, redirect_stdout
from datetime import datetime
import io
import json
from pathlib import Path
import re
import sqlite3
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from services import semantic_search_service as service


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    config = dotenv_values(ROOT / '.env')
    model = str(config.get('AI_EMBEDDING_MODEL_NAME') or '').strip()
    rows = service.load_sqlite_index_rows()
    before = service.coverage_status(rows, model, sync_pending=args.apply)
    print(json.dumps({'stage': 'coverage', **before}), flush=True)
    if not args.apply:
        return
    if not model or not config.get('AI_API_KEY') or not config.get('AI_BASE_URL'):
        raise SystemExit('Embedding configuration is incomplete; no requests sent.')
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    receipt = ROOT / 'reports' / ('sqlite_semantic_update_' + stamp + '.json')
    index = Path(service.SEMANTIC_INDEX_PATH)
    backup = ROOT / 'data/backups' / ('semantic_index_before_sqlite_refresh_' + stamp + '.sqlite3')
    if index.exists():
        with closing(sqlite3.connect(index.resolve().as_uri() + '?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
                assert destination.execute('PRAGMA quick_check').fetchone()[0] == 'ok'
    original_request = service.request_embeddings
    def request(*request_args):
        for attempt in range(3):
            try:
                # The service normally prints the endpoint URL; this runner
                # records only counters and safe error categories.
                with redirect_stdout(io.StringIO()):
                    return original_request(*request_args, timeout=45)
            except service.SemanticSearchError as exc:
                message = str(exc)
                retryable = any(token in message for token in ('HTTP 429', 'HTTP 500', 'HTTP 502', 'HTTP 503', 'HTTP 504'))
                if not retryable or attempt == 2:
                    raise
                time.sleep(2 * (attempt + 1))
    service.request_embeddings = request
    result = {'before': before, 'model': model, 'source': 'sqlite_formal_questions',
              'backup': backup.relative_to(ROOT).as_posix(), 'formal_database_modified': False}
    def progress(done, total):
        print(json.dumps({'stage': 'embedding', 'done': done, 'total': total}), flush=True)
    try:
        result['update'] = service.build_index(
            rows, str(config.get('AI_BASE_URL') or ''), str(config.get('AI_API_KEY') or ''),
            model, progress=progress)
        # Imports may continue while a snapshot is being indexed. Compare
        # against the latest formal bank and leave any new work queued.
        result['after'] = service.coverage_status(service.load_sqlite_index_rows(), model, sync_pending=True)
        result['success'] = True
    except Exception as exc:
        result['success'] = False
        message = str(exc)
        http_status = re.search(r'HTTP (\d{3})', message)
        result['error_type'] = type(exc).__name__
        result['safe_error'] = 'HTTP ' + http_status[1] if http_status else (
            'Embedding transport failure' if '请求失败' in message else 'Embedding update failed')
        result['after'] = service.coverage_status(service.load_sqlite_index_rows(), model, sync_pending=True)
    finally:
        service.request_embeddings = original_request
    receipt.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({'receipt': receipt.relative_to(ROOT).as_posix(), **result}, ensure_ascii=False), flush=True)
    if not result['success']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
