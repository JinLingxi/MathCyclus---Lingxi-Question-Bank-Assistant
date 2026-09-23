from __future__ import annotations
import argparse,json,re,shutil,sqlite3,hashlib
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
DEFAULT_DB=ROOT/'data/mathcyclus.sqlite3'
DEFAULT_PLAN=ROOT/'reports/g_paper_review_execution_dry_run_20260908_225905.json'
HOLD={'Pe06a51d244c2dd','P7248027c077ac9','Pdb0c9100de','Pbf81a39c2f','P6cecc2238c'}
SPECIAL_ONLY={'P9a2a4bed0b'}

def sid(*values): return 'QR'+hashlib.sha1('|'.join(map(str,values)).encode()).hexdigest()[:20]
def rel(p): return str(p.resolve().relative_to(ROOT.resolve())).replace('\\','/')
def rewrite(text,y,s,source,num,topic):
    pat=re.compile(r'\\begin\{problem\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}\{[^{}]*\}')
    head=chr(92)+'begin{problem}{%s}{%s}{%s}{%s}{%s}'%(y,s,source,num,topic)
    return pat.sub(lambda _:head,(text or '').replace('\r\n','\n').replace('\r','\n'),count=1)
def backup_db(db,dest):
    a=sqlite3.connect(db); b=sqlite3.connect(dest); a.backup(b); b.close(); a.close()
def add_revision(c,qid,before,after,batch):
    c.execute('insert into question_revision(revision_id,question_id,change_source,changed_fields_json,before_json,after_json,operator,note) values(?,?,?,?,?,?,?,?)',(sid(qid,after.get('legacy_file_path',''),batch),qid,'g_paper_catalog_review',json.dumps(list(after),ensure_ascii=False),json.dumps(before,ensure_ascii=False),json.dumps(after,ensure_ascii=False),'maintenance','G paper catalog manual review'))
def sync(c,qid,paper,num,batch,backup_root,log):
    q=c.execute('select * from question where question_id=?',(qid,)).fetchone(); lm=c.execute('select * from legacy_question_map where question_id=?',(qid,)).fetchone()
    old=ROOT/lm['legacy_file_path']; topic=(lm['detected_topic'] or lm['detected_chapter'] or old.stem.split('-')[-1]).strip(); source=paper['source_name'] or paper['paper_name']; new=old.parent.parent/str(paper['year'])/('%s-%s-%s-%s-%s.tex'%(paper['year'],paper['paper_series'],source,num,topic))
    if new.resolve()!=old.resolve() and new.exists(): raise RuntimeError('target exists: '+str(new))
    raw=rewrite(q['raw_source_tex'],paper['year'],paper['paper_series'],source,num,topic) if q['raw_source_tex'] else ''
    can=rewrite(q['canonical_tex'],paper['year'],paper['paper_series'],source,num,topic) if q['canonical_tex'] else ''
    text=old.read_text(encoding='utf-8') if old.exists() else raw or can; text=rewrite(text,paper['year'],paper['paper_series'],source,num,topic); new_rel=rel(new)
    before={'legacy_file_path':lm['legacy_file_path'],'raw_source_tex':q['raw_source_tex'],'canonical_tex':q['canonical_tex']}
    c.execute('update question set raw_source_tex=?,canonical_tex=?,legacy_file_path=?,updated_at=current_timestamp where question_id=?',(raw,can,new_rel,qid))
    c.execute('update legacy_question_map set legacy_file_path=?,detected_year=?,detected_source=?,content_hash=?,updated_at=current_timestamp where question_id=?',(new_rel,paper['year'],source,hashlib.sha1(text.encode()).hexdigest()[:16],qid))
    if new.resolve()!=old.resolve() and old.exists(): new.parent.mkdir(parents=True,exist_ok=True); old.rename(new)
    if new.exists(): new.write_text(text,encoding='utf-8')
    add_revision(c,qid,before,{'legacy_file_path':new_rel,'raw_source_tex':raw,'canonical_tex':can},batch); log['moves'].append({'question_id':qid,'from':rel(old),'to':new_rel})
def main():
    ap=argparse.ArgumentParser(); ap.add_argument('--db',default=str(DEFAULT_DB)); ap.add_argument('--plan',default=str(DEFAULT_PLAN)); ap.add_argument('--apply',action='store_true'); a=ap.parse_args()
    db=Path(a.db); plan=json.loads(Path(a.plan).read_text(encoding='utf-8')); stamp=datetime.now().strftime('%Y%m%d_%H%M%S'); backup_root=ROOT/'.backups'/'g_paper_catalog_review'/stamp; backup_root.mkdir(parents=True,exist_ok=True)
    if not a.apply:
        print(json.dumps(plan['summary'],ensure_ascii=False)); return
    backup_db_path=backup_root/'mathcyclus_before.sqlite3'; backup_db(db,backup_db_path)
    c=sqlite3.connect(db); c.row_factory=sqlite3.Row; c.execute('pragma foreign_keys=on'); log={'stamp':stamp,'database_backup':rel(backup_db_path),'held_conflicts':sorted(HOLD),'normalized':[],'deleted':[],'special':[],'moves':[]}
    paths=set()
    for item in plan['deletions']:
        for q in item['questions']:
            x=c.execute('select legacy_file_path from legacy_question_map where question_id=?',(q['question_id'],)).fetchone();
            if x: paths.add(x[0])
    for item in plan['normalizations']:
        if item['paper_id'] in HOLD or item['paper_id'] in SPECIAL_ONLY: continue
        for q in item['questions']:
            x=c.execute('select legacy_file_path from legacy_question_map where question_id=?',(q['question_id'],)).fetchone();
            if x: paths.add(x[0])
    for qid in ('Q000201','Q000568'):
        x=c.execute('select legacy_file_path from legacy_question_map where question_id=?',(qid,)).fetchone();
        if x: paths.add(x[0])
    for p in paths:
        src=ROOT/p
        if src.exists(): dst=backup_root/'tex_before'/p; dst.parent.mkdir(parents=True,exist_ok=True); shutil.copy2(src,dst)
    try:
        c.execute('begin')
        for item in plan['deletions']:
            for q in item['questions']:
                qid=q['question_id']; x=c.execute('select legacy_file_path from legacy_question_map where question_id=?',(qid,)).fetchone(); old=ROOT/x[0]; dst=backup_root/'quarantine'/x[0]; dst.parent.mkdir(parents=True,exist_ok=True); shutil.move(str(old),str(dst)); c.execute('delete from question where question_id=?',(qid,)); log['deleted'].append({'question_id':qid,'paper_id':item['paper_id'],'quarantine':rel(dst)})
        for item in plan['normalizations']:
            if item['paper_id'] in HOLD or item['paper_id'] in SPECIAL_ONLY: continue
            t=item['to']; target=c.execute('select * from paper where year=? and paper_series=? and track=? and paper_name=?',(t['year'],t['series'],t['track'],t['name'])).fetchone()
            if target is None:
                pid='P'+hashlib.sha1('|'.join(map(str,(t['year'],t['series'],t['track'],t['name']))).encode()).hexdigest()[:14]; c.execute('insert into paper(paper_id,year,paper_series,track,paper_name,source_name,description) values(?,?,?,?,?,?,?)',(pid,t['year'],t['series'],t['track'],t['name'],t['source_name'],'manual review normalization')); target=c.execute('select * from paper where paper_id=?',(pid,)).fetchone()
            for q in item['questions']:
                link=c.execute('select * from paper_question where paper_id=? and question_id=?',(item['paper_id'],q['question_id'])).fetchone()
                if not link: continue
                duplicate=c.execute('select paper_question_id from paper_question where paper_id=? and question_id=? and question_number=? and sub_number=?',(target['paper_id'],q['question_id'],link['question_number'],link['sub_number'])).fetchone()
                if duplicate: c.execute('delete from paper_question where paper_question_id=?',(link['paper_question_id'],))
                else: c.execute('update paper_question set paper_id=?,updated_at=current_timestamp where paper_question_id=?',(target['paper_id'],link['paper_question_id']))
                sync(c,q['question_id'],target,link['question_number'],stamp,backup_root,log)
            c.execute('delete from paper where paper_id=? and not exists(select 1 from paper_question where paper_id=?)',(item['paper_id'],item['paper_id'])); log['normalized'].append({'from':item['paper_id'],'to':target['paper_id'],'target':t})
        mock_track='\u7efc\u5408'
        mock_name='\u6c5f\u82cf\u7701\u82cf\u5317\u4e03\u5e022026\u5c4a\u9ad8\u4e09\u7b2c\u4e00\u6b21\u8c03\u7814\u6d4b\u8bd5'
        mock=c.execute('select * from paper where year=2026 and paper_series=? and track=? and paper_name=?',('M',mock_track,mock_name)).fetchone()
        if mock is None:
            pid='P'+hashlib.sha1(('2026|M|'+mock_track+'|'+mock_name).encode()).hexdigest()[:14]; c.execute('insert into paper(paper_id,year,paper_series,track,paper_name,source_name,description) values(?,?,?,?,?,?,?)',(pid,2026,'M',mock_track,mock_name,mock_name,'manual relation repair')); mock=c.execute('select * from paper where paper_id=?',(pid,)).fetchone()
        for link in list(c.execute('select * from paper_question where paper_id=?',('P434d0f9a4e',))): c.execute('update paper_question set paper_id=?,updated_at=current_timestamp where paper_question_id=?',(mock['paper_id'],link['paper_question_id']))
        c.execute('delete from paper where paper_id=?',('P434d0f9a4e',)); log['special'].append({'kind':'mock_to_M','paper_id':mock['paper_id']})
        link=c.execute('select p.*,pq.question_number from paper p join paper_question pq on pq.paper_id=p.paper_id where pq.question_id=?',('Q000201',)).fetchone(); c.execute('update paper set paper_series=? where paper_id=?',('XK',link['paper_id'])); paper_row=c.execute('select * from paper where paper_id=?',(link['paper_id'],)).fetchone(); sync(c,'Q000201',paper_row,link['question_number'],stamp,backup_root,log); log['special'].append({'kind':'G_to_XK','question_id':'Q000201'})
        link=c.execute('select p.*,pq.question_number from paper p join paper_question pq on pq.paper_id=p.paper_id where pq.question_id=?',('Q000568',)).fetchone(); c.execute('update paper set year=? where paper_id=?',(2016,link['paper_id'])); paper_row=c.execute('select * from paper where paper_id=?',(link['paper_id'],)).fetchone(); sync(c,'Q000568',paper_row,link['question_number'],stamp,backup_root,log); log['special'].append({'kind':'year_fix','question_id':'Q000568'})
        c.execute('delete from paper where not exists(select 1 from paper_question where paper_question.paper_id=paper.paper_id)')
        if c.execute('pragma integrity_check').fetchone()[0]!='ok' or list(c.execute('pragma foreign_key_check')): raise RuntimeError('integrity failure')
        c.commit(); log['integrity_check']='ok'
    except Exception as exc:
        c.rollback(); log['error']=str(exc); (backup_root/'failed_manifest.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); raise
    finally: c.close()
    log['summary']={'normalized_papers':len(log['normalized']),'deleted_questions':len(log['deleted']),'special_actions':len(log['special']),'held_conflicts':len(HOLD)}; (backup_root/'manifest.json').write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); out=ROOT/'reports'/('g_paper_review_applied_'+stamp+'.json'); out.write_text(json.dumps(log,ensure_ascii=False,indent=2),encoding='utf-8'); print(json.dumps(log['summary'],ensure_ascii=False)); print(out)
if __name__=='__main__': main()
