import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.audit_ingestion_references import audit, literal_directory_matches, file_directory_matches


class IngestionReferenceAuditTests(unittest.TestCase):
    def test_large_payload_reference_across_chunk_boundary(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "payload.json"
            path.write_text("x" * (1024 * 1024 - 8) + "/codex_2024_restart_v2/image.png", encoding="utf-8")
            self.assertEqual(file_directory_matches(path, ["codex_2024_restart", "codex_2024_restart_v2"]),
                             ["codex_2024_restart_v2"])

    def test_windows_json_paths_and_directory_boundaries(self):
        names = ["codex_2024_restart", "codex_2024_restart_v2"]
        self.assertEqual(literal_directory_matches(
            r'D:\\project\\data\\imports\\codex_2024_restart_v2\\image.png', names),
            ["codex_2024_restart_v2"])
        self.assertEqual(literal_directory_matches("data/imports/codex_2024_restart/a.png", names),
                         ["codex_2024_restart"])

    def test_database_json_and_external_source_refs_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ("year_a", "year_b", "unknown"):
                task = root / "data" / "imports" / name
                task.mkdir(parents=True)
                (task / "image.png").write_bytes(b"image")
            conn = sqlite3.connect(root / "data" / "mathcyclus.sqlite3")
            conn.execute("CREATE TABLE question_import_draft(draft_id TEXT,extra_json TEXT)")
            conn.execute("INSERT INTO question_import_draft VALUES (?,?)",
                         ("draft", json.dumps({"question_crop_paths": ["data/imports/year_a/image.png"]})))
            conn.commit()
            conn.close()
            scripts = root / "scripts"
            scripts.mkdir()
            marker = root / "must_not_execute"
            (scripts / "historical.py").write_text(
                "SOURCE='data/imports/year_b/image.png'\nraise RuntimeError('must not execute')",
                encoding="utf-8")
            report = audit(root)
            by_path = {row["directory"]: row for row in report["directories"]}
            self.assertEqual(by_path["data/imports/year_a"]["database_count"], 1)
            self.assertEqual(by_path["data/imports/year_b"]["external_text_count"], 1)
            self.assertEqual(by_path["data/imports/unknown"]["decision"], "manual_review_no_static_evidence")
            self.assertFalse(any(row["delete_authorized"] for row in report["directories"]))
            self.assertFalse(marker.exists())
            self.assertEqual(report["deleted_files"], 0)
            self.assertEqual((root / "data/imports/year_a/image.png").read_bytes(), b"image")


if __name__ == "__main__":
    unittest.main()
