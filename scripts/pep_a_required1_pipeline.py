"""Editable textbook transcription, preview and additive draft-only delivery."""
from collections import Counter
from datetime import datetime
import argparse,hashlib,json,runpy,sqlite3,subprocess,sys,re
from pathlib import Path
import fitz
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parent))
import qj_book_pipeline as common
from services.import_service import normalize_draft_question,validate_draft_question,insert_draft_question,stable_id
from services.export_service import question_to_legacy_tex
ROOT=common.ROOT;LIVE=common.LIVE;WORK=ROOT/'data/imports/pep_a_required1'
PREFIX='pep-a-bx1-'
common.WORK=WORK
def read(n):return json.loads((WORK/n).read_text(encoding='utf8'))
def save(n,v):(WORK/n).write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
def signature(p):return hashlib.sha256(json.dumps([p['stem_tex'],p['choices'],p['question_type_id']],ensure_ascii=False).encode()).hexdigest()

def append_preserving_current(db,additions):
    """Append under one write lock, preserving every row present when it starts."""
    allowed={'import_batch','question_import_draft','question_import_draft_asset','draft_review_event'}
    assert set(additions)<=allowed
    db.row_factory=sqlite3.Row;db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
    tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    before={t:common.fingerprint(db,t) for t in tables}
    formal_before=db.execute('SELECT COUNT(*) FROM question').fetchone()[0]
    inserted={}
    try:
        for t,rows in additions.items():
            pk=next(r[1] for r in db.execute('PRAGMA table_info("'+t+'")') if r[5]);inserted[t]=(pk,set())
            for row in rows:
                assert not db.execute('SELECT 1 FROM "'+t+'" WHERE "'+pk+'"=?',(row[pk],)).fetchone(),('new row key already exists',t,row[pk])
                if t=='question_import_draft':
                    assert row['source_item_id'].startswith(PREFIX) and row['review_status']=='needs_review'
                    assert not db.execute('SELECT 1 FROM question_import_draft WHERE source_item_id=?',(row['source_item_id'],)).fetchone(),('source already imported',row['source_item_id'])
                db.execute('INSERT INTO "'+t+'" ('+','.join('"'+k+'"' for k in row)+') VALUES ('+','.join('?' for k in row)+')',list(row.values()))
                inserted[t][1].add(row[pk])
        for t,digest in before.items():
            if t not in inserted or not inserted[t][1]:assert common.fingerprint(db,t)==digest,t
            else:
                pk,keys=inserted[t]
                old=sorted(json.dumps(list(r),ensure_ascii=False,default=lambda x:x.hex() if isinstance(x,bytes) else str(x)) for r in db.execute('SELECT * FROM "'+t+'"') if r[pk] not in keys)
                assert hashlib.sha256('\n'.join(old).encode()).hexdigest()==digest,t
        assert db.execute('SELECT COUNT(*) FROM question').fetchone()[0]==formal_before
        assert not db.execute('PRAGMA foreign_key_check').fetchall();assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok'
        db.commit()
    except BaseException:
        db.rollback();raise
    return dict(all_preexisting_rows_preserved=True,formal_count_before=formal_before,formal_count_after=formal_before,formal_writes=0)

def build():
    inv=read('source_inventory.json');assert common.sha(inv['source'])==inv['source_sha256']
    doc=fitz.open(inv['source']);items=[];checks=[];original={}
    cache=read('compile_cache.json') if (WORK/'compile_cache.json').exists() else {}
    for path in sorted(WORK.glob('section_*.py')):
        module=runpy.run_path(str(path))
        if not module.get('COMPLETE'):continue
        section=next(s for s in inv['sections'] if s['key']==path.stem)
        paper_tex=[];start=len(items)
        local_totals=Counter((min(r['pages']),r['column_name']) for r in module['ROWS'] if not r.get('exercise_number'))
        local_seen=Counter()
        for order,row in enumerate(module['ROWS'],1):
            key=PREFIX+path.stem+f'-q{order:03}'
            original[key]=row
            correction=row.get('correction')
            if correction:
                fields={k:v for k,v in correction.items() if k!='reason'}
                assert fields and set(fields)<={'answer_tex','solution_tex'},key
                row=dict(row,**fields)
            assert set(row['topic'].split('，'))<=common.NSUBJECTS
            assert all(section['page_start']<=p<=section['page_end'] for p in row['pages'])
            folder=WORK/path.stem/f'q{order:03}';folder.mkdir(parents=True,exist_ok=True)
            assets=[]
            for i,(page,bbox,alias,caption) in enumerate(row.get('figures',[]),1):
                target=folder/(alias+'.png')
                doc[page-1].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(bbox),alpha=False).save(target)
                assets.append(dict(role='solution' if alias.startswith('solution') else 'problem',source_path=target.relative_to(ROOT).as_posix(),caption=caption,sort_order=i,
                    extra=dict(alias=alias,page_number=page,bbox=bbox,input_sha256=inv['source_sha256'],file_sha256=common.sha(target),source_visual_review='original_page_compared')))
            stem,answer,solution=[common.format_tex(row.get(k,'')) for k in ['stem_tex','answer_tex','solution_tex']]
            choices=[common.format_tex(c) for c in row.get('choices',[])]
            refs=re.findall(r'\\questionasset\{([^{}]+)\}','\n'.join([stem,*choices,answer,solution]))
            assert sorted(refs)==sorted(a['extra']['alias'] for a in assets),(key,'assets')
            number=row.get('exercise_number','');column=row['column_name'];group=row.get('group_name','')
            local_key=(min(row['pages']),column)
            shown_column=column
            if not number and local_totals[local_key]>1:
                local_seen[local_key]+=1
                shown_column+=chr(0x2460+local_seen[local_key]-1)
            book_pages=[p-inv['pdf_to_book_offset'] for p in row['pages']]
            leaf_title=row.get('section_title') or section['title']
            position='·'.join(str(x) for x in [leaf_title,'P'+str(min(book_pages)),shown_column,group,number] if x)
            extra=dict(source_kind='教材',paper_series='BK',detected_year='',detected_source=inv['title'],detected_topic=row['topic'],
                detected_question_number=position,question_number=str(order),
                book_title=inv['title'],book_publisher=inv['publisher'],book_edition=inv['edition'],book_grade=inv['grade'],book_volume=inv['volume'],
                book_section_title=leaf_title,book_section_path=[dict(title=section['chapter_name'],sort_order=section['chapter_order']),dict(title=section['title'],sort_order=section['book_page_start'])]+([dict(title=leaf_title,sort_order=min(book_pages))] if leaf_title!=section['title'] else []),
                book_column_name=column,book_group_name=group,book_exercise_number=number,book_page_number=min(book_pages),book_page_end=max(book_pages),
                book_display_order=min(row['pages'])*1000+order,book_source_note=dict(group_name=group,source_pages=row['pages'],section_path=[section['chapter_name'],section['title']]),
                source_pages=row['pages'],page_start=min(row['pages']),page_end=max(row['pages']),book_pages=book_pages,
                input_sha256=inv['source_sha256'],source_path=inv['source'],source_page_images=[(WORK/'pages'/f'p{p:03}.png').relative_to(ROOT).as_posix() for p in row['pages']],
                transcription_method='codex_visual_textbook_v1',visual_source_compared=True,source_warning='',
                answer_origin='source_book' if answer else 'not_provided',solution_origin='source_book' if solution else 'not_provided',
                source_context=row.get('context_reference',''),page_local_index=order,section_key=path.stem)
            if correction:
                extra['source_correction']=dict(status='resolved',reason=correction['reason'],revision_kind='answer_analysis_only',
                    original_preserved_in='original_transcription_rows.json',source_subject_unchanged=True)
                if 'solution_tex' in correction:extra['solution_origin']='verified_editorial_revision'
                if 'answer_tex' in correction:extra['answer_origin']='verified_editorial_revision'
            if row.get('optional'):
                extra['is_optional']=True
                extra['book_source_note']['optional']=True
            item=dict(source_item_id=key,source_label=f'{inv["title"]}·{inv["volume"]}｜{position}',proposed_action='insert',review_status='needs_review',
                question_type_id=row['question_type_id'],stem_tex=stem,choices=choices,answer_tex=answer,solution_tex=solution,tags=[],note='',official_flag=False,assets=assets,extra=extra)
            v=validate_draft_question(normalize_draft_question(item));assert not v['errors'],(key,v)
            item['validation']=dict(draft_validation=v,visual_source_compared=True)
            items.append(item)
            tex=question_to_legacy_tex(dict(item,question_id=key,choices_json=json.dumps(choices,ensure_ascii=False),tags_json='[]',
                detected_year=inv['volume'],paper_series='BK',detected_source=inv['title'],detected_question_number=position,detected_topic=row['topic']))
            for i in range(20):
                tex=tex.replace(chr(0x2460+i),r'\circled{'+str(i+1)+'}')
            (folder/'question.tex').write_text(tex,encoding='utf8')
            for a in assets:
                graphic_options=r'width=0.48\linewidth,keepaspectratio'
                if fitz.Pixmap(ROOT/a['source_path']).height > fitz.Pixmap(ROOT/a['source_path']).width*3:
                    graphic_options+=r',height=0.85\textheight'
                tex=tex.replace('\\questionasset{'+a['extra']['alias']+'}',r'\begin{center}\includegraphics['+graphic_options+']{'+(ROOT/a['source_path']).as_posix()+r'}\end{center}')
            paper_tex.append(tex)
        target=WORK/('preview_'+path.stem+'.tex');target.write_text(common.PREAMBLE+'\n'.join(paper_tex)+r'\end{document}',encoding='utf8')
        digest=hashlib.sha256(target.read_bytes()+json.dumps([a['extra']['file_sha256'] for p in items[start:] for a in p['assets']]).encode()).hexdigest()
        code=0
        if cache.get(path.name)!=digest or not target.with_suffix('.pdf').exists():
            code=subprocess.run(['xelatex','-interaction=nonstopmode','-halt-on-error',target.name],cwd=WORK,capture_output=True).returncode
        log=target.with_suffix('.log').read_text(encoding='utf8',errors='replace')
        check=dict(module=path.name,questions=len(module['ROWS']),compile_passed=code==0,overfull=log.count('Overfull'),missing=log.count('Missing character:'))
        checks.append(check);print(json.dumps(check),flush=True)
        if not code and not check['overfull'] and not check['missing']:cache[path.name]=digest
        elif code:print(log[-1800:])
    save('visual_payloads.json',items);save('original_transcription_rows.json',original);save('compile_cache.json',cache)
    save('compile_checks.json',dict(expected_sections=len(inv['sections']),completed_source_modules=len(checks),questions=len(items),images=sum(len(p['assets']) for p in items),checks=checks,complete=len(checks)==len(inv['sections'])))
    common.preview(items)
    preview_path=WORK/'browser_preview.html'
    preview_path.write_text(preview_path.read_text(encoding='utf8').replace('&lt;code&gt;','<code>').replace('&lt;/code&gt;','</code>'),encoding='utf8')
    return all(c['compile_passed'] and not c['overfull'] and not c['missing'] for c in checks)

def stage():
    checks=read('compile_checks.json');assert checks['checks'] and all(c['compile_passed'] and not c['overfull'] and not c['missing'] for c in checks['checks'])
    assert read('preview_browser_checks.json')['status']=='ok'
    assert read('preview_browser_checks.json')['payload_sha256']==common.sha(WORK/'visual_payloads.json')
    inv=read('source_inventory.json');payload=read('visual_payloads.json');duplicates=read('duplicate_checks.json')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S');isolated=WORK/f'staged_{stamp}.sqlite3';frozen=WORK/f'stage_baseline_{stamp}.sqlite3'
    common.snapshot(LIVE,frozen);common.snapshot(frozen,isolated)
    with common.connect(frozen) as db:
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before={t:common.fingerprint(db,t) for t in tables}
        existing={r['source_item_id']:dict(r) for r in db.execute('SELECT * FROM question_import_draft WHERE source_item_id LIKE ?',(PREFIX+'%',))}
    root=stable_id('IB','codex_task',inv['task_key']+'-'+inv['source_sha256'][:16]);children={}
    with sqlite3.connect(isolated) as db:
        db.execute('PRAGMA foreign_keys=ON')
        for s in [None,*inv['sections']]:
            bid=root if s is None else stable_id('IB',root,s['key'])
            summary=dict(source_kind='教材',stage='pending_transcription') if s is None else dict(s,source_kind='教材')
            db.execute('''INSERT INTO import_batch(batch_id,import_type,source_path,mode,task_id,parent_batch_id,hierarchy_level,subset_key,subset_label,summary)
                VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(batch_id) DO NOTHING''',
                (bid,'codex_task' if s is None else 'codex_subset',inv['source'],'task' if s is None else 'subset',root,None if s is None else root,
                 0 if s is None else 1,inv['task_key'] if s is None else s['key'],inv['task_title'] if s is None else s['title'],json.dumps(summary,ensure_ascii=False)))
            if s:children[s['key']]=bid
    added=[]
    for item in payload:
        key=item['source_item_id']
        if key in existing:
            row=existing[key]
            for f in ['stem_tex','answer_tex','solution_tex','question_type_id']:assert row[f]==item[f],(key,f,'installed content changed')
            assert json.loads(row['choices_json'])==item['choices'];continue
        dup=duplicates[key];assert dup['signature']==signature(item)
        item['validation'].update(similarity_candidates=dup['similarity_candidates'],source_position_conflicts=dup['position_conflicts'],latex_compile='passed')
        did,v=insert_draft_question(str(isolated),children[item['extra']['section_key']],normalize_draft_question(item),item['extra']['page_local_index'])
        assert not v['errors'],v;added.append(did)
    assert added,'No new drafts'
    allowed=['import_batch','question_import_draft','question_import_draft_asset','draft_review_event'];additions={}
    with common.connect(frozen) as a,common.connect(isolated) as b:
        for t in tables:
            if t not in allowed:assert common.fingerprint(b,t)==before[t],t
        for t in allowed:
            pk=next(r[1] for r in a.execute('PRAGMA table_info("'+t+'")') if r[5]);old={r[pk]:list(r) for r in a.execute('SELECT * FROM "'+t+'"')};additions[t]=[]
            for r in b.execute('SELECT * FROM "'+t+'"'):
                if r[pk] in old:assert list(r)==old[r[pk]],(t,r[pk])
                else:additions[t].append(dict(r))
        assert not b.execute('PRAGMA foreign_key_check').fetchall()
    save('install_plan.json',dict(root_batch_id=root,isolated=str(isolated.relative_to(ROOT)),stage_baseline=str(frozen.relative_to(ROOT)),live_fingerprints=before,
        payload_sha256=common.sha(WORK/'visual_payloads.json'),new_drafts=added,additions=additions))
    print(json.dumps(dict(stage='isolated_checked',new_drafts=len(added),root_batch_id=root)))

def apply():
    plan=read('install_plan.json');assert read('preview_browser_checks.json')['payload_sha256']==plan['payload_sha256']==common.sha(WORK/'visual_payloads.json')
    backup=ROOT/'data/backups'/('before_'+WORK.name+'_'+datetime.now().strftime('%Y%m%d_%H%M%S')+'.sqlite3');common.snapshot(LIVE,backup)
    with sqlite3.connect(LIVE) as db:
        preservation=append_preserving_current(db,plan['additions'])
    report=dict(status='ready_for_human_review' if read('compile_checks.json')['complete'] else 'partial_ready_for_human_review',root_batch_id=plan['root_batch_id'],
        new_drafts=len(plan['new_drafts']),backup=str(backup.relative_to(ROOT)),transaction_preservation=preservation,**read('compile_checks.json'))
    save('delivery.json',report)
    history=read('delivery_history.json') if (WORK/'delivery_history.json').exists() else []
    history.append(dict(backup=report['backup'],new_drafts=report['new_drafts'],payload_sha256=plan['payload_sha256'],transaction_preservation=preservation))
    save('delivery_history.json',history);audit()

def audit():
    expected={p['source_item_id']:p for p in read('visual_payloads.json')}
    with common.connect(WORK/'baseline_before_batch.sqlite3') as before,common.connect(LIVE) as after:
        tables=[r[0] for r in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        differences={}
        for t in tables:
            if t not in {'import_batch','question_import_draft','question_import_draft_asset','draft_review_event'}:
                if common.fingerprint(before,t)!=common.fingerprint(after,t):differences[t]='changed_since_task_started'
                continue
            primary=[r[1] for r in sorted(before.execute('PRAGMA table_info("'+t+'")'),key=lambda r:r[5]) if r[5]]
            for row in before.execute('SELECT * FROM "'+t+'"'):
                actual=after.execute('SELECT * FROM "'+t+'" WHERE '+' AND '.join('"'+pk+'"=?' for pk in primary),[row[pk] for pk in primary]).fetchone()
                if not actual or tuple(actual)!=tuple(row):differences[t]=int(differences.get(t,0))+1
        rows=list(after.execute('SELECT * FROM question_import_draft WHERE source_item_id LIKE ?',(PREFIX+'%',)));assert {r['source_item_id'] for r in rows}==set(expected)
        statuses=Counter()
        for r in rows:
            p=expected[r['source_item_id']];assert json.loads(r['tags_json'])==[]
            statuses[r['review_status']]+=1
            for f in ['stem_tex','answer_tex','solution_tex','question_type_id']:assert r[f]==p[f]
            actual_extra=json.loads(r['extra_json'])
            for k,v in p['extra'].items():assert actual_extra.get(k)==v,(r['source_item_id'],k)
            assert json.loads(r['choices_json'])==p['choices']
        report=dict(status='ok',installed_questions=len(rows),installed_sections=len({p['extra']['section_key'] for p in expected.values()}),
            complete=read('compile_checks.json')['complete'],historical_drafts_preserved=before.execute('SELECT COUNT(*) FROM question_import_draft').fetchone()[0],
            formal_questions=after.execute('SELECT COUNT(*) FROM question').fetchone()[0],all_baseline_rows_unchanged=not differences,
            changes_since_task_started=differences,agent_formal_writes=0,last_apply_preserved_preexisting_rows=read('delivery.json').get('transaction_preservation',{}).get('all_preexisting_rows_preserved',True),
            review_status=dict(statuses),all_tags_empty=True,payload_sha256=common.sha(WORK/'visual_payloads.json'))
    save('delivery_cumulative.json',report);print(json.dumps(report))

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8');p=argparse.ArgumentParser();p.add_argument('--stage',action='store_true');p.add_argument('--apply',action='store_true');p.add_argument('--audit',action='store_true');a=p.parse_args()
    if a.stage:stage()
    elif a.apply:apply()
    elif a.audit:audit()
    else:raise SystemExit(0 if build() else 1)
