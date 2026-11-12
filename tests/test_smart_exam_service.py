import json
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from contextlib import contextmanager

from services.smart_exam_service import (CandidateOptions, build_candidate_pool, load_exam_rows,
    plan_selection, ensure_plan_current, question_ref)
from services.question_db_service import QuestionListFilters
from services.exam_basket_service import (materialize_exam_blocks, upgrade_basket_refs,
                                         increment_sqlite_exam_usage)

ROOT = Path(__file__).resolve().parents[1]


class SmartExamTests(unittest.TestCase):
    @contextmanager
    def connection(self):
        conn=sqlite3.connect(self.db)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.db = str(self.root / "bank.sqlite3")
        with self.connection() as conn:
            conn.executescript((ROOT / "db/schema.sql").read_text(encoding="utf-8"))
            conn.execute("DELETE FROM question_type")
            conn.execute("DELETE FROM knowledge_area")
            for index, code in enumerate(("single_choice", "multiple_choice", "fill_blank", "solution"), 1):
                conn.execute("INSERT INTO question_type(question_type_id,code,name) VALUES(?,?,?)", (index, code, code))
            for name in ("集合", "函数", "新增板块"):
                conn.execute("INSERT INTO knowledge_area(knowledge_area_id,name) VALUES(?,?)", (name, name))
        self.add("Q000001", 1, 1, "集合", 2000)
        self.add("Q000002", 2, 3, "函数", 2024)
        self.add("Q000003", 3, None, "新增板块", 2024)
        self.add("Q000004", 4, 5, "函数", 2024)
        self.add("Q009999", 1, 3, "新增板块", 2025)
        with self.connection() as conn:
            conn.execute("INSERT INTO question_knowledge_area(question_id,knowledge_area_id,is_primary) VALUES(?,?,0)", ("Q000002","新增板块"))

    def tearDown(self):
        self.temp.cleanup()

    def add(self, qid, kind, difficulty, subject, year, stem=None, choices="[]"):
        with self.connection() as conn:
            conn.execute("INSERT INTO question(question_id,question_type_id,stem_tex,choices_json,difficulty) VALUES(?,?,?,?,?)",
                         (qid,kind,stem or "题目 "+qid,choices,difficulty))
            conn.execute("INSERT INTO legacy_question_map(question_id,legacy_file_path,detected_year,detected_chapter,detected_source) VALUES(?,?,?,?,?)",
                         (qid,"missing/"+qid+".tex",year,subject,"测试卷"))
            conn.execute("INSERT INTO question_knowledge_area(question_id,knowledge_area_id,is_primary) VALUES(?,?,1)",(qid,subject))

    def test_full_bank_filters_before_cap_and_retains_formal_type(self):
        pool = build_candidate_pool(self.db, filters=QuestionListFilters(year=2025), limit=1)
        self.assertEqual([r["question_id"] for r in pool["rows"]], ["Q009999"])
        pool = build_candidate_pool(self.db, limit=0)
        self.assertEqual(next(r for r in pool["rows"] if r["question_id"]=="Q000002")["type_code"],"multiple_choice")

    def test_added_knowledge_and_primary_matching_are_distinct(self):
        full = load_exam_rows(self.db, options=CandidateOptions(subjects=("新增板块",)))
        primary = load_exam_rows(self.db, options=CandidateOptions(subjects=("新增板块",),primary_only=True))
        self.assertIn("Q000002", {r["question_id"] for r in full})
        self.assertNotIn("Q000002", {r["question_id"] for r in primary})
        inherited = load_exam_rows(self.db, QuestionListFilters(chapter="新增板块"))
        self.assertIn("Q000002", {r["question_id"] for r in inherited})

    def test_unknown_is_not_easy_and_constraints_do_not_silently_relax(self):
        rows = load_exam_rows(self.db, options=CandidateOptions(minimum_difficulty=1,maximum_difficulty=1,include_unknown=False))
        self.assertEqual([r["question_id"] for r in rows],["Q000001"])
        pool = build_candidate_pool(self.db, limit=0)
        plan = plan_selection(pool,target_count=1,quotas={"fill_blank":1},unknown_limit=0)
        self.assertFalse(plan["ready"])
        self.assertEqual(plan["shortages"],[{"type":"填空题","missing":1}])
        self.assertEqual(plan["rows"],[])

    def test_type_quota_reservation_keeps_rare_types_in_small_pool(self):
        pool = build_candidate_pool(self.db,limit=2,quotas={"single_choice":1,"multiple_choice":1})
        plan = plan_selection(pool,target_count=2,quotas={"single_choice":1,"multiple_choice":1})
        self.assertTrue(plan["ready"])
        self.assertEqual({r["type_code"] for r in plan["rows"]},{"single_choice","multiple_choice"})

    def test_pinned_questions_and_order_survive_outside_filter(self):
        pool = build_candidate_pool(self.db,filters=QuestionListFilters(year=2025),limit=0)
        pinned = load_exam_rows(self.db,question_ids=["Q000001"])
        plan = plan_selection(pool,target_count=2,pinned_rows=pinned)
        self.assertTrue(plan["ready"])
        self.assertEqual([r["question_id"] for r in plan["rows"]],["Q000001","Q009999"])
        self.assertTrue(plan["warnings"])

    def test_exact_content_and_confirmed_equivalence_are_deduplicated(self):
        self.add("Q000010",1,1,"集合",2000,stem="题目 Q000001")
        with self.connection() as conn:
            conn.execute("INSERT INTO question_equivalence(equivalence_id,question_id_a,question_id_b,relation_type,review_status) VALUES('EQ','Q000004','Q009999','same_question','approved')")
        pool = build_candidate_pool(self.db,limit=0)
        ids={r["question_id"] for r in pool["rows"]}
        self.assertEqual(len(ids.intersection({"Q000010","Q000001"})),1)
        self.assertEqual(len(ids.intersection({"Q000004","Q009999"})),1)

    def test_exclusions_and_plan_freshness(self):
        pool=build_candidate_pool(self.db,limit=0)
        plan=plan_selection(pool,target_count=2,excluded_ids=["Q009999"])
        self.assertNotIn("Q009999",{r["question_id"] for r in plan["rows"]})
        with self.connection() as conn:
            conn.execute("UPDATE question SET stem_tex='changed' WHERE question_id=?",(plan["rows"][0]["question_id"],))
        with self.assertRaises(ValueError):
            ensure_plan_current(self.db,plan["rows"])

    def test_same_text_different_registered_images_are_not_collapsed(self):
        self.add("Q000010",1,1,"集合",2000,stem="图形题")
        self.add("Q000011",1,1,"集合",2000,stem="图形题")
        with self.connection() as conn:
            for qid,digest in [("Q000010","a"*64),("Q000011","b"*64)]:
                conn.execute("INSERT INTO question_asset(asset_id,question_id,role,file_path,file_hash) VALUES(?,?,?,?,?)",(qid,qid,"problem",qid+".png",digest))
        ids={r["question_id"] for r in build_candidate_pool(self.db,limit=0)["rows"]}
        self.assertTrue({"Q000010","Q000011"}.issubset(ids))

    def test_sqlite_only_question_materializes_images_without_changing_content(self):
        from PIL import Image
        image=self.root/"figure_01.png"
        Image.new("RGB",(20,20),"white").save(image)
        with self.connection() as conn:
            conn.execute("UPDATE question SET stem_tex=? WHERE question_id='Q009999'",(r"题图\questionasset{figure_01}",))
            conn.execute("INSERT INTO question_asset(asset_id,question_id,role,file_path) VALUES('A','Q009999','problem',?)",
                         (str(image),))
            before=conn.execute("SELECT * FROM question ORDER BY question_id").fetchall()
        blocks=[{"type":"question","path":question_ref("Q009999"),"selection_ref":question_ref("Q009999")}]
        prepared=materialize_exam_blocks(self.db,blocks,self.root)
        text=Path(prepared[0]["path"]).read_text(encoding="utf-8")
        self.assertIn(r"\includegraphics{",text)
        self.assertNotIn(r"\questionasset{",text)
        self.assertTrue(list(Path(prepared[0]["path"]).parent.glob("figures/*.png")))
        materialize_exam_blocks(self.db,blocks,self.root)
        self.assertEqual(len(list(Path(prepared[0]["path"]).parent.glob("figures/*.png"))),1)
        with self.connection() as conn:
            self.assertEqual(before,conn.execute("SELECT * FROM question ORDER BY question_id").fetchall())

    def test_upgrade_legacy_refs_and_usage_only_modify_counter(self):
        result=upgrade_basket_refs(self.db,[str(self.root/"missing/Q000001.tex")],self.root)
        self.assertEqual(result,[question_ref("Q000001")])
        with self.connection() as conn:
            before=conn.execute("SELECT stem_tex,choices_json,question_type_id FROM question WHERE question_id='Q000001'").fetchone()
        self.assertEqual(increment_sqlite_exam_usage(self.db,["Q000001","Q000001"]),1)
        with self.connection() as conn:
            self.assertEqual(before,conn.execute("SELECT stem_tex,choices_json,question_type_id FROM question WHERE question_id='Q000001'").fetchone())
            self.assertEqual(conn.execute("SELECT usage_count FROM question WHERE question_id='Q000001'").fetchone()[0],1)

    def test_legacy_blocks_do_not_require_a_sqlite_database(self):
        blocks=[{"type":"question","path":str(self.root/"legacy.tex"),"score":5}]
        self.assertEqual(materialize_exam_blocks(str(self.root/"absent.sqlite3"),blocks,self.root),blocks)

    def test_relation_changes_invalidate_existing_plan(self):
        rows=load_exam_rows(self.db,question_ids=["Q000001","Q009999"])
        with self.connection() as conn:
            conn.execute("INSERT INTO question_equivalence(equivalence_id,question_id_a,question_id_b,relation_type,review_status) VALUES('EQ','Q000001','Q009999','same_question','approved')")
        with self.assertRaises(ValueError):
            ensure_plan_current(self.db,rows)

    def test_final_exam_exports_sqlite_only_question_using_formal_type(self):
        import question_bank_app as app
        import services.database_service as database
        template=self.root/"Test Paper Group"/"主题模板"/"试卷类模板"
        template.mkdir(parents=True)
        (template/"试卷类模板.tex").write_text(
            r"\documentclass{article}\begin{document}\section{placeholder}\end{document}",encoding="utf-8")
        blocks=[{"type":"question","path":question_ref("Q000004"),"selection_ref":question_ref("Q000004")}]
        with patch.object(database,"DEFAULT_DATABASE_PATH",self.db),patch.object(app,"BASE_DIR",str(self.root)):
            output=app.generate_exam_paper("test",str(self.root/"exports"),blocks,"试卷类模板")
        self.assertTrue(output)
        tex=Path(output).read_text(encoding="utf-8")
        self.assertIn(r"\begin{problem}[points = 12]",tex)
        self.assertNotIn(r"\begin{question}",tex)

    def test_standard_paper_retains_existing_solution_points(self):
        import question_bank_app as app
        import services.database_service as database
        groups={1:["Q000001","Q009999"],2:["Q000002"],3:["Q000003"],4:["Q000004"]}
        targets={1:8,2:3,3:3,4:5}
        for kind,count in targets.items():
            for index in range(count-len(groups[kind])):
                qid=f"Q{kind}TEST{index}"
                self.add(qid,kind,3,"集合",2025)
                groups[kind].append(qid)
        template=self.root/"Test Paper Group"/"主题模板"/"试卷类模板"
        template.mkdir(parents=True)
        (template/"试卷类模板.tex").write_text(
            r"\documentclass{article}\begin{document}\section{placeholder}\end{document}",encoding="utf-8")
        blocks=[{"type":"question","path":question_ref(qid),"selection_ref":question_ref(qid)}
                for kind in targets for qid in groups[kind]]
        with patch.object(database,"DEFAULT_DATABASE_PATH",self.db),patch.object(app,"BASE_DIR",str(self.root)):
            output=app.generate_exam_paper("standard",str(self.root/"exports"),blocks,"试卷类模板")
        tex=Path(output).read_text(encoding="utf-8")
        self.assertEqual(tex.count(r"\begin{problem}[points = 13]"),1)
        self.assertEqual(tex.count(r"\begin{problem}[points = 15]"),2)
        self.assertEqual(tex.count(r"\begin{problem}[points = 17]"),2)


if __name__=="__main__":
    unittest.main()
