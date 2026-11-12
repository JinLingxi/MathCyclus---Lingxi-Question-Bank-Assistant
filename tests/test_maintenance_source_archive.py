import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.archive_maintenance_sources import archive_sources


class MaintenanceSourceArchiveTests(unittest.TestCase):
    def test_sources_and_transitive_call_dependencies_are_retained_without_execution(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            scripts = root / "scripts"
            scripts.mkdir()
            (scripts / "stage_year.py").write_text("import scripts.helper\nraise RuntimeError('do not execute')", encoding="utf-8")
            (scripts / "helper.py").write_text("import utility\n", encoding="utf-8")
            (scripts / "utility.py").write_text("VALUE=1\n", encoding="utf-8")
            target = root / "archive.zip"
            report = archive_sources(root, target, apply=False)
            self.assertEqual(report["historical_candidates"], 1)
            self.assertEqual(report["dependency_sources"], 2)
            self.assertFalse(target.exists())
            applied = archive_sources(root, target, apply=True)
            self.assertEqual(applied["verified_sources"], 3)
            self.assertEqual(applied["moved_files"], 0)
            with zipfile.ZipFile(target) as archive:
                for path in scripts.glob("*.py"):
                    self.assertEqual(archive.read("scripts/" + path.name), path.read_bytes())
                manifest = json.loads(archive.read("script_manifest.json"))
                self.assertEqual(len(manifest["entries"]), 3)
            with self.assertRaises(FileExistsError):
                archive_sources(root, target, apply=True)


if __name__ == "__main__":
    unittest.main()
