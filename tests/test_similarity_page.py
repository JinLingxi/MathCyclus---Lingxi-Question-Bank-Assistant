"""Exercise the actual page function without booting the entire application."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch

from streamlit.testing.v1 import AppTest


class SimilarityPageTests(unittest.TestCase):
    def test_mode_change_hides_old_results_and_differences_render(self):
        source = Path(__file__).resolve().parents[1] / "question_bank_app.py"
        module = ast.parse(source.read_text(encoding="utf-8-sig"))
        node = next(node for node in module.body
                    if isinstance(node, ast.FunctionDef) and node.name == "render_similar_questions_page")
        page = ast.unparse(node)
        prefix = """
import html
import json
import streamlit as st
from services.semantic_search_service import search_similar_row as semantic_search_similar_row, SemanticSearchError
_semantic_api_config = lambda: {"model_name": ""}
_db_preview_json_list = json.loads
_cached_latex_to_markdown = lambda text: text
_render_preview_with_inline_assets = lambda text: st.markdown(text)
"""
        rows = [
            {"SQLite题目ID": "Q1", "题型ID": 3, "题型": "填空题", "题干": "已知函数的解析式为二次函数，求函数的最小值。",
             "选项": "", "知识板块": "函数"},
            {"SQLite题目ID": "Q2", "题型ID": 1, "题型": "单选题", "题干": "已知函数的解析式为二次函数，求函数的最小值。",
             "选项": "0\n1\n2\n3", "知识板块": "函数", "配图数量": 1},
        ]
        options = {"years": [], "sources": [], "all_question_types": [], "difficulties": [], "chapters": []}
        def bundle(db_path, qid):
            selected = next(row for row in rows if row["SQLite题目ID"] == qid)
            return {"question": {"choices_json": "[]"}, "row": selected}
        with (patch("services.sqlite_legacy_adapter.list_sqlite_legacy_rows", return_value=rows),
              patch("services.sqlite_legacy_adapter.sqlite_bundle_to_legacy_card", side_effect=lambda value: value),
              patch("services.question_db_service.list_question_filter_options", return_value=options),
              patch("services.question_db_service.get_question_bundle", side_effect=bundle)):
            app = AppTest.from_string(prefix + "\n" + page + "\nrender_similar_questions_page()").run()
            self.assertFalse(app.exception)
            app.selectbox[0].set_value("Q1").run()
            next(button for button in app.button if button.label == "查找相似题").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("选项" in text.value for text in app.text))
            self.assertTrue(any("配图" in text.value for text in app.text))
            self.assertTrue(any("推荐相关度" in text.value for text in app.markdown))
            app.radio[0].set_value("verification").run()
            self.assertFalse(app.exception)
            self.assertFalse(any("推荐相关度" in text.value for text in app.markdown))
            next(button for button in app.button if button.label == "查找相似题").click().run()
            self.assertFalse(app.exception)
            self.assertTrue(any("核对相关度" in text.value for text in app.markdown))


if __name__ == "__main__":
    unittest.main()
