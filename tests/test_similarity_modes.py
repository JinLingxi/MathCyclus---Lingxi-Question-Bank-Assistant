import sqlite3
import tempfile
import unittest
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from services import semantic_search_service as semantic
from services.sqlite_legacy_adapter import enrich_similarity_metadata, sqlite_summary_to_legacy_row
from services.question_similarity_service import SIM_MAIN_THRESHOLD


def row(qid="Q1", stem=r"已知函数 $f(x)=x^2+2x+1$，求函数的最小值。", type_id=3):
    return {"SQLite题目ID": qid, "题型ID": type_id, "题型": "填空题" if type_id == 3 else "单选题",
            "题干": stem, "选项": "", "知识板块": "函数"}


class SimilarityModesTests(unittest.TestCase):
    def test_modes_keep_relationship_rules_and_recommendation_compatibility(self):
        left, right = row(), row("Q2")
        default = semantic.combined_similarity_score(left, right, 0.7)
        for mode in semantic.SIMILARITY_MODES:
            result = semantic.combined_similarity_score(left, right, 0.7, mode=mode)
            self.assertEqual(result["relationship_kind"], "same_question")
            self.assertAlmostEqual(sum(result["effective_weights"].values()), 1)
        self.assertEqual(default["score"], semantic.combined_similarity_score(
            left, right, 0.7, mode="recommendation")["score"])
        self.assertEqual(SIM_MAIN_THRESHOLD, 0.60)

    def test_semantic_recommendation_does_not_establish_a_relationship(self):
        result = semantic.combined_similarity_score(
            row(), row("Q2", "在三角形中，已知两边的长度和夹角，计算其面积。"), 1.0)
        self.assertFalse(result["relationship_eligible"])

    def test_type_and_options_differences_are_visible(self):
        left, right = row(), row("Q2", type_id=1)
        right["选项"] = "0\n1\n2\n3"
        result = semantic.combined_similarity_score(left, right, 0.99)
        self.assertNotEqual(result["relationship_kind"], "same_question")
        notes = " ".join(result["comparison"]["differences"])
        self.assertIn("题型不同", notes)
        self.assertIn("选项", notes)

    def test_attached_diagram_prevents_unverified_exact_match(self):
        left, right = row(), row("Q2")
        right["配图数量"] = 1
        result = semantic.combined_similarity_score(left, right, 1.0)
        self.assertEqual(result["relationship_kind"], "similar_question")
        self.assertTrue(result["comparison"]["visual_pending"])
        self.assertIn("配图内容尚未比较", result["comparison"]["differences"])

    def test_parameters_and_missing_vector_are_explained(self):
        result = semantic.combined_similarity_score(
            row(), row("Q2", r"已知函数 $f(x)=x^2+3x+1$，求函数的最小值。"), None)
        self.assertTrue(any("数字或参数不同" in note for note in result["comparison"]["differences"]))
        self.assertIn("语义向量未参与", result["comparison"]["unavailable"])
        self.assertNotIn("semantic", result["effective_weights"])

    def test_local_search_propagates_mode_and_sorts_exact_candidates_first(self):
        reference = row()
        with patch.object(semantic, "SEMANTIC_INDEX_PATH", "__missing_test_index__"):
            results = semantic.search_similar_row(
                reference, [row("Q2", "求三角形的面积。"), row("Q3")], "", mode="verification")
        self.assertEqual(results[0]["row"]["SQLite题目ID"], "Q3")
        self.assertTrue(all(item["mode"] == "verification" for item in results))
        with self.assertRaises(ValueError):
            semantic.search_similar_row(reference, [], "", mode="invalid")

    def test_metadata_enrichment_preserves_vectors_and_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "formal.sqlite3"
            with closing(sqlite3.connect(path)) as db:
                db.executescript("""
                    CREATE TABLE knowledge_area(knowledge_area_id,name,sort_order);
                    CREATE TABLE question_knowledge_area(question_id,knowledge_area_id,is_primary);
                    CREATE TABLE question_asset(question_id,role);
                    INSERT INTO knowledge_area VALUES('K1','函数',1),('K2','导数',2);
                    INSERT INTO question_knowledge_area VALUES('Q1','K1',1),('Q1','K2',0);
                    INSERT INTO question_asset VALUES('Q1','stem'),('Q1','solution');
                """)
            before_bytes = path.read_bytes()
            adapted = sqlite_summary_to_legacy_row(
                {"question_id": "Q1", "question_type_id": 3, "stem_tex": "函数求值"},
                question_type_labels={3: "填空题"})
            fingerprint = semantic.row_fingerprint(adapted)
            enriched = enrich_similarity_metadata([adapted], str(path))[0]
            self.assertEqual(enriched["题型ID"], 3)
            self.assertEqual(enriched["关联知识板块"], ["函数", "导数"])
            self.assertEqual(enriched["配图数量"], 1)
            self.assertEqual(semantic.row_fingerprint(enriched), fingerprint)
            self.assertEqual(path.read_bytes(), before_bytes)


if __name__ == "__main__":
    unittest.main()
