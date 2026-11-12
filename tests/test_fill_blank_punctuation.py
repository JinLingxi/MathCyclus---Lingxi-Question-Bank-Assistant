import unittest

from services.question_text_format_service import normalize_fill_blank_stop,normalize_choice_blank_stop


class FillBlankPunctuationTests(unittest.TestCase):
    def test_exact_fill_blank_chinese_stop_becomes_ascii(self):
        self.assertEqual(normalize_fill_blank_stop(r"结果为\underline{\hspace{4em}}。"),
                         r"结果为\underline{\hspace{4em}}.")

    def test_other_punctuation_and_math_are_unchanged(self):
        for text in [r"普通句子。",r"\underline{\hspace{3em}}。",
                     r"\underline{\hspace{4em}}，",r"条件为$x>0$。"]:
            self.assertEqual(normalize_fill_blank_stop(text),text)

    def test_choice_rule_and_future_import_fill_rule_coexist(self):
        self.assertEqual(normalize_choice_blank_stop(r"选（\hspace{1cm}）。"),r"选（\hspace{1cm}）")
        self.assertEqual(normalize_choice_blank_stop(r"填\underline{\hspace{4em}}。"),
                         r"填\underline{\hspace{4em}}.")


if __name__=="__main__":unittest.main()
