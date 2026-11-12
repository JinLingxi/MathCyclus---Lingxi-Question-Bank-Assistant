"""Exercise the real task-review route against an isolated database."""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from streamlit.testing.v1 import AppTest
from services.database_service import initialize_database, readonly_database_connection, existing_database_connection
from services.ingestion_review_service import create_task_plan, task_tree, paper_drafts
from services.import_service import create_import_batch, create_manual_entry_draft, get_draft_question
from services.schema_migration_service import migration_status


def main():
    with tempfile.TemporaryDirectory(prefix='task_review_', dir=str(ROOT / 'data')) as tmp:
        db = str(Path(tmp) / 'test.sqlite3')
        initialize_database(db)
        assert migration_status(db)['status'] == 'ok'
        args = dict(task_key='test-task', title='2026年录题任务', source_path='test.pdf', papers=[
            {'year': 2026, 'paper_name': '全国I卷', 'page_start': 14, 'page_end': 16},
            {'year': 2026, 'paper_name': '北京卷', 'page_start': 20, 'page_end': 23},
            {'year': 2025, 'paper_name': '北京卷', 'page_start': 40, 'page_end': 42},
        ])
        root = create_task_plan(db, **args)
        nodes, roots = task_tree(db)
        paper = next(n for n in nodes if n['label'] == '全国I卷')
        leaf = create_import_batch(db, 'codex_subset', 'test-leaf', 'subset', 'one',
                                   task_id=root, parent_batch_id=paper['batch_id'], hierarchy_level=2)
        for num in (10, 2, 11):
            create_manual_entry_draft(db, {
                'source_item_id': f'q{num}', 'stem_tex': '完整题干 ' * 60 + f'末尾标记{num}',
                'answer_tex': '$2$', 'solution_tex': '解答内容', 'review_status': 'needs_review',
                'question_type_id': 1 if num == 10 else 5,
                'choices': ['$1$', '$2$', '$3$', '$4$'] if num == 10 else [],
                'tags': ['单调性', '<script>bad</script>'],
                'note': '对照原书扫描页转写，保留原书答案及解法。 来源疑点：保留审核提醒',
                'extra': {'detected_year': 2026, 'detected_source': '全国I卷',
                          'detected_question_number': str(num), 'detected_topic': '函数，导数',
                          'source_kind': '试卷', 'paper_series': 'G', 'track': '综合'},
            }, batch_id=leaf)
        create_manual_entry_draft(db, {'stem_tex': 'Historical manual draft'})
        create_task_plan(db, **args)
        nodes, roots = task_tree(db)
        assert len(roots) == 1 and roots[0]['draft_count'] == 3
        assert len(paper_drafts(db, nodes, paper['batch_id'])) == 3
        with existing_database_connection(db) as c:
            c.execute("INSERT INTO question(question_id,stem_tex,question_type_id) VALUES ('Q000001',?,5)", ('完整题干 ' * 60 + '末尾标记2',))
            c.execute("INSERT INTO question(question_id,stem_tex,question_type_id) VALUES ('Q000002',?,5)", ('完整题干 ' * 60 + '末尾标记3补充',))
            c.execute("INSERT INTO paper(paper_id,year,paper_series,track,paper_name) VALUES ('PTEST',2026,'G','综合','全国I卷')")
            c.execute("INSERT INTO paper_question(paper_question_id,paper_id,question_id,question_number) VALUES ('PQTEST','PTEST','Q000001','2')")
        script = f'''
import sys
sys.path.insert(0, {ascii(str(ROOT))})
import streamlit as st
import services.database_service as database
database.DEFAULT_DATABASE_PATH = {ascii(db)}
from question_bank_app import page_tools
st.session_state['tools_subpage'] = 'ingestion_task_review'
page_tools()
'''
        compile(script, '<ui-test>', 'exec')
        app = AppTest.from_string(script, default_timeout=30).run()
        assert not app.exception, [e.message for e in app.exception]
        assert app.radio(key='ingestion_review_year').value == '2026'
        rendered = '\n'.join(str(x.value) for x in app.markdown)
        rendered_all = rendered + '\n' + '\n'.join(str(x.value) for x in app.caption)
        assert '对照原书扫描页转写，保留原书答案及解法。' not in rendered_all
        assert '来源疑点：保留审核提醒' in rendered_all
        assert '末尾标记10' in rendered and '末尾标记2' in rendered
        assert '同位置重复' in rendered_all and '高度相似' in rendered_all
        assert rendered.index('第 2 题') < rendered.index('第 10 题')
        assert rendered.index('第 2 题') < rendered.index('已有题目 · Q000001')
        assert 'Historical manual draft' not in rendered
        assert len([b for b in app.button if b.label == '✅ 确认本题审核通过']) == 3
        assert len([b for b in app.button if b.label == '❌ 本题放弃录入']) == 3
        year_bulk = [b for b in app.button if b.label.startswith('录入本批')]
        assert len(year_bulk) == 3
        assert len([b for b in app.button if b.label.startswith('录入所有')]) == 3
        assert not [b for b in app.button if b.label == '将已批准题目入库']
        assert 'mc-review-topic' in rendered and 'mc-review-tag' in rendered
        assert '&lt;script&gt;bad&lt;/script&gt;' in rendered
        assert '题干完全相同' in rendered and '题干高度相似' in rendered and '同卷题号已有题目' in rendered, [x.value for x in app.markdown if 'mc-review-notice ' in x.value]
        assert 'data-duplicate-preview-id="Q000001"' in rendered
        assert '差异提示：数字 2→3' in rendered, [x.value for x in app.markdown if 'mc-review-notice ' in x.value]
        assert 'data-question-id="Q000001"' in rendered
        assert '预览读取失败' not in rendered
        options = [x for x in app.text_area if x.label.startswith('选项 ')]
        assert [x.label for x in options] == ['选项 A', '选项 B', '选项 C', '选项 D']
        options[1].set_value('$20$')
        [b for b in app.button if b.label == '保存修改'][1].click().run()
        assert not app.exception, [e.message for e in app.exception]
        edited = next(d for d in paper_drafts(db, nodes, paper['batch_id']) if d['source_item_id'] == 'q10')
        assert json.loads(get_draft_question(db, edited['draft_id'])['choices_json']) == ['$1$', '$20$', '$3$', '$4$']
        ids = [n['batch_id'] for n in nodes if n['label'] == '北京卷' and n['metadata'].get('year') == 2026]
        app.radio(key='ingestion_review_paper').set_value(ids[0]).run()
        assert not app.exception, [e.message for e in app.exception]
        assert any('没有可审核草稿' in x.value for x in app.info)
        app.radio(key='ingestion_review_year').set_value('2025').run()
        assert not app.exception, [e.message for e in app.exception]
        with readonly_database_connection(db) as c:
            assert c.execute('SELECT COUNT(*) FROM question').fetchone()[0] == 2
    print('ingestion_review_ui=ok (task isolation, years, papers, subtree counts, full content, idempotency)')


if __name__ == '__main__':
    main()
