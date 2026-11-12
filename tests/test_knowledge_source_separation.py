import tempfile
import unittest
from pathlib import Path

from services.database_service import database_connection, SCHEMA_PATH
from services.question_db_service import get_question_bundle


class KnowledgeSourceSeparationTests(unittest.TestCase):
    def test_book_appearance_does_not_assign_knowledge_and_inverse(self):
        with tempfile.TemporaryDirectory() as directory:
            db = str(Path(directory) / "test.sqlite3")
            with database_connection(db) as conn:
                conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
            with database_connection(db) as conn:
                conn.execute("INSERT INTO question(question_id, stem_tex) VALUES ('q', 'test')")
                conn.execute("INSERT INTO book(book_id, title) VALUES ('b', 'textbook')")
                conn.execute("INSERT INTO book_exercise_question(book_exercise_question_id,book_id,question_id) VALUES ('l','b','q')")
            bundle = get_question_bundle(db, "q")
            self.assertEqual(len(bundle["book_links"]), 1)
            self.assertEqual(bundle["knowledge_areas"], [])
            with database_connection(db) as conn:
                conn.execute("INSERT INTO knowledge_area(knowledge_area_id,name) VALUES ('k','algebra')")
                conn.execute("INSERT INTO question_knowledge_area(question_id,knowledge_area_id,is_primary,source,confidence) VALUES ('q','k',1,'migration',0.7)")
                conn.execute("DELETE FROM book_exercise_question")
            bundle = get_question_bundle(db, "q")
            self.assertEqual(bundle["book_links"], [])
            self.assertEqual(bundle["knowledge_areas"][0]["source"], "migration")
            self.assertEqual(bundle["knowledge_areas"][0]["confidence"], 0.7)
            self.assertEqual(bundle["knowledge_areas"][0]["is_primary"], 1)


if __name__ == "__main__":
    unittest.main()
