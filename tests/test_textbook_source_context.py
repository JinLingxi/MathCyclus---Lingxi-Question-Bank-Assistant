import json,sqlite3,unittest,tempfile
from pathlib import Path
from services.import_service import _upsert_book_link_from_draft_conn
from services.export_service import _apply_source_context,_book_position_label
from utils.latex_ops import latex_to_markdown

class TextbookContextTests(unittest.TestCase):
    def test_chapter_section_column_and_group_survive_independently(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        db.executescript((Path(__file__).resolve().parents[1]/'db/schema.sql').read_text(encoding='utf8'))
        db.execute("INSERT INTO question(question_id) VALUES('q')")
        extra=dict(source_kind='教材',book_title='人教A版高中数学',book_volume='必修第一册',book_section_title='1.1 集合的概念',
            book_section_path=['第一章 集合与常用逻辑用语','1.1 集合的概念'],book_column_name='习题1.1',book_exercise_number='2',
            book_page_number=5,book_display_order=12010,book_source_note=dict(group_name='复习巩固'))
        _upsert_book_link_from_draft_conn(db,'q',dict(extra_json=json.dumps(extra,ensure_ascii=False)))
        row=dict(db.execute('SELECT beq.*,s.title AS section_title FROM book_exercise_question beq JOIN book_section s USING(section_id)').fetchone())
        self.assertEqual(row['column_name'],'习题1.1');self.assertEqual(row['section_title'],'1.1 集合的概念')
        self.assertEqual(row['display_order'],12010);self.assertEqual(db.execute('SELECT COUNT(*) FROM book_section').fetchone()[0],2)
        self.assertEqual(_book_position_label(row),'1.1 集合的概念·P5·习题1.1·复习巩固·2')
        rendered=_apply_source_context('book',dict(detected_topic='集合'),dict(title='人教A版高中数学',volume='必修第一册'),row)
        self.assertEqual(rendered['detected_topic'],'集合');self.assertEqual(rendered['detected_year'],'必修第一册')
        self.assertEqual(rendered['detected_source'],'人教A版高中数学')
        _upsert_book_link_from_draft_conn(db,'q',dict(extra_json=json.dumps(extra,ensure_ascii=False)))
        self.assertEqual(db.execute('SELECT COUNT(*) FROM book_exercise_question').fetchone()[0],1)
        db.close()

    def test_book_header_and_existing_paper_header(self):
        self.assertIn('人教A版高中数学·必修第一册｜1.1·P4·例2',latex_to_markdown(r'\begin{problem}{必修第一册}{BK}{人教A版高中数学}{1.1·P4·例2}{集合}题干\end{problem}'))
        self.assertIn('2025  全国I卷，1',latex_to_markdown(r'\begin{problem}{2025}{G}{全国I卷}{1}{集合}题干\end{problem}'))

    def test_software_input_caret_is_literal_and_math_is_preserved(self):
        text=latex_to_markdown(r'输入“\texttt{y=x\textasciicircum 3}”，对应图象为 $y=x^{3}$。')
        self.assertIn('<code>y=x^3</code>',text)
        self.assertIn('$y=x^{3}$',text)

    def test_generic_question_reference_uses_book_context_without_paper(self):
        from services.question_db_service import get_question
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.sqlite3'
            with sqlite3.connect(path) as db:
                db.row_factory=sqlite3.Row
                db.executescript((Path(__file__).resolve().parents[1]/'db/schema.sql').read_text(encoding='utf8'))
                db.execute("INSERT INTO question(question_id,stem_tex) VALUES('q','原题')")
                _upsert_book_link_from_draft_conn(db,'q',dict(extra_json=json.dumps(dict(source_kind='教材',book_title='人教A版高中数学',book_volume='必修第一册',
                    book_section_title='1.1 集合的概念',book_column_name='例题',book_exercise_number='2',book_page_number=4),ensure_ascii=False)))
            db.close()
            result=get_question(str(path),'q')
            self.assertEqual(result['paper_series'],'BK')
            self.assertEqual(result['detected_year'],'必修第一册')
            self.assertEqual(result['detected_question_number'],'1.1 集合的概念·P4·例题·2')
            self.assertEqual(result['stem_tex'],'原题')

    def test_chapter_filter_includes_subsections_and_keeps_original_page_order(self):
        from services.book_service import list_book_questions,count_book_questions,list_book_sections
        from services.export_service import get_source_export_bundle
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'book.sqlite3'
            with sqlite3.connect(path) as db:
                db.executescript((Path(__file__).resolve().parents[1]/'db/schema.sql').read_text(encoding='utf8'))
                db.execute("INSERT INTO book(book_id,title,volume) VALUES('b','人教A版高中数学','必修第一册')")
                db.execute("INSERT INTO book_section(section_id,book_id,title,sort_order) VALUES('parent','b','1.4',17)")
                db.execute("INSERT INTO book_section(section_id,book_id,parent_section_id,title,sort_order) VALUES('child','b','parent','1.4.2',20)")
                for qid,sid,page,order in [('early','child',22,22013),('later','parent',22,22017),('last','parent',23,23018)]:
                    db.execute('INSERT INTO question(question_id,stem_tex) VALUES(?,?)',(qid,qid))
                    db.execute('INSERT INTO book_exercise_question(book_exercise_question_id,book_id,section_id,question_id,page_number,display_order) VALUES(?,?,?,?,?,?)',(qid,'b',sid,qid,page,order))
            db.close()
            expected=['early','later','last']
            self.assertEqual([r['question_id'] for r in list_book_questions(str(path),'b','parent')],expected)
            self.assertEqual(count_book_questions(str(path),'b','parent'),3)
            counts={r['section_id']:r['question_link_count'] for r in list_book_sections(str(path),'b')}
            self.assertEqual(counts,dict(parent=3,child=1))
            self.assertEqual([r['question_id'] for r in get_source_export_bundle(str(path),'book','b',section_id='parent')['items']],expected)

if __name__=='__main__':unittest.main()
