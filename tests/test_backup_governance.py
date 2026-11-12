import json
import sqlite3
import tempfile
import unittest
import zipfile
from pathlib import Path

from scripts.archive_historical_backups import build_archive, verify_archive
from scripts.audit_backup_retention import audit_backups, inspect_snapshot
from scripts.catalog_maintenance_scripts import catalog


class BackupGovernanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.backups = self.root / ".backups" / "historical"
        self.backups.mkdir(parents=True)
        self.database = self.backups / "before.sqlite3"
        conn = sqlite3.connect(self.database)
        conn.execute("CREATE TABLE question(question_id TEXT)")
        conn.execute("INSERT INTO question VALUES ('preserve')")
        conn.commit()
        conn.close()
        (self.backups / "original.tex").write_text("题干", encoding="utf-8")

    def test_dry_run_and_verified_cold_archive_preserve_originals(self):
        target = self.root / "data" / "backups" / "cold.zip"
        before = {p.name: p.read_bytes() for p in self.backups.iterdir()}
        plan = build_archive(self.root, target)
        self.assertEqual(plan["mode"], "dry_run")
        self.assertFalse(target.exists())
        result = build_archive(self.root, target, apply=True)
        self.assertEqual(result["verified_restored_files"], 2)
        self.assertEqual(result["verified_restored_databases"], 1)
        self.assertEqual(result["deleted_files"], 0)
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.backups.iterdir()})
        self.assertEqual(verify_archive(target)["verified_restored_files"], 2)
        with self.assertRaises(FileExistsError):
            build_archive(self.root, target, apply=True)

    def test_archive_rejects_invalid_database_without_publishing(self):
        self.database.write_bytes(b"invalid database")
        target = self.root / "cold.zip"
        with self.assertRaises(ValueError):
            build_archive(self.root, target, apply=True)
        self.assertFalse(target.exists())

    def test_restoration_detects_tampering(self):
        target = self.root / "cold.zip"
        build_archive(self.root, target, apply=True)
        altered = self.root / "altered.zip"
        with zipfile.ZipFile(target) as source, zipfile.ZipFile(altered, "w") as output:
            for name in source.namelist():
                output.writestr(name, b"modified" if name.endswith(".tex") else source.read(name))
        with self.assertRaises(ValueError):
            verify_archive(altered)

    def test_wal_snapshot_is_flagged_and_not_silently_read(self):
        wal = self.database.with_name(self.database.name + "-wal")
        wal.write_bytes(b"pending wal")
        self.assertEqual(inspect_snapshot(self.database)["status"], "wal_present_requires_consistent_snapshot")
        with self.assertRaises(ValueError):
            build_archive(self.root, self.root / "cold.zip", apply=True)

    def test_duplicate_backup_is_retained_in_catalog(self):
        copy = self.backups / "another.sqlite3"
        copy.write_bytes(self.database.read_bytes())
        report = audit_backups(self.root)
        self.assertTrue(report["duplicate_groups"])
        self.assertEqual(report["duplicate_groups"][0]["action"], "retain_all_paths")
        self.assertEqual(report["deleted_files"], 0)
        self.assertFalse(list(self.backups.glob("*-shm")))

    def test_script_catalog_does_not_execute_top_level_mutation(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        marker = self.root / "must_not_exist"
        (scripts / "fix.py").write_text(
            "from pathlib import Path\nPath(" + repr(str(marker)) + ").write_text('bad')\n", encoding="utf-8")
        (scripts / "caller.py").write_text("import scripts.fix\n", encoding="utf-8")
        report = catalog(self.root)
        row = next(item for item in report["scripts"] if item["path"] == "scripts/fix.py")
        self.assertIn("write_text", row["write_signals"])
        self.assertIn("scripts/caller.py", row["referenced_by"])
        self.assertFalse(marker.exists())
        self.assertEqual(report["moved_files"], 0)


if __name__ == "__main__":
    unittest.main()
