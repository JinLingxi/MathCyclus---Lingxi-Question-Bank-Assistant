"""Remove only the sentence stop immediately after a choice-answer blank."""
import ast
import io
import json
import re
import sqlite3
import sys
import tokenize
from datetime import datetime
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from services.ingestion_review_service import descendants
from services.schema_migration_service import backup_database

PATTERN=re.compile(r'([（(]\s*\\hspace\{1cm\}\s*[）)])\s*[。.]')
def clean(text):
    return PATTERN.sub(r'\1',text)

def main():
    db=ROOT/'data/mathcyclus.sqlite3'
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    report={'migration':'choice_blank_trailing_stop','drafts':[],'source_files':[]}
    with sqlite3.connect(db) as c:
        c.row_factory=sqlite3.Row
        formal=c.execute('select count(*) from question').fetchone()[0]
        nodes=[dict(r) for r in c.execute('select * from import_batch')]
        scope=set().union(*(descendants(nodes,r) for r in
            ['IBeb3cfd0d478907','IB55f5e41f2d59d9','IB22a329c1290743','IB181079d7a74dd2']))
        rows=[r for r in c.execute('select * from question_import_draft')
              if r['batch_id'] in scope and r['review_status']!='committed' and PATTERN.search(r['stem_tex'] or '')]
        if rows:
            report['database_backup']=backup_database(db,'choice_blank_stop_'+stamp)
            for r in rows:
                revised=clean(r['stem_tex'])
                report['drafts'].append({'draft_id':r['draft_id'],'before':r['stem_tex'],'after':revised})
                c.execute('update question_import_draft set stem_tex=? where draft_id=?',(revised,r['draft_id']))
            c.commit()
        assert formal==c.execute('select count(*) from question').fetchone()[0]
        assert not c.execute('pragma foreign_key_check').fetchall()
    backup=ROOT/'data/backups'/('choice_blank_sources_'+stamp)
    for folder in ROOT.glob('data/imports/codex_*_restart'):
        for p in folder.glob('paper_*.py'):
            source=p.read_text(encoding='utf-8-sig');tokens=[];changed=False
            for token in tokenize.generate_tokens(io.StringIO(source).readline):
                if token.type==tokenize.STRING:
                    try:value=ast.literal_eval(token.string)
                    except (ValueError,SyntaxError):value=None
                    if isinstance(value,str) and PATTERN.search(value):
                        token=token._replace(string=repr(clean(value)));changed=True
                tokens.append(token)
            if changed:
                revised=tokenize.untokenize(tokens);ast.parse(revised)
                target=backup/p.relative_to(ROOT);target.parent.mkdir(parents=True,exist_ok=True)
                target.write_text(source,encoding='utf8');p.write_text(revised,encoding='utf8')
                report['source_files'].append(p.relative_to(ROOT).as_posix())
    report.update(changed_drafts=len(report['drafts']),changed_source_files=len(report['source_files']),formal_questions=formal)
    (ROOT/'reports/import_choice_punctuation_normalization.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({k:report[k] for k in ['changed_drafts','changed_source_files','formal_questions']}))

if __name__=='__main__':main()
