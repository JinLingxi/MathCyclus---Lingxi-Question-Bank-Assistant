import tempfile
import unittest
from pathlib import Path

from services.asset_service import collect_asset_reference_issues, file_hash
from services.source_review_service import CHECKS, make_source_review, validate_source_review


class SourceReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.crop = self.root / "crop.png"
        self.source = self.root / "source.pdf"
        self.crop.write_bytes(b"crop-v1")
        self.source.write_bytes(b"source-v1")
        self.extra = {"source_region": {"source_path": "source.pdf", "page_index": 0, "box": [1, 2, 30, 40], "anchor_id": "draft-1"}}
        self.extra["source_review"] = make_source_review(
            self.crop, self.extra, project_root=self.root, reviewer="test-reviewer",
            checks={key: True for key in CHECKS})

    def status(self):
        return validate_source_review(self.crop, self.extra, project_root=self.root)["status"]

    def test_bound_review_and_stale_crop(self):
        self.assertEqual(self.status(), "verified")
        self.crop.write_bytes(b"crop-v2")
        self.assertEqual(self.status(), "stale")

    def test_source_bytes_and_region_invalidate_review(self):
        self.extra["source_region"]["box"][0] = 2
        self.assertEqual(self.status(), "stale")
        self.extra["source_region"]["box"][0] = 1
        self.source.write_bytes(b"source-v2")
        self.assertEqual(self.status(), "stale")

    def test_incomplete_and_non_boolean_reviews_fail(self):
        self.extra["source_review"]["checks"][CHECKS[0]] = "false"
        self.assertEqual(self.status(), "invalid")
        self.extra["source_review"]["checks"] = {}
        self.assertEqual(self.status(), "invalid")

    def test_failed_human_observation_is_not_verified(self):
        self.extra["source_review"]["checks"][CHECKS[1]] = False
        self.assertEqual(self.status(), "failed")

    def test_reassignment_and_coordinate_unit_change_invalidate_review(self):
        self.extra["source_region"]["anchor_id"] = "draft-2"
        self.assertEqual(self.status(), "stale")
        self.extra["source_region"]["anchor_id"] = "draft-1"
        self.extra["source_region"]["coordinate_space"] = "page_pixels"
        self.assertEqual(self.status(), "stale")

    def test_unrecorded_does_not_manufacture_a_visual_pass(self):
        self.extra.pop("source_review")
        self.assertEqual(self.status(), "unrecorded")

    def test_choices_are_included_in_formal_reference_checks(self):
        result = collect_asset_reference_issues({"choices_json": '["\\\\questionasset{missing}"]'}, [], project_root=self.root)
        self.assertTrue(result["has_blockers"])
        self.assertEqual(result["unresolved_questionasset"][0]["alias"], "missing")

    def test_hash_changes_block_draft_approval_validation(self):
        from services.import_service import DraftAssetInput, DraftQuestionInput, validate_draft_question
        asset = DraftAssetInput(source_path=str(self.crop), file_hash=file_hash(self.crop))
        draft = DraftQuestionInput(stem_tex="test", question_type_id=4, assets=[asset])
        self.assertFalse(validate_draft_question(draft)["errors"])
        self.crop.write_bytes(b"changed")
        self.assertTrue(validate_draft_question(draft)["errors"])

    def test_persisted_asset_hash_survives_draft_conversion(self):
        from services.import_service import _draft_row_to_input, validate_draft_question
        record = {"stem_tex": "test", "question_type_id": 4,
                  "assets": [{"source_path": str(self.crop), "file_hash": file_hash(self.crop)}]}
        draft = _draft_row_to_input(record)
        self.assertTrue(draft.assets[0].file_hash)
        self.crop.write_bytes(b"changed-after-persistence")
        self.assertTrue(validate_draft_question(draft)["errors"])

    def test_stale_review_is_reported_by_asset_validation(self):
        self.extra["source_region"]["page_index"] = 1
        result = collect_asset_reference_issues({}, [{"source_path": str(self.crop), "extra": self.extra}], project_root=self.root)
        self.assertTrue(result["has_blockers"])
        self.assertEqual(result["source_reviews"][0]["status"], "stale")

    def test_changed_file_cannot_commit_with_old_human_approval(self):
        from services.database_service import database_connection, SCHEMA_PATH
        from services.schema_migration_service import apply_pending_migrations
        from services.import_service import (create_manual_entry_draft, approve_draft_for_commit,
                                             commit_draft_to_question, get_draft_question)
        db = str(self.root / "review.sqlite3")
        with database_connection(db) as conn:
            conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
        apply_pending_migrations(db, apply=True, backup=False, allow_external_database=True)
        result = create_manual_entry_draft(db, {
            "source_item_id": "file-review", "stem_tex": "test", "question_type_id": 4,
            "assets": [{"source_path": str(self.crop)}],
        }, stamp="file_review_test")
        draft_id = result["draft_id"]
        self.assertTrue(get_draft_question(db, draft_id)["assets"][0]["file_hash"])
        approve_draft_for_commit(db, draft_id, operator="test-reviewer")
        from services.draft_asset_storage_service import resolve_draft_source
        managed_path = get_draft_question(db, draft_id)["assets"][0]["source_path"]
        resolve_draft_source(managed_path).write_bytes(b"changed-after-human-approval")
        with self.assertRaises(ValueError):
            commit_draft_to_question(db, draft_id)
        with database_connection(db) as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM question").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
