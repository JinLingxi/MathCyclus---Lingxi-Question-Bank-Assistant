"""Verify the recorded migration and that every formal question stayed intact."""
import hashlib,json,sqlite3,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.question_text_format_service import CHOICE_BLANK_STOP,normalize_choice_blank_stop
report=json.loads((ROOT/'reports/import_choice_punctuation_normalization.json').read_text(encoding='utf8'))
def formal_digest(c):
 rows=c.execute('select * from question order by question_id').fetchall()
 return hashlib.sha256(json.dumps([list(r) for r in rows],ensure_ascii=False,default=str).encode()).hexdigest()
with sqlite3.connect(ROOT/'data/mathcyclus.sqlite3') as c,sqlite3.connect(ROOT/report['database_backup']['path']) as old:
 assert formal_digest(c)==formal_digest(old)
 for change in report['drafts']:
  assert normalize_choice_blank_stop(change['before'])==change['after']
  assert c.execute('select stem_tex from question_import_draft where draft_id=?',(change['draft_id'],)).fetchone()[0]==change['after']
 assert not c.execute('pragma foreign_key_check').fetchall()
print(json.dumps({'verified_drafts':len(report['drafts']),'formal_questions_unchanged':True}))
