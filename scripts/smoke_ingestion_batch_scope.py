"""Exercise batch scope and duplicate filters using only temporary SQLite DBs."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import sys
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from streamlit.testing.v1 import AppTest
from services.database_service import initialize_database, readonly_database_connection, existing_database_connection
from services.ingestion_review_service import create_task_plan,task_tree
from services.import_service import create_import_batch,create_manual_entry_draft,get_draft_question
from components.ingestion_review import _run_bulk_review_action

def main():
    with TemporaryDirectory(prefix='bulk_scope_',dir=ROOT/'data') as tmp:
        db=str(Path(tmp)/'test.sqlite3');initialize_database(db)
        root=create_task_plan(db,task_key='scope-test',title='Scope test',source_path='test.pdf',papers=[
            {'year':2026,'paper_name':'A'}, {'year':2026,'paper_name':'B'}, {'year':2025,'paper_name':'C'}])
        outsider=create_task_plan(db,task_key='outside',title='Outside',source_path='other.pdf',papers=[{'year':2026,'paper_name':'D'}])
        nodes,_=task_tree(db);ids={}
        for name in 'ABCD':
            paper=next(n for n in nodes if n['label']==name)
            leaf=create_import_batch(db,'codex_subset','test','subset',name,task_id=paper['task_id'],parent_batch_id=paper['batch_id'],hierarchy_level=2)
            r=create_manual_entry_draft(db,{'source_item_id':name,'stem_tex':f'Unique question {name} with distinct condition {ord(name)}',
                'question_type_id':5,'extra':{'detected_year':2026 if name!='C' else 2025,'detected_question_number':'1'}},batch_id=leaf)
            ids[name]=r['draft_id'] if 'draft_id' in r else r['draft']['draft_id']
        app_script=f'''
import sys
sys.path.insert(0,{ascii(str(ROOT))})
import streamlit as st
import components.ingestion_review as review
st.session_state.setdefault('ingestion_review_task',{ascii(root)})
def capture(db,rows,mode):
    st.session_state['bulk_ids']=[r['draft_id'] for r in rows]
    st.session_state['bulk_mode']=mode
original=review._run_bulk_review_action
review._run_bulk_review_action=capture
try: review.render({ascii(db)}, lambda draft: st.markdown(draft['stem_tex']), lambda q: None)
finally: review._run_bulk_review_action=original
'''
        app=AppTest.from_string(app_script,default_timeout=30).run();assert not app.exception
        next(b for b in app.button if b.label=='录入本批所有未处理题目').click().run()
        assert set(app.session_state['bulk_ids'])=={ids['A'],ids['B']}
        app.radio(key=f'ingestion_bulk_scope_{root}').set_value('整个任务').run()
        next(b for b in app.button if b.label=='录入本批非重复与相似题目').click().run()
        assert set(app.session_state['bulk_ids'])=={ids['A'],ids['B'],ids['C']}
        assert app.session_state['bulk_mode']=='non_exact'
        assert ids['D'] not in app.session_state['bulk_ids']
        # Test the real commit path separately; a click captures the selected
        # scope above, and this test verifies filtering and idempotency.
        with patch('components.ingestion_review.find_question_content_matches',return_value=[{'kind':'similar','score':0.99}]), patch('components.ingestion_review.st'):
            _run_bulk_review_action(db,[{'draft_id':ids['A']}],'non_exact')
        assert get_draft_question(db,ids['A'])['review_status']=='needs_review'
        with patch('components.ingestion_review.find_question_content_matches',return_value=[{'kind':'exact','score':1}]), patch('components.ingestion_review.st'):
            _run_bulk_review_action(db,[{'draft_id':ids['A']}],'non_duplicate')
        assert get_draft_question(db,ids['A'])['review_status']=='needs_review'
        with patch('components.ingestion_review.find_question_content_matches',return_value=[]), patch('components.ingestion_review.st'):
            _run_bulk_review_action(db,[{'draft_id':ids['A']},{'draft_id':ids['B']}],'all')
            _run_bulk_review_action(db,[{'draft_id':ids['A']},{'draft_id':ids['B']}],'all')
        assert get_draft_question(db,ids['A'])['review_status']=='committed'
        assert get_draft_question(db,ids['C'])['review_status']=='needs_review'
        assert get_draft_question(db,ids['D'])['review_status']=='needs_review'
        with readonly_database_connection(db) as c: assert c.execute('select count(*) from question').fetchone()[0]==2
    print('ingestion_batch_scope=ok (year, whole task, isolation, filters, idempotency)')
if __name__=='__main__':main()
