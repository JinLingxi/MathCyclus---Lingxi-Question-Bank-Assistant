"""Read-only delivery audit: compare installed drafts, stable images, and baseline data."""
import argparse
import hashlib
import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from scripts.stage_visual_year_additions import fingerprint


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--year',type=int,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    a=p.parse_args()
    work=ROOT/f'data/imports/codex_{a.year}_restart'
    payload=json.loads((work/'visual_payloads.json').read_text(encoding='utf8'))
    compile_checks=json.loads((work/'visual_compile_checks.json').read_text(encoding='utf8'))
    browser=json.loads((work/'preview_browser_checks.json').read_text(encoding='utf8'))
    digest=hashlib.sha256((work/'visual_payloads.json').read_bytes()).hexdigest()
    assert browser['status']=='ok' and browser['payload_sha256']==digest
    assert all(c['compile_passed'] and not c['overfull_boxes'] and not c['missing_characters']
               for c in compile_checks['compile_checks'])
    live=sqlite3.connect((ROOT/'data/mathcyclus.sqlite3').resolve().as_uri()+'?mode=ro',uri=True)
    baseline=sqlite3.connect(a.baseline.resolve().as_uri()+'?mode=ro',uri=True)
    live.row_factory=baseline.row_factory=sqlite3.Row
    changed_allowed={'import_batch','question_import_draft','question_import_draft_asset','draft_review_event'}
    tables=[r[0] for r in baseline.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    unchanged=[]
    for table in tables:
        if table in changed_allowed:continue
        assert fingerprint(live,table)==fingerprint(baseline,table),('unexpected_table_change',table)
        unchanged.append(table)
    old_drafts=0
    for old in baseline.execute('SELECT * FROM question_import_draft'):
        now=live.execute('SELECT * FROM question_import_draft WHERE draft_id=?',(old['draft_id'],)).fetchone()
        assert now is not None and tuple(old)==tuple(now),('old_draft_changed',old['draft_id'])
        old_drafts+=1
    images=0
    for item in payload:
        draft=live.execute('SELECT * FROM question_import_draft WHERE source_item_id=?',(item['source_item_id'],)).fetchall()
        assert len(draft)==1,('installed_count',item['source_item_id'])
        draft=draft[0]
        for key in ('stem_tex','answer_tex','solution_tex','question_type_id'):
            expected=item[key].strip() if isinstance(item[key],str) else item[key]
            assert draft[key]==expected,('content_mismatch',item['source_item_id'],key)
        assert json.loads(draft['choices_json'] or '[]')==item['choices']
        assert draft['review_status']=='needs_review'
        assets=live.execute('SELECT * FROM question_import_draft_asset WHERE draft_id=? ORDER BY sort_order',(draft['draft_id'],)).fetchall()
        assert len(assets)==len(item['assets'])
        for asset,expected in zip(assets,item['assets']):
            path=ROOT/asset['source_path']
            assert path.is_file(),str(path)
            assert hashlib.sha256(path.read_bytes()).hexdigest()==expected['extra']['file_sha256']
            images+=1
    assert not live.execute('PRAGMA foreign_key_check').fetchall()
    papers=Counter(item['extra']['transcription_paper_name'] for item in payload)
    report=dict(year=a.year,status='ready_for_human_review',year_complete=len(papers)==compile_checks['expected_papers'],
                papers=len(papers),expected_papers=compile_checks['expected_papers'],questions=len(payload),images=images,
                paper_counts=dict(papers),source_warning_questions=sum(bool(x['extra']['source_warning']) for x in payload),
                formal_questions=live.execute('SELECT count(*) FROM question').fetchone()[0],
                formal_tables_unchanged=True,baseline_drafts_unchanged=old_drafts,unchanged_tables=unchanged,
                payload_sha256=digest,browser_status=browser['status'],compile_status=compile_checks['status'],
                baseline=str(a.baseline),formal_import_performed=False)
    (work/'delivery_cumulative.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    if report['year_complete']:
        (work/'delivery.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('paper_counts','unchanged_tables')},ensure_ascii=False))
    live.close();baseline.close()


if __name__=='__main__':main()
