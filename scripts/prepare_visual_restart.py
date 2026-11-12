"""Build and compile only paper modules actually transcribed from page images.

This never writes to the live database. Installation is a separate, gated
operation after all modules, source figures, and browser checks are complete.
"""
from __future__ import annotations
import argparse, hashlib, json, re, runpy, sqlite3, subprocess, sys
from collections import Counter
from pathlib import Path
import fitz

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from services.import_service import normalize_draft_question, validate_draft_question
from services.export_service import question_to_legacy_tex
from services.question_text_format_service import normalize_choice_blank_stop

PREAMBLE=r'''\documentclass[UTF8,a4paper]{ctexart}
\usepackage[margin=20mm]{geometry}
\usepackage{amsmath,amssymb,graphicx}
\newenvironment{problem}[5]{\par\bigskip\noindent\textbf{#1 #3 第#4题（#5）}\par}{\par}
\newenvironment{answer}{\par\textbf{答案：}}{\par}
\newenvironment{solutions}{\par\textbf{解析：}}{\par}
\newcounter{opt}
\newenvironment{choices}{\setcounter{opt}{0}\begin{list}{}{\setlength{\leftmargin}{1.8em}}}{\end{list}}
\newcommand{\choice}[1]{\stepcounter{opt}\item[\Alph{opt}.] #1}
\newcommand{\circled}[1]{\textcircled{#1}}
\begin{document}
'''

def style(tex):
    tex=normalize_choice_blank_stop(tex)
    # No inference from PDF text: this only groups simple superscripts and
    # separates punctuation around math spans already authored in the module.
    chunks=re.split(r'(\$\$[\s\S]*?\$\$|\$[^$]*\$)',tex)
    for i,chunk in enumerate(chunks):
        if chunk.startswith('$'):
            # Chinese punctuation in a math span has no glyph in the math
            # fonts used by XeLaTeX. Preserve the punctuation using TeX forms.
            chunk=chunk.translate(str.maketrans({'，':',','。':'.','；':';','：':':'}))
            chunk=re.sub(r'([_^])(?!\{)([A-Za-z0-9])',r'\1{\2}',chunk)
        else:
            chunk=re.sub(r'^。', '.', chunk)
        chunks[i]=chunk
    return ''.join(chunks)

def build(year):
    work=ROOT/f'data/imports/codex_{year}_restart'
    cache_path=work/'compile_fingerprints.json'
    compile_cache=json.loads(cache_path.read_text(encoding='utf8')) if cache_path.exists() else {}
    modules=sorted(work.glob('paper_*.py'),key=lambda p:int(p.stem.split('_')[1]))
    if not modules:raise RuntimeError('No visually transcribed modules exist')
    source=next(ROOT.glob('1952-2026*.pdf'));sha=hashlib.sha256(source.read_bytes()).hexdigest()
    pdf=fitz.open(source);items=[];checks=[]
    inventory_path=work/'source_inventory.json'
    inventory=json.loads(inventory_path.read_text(encoding='utf8')) if inventory_path.exists() else []
    # Match actual source names against the existing catalogue; preserve its
    # spelling and ID even where the OCR prompt uses a historical name alias.
    with sqlite3.connect(f'file:{ROOT / "data/mathcyclus.sqlite3"}?mode=ro',uri=True) as conn:
        conn.row_factory=sqlite3.Row
        catalogue=[dict(r) for r in conn.execute('SELECT * FROM paper_standard_catalog WHERE year=? AND paper_series=?',(year,'G'))]
    for module in modules:
        data=runpy.run_path(str(module));name=data['PAPER'];rows=data['ROWS'];tex=[]
        source_name=data.get('SOURCE_PAPER') or (name.replace('新课标','新高考') if year>=2020 else name)
        entry=next((x for x in catalogue if x['source_name']==source_name or x['paper_name']==source_name),None)
        if entry is None:
            aliases={'上海春考卷':'上海春季高考'}
            if year==2023:
                aliases.update({'新高考I卷':'新课标I卷','新高考II卷':'新课标II卷'})
            catalog_name=aliases.get(source_name,source_name)
            entry=next((x for x in catalogue if x['source_name']==catalog_name or x['paper_name']==catalog_name),None)
        if entry is None and year==2014:
            catalog_name=re.sub(r'^2014年?', '', source_name)
            entry=next((x for x in catalogue if x['source_name']==catalog_name or x['paper_name']==catalog_name),None)
        if entry is None and year==2012:
            catalog_name=re.sub(r'^2012年?', '', source_name)
            entry=next((x for x in catalogue if x['source_name']==catalog_name or x['paper_name']==catalog_name),None)
        if entry is None:raise RuntimeError(f'Cannot resolve standard catalogue: {year} {name}')
        if [r['number'] for r in rows]!=list(range(1,len(rows)+1)):raise RuntimeError((name,'question coverage'))
        source_numbers=[str(r.get('source_number',r['number'])) for r in rows]
        if len(set(source_numbers))!=len(rows):raise RuntimeError((name,'duplicate source question number'))
        bounds=inventory[int(module.stem.split('_')[1])-1][1:] if inventory else None
        for row in rows:
            n=row['number'];folder=work/module.stem/f'q{n:02d}';folder.mkdir(parents=True,exist_ok=True);assets=[]
            source_number=str(row.get('source_number',n))
            if not row['pages'] or (bounds and not all(bounds[0]<=p<=bounds[1] for p in row['pages'])):
                raise RuntimeError((name,n,'source page outside paper'))
            for value in [row['stem_tex'],*row['choices'],row['source_warning']]:
                if re.search(r'\\par(?![A-Za-z])',value):
                    raise RuntimeError((name,n,'paragraph command forbidden; use two spaces and a real newline'))
                if '\ufffd' in value or '??' in value or re.search(r'[\x00-\x09\x0b\x0c\x0e-\x1f]',value):
                    raise RuntimeError((name,n,'damaged text encoding or control character'))
            for fi,(page,bbox) in enumerate(row['figures'],1):
                if page not in row['pages']:raise RuntimeError((name,n,'figure outside question pages'))
                path=folder/f'figure_{fi:02d}.png';pdf[page-1].get_pixmap(matrix=fitz.Matrix(3,3),clip=fitz.Rect(bbox),alpha=False).save(path)
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                assets.append(dict(role='problem',source_path=path.relative_to(ROOT).as_posix(),caption=f'figure_{fi:02d}',sort_order=fi,extra=dict(alias=f'figure_{fi:02d}',page_number=page,bbox=bbox,input_sha256=sha,file_sha256=digest)))
            for embedded in row.get('embedded_figures',[]):
                page=embedded['page'];xref=embedded['xref'];fi=len(assets)+1
                assert page in row['pages'] and xref in {im[0] for im in pdf[page-1].get_images(full=True)}
                raw=pdf.extract_image(xref);path=folder/f'figure_{fi:02d}.{raw["ext"]}';path.write_bytes(raw['image'])
                digest=hashlib.sha256(path.read_bytes()).hexdigest()
                assets.append(dict(role='problem',source_path=path.relative_to(ROOT).as_posix(),caption=f'figure_{fi:02d}',sort_order=fi,extra=dict(alias=f'figure_{fi:02d}',page_number=page,pdf_image_xref=xref,input_sha256=sha,file_sha256=digest)))
            stem=style(row['stem_tex']);choices=[style('$'+c+'$' if re.fullmatch(r'-?\d+(?:\.\d+)?',c) else c) for c in row['choices']]
            refs=re.findall(r'\\questionasset\{([^}]+)\}','\n'.join([stem,*choices]))
            assert refs==[a['caption'] for a in assets],(name,n,'figure references')
            assert len(choices)==4 if row['question_type_id'] in (1,2) else not choices
            for content in [stem,*choices]:
                assert content.count('$')%2==0,(name,n,'dollars')
                assert not re.search(r'(?<!\\)\b(sin|cos|tan|log|ln)\b',content),(name,n,'function')
                assert not re.search(r'\\[\[\]()]',content),(name,n,'math delimiter')
            source_verified=data.get('SOURCE_VERIFIED',True) and not ('OCR source' in row['tags'] or r'\detokenize' in stem)
            extra=dict(source_kind='试卷',detected_year=year,paper_series='G',track=entry['track'],detected_source=source_name,source_name_on_page=source_name,transcription_paper_name=name,paper_standard_id=entry['paper_standard_id'],paper_match_status='standard_catalog_verified',detected_question_number=str(n),question_number=str(n),detected_topic=row['topic'],page_start=min(row['pages']),page_end=max(row['pages']),source_pages=row['pages'],input_sha256=sha,source_path=source.name,answer_origin='not_provided',solution_origin='not_provided',transcription_method=f'codex_visual_transcription_{year}_v1' if source_verified else 'ocr_preparation_only',source_warning=row['source_warning'],visual_source_compared=source_verified,ingestion_checks_complete=source_verified)
            p=dict(source_item_id=f'{year}-visual-{module.stem}-q{n:02d}',source_label=f'{year} {name} · 第 {n} 题',proposed_action='insert',review_status='needs_review',question_type_id=row['question_type_id'],stem_tex=stem,choices=choices,answer_tex='',solution_tex='',tags=row['tags'],note='按原始 PDF 页逐题视觉转写；原页未提供答案和解析。'+(' 来源提醒：'+row['source_warning'] if row['source_warning'] else ''),official_flag=False,assets=assets,extra=extra)
            validation=validate_draft_question(normalize_draft_question(p));assert not validation['errors'],(name,n,validation)
            if not source_verified:
                p['note']='OCR preparation only; original-page comparison and mathematical TeX transcription are incomplete.'
            p['validation']={'draft_validation':validation,'visual_source_compared':source_verified};items.append(p)
            extra.update(detected_question_number=source_number,question_number=source_number)
            p['source_label']=f'{year} {name} · 第 {source_number} 题'
            q=dict(p,question_id=p['source_item_id'],choices_json=json.dumps(choices,ensure_ascii=False),tags_json=json.dumps(p['tags'],ensure_ascii=False),**{k:v for k,v in extra.items() if k.startswith('detected_')},paper_series='G')
            qtex=question_to_legacy_tex(q);(folder/'question.tex').write_text(qtex,encoding='utf8')
            for a in assets:
                bs=chr(92)
                asset_ref=bs*2+'questionasset{'+a['caption']+'}'
                image_width=str(row.get('asset_width') or '0.58')
                image_tex=bs+'begin{center}'+bs+'includegraphics[width='+image_width+bs+'linewidth,keepaspectratio]{'+str((ROOT/a['source_path']).resolve()).replace(chr(92),'/')+'}'+bs+'end{center}'
                qtex=qtex.replace(asset_ref,image_tex).replace(bs+'questionasset{'+a['caption']+'}',image_tex)
            tex.append(qtex)
        preview=work/f'preview_{module.stem}.tex';preview.write_text(PREAMBLE+'\n'.join(tex)+r'\end{document}',encoding='utf8')
        module_assets=[a['extra']['file_sha256'] for item in items if item['source_item_id'].startswith(f'{year}-visual-{module.stem}-') for a in item['assets']]
        compile_key=hashlib.sha256(preview.read_bytes()+'\n'.join(module_assets).encode()).hexdigest()
        cached=compile_cache.get(module.name)==compile_key and preview.with_suffix('.pdf').exists() and preview.with_suffix('.log').exists()
        result=subprocess.CompletedProcess([],0,b'',b'') if cached else subprocess.run(['xelatex','-interaction=nonstopmode','-halt-on-error',preview.name],cwd=work,capture_output=True)
        log=preview.with_suffix('.log').read_text(encoding='utf8',errors='replace')
        check=dict(paper=name,module=module.name,questions=len(rows),compile_passed=result.returncode==0,overfull_boxes=log.count('Overfull'),missing_characters=log.count('Missing character:'),log=preview.with_suffix('.log').relative_to(ROOT).as_posix());checks.append(check)
        print(json.dumps(check,ensure_ascii=False),flush=True)
        if check['compile_passed'] and not check['overfull_boxes'] and not check['missing_characters']:
            compile_cache[module.name]=compile_key
            cache_path.write_text(json.dumps(compile_cache,indent=2),encoding='utf8')
        if result.returncode:print(result.stdout.decode('utf8',errors='replace')[-2000:]);break
    pdf.close()
    expected_papers=len(inventory) if inventory else {2020:14,2021:11,2022:11,2023:10,2024:8,2025:6}.get(year)
    source_clean=all(x['compile_passed'] and not x['overfull_boxes'] and not x['missing_characters'] for x in checks)
    complete=expected_papers is not None and len(checks)==expected_papers
    status='blocked_compile' if not source_clean else 'compiled_source_modules' if complete else 'partial_source_modules'
    report={'year':year,'status':status,'expected_papers':expected_papers,'papers':len(checks),'questions':len(items),'images':sum(len(x['assets']) for x in items),'paper_counts':dict(Counter(x['extra']['detected_source'] for x in items)),'compile_checks':checks,'browser_checked':False,'installed':False}
    (work/'visual_payloads.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf8')
    (work/'visual_compile_checks.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    return report

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--year',type=int,required=True);a=ap.parse_args();r=build(a.year)
    print(json.dumps(r,ensure_ascii=False));raise SystemExit(0 if r['status'] in {'compiled_source_modules','partial_source_modules'} else 1)
