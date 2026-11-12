"""Read-only fixture for the actual preview renderer."""
import sys,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
import streamlit as st
from question_bank_app import (inject_custom_css,inject_unified_visual_system_css,
    render_question_preview,_sqlite_draft_preview_with_assets,_sqlite_draft_standard_preview_tex)
st.set_page_config(layout='wide')
inject_custom_css();inject_unified_visual_system_css()
items=json.loads((ROOT/'data/imports/codex_2011_restart/visual_payloads.json').read_text(encoding='utf8'))
short=dict(stem_tex=r'分式显示 $\frac{20}{3}$',choices=[r'$\frac{20}{3}$',r'$\frac72$',r'$\frac{16}5$',r'$\frac{15}8$'],answer_tex='',solution_tex='')
long=dict(short,choices=['这是用于检查选项宽度的较长说明文字，每一个条件都应完整显示。']*4)
for title,payload in [('short',short),('long',long),('images',next(p for p in items if p['source_item_id']=='2011-visual-paper_16-q10'))]:
    st.markdown('### '+title)
    with st.columns([1,1])[0]:
        render_question_preview('',prepared_markdown=_sqlite_draft_preview_with_assets(_sqlite_draft_standard_preview_tex(payload),payload.get('assets',[])))
