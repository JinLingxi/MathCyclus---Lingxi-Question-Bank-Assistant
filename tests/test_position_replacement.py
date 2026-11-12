import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from services.database_service import SCHEMA_PATH
from services.position_replacement_service import execute_replacement,merge_response


class PositionReplacementTests(unittest.TestCase):
    def test_response_conflict_preserves_target(self):
        self.assertEqual(merge_response("existing","old"),("existing","conflict"))
        self.assertEqual(merge_response("","old"),("old","copied"))

    def test_atomic_replacement_routes_other_answer_and_recovers_uncertain_old_content(self):
        with tempfile.TemporaryDirectory() as directory:
            conn=sqlite3.connect(Path(directory)/"bank.sqlite3");conn.row_factory=sqlite3.Row
            conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf8"))
            conn.execute("INSERT INTO import_batch(batch_id,import_type,source_path,mode) VALUES ('B','test','test','test')")
            entries=[]
            for index in (1,2):
                qid,did=f"Q{index}",f"D{index}"
                conn.execute("INSERT INTO question(question_id,question_type_id,stem_tex,answer_tex,solution_tex) VALUES (?,4,?,?,?)",
                             (qid,"old"+str(index),"answer"+str(index),"solution"+str(index)))
                conn.execute("INSERT INTO paper(paper_id,year,paper_series,track,paper_name) VALUES (?,2026,'G','',?)",
                             ("P"+str(index),"Paper"+str(index)))
                conn.execute("INSERT INTO paper_question(paper_question_id,paper_id,question_id,question_number) VALUES (?,?,?,'1')",
                             ("PQ"+str(index),"P"+str(index),qid))
                extra=json.dumps({"source_kind":"试卷","detected_year":2026,"paper_series":"G",
                                  "detected_source":"Paper"+str(index),"detected_question_number":"1"})
                conn.execute("INSERT INTO question_import_draft(draft_id,batch_id,question_type_id,stem_tex,extra_json) VALUES (?,'B',4,?,?)",
                             (did,"trusted"+str(index),extra))
                entries.append({"draft_id":did,"question_id":qid,
                    "old":dict(conn.execute("SELECT * FROM question WHERE question_id=?",(qid,)).fetchone()),
                    "draft_before":dict(conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(did,)).fetchone()),
                    "routing_status":"requires_review" if index==1 else "matched_other_draft",
                    "route":None if index==1 else {"draft_id":"D3","formal_question_id":"Q3"}})
            conn.execute("INSERT INTO question(question_id,question_type_id,stem_tex) VALUES ('Q3',4,'actual target')")
            conn.execute("INSERT INTO question_import_draft(draft_id,batch_id,question_type_id,stem_tex,review_status) VALUES ('D3','B',4,'actual target','committed')")
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            result=execute_replacement(conn,{"entries":entries,"test_fixture":True},copy_assets=False)
            self.assertEqual(len(result["replaced"]),2)
            self.assertEqual(conn.execute("SELECT stem_tex FROM question WHERE question_id='Q1'").fetchone()[0],"trusted1")
            self.assertEqual(conn.execute("SELECT answer_tex FROM question WHERE question_id='Q1'").fetchone()[0],"")
            self.assertEqual(conn.execute("SELECT answer_tex FROM question WHERE question_id='Q2'").fetchone()[0],"")
            self.assertEqual(conn.execute("SELECT answer_tex FROM question WHERE question_id='Q3'").fetchone()[0],"answer2")
            recovered=result["recovery"][0]["recovery_draft_id"]
            row=conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(recovered,)).fetchone()
            self.assertEqual(row["stem_tex"],"old1")
            self.assertEqual(row["answer_tex"],"answer1")
            self.assertEqual(row["review_status"],"needs_review")
            self.assertFalse(conn.execute("PRAGMA foreign_key_check").fetchall())
            conn.rollback()
            self.assertEqual(conn.execute("SELECT stem_tex FROM question WHERE question_id='Q1'").fetchone()[0],"old1")
            self.assertIsNone(conn.execute("SELECT * FROM question_import_draft WHERE draft_id=?",(recovered,)).fetchone())
            conn.close()


if __name__=="__main__":unittest.main()
