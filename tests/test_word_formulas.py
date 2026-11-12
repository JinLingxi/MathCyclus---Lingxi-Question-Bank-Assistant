import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

from services.word_formula_service import M, W, omml_to_latex, read_docx_formula_paragraphs


class WordFormulaTests(unittest.TestCase):
    def test_nested_fraction_root_and_superscript(self):
        xml = f'''<m:oMath xmlns:m="{M}"><m:f><m:num><m:sSup><m:e><m:r><m:t>x</m:t></m:r></m:e><m:sup><m:r><m:t>2</m:t></m:r></m:sup></m:sSup></m:num><m:den><m:rad><m:deg/><m:e><m:r><m:t>3</m:t></m:r></m:e></m:rad></m:den></m:f></m:oMath>'''
        self.assertEqual(omml_to_latex(ET.fromstring(xml)), r"\frac{{x}^{2}}{\sqrt{3}}")

    def test_docx_order_and_unsupported_objects_are_visible(self):
        xml = f'''<w:document xmlns:w="{W}" xmlns:m="{M}"><w:body><w:p><w:r><w:t>题干</w:t></w:r><m:oMath><m:r><m:t>x</m:t></m:r></m:oMath><w:r><w:br/></w:r><m:oMath><m:nary/></m:oMath><w:r><w:object/></w:r></w:p></w:body></w:document>'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "test.docx"
            with ZipFile(path, "w") as archive:
                archive.writestr("word/document.xml", xml)
            result = read_docx_formula_paragraphs(path)
        self.assertEqual(result["equation_count"], 2)
        self.assertTrue(result["requires_human_review"])
        self.assertTrue(result["paragraphs"][0]["tex"].startswith("题干$x$  \n"))
        self.assertIn("公式待复核", result["paragraphs"][0]["tex"])
        self.assertEqual([d["kind"] for d in result["diagnostics"]], ["unsupported_omml", "embedded_object"])
        self.assertIn("nary", result["diagnostics"][0]["xml"])

    def test_math_special_characters_are_escaped(self):
        node = ET.fromstring(f'<m:t xmlns:m="{M}">a_b%{{c}}</m:t>')
        self.assertEqual(omml_to_latex(node), r"a\_b\%\{c\}")


if __name__ == "__main__":
    unittest.main()
