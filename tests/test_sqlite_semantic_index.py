import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from contextlib import closing

from services import semantic_search_service as service


def question(qid, stem="函数求值", path=""):
    return {"SQLite题目ID": qid, "题目ID": "old-" + qid,
            "相对文件路径": path, "题干": stem, "选项": "", "知识板块": "函数"}


class SQLiteSemanticIndexTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.index = str(Path(self.directory.name) / "vectors.sqlite3")
        self.path_patch = patch.object(service, "SEMANTIC_INDEX_PATH", self.index)
        self.path_patch.start()
        self.addCleanup(self.path_patch.stop)
        self.api = patch.object(service, "request_embeddings",
                                side_effect=lambda *args: [[1.0, 0.5] for _ in args[3]])
        self.request = self.api.start()
        self.addCleanup(self.api.stop)
        service._clear_query_cache()

    def build(self, rows, model="test"):
        return service.build_index(rows, "", "secret", model)

    def test_stable_id_missing_file_and_incremental_changes(self):
        rows = [question("Q1"), question("Q2")]
        self.assertEqual(self.build(rows)["updated"], 2)
        with closing(sqlite3.connect(self.index)) as db:
            self.assertEqual(db.execute(
                "SELECT relative_path,question_id FROM semantic_embeddings ORDER BY question_id"
            ).fetchall(), [("sqlite://Q1", "Q1"), ("sqlite://Q2", "Q2")])
        rows[0]["相对文件路径"] = "renamed.tex"
        self.assertEqual(self.build(rows)["updated"], 0)
        rows[1]["题干"] = "不等式证明"
        self.assertEqual(service.coverage_status(rows, "test", sync_pending=True)["pending"], 1)
        self.assertEqual(self.build(rows)["updated"], 1)
        self.assertEqual(service.coverage_status(rows, "test")["covered"], 2)
        self.assertEqual(self.build(rows, model="new-model")["updated"], 2)
        self.assertEqual(self.build(rows[:1], model="new-model")["removed"], 1)

    def test_failed_request_preserves_old_index_and_completed_batches_resume(self):
        rows = [question(f"Q{i}") for i in range(23)]
        self.build([question("old")])
        calls = 0
        def unreliable(*args):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise service.SemanticSearchError("temporary outage")
            return [[1.0, 0.5] for _ in args[3]]
        self.request.side_effect = unreliable
        with self.assertRaises(service.SemanticSearchError):
            self.build(rows)
        self.assertEqual(service.coverage_status(rows, "test")["covered"], 20)
        with closing(sqlite3.connect(self.index)) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM semantic_embeddings WHERE question_id='old'"
            ).fetchone()[0], 1)
        self.request.side_effect = lambda *args: [[1.0, 0.5] for _ in args[3]]
        self.assertEqual(self.build(rows)["updated"], 3)

    def test_changed_vector_is_not_used_in_similarity(self):
        rows = [question("Q1"), question("Q2")]
        self.build(rows)
        self.assertIsNotNone(service.search_similar_row(rows[0], rows, "test")[0]["semantic_score"])
        rows[1]["题干"] = "新的数学条件"
        self.assertIsNone(service.search_similar_row(rows[0], rows, "test")[0]["semantic_score"])
        rows[0]["题干"] = "基准题也已修改"
        self.assertIsNone(service.search_similar_row(rows[0], rows, "test")[0]["semantic_score"])

    def test_query_search_uses_sqlite_keys_and_ignores_changed_content(self):
        rows = [question("Q1"), question("Q2")]
        self.build(rows)
        self.assertEqual(len(service.search("函数", rows, "", "secret", "test")), 2)
        rows[1]["题干"] = "已改变的内容"
        matches = service.search("函数", rows, "", "secret", "test")
        self.assertEqual([item["row"]["SQLite题目ID"] for item in matches], ["Q1"])

    def test_large_bank_does_not_depend_on_sql_variable_limit(self):
        original_connect = service._connect
        def limited_connection():
            conn = original_connect()
            conn.setlimit(sqlite3.SQLITE_LIMIT_VARIABLE_NUMBER, 16)
            return conn
        with patch.object(service, "_connect", limited_connection):
            self.assertEqual(self.build([question(f"Q{i}") for i in range(100)])["updated"], 100)

    def test_bulk_loader_reads_formal_rows_without_legacy_csv(self):
        db_path = Path(self.directory.name) / "main.sqlite3"
        with closing(sqlite3.connect(db_path)) as db:
            db.executescript("""
                CREATE TABLE question(question_id,legacy_id,question_type_id,stem_tex,choices_json,tags_json);
                CREATE TABLE question_type(question_type_id,name);
                CREATE TABLE legacy_question_map(question_id,legacy_file_path,detected_chapter,detected_topic);
                INSERT INTO question_type VALUES(1,'单选题');
                INSERT INTO question VALUES('Q1','',1,'函数题','["甲","乙"]','[]');
                INSERT INTO question VALUES('Q2','',1,'第二题','[]','[]');
                INSERT INTO legacy_question_map VALUES('Q1','old.tex','函数','');
            """)
        rows = service.load_sqlite_index_rows(str(db_path))
        self.assertEqual([row["SQLite题目ID"] for row in rows], ["Q1", "Q2"])
        self.assertEqual(rows[1]["相对文件路径"], "")
        self.assertEqual(rows[0]["选项"], "甲\n乙")
        self.assertEqual(self.build(rows)["updated"], 2)


if __name__ == "__main__":
    unittest.main()
