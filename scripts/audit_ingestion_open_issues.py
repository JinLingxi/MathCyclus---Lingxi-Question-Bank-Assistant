"""Read-only inventory of retained source warnings and historical review items."""
import argparse
import csv
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.database_service import DEFAULT_DATABASE_PATH, readonly_database_connection

NOTE_HINT = re.compile(r"疑点|疑误|待(?:人工)?(?:核对|复核|补源)|缺图|缺少(?:条件|配图)|未见.{0,18}(?:配图|图形)|原(?:题|书|文).{0,20}(?:矛盾|异常|有误)")


def obj(value):
    try:
        value = json.loads(value or '{}')
        return value if isinstance(value, dict) else {}
    except (ValueError, TypeError):
        return {}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-prefix', required=True, type=Path)
    args = parser.parse_args()
    paths = [Path(str(args.output_prefix) + suffix) for suffix in ('.json', '.csv', '.md')]
    for path in paths:
        if path.exists():
            raise FileExistsError(path)
    with readonly_database_connection(DEFAULT_DATABASE_PATH) as conn:
        conn.execute('BEGIN')
        drafts = {r['draft_id']: dict(r) for r in conn.execute(
            'SELECT draft_id,batch_id,source_label,review_status,note,extra_json,target_question_id FROM question_import_draft')}
        batches = {r['batch_id']: dict(r) for r in conn.execute('SELECT batch_id,import_type,subset_label FROM import_batch')}
        questions = {r['question_id']: dict(r) for r in conn.execute('SELECT question_id,note,legacy_file_path FROM question')}
        links = {}
        for row in conn.execute('SELECT source_file,question_id FROM import_report_item WHERE question_id IS NOT NULL'):
            if row['source_file'] in drafts and row['question_id'] in questions:
                links.setdefault(row['source_file'], set()).add(row['question_id'])
    for draft in drafts.values():
        target = draft.get('target_question_id')
        if target in questions:
            links.setdefault(draft['draft_id'], set()).add(target)
    records = []
    for draft in drafts.values():
        extra = obj(draft['extra_json'])
        warning = str(extra.get('source_warning') or '').strip()
        recovery = batches.get(draft['batch_id'], {}).get('import_type') == 'answer_recovery'
        if recovery:
            if draft['review_status'] in {'committed', 'rejected'}:
                continue
            category, warning = '旧答案解析归属待确认', warning or draft['note']
        elif warning:
            category = '保留的来源提醒'
        elif NOTE_HINT.search(draft['note'] or ''):
            category, warning = '备注疑点线索（需人工确认）', draft['note']
        else:
            continue
        old = extra.get('old_paper_metadata') or {}
        source = draft['source_label']
        if recovery and old:
            source = f"{old.get('year', '')} {old.get('source', '')} 第{old.get('number', '')}题（旧答案保全）"
        records.append({'category': category, 'draft_id': draft['draft_id'],
            'source': source, 'year': str(extra.get('detected_year') or old.get('year') or ''),
            'review_status': draft['review_status'], 'question_ids': sorted(links.get(draft['draft_id'], [])),
            'source_pages': extra.get('source_pages', []), 'warning': warning,
            'source_path': str(extra.get('source_path') or ''), 'evidence_report': ''})
    warned_ids = {qid for r in records for qid in r['question_ids']}
    labels = {qid: draft['source_label'] for draft in drafts.values() for qid in links.get(draft['draft_id'], [])}
    for qid, question in questions.items():
        if qid not in warned_ids and NOTE_HINT.search(question['note'] or ''):
            records.append({'category': '正式题备注线索（需人工确认）', 'draft_id': '',
                'source': labels.get(qid) or question['legacy_file_path'] or qid, 'year': '',
                'review_status': '正式题', 'question_ids': [qid], 'source_pages': [],
                'warning': question['note'], 'source_path': '', 'evidence_report': ''})
    # Saved duplicate reports are historical decisions, not a fresh duplicate
    # classification. Exclude drafts that have since been committed/rejected.
    skip_events = {}
    reports = list((ROOT / 'reports').glob('*nonduplicate*applied*.json'))
    reports += list((ROOT / 'reports').glob('qj_three_tasks_applied_*.json'))
    for path in sorted(reports, key=lambda p: (re.findall(r'20\d{6}', p.name)[-1:], p.name)):
        report = obj(path.read_text(encoding='utf-8'))
        if report.get('mode') != 'apply':
            continue
        for event in report.get('events', []):
            draft = drafts.get(event.get('draft_id'))
            if draft and draft['review_status'] not in {'committed', 'rejected'} and event.get('status') in {'exact_duplicate', 'position_conflict'}:
                skip_events[draft['draft_id']] = {**event, 'evidence_report': path.relative_to(ROOT).as_posix()}
    for did, event in skip_events.items():
        draft = drafts[did]
        records.append({'category': '历史查重跳过且仍待审核', 'draft_id': did, 'source': draft['source_label'],
            'year': str(obj(draft['extra_json']).get('detected_year') or ''), 'review_status': draft['review_status'],
            'question_ids': [qid for qid in event.get('matches', []) if qid in questions], 'source_pages': [],
            'warning': '历史完全重复，未重跑当前查重' if event['status'] == 'exact_duplicate' else '历史来源位置冲突，未重新核对当前题位',
            'source_path': '', 'evidence_report': event['evidence_report']})
    records.sort(key=lambda r: (r['category'], r['year'], r['source'], r['draft_id']))
    summary = {'created_at': datetime.now().isoformat(timespec='seconds'), 'mode': 'read_only',
        'formal_questions': len(questions), 'drafts': len(drafts),
        'draft_states': dict(Counter(d['review_status'] for d in drafts.values())),
        'categories': dict(Counter(r['category'] for r in records)),
        'source_warning_states': dict(Counter(r['review_status'] for r in records if r['category'] == '保留的来源提醒')),
        'historical_skip_reasons': dict(Counter(event['status'] for event in skip_events.values())),
        'limits': '提醒与历史记录清单，不是重新核源或数学正确性结论；类别可能按同一草稿重叠。无自动修复、提交或删除。'}
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    with paths[0].open('x', encoding='utf-8') as output:
        json.dump({'summary': summary, 'records': records}, output, ensure_ascii=False, indent=2)
    with paths[1].open('x', encoding='utf-8-sig', newline='') as output:
        writer = csv.DictWriter(output, fieldnames=list(records[0]) if records else ['category'])
        writer.writeheader()
        for record in records:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, list) else value for key, value in record.items()})
    lines = ['# 历次录入疑点与异常线索复核', '', summary['limits'], '', '## 当前快照', '']
    lines += [f'- {category}：{count} 条。' for category, count in summary['categories'].items()]
    lines += ['', '来源提醒可以存在于已入库题目中；已入库不证明原书疑点已解决。旧答案保全独立列示，不重复计入来源提醒。历史查重跳过项仍需当前查重和来源复核，不能直接当作当前已确认重复。', '', '## 来源提醒与答案保全明细', '', '| 类别 | 题目 | 状态 | 正式题 ID | 草稿 ID | 提醒 |', '| --- | --- | --- | --- | --- | --- |']
    for record in records:
        if record['category'] == '历史查重跳过且仍待审核':
            continue
        values = [record['category'], record['source'], record['review_status'], ', '.join(record['question_ids']), record['draft_id'], record['warning']]
        lines.append('| ' + ' | '.join(str(value).replace('|', '\\|').replace('\n', '<br>') for value in values) + ' |')
    lines += ['', '全部历史查重跳过项及来源页码、路径见同名 CSV/JSON。此报告只记录当前快照，不改人工审核状态或题库数据。']
    with paths[2].open('x', encoding='utf-8') as output:
        output.write('\n'.join(lines) + '\n')
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
