import hashlib
import json
import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import zipfile

import fitz

from services.pdf_import_service import create_pdf_import_job, load_pdf_import_job
from services.source_pdf_storage_service import sha256_file
from services.source_pdf_migration_service import (
    plan_source_pdf_migration, apply_source_pdf_migration, rollback_source_pdf_migration,
)


class SourcePDFStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def pdf(self, path, text="Source PDF"):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), text)
            document.save(path)

    def job(self, job_id, source, jobs_root):
        result = create_pdf_import_job(source, jobs_root=jobs_root, job_id=job_id,
                                       source_type="pdf_misc", render_dpi=72)
        return load_pdf_import_job(job_id, jobs_root), result

    def test_new_job_keeps_compatible_immutable_local_source(self):
        project = self.root / "project"
        jobs = project / "data" / "imports" / "jobs"
        original = self.root / "input.pdf"
        self.pdf(original)
        source_root = self.root / "data" / "source_pdfs"
        with patch("services.pdf_import_service.DEFAULT_JOBS_ROOT", jobs), \
             patch("services.source_pdf_storage_service.PROJECT_ROOT", project):
            loaded, result = self.job("job_one", original, jobs)
        job_pdf = loaded["job_dir"] / "source.pdf"
        digest = hashlib.sha256(original.read_bytes()).hexdigest()
        self.assertTrue(job_pdf.is_file())
        self.assertEqual(sha256_file(job_pdf), digest)
        self.assertEqual(loaded["manifest"]["source"]["sha256"], digest)
        self.assertEqual(loaded["draft_payload"]["source_path"], "source.pdf")
        object_pdf = project / "data" / "source_pdfs" / digest[:2] / (digest + ".pdf")
        self.assertTrue(object_pdf.is_file())
        self.assertEqual(sha256_file(object_pdf), digest)
        # Hard links must never include the caller's writable upload.
        self.assertNotEqual(os.stat(original).st_ino, os.stat(object_pdf).st_ino)
        if result["status"] == "drafted":
            with fitz.open(job_pdf) as document:
                self.assertEqual(document.page_count, 1)

    def make_legacy_project(self):
        imports = self.root / "project" / "data" / "imports"
        imports.mkdir(parents=True)
        original = self.root / "original.pdf"
        self.pdf(original, "Identical source")
        digest = sha256_file(original)
        jobs = []
        for name in ("job_a", "job_b", "job_c"):
            job = imports / name
            job.mkdir()
            destination = job / "source.pdf"
            destination.write_bytes(original.read_bytes())
            manifest = {"job_id": name, "source": {"sha256": digest, "size_bytes": original.stat().st_size}}
            manifest_path = job / "job_manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            jobs.append((destination, manifest_path, sha256_file(manifest_path)))
        extra = imports / "unrelated"
        extra.mkdir()
        (extra / "draft_payload.json").write_text('{"preserve":true}', encoding="utf-8")
        return imports, original, digest, jobs, extra

    def test_dry_run_apply_and_rollback_preserve_all_task_paths_and_manifests(self):
        _, _, digest, jobs, extra = self.make_legacy_project()
        before = [(path.read_bytes(), mode(path), path.stat().st_mtime_ns, manifest.read_bytes())
                  for path, manifest, _ in jobs]
        plan = plan_source_pdf_migration(self.root / "project")
        self.assertEqual(len(plan["groups"]), 1)
        self.assertEqual(len(plan["groups"][0]["files"]), 3)
        self.assertEqual((jobs[0][0].read_bytes(), jobs[0][1].read_bytes()),
                         (before[0][0], before[0][3]))
        journal = self.root / "migration.json"
        backup = self.root / "before.zip"
        result = apply_source_pdf_migration(plan, journal, backup)
        object_pdf = self.root / "project" / "data" / "source_pdfs" / digest[:2] / (digest + ".pdf")
        self.assertEqual(result["state"], "complete")
        self.assertTrue(all(path.is_file() and os.path.samefile(path, object_pdf) for path, _, _ in jobs))
        self.assertEqual([manifest.read_bytes() for _, manifest, _ in jobs], [item[3] for item in before])
        self.assertEqual((extra / "draft_payload.json").read_text(encoding="utf-8"), '{"preserve":true}')
        self.assertEqual(plan["groups"][0]["size"] * 2, result["groups"][0]["size"] * 2)
        with zipfile.ZipFile(backup) as archive:
            self.assertEqual(archive.namelist().count(digest + ".pdf"), 1)
            self.assertEqual(hashlib.sha256(archive.read(digest + ".pdf")).hexdigest(), digest)
        rollback_source_pdf_migration(journal)
        for (path, manifest, _), original_state in zip(jobs, before):
            content, permissions, mtime_ns, manifest_bytes = original_state
            self.assertEqual(path.read_bytes(), content)
            self.assertEqual(manifest.read_bytes(), manifest_bytes)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), permissions)
            self.assertEqual(path.stat().st_mtime_ns, mtime_ns)
            self.assertFalse(os.path.samefile(path, object_pdf))

    def test_plan_refuses_source_manifest_hash_mismatch(self):
        self.make_legacy_project()
        manifest = self.root / "project" / "data" / "imports" / "job_a" / "job_manifest.json"
        manifest.write_text(json.dumps({"source": {"sha256": "0" * 64}}), encoding="utf-8")
        with self.assertRaises(ValueError):
            plan_source_pdf_migration(self.root / "project")

    def test_rollback_refuses_modified_shared_source(self):
        _, _, _, jobs, _ = self.make_legacy_project()
        result = apply_source_pdf_migration(plan_source_pdf_migration(self.root / "project"),
                                            self.root / "journal.json", self.root / "backup.zip")
        jobs[0][0].chmod(stat.S_IRUSR | stat.S_IWUSR)
        jobs[0][0].write_bytes(b"modified")
        with self.assertRaises(ValueError):
            rollback_source_pdf_migration(self.root / "journal.json")
        self.assertEqual(result["state"], "complete")


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


if __name__ == "__main__":
    unittest.main()
