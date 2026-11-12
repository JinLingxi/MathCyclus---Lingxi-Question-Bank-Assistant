import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from services import asset_service, export_service


class ExportResourceCompatibilityTests(unittest.TestCase):
    def test_shared_reference_parsing_and_lookup_preserve_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "chapters/topic/source.tex"
            source.parent.mkdir(parents=True)
            image = source.parent / "图.png"
            image.write_bytes(b"original")
            text = r"\includegraphics[width=3cm]{图.png}\questionasset{figure_01}"
            self.assertEqual(export_service.find_includegraphics_refs(text), ["图.png"])
            self.assertEqual(export_service.find_questionasset_refs(text), ["figure_01"])
            self.assertEqual(export_service.resolve_graphics_ref("图.png", "chapters/topic/source.tex", root), image)
            self.assertEqual(export_service.resolve_graphics_ref("图.png", str(source), root), image)
            self.assertIsNone(export_service.resolve_asset_path({"source_path": str(image)}, root))
            self.assertEqual(export_service.resolve_asset_path({"file_path": str(image)}, root), image)

    def test_both_copy_paths_keep_collision_suffixes_and_original_bytes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = root / "same.png"
            original.write_bytes(b"original")
            output = root / "export"
            figures = output / "figures"
            figures.mkdir(parents=True)
            (figures / "same.png").write_bytes(b"already exported")
            question = {"question_id": "Q1"}
            text, result = export_service.copy_graphics_for_export(
                question, r"\includegraphics{same.png}", output, root)
            self.assertIn("figures/same-2.png", text)
            self.assertEqual(result[0]["status"], "copied")
            with patch("services.export_service.list_assets", return_value=[
                {"file_path": str(original), "extra_json": '{"alias":"figure"}'}]):
                text, result = export_service.copy_questionassets_for_export(
                    question, r"\questionasset{figure}", output, root, db_path="unused")
            self.assertIn("figures/same-3.png", text)
            self.assertEqual((figures / "same.png").read_bytes(), b"already exported")
            self.assertEqual((figures / "same-2.png").read_bytes(), b"original")
            self.assertEqual((figures / "same-3.png").read_bytes(), b"original")
            self.assertEqual(original.read_bytes(), b"original")


if __name__ == "__main__":
    unittest.main()
