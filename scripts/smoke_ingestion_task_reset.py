"""Check task reset isolation, stale-plan rejection and FK cascades."""
import sys
import sqlite3
from contextlib import closing
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.database_service import initialize_database, readonly_database_connection
from services.import_service import create_manual_entry_draft, get_draft_question, update_draft_question_fields
from services.ingestion_review_service import (create_task_plan, task_tree, task_reset_snapshot, delete_uncommitted_task,
    paper_scope_snapshot, replace_uncommitted_papers)


def main():
    with tempfile.TemporaryDirectory(dir=ROOT / 'data', prefix='task_reset_smoke_') as directory:
        db = str(Path(directory) / 'test.sqlite3')
        initialize_database(db)
        tasks = []
        drafts = []
        for year in (2025, 2026):
            root = create_task_plan(db, task_key=str(year), title=f'{year} test', source_path='test.pdf',
                                    papers=[{'year': year, 'paper_name': 'test paper'}])
            nodes, _ = task_tree(db)
            paper = next(n for n in nodes if n.get('parent_batch_id') == root)
            draft = create_manual_entry_draft(db, {'source_item_id': str(year), 'stem_tex': '$x=1$'},
                                              batch_id=paper['batch_id'])
            tasks.append(root)
            drafts.append(draft['draft_id'])
        plan = task_reset_snapshot(db, tasks[0])
        update_draft_question_fields(db, drafts[0], {'stem_tex': '$x=2$'})
        try:
            delete_uncommitted_task(db, tasks[0], expected_fingerprint=plan['fingerprint'])
        except ValueError:
            pass
        else:
            raise AssertionError('stale cleanup plan was accepted')
        assert get_draft_question(db, drafts[0])
        nodes, _ = task_tree(db)
        selected = [n['batch_id'] for n in nodes if n.get('parent_batch_id') == tasks[0]]
        paper_plan = paper_scope_snapshot(db, selected)
        prepared = str(Path(directory) / 'prepared.sqlite3')
        with closing(sqlite3.connect(db)) as source, closing(sqlite3.connect(prepared)) as target:
            source.backup(target)
        update_draft_question_fields(prepared, drafts[0], {'stem_tex': '$x=3$'})
        unaffected = get_draft_question(db, drafts[1])
        replacement = replace_uncommitted_papers(db, prepared, selected, expected_fingerprint=paper_plan['fingerprint'])
        assert replacement['installed']['question_import_draft'] == 1
        assert get_draft_question(db, drafts[0])['stem_tex'] == '$x=3$'
        assert get_draft_question(db, drafts[1]) == unaffected
        try:
            replace_uncommitted_papers(db, prepared, selected, expected_fingerprint=paper_plan['fingerprint'])
        except ValueError:
            pass
        else:
            raise AssertionError('stale paper replacement was accepted')
        assert get_draft_question(db, drafts[0])['stem_tex'] == '$x=3$'
        plan = task_reset_snapshot(db, tasks[0])
        assert plan['counts']['draft_review_event'] > 0
        other_before = task_reset_snapshot(db, tasks[1])
        delete_uncommitted_task(db, tasks[0], expected_fingerprint=plan['fingerprint'])
        assert task_reset_snapshot(db, tasks[1]) == other_before
        assert get_draft_question(db, drafts[1])
        with readonly_database_connection(db) as conn:
            assert not conn.execute('SELECT 1 FROM import_batch WHERE batch_id=?', (tasks[0],)).fetchone()
            assert not conn.execute('SELECT 1 FROM question_import_draft WHERE draft_id=?', (drafts[0],)).fetchone()
            assert not conn.execute('SELECT 1 FROM draft_review_event WHERE draft_id=?', (drafts[0],)).fetchone()
            assert not conn.execute('PRAGMA foreign_key_check').fetchall()
    print('ingestion_task_reset=ok (isolation, stale plans, cascades)')


if __name__ == '__main__':
    main()
