"""Read-only verification of paragraph commands across all entry tasks."""
import json,re,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.ingestion_review_service import descendants
pattern=re.compile(r'\\par(?![A-Za-z])')
with sqlite3.connect(f'file:{ROOT / "data/mathcyclus.sqlite3"}?mode=ro',uri=True) as c:
 c.row_factory=sqlite3.Row
 nodes=[dict(r) for r in c.execute('select * from import_batch')]
 roots=[n['batch_id'] for n in nodes if n['import_type']=='codex_task' and not n['parent_batch_id']]
 drafts=[dict(r) for r in c.execute('select * from question_import_draft')]
 records=[]
 for root in roots:
  ids=descendants(nodes,root)
  rows=[r for r in drafts if r['batch_id'] in ids]
  hits=[]
  for row in rows:
   for field in ['stem_tex','answer_tex','solution_tex','choices_json']:
    values=json.loads(row[field] or '[]') if field=='choices_json' else [row[field] or '']
    for i,value in enumerate(values):
     if isinstance(value,str) and pattern.search(value):hits.append({'draft_id':row['draft_id'],'field':field,'index':i})
  node=next(n for n in nodes if n['batch_id']==root)
  records.append({'root_batch_id':root,'task_name':node.get('subset_label') or node.get('source_path'),'batches_checked':len(ids),'drafts_checked':len(rows),'remaining_par_commands':len(hits),'hits':hits})
 result={'scope':'All root entry tasks and every descendant batch; all review statuses included','fields':['stem_tex','choices_json (decoded options)','answer_tex','solution_tex'],'tasks':records,'total_drafts_checked':sum(r['drafts_checked'] for r in records),'status':'passed' if not any(r['hits'] for r in records) else 'failed'}
 (ROOT/'reports/task_par_break_audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
 print(json.dumps(result,ensure_ascii=False))
 assert result['status']=='passed'
