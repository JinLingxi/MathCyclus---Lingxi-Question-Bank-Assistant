import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.local_data_bundle import export_bundle, restore_bundle, safe_zip_relative_path, MANIFEST_NAME

ROOT = Path(__file__).resolve().parents[1]


class IngestionBundleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.target = self.root / "target"
        for base in (self.source, self.target):
            (base / "db").mkdir(parents=True)
            shutil.copy2(ROOT / "db/schema.sql", base / "db/schema.sql")
        (self.source / "data").mkdir()
        conn = sqlite3.connect(self.source / "data/mathcyclus.sqlite3")
        conn.execute("CREATE TABLE question(question_id TEXT)")
        conn.execute("INSERT INTO question VALUES ('existing')")
        conn.commit()
        conn.close()
        self.task = self.source / "data/imports/example"
        self.task.mkdir(parents=True)
        (self.task / "job_manifest.json").write_text('{"source":"source.pdf"}', encoding="utf-8")
        (self.task / "source.pdf").write_bytes(b"source")
        (self.task / "page.png").write_bytes(b"page")
        self.bundle = self.source / "data/backups/tasks.zip"

    def test_opt_in_task_roundtrip_and_default_scope(self):
        default = export_bundle(project_root=self.source, dry_run=True)
        self.assertNotIn("ingestion_tasks", default["counts_by_kind"])
        report = export_bundle(project_root=self.source, output=self.bundle, include_ingestion=True)
        self.assertEqual(report["counts_by_kind"]["ingestion_tasks"], 3)
        result = restore_bundle(project_root=self.target, bundle=self.bundle, apply=True)
        self.assertEqual(result["status"], "ok")
        for name in ("source.pdf", "page.png", "job_manifest.json"):
            self.assertEqual((self.target / "data/imports/example" / name).read_bytes(),
                             (self.task / name).read_bytes())
        with self.assertRaises(FileExistsError):
            export_bundle(project_root=self.source, output=self.bundle)

    def test_export_includes_committed_wal_data(self):
        conn = sqlite3.connect(self.source / "data/mathcyclus.sqlite3")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("INSERT INTO question VALUES ('wal-record')")
        conn.commit()
        export_bundle(project_root=self.source, output=self.bundle)
        self.assertEqual(restore_bundle(project_root=self.target, bundle=self.bundle, apply=True)["status"], "ok")
        restored = sqlite3.connect(self.target / "data/mathcyclus.sqlite3")
        self.assertEqual(restored.execute("SELECT COUNT(*) FROM question").fetchone()[0], 2)
        restored.close()
        conn.close()

    def test_corruption_blocks_all_writes(self):
        export_bundle(project_root=self.source, output=self.bundle, include_ingestion=True)
        damaged = self.source / "data/backups/damaged.zip"
        with zipfile.ZipFile(self.bundle) as source, zipfile.ZipFile(damaged, "w") as output:
            for name in source.namelist():
                output.writestr(name, b"broken" if name.endswith("page.png") else source.read(name))
        result = restore_bundle(project_root=self.target, bundle=damaged, apply=True)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["restored_count"], 0)
        self.assertFalse((self.target / "data").exists())

    def test_conflict_blocks_unrelated_new_task_writes(self):
        export_bundle(project_root=self.source, output=self.bundle, include_ingestion=True)
        (self.target / "data").mkdir()
        (self.target / "data/mathcyclus.sqlite3").write_bytes(b"existing")
        result = restore_bundle(project_root=self.target, bundle=self.bundle, apply=True)
        self.assertEqual(result["status"], "blocked")
        self.assertFalse((self.target / "data/imports").exists())
        self.assertEqual((self.target / "data/mathcyclus.sqlite3").read_bytes(), b"existing")

    def test_path_traversal_variants_are_rejected(self):
        for path in ("/data/a", "../data/a", "data/../a", "D:/a", "data/a:stream", "data/a."):
            with self.subTest(path=path), self.assertRaises(ValueError):
                safe_zip_relative_path(path)


if __name__ == "__main__":
    unittest.main()
