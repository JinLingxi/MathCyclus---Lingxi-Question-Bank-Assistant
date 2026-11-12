import unittest

from services.question_similarity_service import score_question_pair


class SimilarityReviewDetailsTests(unittest.TestCase):
    def test_unknown_math_commands_are_not_exact(self):
        result = score_question_pair(r"求 $\sin{x}$ 的值。", r"求 $\cos{x}$ 的值。")
        self.assertEqual(result["kind"], "similar")

    def test_option_interval_and_function_changes_are_not_exact(self):
        for left, right in [("[0,1)", "(0,1)"), (r"\sin{x}", r"\cos{x}")]:
            with self.subTest(left=left):
                result = score_question_pair("求值", "求值", left_choices=[left], right_choices=[right])
                self.assertEqual(result["kind"], "similar")

    def test_images_in_options_require_visual_review(self):
        result = score_question_pair("选择正确图像", "选择正确图像",
                                     left_choices=[r"\questionasset{a}"],
                                     right_choices=[r"\questionasset{a}"])
        self.assertEqual(result["kind"], "similar")
        self.assertEqual(result["differences"][-1]["kind"], "visual_pending")

    def test_legacy_scan_cannot_bypass_option_check(self):
        from services.question_service import scan_duplicate_pairs, PATH_FIELD, STEM_FIELD, TYPE_FIELD
        rows = [{PATH_FIELD: "a.tex", STEM_FIELD: "求函数值", TYPE_FIELD: "1", "choices_json": '["1", "2"]'},
                {PATH_FIELD: "b.tex", STEM_FIELD: "求函数值", TYPE_FIELD: "1", "choices_json": '["1", "3"]'}]
        result = scan_duplicate_pairs(rows=rows)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["kind"], "similar")
        self.assertEqual(result[0]["left"]["differences"][0]["kind"], "choices")

    def test_unchanged_nonvisual_question_remains_exact(self):
        result = score_question_pair("求函数的最小值。", "求函数的最小值。")
        self.assertEqual(result["kind"], "exact")

    def test_equivalent_fraction_presentation_remains_exact(self):
        result = score_question_pair(r"求 $\dfrac{1}{2}$。", r"求 $\frac{1}{2}$。")
        self.assertEqual(result["kind"], "exact")

    def test_same_choice_stem_with_changed_option_is_not_exact(self):
        result = score_question_pair(
            "已知函数，求其最小值。", "已知函数，求其最小值。",
            left_choices=["A. 1", "B. 2"], right_choices=["A. 1", "B. 3"],
            left_question_type_id=1, right_question_type_id=1,
        )
        self.assertEqual(result["kind"], "similar")
        self.assertIn("选项", result["reasons"][0])
        self.assertEqual(result["differences"][0]["kind"], "choices")

    def test_small_numeric_change_is_reported(self):
        left = r"在给定条件和相同背景下，求方程 $x+2=5$ 的全部实数解。"
        right = r"在给定条件和相同背景下，求方程 $x+3=5$ 的全部实数解。"
        result = score_question_pair(left, right)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("数字内容存在变化", result["reasons"])
        self.assertEqual(result["differences"][0]["kind"], "numbers")
        self.assertEqual(result["differences"][0]["left"], ["2"])
        self.assertEqual(result["differences"][0]["right"], ["3"])

    def test_relation_change_is_reported(self):
        left = r"在给定条件和相同背景下，对任意 $x\in[0,1)$，都有 $x<2$。"
        right = r"在给定条件和相同背景下，对任意 $x\in[0,1)$，都有 $x\le2$。"
        result = score_question_pair(left, right)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("关系符号有变化", result["reasons"])

    def test_variable_change_is_not_hidden_by_text_normalization(self):
        left = r"在给定条件和相同背景下，对任意 $x\in[0,1)$，都有 $x<2$。"
        right = r"在给定条件和相同背景下，对任意 $y\in[0,1)$，都有 $y<2$。"
        result = score_question_pair(left, right)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("变量符号集合存在变化", result["reasons"])
        self.assertIn("variables", [item["kind"] for item in result["differences"]])

    def test_quantifier_change_is_reported(self):
        left = r"在给定条件和相同背景下，对任意 $x\in[0,1)$，都有 $x<2$。"
        right = r"在给定条件和相同背景下，存在 $x\in[0,1)$，有 $x<2$。"
        result = score_question_pair(left, right)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("条件词有变化", result["reasons"])

    def test_interval_open_closed_change_is_not_exact(self):
        left = r"在给定条件和相同背景下，对任意 $x\in[0,1)$，都有 $x<2$。"
        right = r"在给定条件和相同背景下，对任意 $x\in(0,1)$，都有 $x<2$。"
        result = score_question_pair(left, right)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("区间端点或开闭边界有变化", result["reasons"])

    def test_same_stem_with_image_placeholder_requires_visual_review(self):
        result = score_question_pair(r"如图求值。\questionasset{figure_a}",
                                     r"如图求值。\questionasset{figure_b}")
        self.assertEqual(result["kind"], "similar")
        self.assertIn("题文相同但配图像素未参与比较", result["reasons"])
        self.assertEqual(result["differences"][-1]["kind"], "visual_pending")

    def test_same_text_with_different_question_type_is_not_exact(self):
        result = score_question_pair("给定函数并求值。", "给定函数并求值。",
                                     left_question_type_id=1, right_question_type_id=4)
        self.assertEqual(result["kind"], "similar")
        self.assertIn("题干与内容相同，但题型标记不同", result["reasons"])


if __name__ == "__main__":
    unittest.main()
