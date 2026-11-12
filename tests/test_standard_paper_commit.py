import sqlite3
import tempfile
import unittest
from pathlib import Path
from services.database_service import SCHEMA_PATH
from services.import_service import _upsert_paper_link_from_draft_conn


class StandardPaperCommitTests(unittest.TestCase):
    def test_confirmed_standard_without_formal_paper_creates_valid_link(self):
        with tempfile.TemporaryDirectory() as directory:
            conn=sqlite3.connect(Path(directory)/"test.sqlite3")
            conn.row_factory=sqlite3.Row
            conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("INSERT INTO question(question_id,stem_tex) VALUES ('Q1','test')")
            conn.execute("INSERT INTO paper_standard_catalog(paper_standard_id,year,paper_series,paper_name) VALUES ('S1',2026,'G','test paper')")
            draft={"extra_json":'{"source_kind":"试卷","paper_standard_id":"S1","detected_question_number":"1"}'}
            link=_upsert_paper_link_from_draft_conn(conn,"Q1",draft)
            row=conn.execute("SELECT * FROM paper_question WHERE paper_question_id=?",(link,)).fetchone()
            self.assertIsNotNone(row)
            self.assertNotEqual(row["paper_id"],"None")
            self.assertEqual(conn.execute("SELECT paper_id FROM paper_standard_catalog WHERE paper_standard_id='S1'").fetchone()[0],row["paper_id"])
            self.assertEqual(conn.execute("PRAGMA foreign_key_check").fetchall(),[])
            conn.close()


if __name__=="__main__":unittest.main()
