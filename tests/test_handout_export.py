import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services.handout_export_service import export_handout


class HandoutExportTests(unittest.TestCase):
    def test_sample_variants_create_new_document_without_overwriting(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "training"
            result = export_handout(output, sample=True, training=True, monochrome=True, title="训练 & 复习")
            self.assertFalse(result["database_modified"])
            self.assertIn("[training,monochrome]", (output / "main.tex").read_text(encoding="utf-8"))
            self.assertIn(r"训练 \& 复习", (output / "main.tex").read_text(encoding="utf-8"))
            self.assertTrue((output / "mathcyclus-handout.sty").is_file())
            with self.assertRaises(FileExistsError):
                export_handout(output, sample=True)

    def test_formal_question_fields_are_exported_verbatim_and_missing_answers_allowed(self):
        question = {"question_id": "Q1", "stem_tex": r"求 $\frac{1}{2}$。",
                    "choices_json": '["$1$", "$2$"]', "answer_tex": "", "solution_tex": ""}
        with tempfile.TemporaryDirectory() as directory, \
             patch("services.handout_export_service.get_question", return_value=question), \
             patch("services.export_service.list_assets", return_value=[]):
            output = Path(directory) / "handout"
            export_handout(output, question_ids=["Q1"])
            body = (output / "body.tex").read_text(encoding="utf-8")
            self.assertIn(question["stem_tex"], body)
            self.assertIn(r"\choice{{$1$}}", body)
            self.assertIn(r"\begin{answer}", body)

    def test_missing_figures_abort_without_publishing_partial_export(self):
        question = {"question_id": "Q1", "stem_tex": r"\questionasset{missing}", "answer_tex": "", "solution_tex": ""}
        with tempfile.TemporaryDirectory() as directory, \
             patch("services.handout_export_service.get_question", return_value=question), \
             patch("services.export_service.list_assets", return_value=[]):
            output = Path(directory) / "handout"
            with self.assertRaises(ValueError):
                export_handout(output, question_ids=["Q1"])
            self.assertFalse(output.exists())

    def test_duplicate_selection_and_mixed_sample_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "handout"
            for arguments in ({"question_ids": ["Q1", "Q1"]},
                              {"question_ids": ["Q1"], "sample": True}, {}):
                with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                    export_handout(output, **arguments)
