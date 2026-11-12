"""Source-backed QJ transcription build and additive, audited draft installation.

Default builds local TeX and preview artifacts only. --stage prepares an
isolated database; --apply requires its matching browser acceptance record.
"""
from __future__ import annotations
import argparse
import base64
from collections import Counter
from datetime import datetime
import hashlib
import html
import json
from pathlib import Path
import re
import runpy
import sqlite3
import subprocess
import sys
import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.import_service import normalize_draft_question, validate_draft_question, create_import_batch, insert_draft_question
from services.export_service import question_to_legacy_tex
from services.ingestion_review_service import create_task_plan
from services.paper_catalog_service import add_standard_paper
from services.question_text_format_service import normalize_choice_blank_stop
from utils.latex_ops import latex_to_markdown
from prepare_visual_restart import PREAMBLE

WORK = ROOT / 'data/imports/qj_2021_2025'
sys.path.insert(0, str(WORK))
LIVE = ROOT / 'data/mathcyclus.sqlite3'
NSUBJECTS = set('集合 复数 不等式 函数 概率 统计 排列组合 解析几何 圆锥曲线 解三角形 三角函数 立体几何 向量 数列 导数 线性规划 数论 命题与逻辑 流程框图'.split())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(name, value):
    (WORK / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')


def read(name):
    return json.loads((WORK / name).read_text(encoding='utf-8'))


def connect(path):
    c = sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro', uri=True)
    c.row_factory = sqlite3.Row
    return c


def snapshot(path, target):
    with connect(path) as s, sqlite3.connect(target) as d:
        s.backup(d)


def fingerprint(conn, table):
    rows = sorted(json.dumps(list(r), ensure_ascii=False, default=lambda x: x.hex() if isinstance(x, bytes) else str(x))
                  for r in conn.execute('SELECT * FROM "'+table+'"'))
    return hashlib.sha256('\n'.join(rows).encode()).hexdigest()


def format_tex(text):
    text = normalize_choice_blank_stop(text.strip())
    parts = re.split(r'(\$\$[\s\S]*?\$\$|\$[^$]*\$)', text)
    for i, p in enumerate(parts):
        if not p.startswith('$'):
            continue
        if re.search(r'\\(?:frac|dfrac|tfrac|sum|prod|int)(?![A-Za-z])', p) and r'\displaystyle' not in p:
            prefix = '$$' if p.startswith('$$') else '$'
            parts[i] = prefix + r'\displaystyle ' + p[len(prefix):]
    text = ''.join(parts)
    assert not re.search(r'\\par(?![A-Za-z])|\\[\[\]()]|[\x00-\x09\x0b\x0c\x0e-\x1f]', text)
    assert text.count('$') % 2 == 0
    # Actual line breaks, with two trailing spaces; never literal \n.
    return '\n'.join(line.rstrip()+'  ' if line.strip() else '' for line in text.split('\n')).rstrip()


def build():
    corrections = {}
    if (WORK/'correction_support.py').exists():
        from correction_support import load_corrections, apply_correction
        corrections = load_corrections()
    inv = read('source_inventory.json')
    source = ROOT / inv['source']
    assert sha(source) == inv['source_sha256']
    doc = fitz.open(source)
    items, checks, source_review = [], [], []
    original_rows = {}
    cache = read('compile_cache.json') if (WORK/'compile_cache.json').exists() else {}
    for module in sorted(WORK.glob('paper_*.py')):
        data = runpy.run_path(str(module))
        if not data.get('COMPLETE',True):
            continue
        entry = next(p for p in inv['papers'] if p['year']==data['YEAR'] and p['paper_name']==data['PAPER'])
        rows = data['ROWS']
        assert [r['number'] for r in rows] == list(range(1, len(rows)+1)), module.name
        paper_tex = []
        for row in rows:
            item_key = f'qj617-{data["YEAR"]}-{module.stem}-q{row["number"]:02}'
            original_rows[item_key] = dict(row)
            original_warning = row['source_warning']
            correction = corrections.get(item_key)
            if correction:
                assert original_warning, (item_key, 'correction must target a documented issue')
                row = apply_correction(row, correction)
            assert set(row['topic'].split('，')) <= NSUBJECTS, (module.name,row['number'],'topic')
            assert set(row['pages']) <= set(entry['source_pdf_pages'])
            n = row['number']
            assets = []
            folder = WORK/module.stem/f'q{n:02}'
            folder.mkdir(parents=True, exist_ok=True)
            for order,(page,bbox,alias,caption) in enumerate(row['figures'],1):
                assert page in row['pages']
                path = folder/(alias+'.png')
                doc[page-1].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(bbox),alpha=False).save(path)
                assets.append(dict(role='solution' if alias.startswith('solution') else 'problem',
                    source_path=path.relative_to(ROOT).as_posix(),caption=caption,sort_order=order,
                    extra=dict(alias=alias,page_number=page,bbox=bbox,input_sha256=inv['source_sha256'],
                               file_sha256=sha(path),source_visual_review='codex_original_page_compared')))
            stem,answer,solution = [format_tex(row[k]) for k in ['stem_tex','answer_tex','solution_tex']]
            choices = [format_tex(x) for x in row['choices']]
            assert len(choices)==4 if row['question_type_id'] in (1,2) else not choices
            refs = re.findall(r'\\questionasset\{([^{}]+)\}', '\n'.join([stem,*choices,answer,solution]))
            assert sorted(refs)==sorted(a['extra']['alias'] for a in assets), (module.name,n,'assets')
            warning = row['source_warning']
            extra = dict(source_kind='试卷',detected_year=data['YEAR'],paper_series='QJ',track='',
                detected_source=data['PAPER'],transcription_paper_name=data['PAPER'],
                detected_question_number=str(n),question_number=str(n),detected_topic=row['topic'],
                source_pages=row['pages'],page_start=min(row['pages']),page_end=max(row['pages']),
                book_title='清北强基数学考什么（修订版）',book_pages=[inv.get('pdf_to_book_page',{}).get(str(p),p-9) for p in row['pages']],
                source_directory_title=entry['directory_title'],input_sha256=inv['source_sha256'],
                source_path=source.name,source_page_images=[(WORK/'pages'/f'p{p:03}.png').relative_to(ROOT).as_posix() for p in row['pages']],
                answer_origin='source_book' if answer else 'not_provided',
                solution_origin='source_book' if solution else 'not_provided',
                transcription_method='codex_visual_qj_book_v1',
                prompt_sha256=sha(ROOT/'ocr_prompt.txt'),visual_source_compared=True,source_warning=warning)
            if correction:
                extra['source_correction'] = dict(status='resolved', reason=correction['reason'],
                    original_source_warning=original_warning, original_preserved_in=inv.get('original_transcription_file','source_payload_before_corrections.json'),
                    revision_kind='answer_analysis_only', source_subject_unchanged=True,
                    withdrawn_subject_fields=correction.get('withdrawn_subject_fields',[]),
                    operator='codex_user_authorized_revision')
                extra['solution_origin'] = 'verified_editorial_revision'
                if 'answer_tex' in correction['fields']:
                    extra['answer_origin'] = 'verified_editorial_revision'
            item = dict(source_item_id=f'qj617-{data["YEAR"]}-{module.stem}-q{n:02}',
                source_label=f'{data["YEAR"]} {data["PAPER"]} · 第 {n} 题',
                proposed_action='insert',review_status='needs_review',question_type_id=row['question_type_id'],
                stem_tex=stem,choices=choices,answer_tex=answer,solution_tex=solution,tags=row['tags'],
                note='对照原书扫描页转写，保留原书答案及解法。'+(' 来源疑点：'+warning if warning else ''),
                official_flag=False,assets=assets,extra=extra)
            validation = validate_draft_question(normalize_draft_question(item))
            assert not validation['errors'], (module.name,n,validation)
            item['validation'] = dict(draft_validation=validation,visual_source_compared=True)
            items.append(item)
            qtex = question_to_legacy_tex(dict(item,question_id=item['source_item_id'],
                choices_json=json.dumps(choices,ensure_ascii=False),tags_json=json.dumps(row['tags'],ensure_ascii=False),
                paper_series='QJ',**{k:v for k,v in extra.items() if k.startswith('detected_')}))
            (folder/'question.tex').write_text(qtex,encoding='utf-8')
            for asset in assets:
                qtex = qtex.replace('\\questionasset{'+asset['extra']['alias']+'}',
                    '\\begin{center}\\includegraphics[width=0.48\\linewidth,keepaspectratio]{'+(ROOT/asset['source_path']).as_posix()+'}\\end{center}')
            paper_tex.append(qtex)
            source_review.append(dict(source_item_id=item['source_item_id'],pages=row['pages'],source_warning=warning,figures=len(assets)))
        tex_path = WORK/('preview_'+module.stem+'.tex')
        tex_path.write_text(PREAMBLE+'\n'.join(paper_tex)+r'\end{document}',encoding='utf-8')
        paper_image_hashes = [a['extra']['file_sha256'] for item in items
                              if item['extra']['detected_year']==data['YEAR']
                              and item['extra']['detected_source']==data['PAPER'] for a in item['assets']]
        key = hashlib.sha256(tex_path.read_bytes()+'\n'.join(paper_image_hashes).encode()).hexdigest()
        if cache.get(module.name)!=key or not tex_path.with_suffix('.pdf').exists():
            result = subprocess.run(['xelatex','-interaction=nonstopmode','-halt-on-error',tex_path.name],cwd=WORK,capture_output=True)
            code = result.returncode
        else:
            code = 0
        log = tex_path.with_suffix('.log').read_text(encoding='utf-8',errors='replace')
        check = dict(module=module.name,year=data['YEAR'],paper=data['PAPER'],questions=len(rows),
            compile_passed=code==0,overfull=log.count('Overfull'),missing=log.count('Missing character:'))
        checks.append(check)
        print(json.dumps(check,ensure_ascii=False),flush=True)
        if code==0 and not check['overfull'] and not check['missing']:
            cache[module.name]=key
        elif code:
            print(log[-1800:],flush=True)
    doc.close()
    save('compile_cache.json',cache)
    if inv.get('original_transcription_file'):
        save(inv['original_transcription_file'], original_rows)
    save('visual_payloads.json',items)
    save('source_review.json',source_review)
    expected_papers=len(inv['papers'])
    save('compile_checks.json',dict(expected_papers=expected_papers,completed_source_modules=len(checks),questions=len(items),
        images=sum(len(x['assets']) for x in items),checks=checks,complete=len(checks)==expected_papers))
    preview(items)
    return checks


def preview(items):
    katex=ROOT/'reports/external_review/judgepeach/math-question-bank-main/static/lib/katex'
    articles=[]
    for item in items:
        fields=[('题干',item['stem_tex']),*[(f'选项 {chr(65+i)}',c) for i,c in enumerate(item['choices'])],
                ('答案',item['answer_tex']),('解析',item['solution_tex'])]
        parts=[]
        for label,value in fields:
            text=html.escape(latex_to_markdown(value,show_title=False))
            def img(m):
                a=next(a for a in item['assets'] if a['extra']['alias']==m[1])
                return '<img alt="'+html.escape(a['caption'])+'" src="data:image/png;base64,'+base64.b64encode((ROOT/a['source_path']).read_bytes()).decode()+'"/>'
            text=re.sub(r'\\questionasset\{([^{}]+)\}',img,text)
            parts.append('<h3>'+label+'</h3><div class="body">'+text+'</div>')
        articles.append('<article><h2>'+html.escape(item['source_label'])+'</h2>'+''.join(parts)+'</article>')
    page='<!doctype html><meta charset="utf-8"><style>body{font-family:Arial,"Microsoft YaHei";max-width:1100px;margin:auto}article{padding:24px;border-bottom:2px solid #ddd}.body{white-space:pre-wrap;overflow-wrap:anywhere}img{max-width:100%;max-height:480px;display:block;margin:12px auto}.katex-display{overflow:auto}</style>'
    page+=f'<link rel="stylesheet" href="{(katex/"katex.min.css").as_uri()}"><script src="{(katex/"katex.min.js").as_uri()}"></script>'
    page+=''.join(articles)
    page+=r"""<script>
window.previewErrors=[];document.querySelectorAll('.body').forEach(node=>{
const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT),texts=[];
while(walker.nextNode())texts.push(walker.currentNode);
for(const text of texts){let last=0,m,found=false;const value=text.nodeValue,fragment=document.createDocumentFragment(),regex=/\$\$([\s\S]*?)\$\$|\$([^$]*?)\$/g;
while((m=regex.exec(value))){found=true;fragment.append(value.slice(last,m.index));const span=document.createElement('span');
try{span.innerHTML=katex.renderToString(m[1]??m[2],{throwOnError:true,displayMode:m[1]!==undefined,strict:"ignore",macros:{"\\circled":"\\text{(#1)}"}})}
catch(e){window.previewErrors.push({question:node.closest('article').querySelector('h2').textContent,formula:m[0],error:String(e)});span.className='math-error';span.textContent=m[0]}
fragment.append(span);last=regex.lastIndex}
if(found){fragment.append(value.slice(last));text.replaceWith(fragment)}
}});window.previewReady=true;
</script>"""
    (WORK/'browser_preview.html').write_text(page,encoding='utf-8')


def stage():
    report=read('compile_checks.json')
    assert report['checks'] and all(x['compile_passed'] and not x['overfull'] and not x['missing'] for x in report['checks'])
    browser=read('preview_browser_checks.json')
    assert browser['status']=='ok' and browser['payload_sha256']==sha(WORK/'visual_payloads.json')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    isolated=WORK/f'staged_{stamp}.sqlite3'
    snapshot(LIVE,isolated)
    inv=read('source_inventory.json')
    with connect(LIVE) as c:
        tables=[r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        before={t:fingerprint(c,t) for t in tables}
        old_catalog={(r['year'],r['paper_series'],r['paper_name']):dict(r) for r in c.execute('SELECT * FROM paper_standard_catalog')}
        existing={r[0] for r in c.execute("SELECT source_item_id FROM question_import_draft WHERE source_item_id LIKE 'qj617-%'")}
    catalog={}
    for p in inv['papers']:
        key=(p['year'],'QJ',p['paper_name'])
        catalog[key]=old_catalog.get(key) or add_standard_paper(str(isolated),year=p['year'],paper_series='QJ',track='',paper_name=p['paper_name'])
    root=create_task_plan(str(isolated),task_key=inv.get('task_key','qj617-2021-2025-'+inv['source_sha256'][:16]),
        title=inv.get('task_title','2021—2025年清北强基数学录题任务'),source_path=inv['source'],papers=inv['papers'])
    with connect(isolated) as c:
        paper_ids={r['subset_key']:r['batch_id'] for r in c.execute('SELECT * FROM import_batch WHERE parent_batch_id=?',(root,))}
    payload=read('visual_payloads.json')
    duplicate_checks=read('duplicate_checks.json')
    leaves={}
    new_ids=[]
    for item in payload:
        if item['source_item_id'] in existing:
            continue
        duplicate=duplicate_checks[item['source_item_id']]
        signature=hashlib.sha256(json.dumps([item['stem_tex'],item['choices'],item['question_type_id']],ensure_ascii=False).encode()).hexdigest()
        assert duplicate['signature']==signature, 'Stale duplicate check'
        item['validation'].update(paper_position_conflicts=duplicate['position_conflicts'],
            similarity_candidates=duplicate['similarity_candidates'],latex_compile='passed')
        e=item['extra']
        key=(e['detected_year'],'QJ',e['detected_source'])
        e['paper_standard_id']=catalog[key]['paper_standard_id']
        e['paper_match_status']='standard_catalog_verified'
        paper=paper_ids[f"{e['detected_year']}|{e['detected_source']}"]
        group=(paper,item['question_type_id'])
        if group not in leaves:
            leaves[group]=create_import_batch(str(isolated),'codex_subset',inv['source'],'subset',
                'qj617-'+paper+'-'+str(group[1]),task_id=root,parent_batch_id=paper,hierarchy_level=2,
                subset_key='type-'+str(group[1]),subset_label={1:'单选题',2:'多选题',3:'填空题',4:'解答题'}[group[1]])
        did,v=insert_draft_question(str(isolated),leaves[group],normalize_draft_question(item),int(e['question_number']))
        assert not v['errors'],v
        new_ids.append(did)
    allowed=['paper_standard_catalog','import_batch','question_import_draft','question_import_draft_asset','draft_review_event']
    additions={}
    with connect(LIVE) as a,connect(isolated) as b:
        for t in tables:
            if t not in allowed:
                assert fingerprint(b,t)==before[t],t
        for t in allowed:
            pk=next(r[1] for r in a.execute('PRAGMA table_info("'+t+'")') if r[5])
            old={r[pk]:list(r) for r in a.execute('SELECT * FROM "'+t+'"')}
            additions[t]=[]
            for r in b.execute('SELECT * FROM "'+t+'"'):
                if r[pk] in old:
                    assert list(r)==old[r[pk]],(t,r[pk],'existing row changed')
                else:
                    additions[t].append(dict(r))
        assert not b.execute('PRAGMA foreign_key_check').fetchall()
    assert new_ids,'No new drafts'
    plan=dict(stage='isolated_checked',root_batch_id=root,isolated=str(isolated.relative_to(ROOT)),
        live_fingerprints=before,payload_sha256=sha(WORK/'visual_payloads.json'),new_drafts=new_ids,additions=additions)
    save('install_plan.json',plan)
    print(json.dumps(dict(stage=plan['stage'],new_drafts=len(new_ids),root_batch_id=root)))


def apply():
    plan=read('install_plan.json')
    assert read('preview_browser_checks.json')['payload_sha256']==plan['payload_sha256']==sha(WORK/'visual_payloads.json')
    stamp=datetime.now().strftime('%Y%m%d_%H%M%S')
    backup=ROOT/'data/backups'/f'before_qj617_drafts_{stamp}.sqlite3'
    snapshot(LIVE,backup)
    with sqlite3.connect(LIVE) as c:
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('BEGIN IMMEDIATE')
        for t,digest in plan['live_fingerprints'].items():
            assert fingerprint(c,t)==digest,('live changed',t)
        for t,rows in plan['additions'].items():
            for row in rows:
                columns=list(row)
                c.execute('INSERT INTO "'+t+'" ('+','.join('"'+k+'"' for k in columns)+') VALUES ('+','.join('?' for _ in columns)+')',list(row.values()))
        assert not c.execute('PRAGMA foreign_key_check').fetchall()
        c.commit()
    with connect(backup) as a,connect(LIVE) as b:
        for t,digest in plan['live_fingerprints'].items():
            if t not in plan['additions'] or not plan['additions'][t]:
                assert fingerprint(b,t)==digest,t
            else:
                pk=next(r[1] for r in a.execute('PRAGMA table_info("'+t+'")') if r[5])
                for r in a.execute('SELECT * FROM "'+t+'"'):
                    assert tuple(b.execute('SELECT * FROM "'+t+'" WHERE "'+pk+'"=?',(r[pk],)).fetchone())==tuple(r),(t,r[pk])
        for did in plan['new_drafts']:
            row=b.execute('SELECT * FROM question_import_draft WHERE draft_id=?',(did,)).fetchone()
            assert row['review_status']=='needs_review' and json.loads(row['extra_json'])['paper_series']=='QJ'
        assert b.execute('PRAGMA quick_check').fetchone()[0]=='ok'
    save('delivery.json',dict(status='ready_for_human_review' if read('compile_checks.json')['complete'] else 'partial_ready_for_human_review',root_batch_id=plan['root_batch_id'],
        installed_new_drafts=len(plan['new_drafts']),backup=str(backup.relative_to(ROOT)),
        cumulative_source_questions=read('compile_checks.json')['questions'],
        expected_papers=read('compile_checks.json')['expected_papers'],source_module_count=read('compile_checks.json')['completed_source_modules'],
        entire_five_year_task_complete=read('compile_checks.json')['complete'],
        existing_rows_unchanged=True,formal_questions_unchanged=True))
    print(json.dumps(read('delivery.json'),ensure_ascii=False))


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    p=argparse.ArgumentParser()
    p.add_argument('--stage',action='store_true')
    p.add_argument('--apply',action='store_true')
    args=p.parse_args()
    if args.apply:
        apply()
    elif args.stage:
        stage()
    else:
        checks=build()
        raise SystemExit(0 if all(c['compile_passed'] and not c['overfull'] and not c['missing'] for c in checks) else 1)
