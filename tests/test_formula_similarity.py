import unittest
from services.formula_similarity_service import compare_formula_texts
from services.semantic_search_service import combined_similarity_score


class FormulaSimilarityTests(unittest.TestCase):
    def compare(self, left, right):
        return compare_formula_texts("$" + left + "$", "$" + right + "$")

    def test_formatting_and_unicode_exponents_are_normalized(self):
        for left, right in ((r"\dfrac{x+1}{x-1}", r"\frac{x+1}{x-1}"),
                            ("x^2", "x^{2}"), ("x²", "x^2"), (r"x\leq 2", "x≤2")):
            with self.subTest(left=left):
                result = self.compare(left, right)
                self.assertTrue(result["complete"])
                self.assertTrue(result["exact"])
                self.assertEqual(result["literal_score"], 1)

    def test_variable_renaming_preserves_repetition_pattern(self):
        renamed = self.compare("x+x", "y+y")
        different = self.compare("x+x", "y+z")
        self.assertEqual(renamed["structure_score"], 1)
        self.assertLess(different["structure_score"], 1)
        self.assertFalse(renamed["exact"])
        multiple = compare_formula_texts("$x=1$，$x=2$", "$x=1$，$y=2$")
        self.assertLess(multiple["structure_score"], 1)

    def test_parameter_variant_and_exponent_change_are_distinct(self):
        parameter = self.compare("2*x+1", "3*x+1")
        exponent = self.compare("x^2+1", "x^3+1")
        self.assertEqual(parameter["structure_score"], 1)
        self.assertLess(exponent["structure_score"], 1)
        self.assertIn("指数表达式不同", exponent["differences"])

    def test_denominator_grouping_is_preserved(self):
        result = self.compare(r"\frac{x}{x+1}", r"\frac{x}{x}+1")
        self.assertFalse(result["exact"])
        self.assertIn("分母表达式不同", result["differences"])

    def test_operator_and_interval_changes_are_not_simplified(self):
        for left, right, note in (
                ("x<2", r"x\leq 2", "公式关系符号不同"),
                (r"A\cup B", r"A\cap B", "集合运算符不同")):
            result = self.compare(left, right)
            self.assertTrue(result["complete"])
            self.assertFalse(result["exact"])
            self.assertIn(note, result["differences"])
        interval = self.compare("[0,1]", "(0,1)")
        self.assertTrue(interval["complete"])
        self.assertFalse(interval["exact"])
        self.assertIn("区间或有序组的端点、边界不同", interval["differences"])

    def test_order_multiplicity_and_function_groups_are_preserved(self):
        for left, right in (("x+y", "x+x"), ("f(x)", "f*x"),
                            (r"\frac{x}{y}", r"\frac{y}{x}"), ("x^(2+1)", "x^2+1")):
            self.assertFalse(self.compare(left, right)["exact"])
        script = self.compare("x_i^2", "x_{i^2}")
        self.assertTrue(script["complete"])
        self.assertFalse(script["exact"])
        self.assertFalse(self.compare("x^2^3", "x^2^3")["complete"])

    def test_unsupported_or_malformed_math_uses_fallback(self):
        for text in (r"\sum_{i=1}^n i", r"\frac{x}{", "(" * 100 + "x" + ")" * 100,
                     "x+" * 600, r"\sqrt[3]{x}", "x^"):
            with self.subTest(text=text[:20]):
                result = self.compare(text, text)
                self.assertFalse(result["complete"])
                self.assertFalse(result["exact"])
                self.assertEqual(result["method"], "token_fallback")

    def test_functions_style_wrappers_and_interval_boundaries(self):
        cases = (
            (r"\sin^2 x", r"\sin x^2"),
            (r"\log_2 x", r"\log_3 x"),
            (r"x\in[0,1)", r"x\in[0,1]"),
            (r"\vec{a}", "a"),
            (r"x\in\mathbb{R}", r"x\in\mathbb{N}"),
        )
        for left, right in cases:
            with self.subTest(left=left):
                result = self.compare(left, right)
                self.assertTrue(result["complete"])
                self.assertFalse(result["exact"])

    def test_difference_evidence_exists_even_for_short_questions(self):
        result = combined_similarity_score(
            {"题干": "$x^2$", "题型ID": 3}, {"题干": "$x^3$", "题型ID": 3}, 0.95)
        self.assertIn("指数表达式不同", result["comparison"]["differences"])
        self.assertFalse(result["relationship_eligible"])


if __name__ == "__main__":
    unittest.main()
