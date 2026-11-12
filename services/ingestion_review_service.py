"""Task planning and complete subtree reads for the ingestion review screen."""

import json
import re
import hashlib

from services.database_service import existing_database_connection, readonly_database_connection
from services.import_service import stable_id


def metadata(value):
    try:
        result = json.loads(value or '{}')
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def descendants(nodes, root_id):
    children = {}
    for node in nodes:
        children.setdefault(node.get('parent_batch_id'), []).append(node['batch_id'])
    return _descendants(children, root_id)


def _descendants(children, root_id):
    found, pending = set(), [root_id]
    while pending:
        current = pending.pop()
        if current in found:
            continue
        found.add(current)
        pending.extend(children.get(current, ()))
    return found


def create_task_plan(db_path, *, task_key, title, source_path, papers):
    """Register a real source inventory, without pretending it contains drafts.

    Repeating a task key preserves existing children, drafts and review events.
    The caller supplies names checked against the local standard catalogue.
    """
    root_id = stable_id('IB', 'codex_task', task_key)
    with existing_database_connection(db_path) as conn:
        for level, key, label, parent, detail in [
            (0, task_key, title, None, {'stage': 'pending_transcription'}),
            *[(1, f"{p['year']}|{p['paper_name']}", p['paper_name'], root_id, p) for p in papers],
        ]:
            batch_id = root_id if level == 0 else stable_id('IB', root_id, key)
            conn.execute('''INSERT INTO import_batch
                (batch_id, import_type, source_path, mode, task_id, parent_batch_id,
                 hierarchy_level, subset_key, subset_label, summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(batch_id) DO NOTHING''', (
                    batch_id, 'codex_task' if level == 0 else 'codex_subset', source_path,
                    'task' if level == 0 else 'subset', root_id, parent, level, key, label,
                    json.dumps(detail, ensure_ascii=False),
                ))
    return root_id


def task_tree(db_path):
    with readonly_database_connection(db_path) as conn:
        rows = [dict(r) for r in conn.execute('''SELECT b.*, COUNT(d.draft_id) AS direct_count
            FROM import_batch b LEFT JOIN question_import_draft d
            ON d.batch_id=b.batch_id AND d.review_status <> 'sample'
            GROUP BY b.batch_id ORDER BY b.started_at DESC, b.batch_id''')]
    roots = [r for r in rows if r['import_type'] == 'codex_task' and not r.get('parent_batch_id')]
    children = {}
    counts = {}
    for row in rows:
        children.setdefault(row.get('parent_batch_id'), []).append(row['batch_id'])
        counts[row['batch_id']] = row['direct_count']
    included = set().union(*(_descendants(children, r['batch_id']) for r in roots)) if roots else set()
    rows = [r for r in rows if r['batch_id'] in included]
    for row in rows:
        subtree = _descendants(children, row['batch_id'])
        row['draft_count'] = sum(counts[i] for i in subtree)
        row['metadata'] = metadata(row.get('summary'))
        row['label'] = row.get('subset_label') or (
            row.get('summary') if not row['metadata'] else ''
        ) or '未命名录题任务'
    return rows, roots


def paper_drafts(db_path, nodes, paper_id, *, with_assets=False):
    ids = sorted(descendants(nodes, paper_id))
    with readonly_database_connection(db_path) as conn:
        rows = [dict(r) for r in conn.execute(
            'SELECT * FROM question_import_draft WHERE review_status <> ? AND batch_id IN ('
            + ','.join('?' for _ in ids) + ')', ['sample', *ids])]
        if with_assets:
            by_id = {r['draft_id']: r for r in rows}
            for row in rows:
                row['assets'] = []
            for asset in conn.execute(
                'SELECT a.* FROM question_import_draft_asset a JOIN question_import_draft d '
                'ON d.draft_id=a.draft_id WHERE d.review_status <> ? AND d.batch_id IN ('
                + ','.join('?' for _ in ids) + ') ORDER BY a.role,a.sort_order,a.draft_asset_id', ['sample', *ids]):
                by_id[asset['draft_id']]['assets'].append(dict(asset))
    def order(row):
        extra = metadata(row.get('extra_json'))
        if extra.get('source_kind') == '教材':
            position = int(extra.get('book_display_order') or int(extra.get('page_start') or 0) * 1000 + int(extra.get('page_local_index') or 0))
            return ((-1, position),), row['draft_id']
        number = str(extra.get('detected_question_number') or extra.get('question_number') or row['source_item_id'])
        return tuple((0, int(p)) if p.isdigit() else (1, p) for p in re.split(r'(\d+)', number)), row['draft_id']
    return sorted(rows, key=order)


def _task_reset_snapshot(conn, root_id):
    root = conn.execute('SELECT * FROM import_batch WHERE batch_id=?', (root_id,)).fetchone()
    if not root or root['import_type'] != 'codex_task' or root['parent_batch_id']:
        raise ValueError('必须指定录题任务的总批次 ID')
    batches = [dict(r) for r in conn.execute('''WITH RECURSIVE tree(id) AS (
        SELECT ? UNION SELECT b.batch_id FROM import_batch b JOIN tree t ON b.parent_batch_id=t.id
    ) SELECT * FROM import_batch WHERE batch_id IN (SELECT id FROM tree) ORDER BY batch_id''', (root_id,))]
    ids = [b['batch_id'] for b in batches]
    placeholders = ','.join('?' for _ in ids)
    rows = {'import_batch': batches}
    for table, key in [('question_import_draft', 'draft_id'), ('draft_review_event', 'event_id'), ('import_report_item', 'item_id')]:
        rows[table] = [dict(r) for r in conn.execute(
            f'SELECT * FROM {table} WHERE batch_id IN ({placeholders}) ORDER BY {key}', ids)]
    rows['question_import_draft_asset'] = [dict(r) for r in conn.execute(
        f'''SELECT a.* FROM question_import_draft_asset a JOIN question_import_draft d ON d.draft_id=a.draft_id
        WHERE d.batch_id IN ({placeholders}) ORDER BY a.draft_asset_id''', ids)]
    statuses = {}
    for row in rows['question_import_draft']:
        status = row['review_status']
        statuses[status] = statuses.get(status, 0) + 1
    # A task with formal commits needs a separate source-relation review.
    if statuses.get('committed') or any(r['question_id'] for r in rows['import_report_item']):
        raise ValueError('任务已有正式入库记录，不能按草稿任务重置')
    linked = conn.execute(f'''SELECT COUNT(*) FROM import_batch
        WHERE task_id=? AND batch_id NOT IN ({placeholders})''', [root_id, *ids]).fetchone()[0]
    if linked:
        raise ValueError('任务有不在子树内的关联批次，需先核对范围')
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode('utf-8')).hexdigest()
    return {'root_batch_id': root_id, 'title': root['subset_label'], 'batch_ids': ids,
            'counts': {table: len(values) for table, values in rows.items()},
            'review_statuses': statuses, 'fingerprint': fingerprint}


def task_reset_snapshot(db_path, root_id):
    """Read the exact task subtree and fingerprint all records affected by reset."""
    with readonly_database_connection(db_path) as conn:
        return _task_reset_snapshot(conn, root_id)


def delete_uncommitted_task(db_path, root_id, *, expected_fingerprint):
    """Delete a backed-up, reviewed task subtree using FK cascades, atomically.

    The caller must retain the SQLite backup and inventory before calling.
    This never deletes formal questions or any files.
    """
    with existing_database_connection(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        snapshot = _task_reset_snapshot(conn, root_id)
        if snapshot['fingerprint'] != expected_fingerprint:
            raise ValueError('任务内容已变化，请重新生成清理清单')
        conn.execute('DELETE FROM import_batch WHERE batch_id=?', (root_id,))
        return snapshot


def _paper_scope(conn, paper_ids):
    """Snapshot only explicitly selected paper subtrees, including full rows."""
    if not paper_ids or len(set(paper_ids)) != len(paper_ids):
        raise ValueError('试卷批次范围为空或重复')
    placeholders = ','.join('?' for _ in paper_ids)
    papers = conn.execute(f'SELECT * FROM import_batch WHERE batch_id IN ({placeholders})', paper_ids).fetchall()
    if len(papers) != len(paper_ids) or any(p['hierarchy_level'] != 1 for p in papers):
        raise ValueError('只能选择明确的试卷批次')
    batches = [dict(r) for r in conn.execute(f'''WITH RECURSIVE tree(id) AS (
        SELECT batch_id FROM import_batch WHERE batch_id IN ({placeholders})
        UNION SELECT b.batch_id FROM import_batch b JOIN tree t ON b.parent_batch_id=t.id
    ) SELECT * FROM import_batch WHERE batch_id IN (SELECT id FROM tree) ORDER BY hierarchy_level,batch_id''', paper_ids)]
    ids = [b['batch_id'] for b in batches]
    marks = ','.join('?' for _ in ids)
    rows = {'import_batch': batches}
    for table, key in [('question_import_draft', 'draft_id'), ('draft_review_event', 'event_id'), ('import_report_item', 'item_id')]:
        rows[table] = [dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE batch_id IN ({marks}) ORDER BY {key}', ids)]
    rows['question_import_draft_asset'] = [dict(r) for r in conn.execute(f'''SELECT a.* FROM question_import_draft_asset a
        JOIN question_import_draft d ON d.draft_id=a.draft_id WHERE d.batch_id IN ({marks}) ORDER BY a.draft_asset_id''', ids)]
    if any(d['review_status'] in {'committed','approved'} for d in rows['question_import_draft']) or any(r['question_id'] for r in rows['import_report_item']):
        raise ValueError('选中试卷已有入库或批准记录，不能覆盖')
    fingerprint = hashlib.sha256(json.dumps(rows, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    return rows, fingerprint


def paper_scope_snapshot(db_path, paper_ids):
    with readonly_database_connection(db_path) as conn:
        rows, fingerprint = _paper_scope(conn, paper_ids)
        return {'fingerprint': fingerprint, 'counts': {k:len(v) for k,v in rows.items()}}


def clear_uncommitted_papers(db_path, paper_ids, *, expected_fingerprint):
    """Remove a backed-up paper scope; used in the isolated preparation DB."""
    with existing_database_connection(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        _, fingerprint = _paper_scope(conn, paper_ids)
        if fingerprint != expected_fingerprint:
            raise ValueError('试卷数据已变化')
        for paper_id in paper_ids:
            conn.execute('DELETE FROM import_batch WHERE batch_id=?', (paper_id,))


def replace_uncommitted_papers(db_path, prepared_db_path, paper_ids, *, expected_fingerprint):
    """Atomically install reviewed paper drafts from a prepared SQLite copy.

    Does not copy formal questions or any other task. Backups belong to caller.
    """
    with readonly_database_connection(prepared_db_path) as prepared:
        replacement, _ = _paper_scope(prepared, paper_ids)
    with existing_database_connection(db_path) as conn:
        conn.execute('BEGIN IMMEDIATE')
        old, fingerprint = _paper_scope(conn, paper_ids)
        if fingerprint != expected_fingerprint:
            raise ValueError('正式草稿已变化，不能覆盖，请重新核对')
        for paper_id in paper_ids:
            conn.execute('DELETE FROM import_batch WHERE batch_id=?', (paper_id,))
        for table in ('import_batch','question_import_draft','question_import_draft_asset','draft_review_event','import_report_item'):
            for row in replacement[table]:
                columns = list(row)
                conn.execute(f'INSERT INTO {table} ({",".join(columns)}) VALUES ({",".join("?" for _ in columns)})',
                             [row[k] for k in columns])
        return {'removed': {k:len(v) for k,v in old.items()}, 'installed': {k:len(v) for k,v in replacement.items()}}
