import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from services.database_service import SCHEMA_PATH, database_connection
from services.schema_migration_service import apply_pending_migrations
from services.asset_service import file_hash, asset_aliases, collect_asset_reference_issues
from services.draft_asset_storage_service import stabilize_draft_asset, resolve_draft_source
from services.draft_asset_migration_service import (
    build_draft_asset_relocation_plan, apply_draft_asset_relocation, rollback_draft_asset_relocation,
)
from services.import_service import (
    create_manual_entry_draft, get_draft_question, approve_draft_for_commit, commit_draft_to_question,
    add_draft_asset, update_draft_asset_fields,
)


class DraftAssetStorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.db = str(self.root / "bank.sqlite3")
        with database_connection(self.db) as conn:
            conn.executescript(Path(SCHEMA_PATH).read_text(encoding="utf-8"))
            conn.execute("INSERT OR IGNORE INTO question_type VALUES (4,'solution','解答题','')")
        apply_pending_migrations(self.db, apply=True, backup=False, allow_external_database=True)
        self.source = self.root / "task" / "figure_01.png"
        self.source.parent.mkdir()
        Image.new("RGB", (16, 12), "red").save(self.source)

    def draft(self, with_asset=True):
        return create_manual_entry_draft(self.db, {
            "source_item_id": "storage-test", "question_type_id": 4,
            "stem_tex": r"如图求值。\questionasset{figure_01}",
            "assets": [{"source_path": str(self.source), "planned_file_path": str(self.source),
                        "caption": "题目配图", "extra": {"alias": "figure_01"}}] if with_asset else [],
        })

    def legacy(self):
        result = self.draft()
        draft_id = result["draft_id"]
        # Reconstruct a pre-migration record without using a new-entry API.
        with database_connection(self.db) as conn:
            conn.execute("UPDATE question_import_draft_asset SET source_path=?,planned_file_path=?,file_hash='' WHERE draft_id=?",
                         (str(self.source), str(self.source), draft_id))
        return draft_id

    def test_new_draft_survives_missing_task_directory_without_visual_changes(self):
        result = self.draft()
        draft = get_draft_question(self.db, result["draft_id"])
        asset = draft["assets"][0]
        self.assertNotEqual(asset["source_path"], str(self.source))
        self.assertEqual(Path(asset["source_path"]).name, self.source.name)
        self.assertEqual(asset["caption"], "题目配图")
        self.assertIn("figure_01", asset_aliases(asset))
        self.assertEqual(file_hash(resolve_draft_source(asset["source_path"])), file_hash(self.source))
        self.source.unlink()
        self.assertFalse(collect_asset_reference_issues(draft, draft["assets"])["has_blockers"])
        self.assertEqual(draft["stem_tex"], r"如图求值。\questionasset{figure_01}")

    def test_add_update_and_commit_use_managed_copy(self):
        result = self.draft(False)
        draft_id = result["draft_id"]
        added = add_draft_asset(self.db, draft_id, {"source_path": str(self.source), "extra": {"alias": "figure_01"}})
        asset = added["asset"]
        self.assertIn("draft_assets", asset["source_path"])
        second = self.root / "task" / "figure_02.png"
        Image.new("RGB", (16, 12), "blue").save(second)
        update_draft_asset_fields(self.db, asset["draft_asset_id"], {"source_path": str(second), "planned_file_path": ""})
        updated = get_draft_question(self.db, draft_id)
        self.assertIn("draft_assets", updated["assets"][0]["source_path"])
        self.source.unlink()
        second.unlink()
        approve_draft_for_commit(self.db, draft_id, operator="test")
        with patch("services.asset_service.ASSET_ROOT", self.root / "questions"):
            committed = commit_draft_to_question(self.db, draft_id)
        with database_connection(self.db) as conn:
            formal = dict(conn.execute("SELECT * FROM question_asset WHERE question_id=?", (committed["question_id"],)).fetchone())
        self.assertTrue(Path(formal["file_path"]).is_file())
        self.assertEqual(Path(formal["file_path"]).stem, "figure_01")

    def test_copy_is_idempotent_and_does_not_link_to_task_source(self):
        asset = {"source_path": str(self.source)}
        first = stabilize_draft_asset(asset, self.db)
        second = stabilize_draft_asset(asset, self.db)
        self.assertEqual(first, second)
        before = file_hash(resolve_draft_source(first["source_path"]))
        self.source.write_bytes(b"new task content")
        self.assertEqual(file_hash(resolve_draft_source(first["source_path"])), before)

    def test_migration_dry_run_apply_and_rollback(self):
        draft_id = self.legacy()
        before = get_draft_question(self.db, draft_id)
        plan = build_draft_asset_relocation_plan(self.db)
        self.assertEqual(len(plan["assets"]), 1)
        self.assertEqual(get_draft_question(self.db, draft_id), before)
        manifest = apply_draft_asset_relocation(plan, backup_path=self.root / "before.sqlite3")
        after = get_draft_question(self.db, draft_id)
        self.assertEqual(after["review_status"], before["review_status"])
        self.assertEqual(after["stem_tex"], before["stem_tex"])
        self.assertEqual(after["assets"][0]["extra_json"], before["assets"][0]["extra_json"])
        self.assertEqual(file_hash(resolve_draft_source(after["assets"][0]["source_path"])), file_hash(self.source))
        self.assertEqual(len(build_draft_asset_relocation_plan(self.db)["assets"]), 0)
        rollback_draft_asset_relocation(manifest, backup_path=self.root / "before_rollback.sqlite3")
        restored = get_draft_question(self.db, draft_id)
        self.assertEqual(restored["assets"], before["assets"])
        self.assertEqual(restored["content_hash"], before["content_hash"])

    def test_preflight_detects_changes_and_rolls_back(self):
        draft_id = self.legacy()
        plan = build_draft_asset_relocation_plan(self.db)
        self.source.write_bytes(b"changed after dry run")
        with self.assertRaises(ValueError):
            apply_draft_asset_relocation(plan, backup_path=self.root / "before.sqlite3")
        self.assertEqual(get_draft_question(self.db, draft_id)["assets"][0]["source_path"], str(self.source))

    def test_approved_drafts_are_protected(self):
        draft_id = self.legacy()
        approve_draft_for_commit(self.db, draft_id, operator="test")
        self.assertFalse(build_draft_asset_relocation_plan(self.db)["assets"])

    def test_rollback_refuses_subsequent_edits(self):
        draft_id = self.legacy()
        manifest = apply_draft_asset_relocation(build_draft_asset_relocation_plan(self.db),
                                               backup_path=self.root / "before.sqlite3")
        with database_connection(self.db) as conn:
            conn.execute("UPDATE question_import_draft SET stem_tex='edited' WHERE draft_id=?", (draft_id,))
        with self.assertRaises(ValueError):
            rollback_draft_asset_relocation(manifest, backup_path=self.root / "before_rollback.sqlite3")
        self.assertEqual(get_draft_question(self.db, draft_id)["stem_tex"], "edited")

    def test_changed_registered_hash_is_not_silently_rebased(self):
        with self.assertRaises(ValueError):
            stabilize_draft_asset({"source_path": str(self.source), "file_hash": "0" * 64}, self.db)

    def test_replacing_source_updates_a_mirrored_planned_path(self):
        result = self.draft()
        asset = get_draft_question(self.db, result["draft_id"])["assets"][0]
        second = self.root / "replacement.png"
        Image.new("RGB", (16, 12), "blue").save(second)
        update_draft_asset_fields(self.db, asset["draft_asset_id"], {"source_path": str(second)})
        changed = get_draft_question(self.db, result["draft_id"])["assets"][0]
        self.assertEqual(changed["source_path"], changed["planned_file_path"])
        self.assertIn("draft_assets", changed["source_path"])
        self.assertEqual(changed["file_hash"], file_hash(second))


if __name__ == "__main__":
    unittest.main()
