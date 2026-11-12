import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from services.database_service import SCHEMA_PATH, database_connection
from scripts.audit_resource_integrity import audit, safe_label, audit_review_materials, ReadabilityChecks


class ResourceIntegrityAuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        with database_connection(str(self.root / "data" / "mathcyclus.sqlite3")) as conn:
            conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
            conn.execute("INSERT OR IGNORE INTO question_type(question_type_id,code,name) VALUES (4,'solution','解答题')")
            conn.execute("INSERT INTO question(question_id,stem_tex,question_type_id) VALUES ('Q1',?,4)",
                         (r"\questionasset{figure_01}",))
            conn.execute("INSERT INTO question_asset(asset_id,question_id,role,file_path,file_hash,caption,sort_order) VALUES ('A1','Q1','problem','assets/questions/Q1/figure.png',?,'figure',1)",
                         (hashlib.sha256(b"correct").hexdigest(),))
            conn.execute("INSERT INTO import_batch(batch_id,import_type,source_path,mode) VALUES ('B1','test','test','test')")
            conn.execute("INSERT INTO question_import_draft(draft_id,batch_id,stem_tex,review_status) VALUES ('D1','B1',?, 'needs_review')",
                         (r"See \questionasset{missing}",))
            conn.execute("INSERT INTO question_import_draft_asset(draft_asset_id,draft_id,source_path,file_hash,extra_json) VALUES ('DA1','D1','data/draft_assets/image.png',?,'{}')",
                         ("0" * 64,))
        self.asset = self.root / "assets/questions/Q1/figure.png"
        self.asset.parent.mkdir(parents=True)
        self.asset.write_bytes(b"changed")
        self.draft_asset = self.root / "data/draft_assets/image.png"
        self.draft_asset.parent.mkdir(parents=True)
        self.draft_asset.write_bytes(b"draft")

    def test_reports_missing_alias_and_hash_without_mutation_or_external_paths(self):
        before = self.asset.read_bytes()
        report = audit(self.root)
        categories = set(report["issue_counts"])
        self.assertIn("formal_integrity", categories)
        self.assertIn("draft_unresolved_questionasset", categories)
        self.assertEqual(self.asset.read_bytes(), before)
        serialized = json.dumps(report, ensure_ascii=False)
        self.assertNotIn(str(self.root), serialized)
        self.assertEqual(report["modified_files"], 0)
        self.assertEqual(report["deleted_files"], 0)

    def test_job_page_and_crop_references_are_checked(self):
        job = self.root / "data/imports/job1"
        job.mkdir(parents=True)
        source = b"source"
        (job / "source.pdf").write_bytes(source)
        (job / "job_manifest.json").write_text(json.dumps({"source": {"sha256": hashlib.sha256(source).hexdigest()}}),
                                               encoding="utf-8")
        (job / "draft_payload.json").write_text(json.dumps({
            "questions": [{"extra": {"source_page_images": ["pages/missing.png"],
                                      "question_crop_paths": ["crops/missing.png"]}, "assets": []}]}),
            encoding="utf-8")
        report = audit(self.root)
        self.assertIn("job_page_reference_missing", report["issue_counts"])
        self.assertIn("job_crop_reference_missing", report["issue_counts"])
        self.assertIn("job_counts", report)

    def test_safe_label_redacts_external_locations(self):
        self.assertEqual(safe_label(self.root, Path("D:/external/private.pdf")), "(external path)")

    def test_legacy_truncated_sha1_is_accepted(self):
        from services.asset_service import asset_file_hash_matches
        digest = hashlib.sha1(b"legacy image").hexdigest()[:16]
        path = self.root / "legacy.png"
        path.write_bytes(b"legacy image")
        self.assertEqual(asset_file_hash_matches(path, digest), (True, "sha1_legacy_truncated"))

    def test_readability_reports_corrupt_images_and_draft_source_page_range(self):
        import fitz
        pdf = self.root / "original.pdf"
        with fitz.open() as document:
            document.new_page()
            document.save(pdf)
        with database_connection(str(self.root / "data/mathcyclus.sqlite3")) as conn:
            conn.execute("UPDATE question_import_draft SET extra_json=? WHERE draft_id='D1'",
                         (json.dumps({"source_path": "original.pdf", "source_pages": [2],
                                      "question_crop_paths": ["missing.png"]}),))
        before = self.asset.read_bytes()
        issues, counts = audit_review_materials(self.root, self.root / "data/mathcyclus.sqlite3")
        categories = {row["category"] for row in issues}
        self.assertIn("registered_asset_decode_review", categories)
        self.assertIn("draft_source_page_out_of_range", categories)
        self.assertIn("draft_review_material_missing", categories)
        self.assertEqual(counts["pdfs_opened"], 1)
        self.assertEqual(self.asset.read_bytes(), before)

    def test_valid_image_decodes_and_is_cached(self):
        from PIL import Image
        image = self.root / "valid.png"
        Image.new("RGB", (12, 8)).save(image)
        checks = ReadabilityChecks()
        self.assertEqual(checks.check(image)["status"], "ok")
        self.assertEqual(checks.check(image)["width"], 12)
        self.assertEqual(len(checks.results), 1)

    def test_job_page_without_candidates_is_still_checked(self):
        job = self.root / "data/imports/empty_candidates"
        job.mkdir(parents=True)
        (job / "job_manifest.json").write_text("{}", encoding="utf-8")
        (job / "draft_payload.json").write_text(json.dumps({
            "questions": [], "pages": [{"image_path": "pages/no_image.png"}]}), encoding="utf-8")
        issues, counts = audit_review_materials(self.root, self.root / "data/mathcyclus.sqlite3")
        self.assertIn("job_page_image_missing", {row["category"] for row in issues})
        self.assertEqual(counts["job_page_images"], 1)


if __name__ == "__main__":
    unittest.main()
