"""Rehearse draft media migration or verify an applied manifest without editing source data."""

import argparse
import ast
import base64
import hashlib
import html
import json
import mimetypes
import os
import sqlite3
import sys
import tempfile
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.database_service import connect_existing_database
from services.asset_service import collect_asset_reference_issues, file_hash, asset_aliases
from services.draft_asset_migration_service import build_draft_asset_relocation_plan, apply_draft_asset_relocation, rollback_draft_asset_relocation
from services.import_service import get_draft_question


def preview_renderer():
    """Exercise actual app image rendering functions without starting its UI."""
    names = {"_db_preview_resolve_project_file", "_db_preview_asset_data_uri",
             "_db_preview_inline_asset_html", "_db_preview_apply_questionasset_previews"}
    tree = ast.parse((ROOT / "question_bank_app.py").read_text(encoding="utf-8"))
    selected = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name in names]
    if len(selected) != len(names):
        raise AssertionError("preview helpers changed; update verification")
    for node in selected:
        node.decorator_list = []
    scope = {"APP_ROOT": str(ROOT), "html": html, "os": os, "mimetypes": mimetypes,
             "base64": base64, "textwrap": textwrap}
    exec(compile(ast.Module(body=selected, type_ignores=[]), "<actual-image-preview>", "exec"), scope)
    return scope["_db_preview_apply_questionasset_previews"]


def table_digest(conn, table):
    rows = [tuple(row) for row in conn.execute(f'SELECT * FROM "{table}" ORDER BY rowid')]
    return hashlib.sha256(json.dumps(rows, ensure_ascii=False).encode("utf-8")).hexdigest()


def verify(manifest, db_path):
    baseline = connect_existing_database(manifest["backup_path"], readonly=True)
    current = connect_existing_database(db_path, readonly=True)
    validation_before, validation_after = [], []
    render = preview_renderer()
    try:
        checked = 0
        for item in manifest["assets"]:
            before, after = item["before"], item["after"]
            if file_hash(Path(item["copy"]["target"])) != item["copy"]["sha256"]:
                raise AssertionError("managed image bytes changed")
            if file_hash(Path(item["copy"]["source"])) != item["copy"]["sha256"]:
                raise AssertionError("original image bytes changed")
            if not asset_aliases(before).issubset(asset_aliases(after)):
                raise AssertionError("image alias lost")
            for field in before:
                if field not in {"source_path", "planned_file_path", "file_hash"} and before[field] != after[field]:
                    raise AssertionError("display metadata changed: " + field)
            stored = current.execute("SELECT * FROM question_import_draft_asset WHERE draft_asset_id=?",
                                     (before["draft_asset_id"],)).fetchone()
            if dict(stored) != after:
                raise AssertionError("applied asset differs from manifest")
            # Original filenames and explicit aliases both remain usable.
            alias = Path(before["source_path"]).stem
            snippet = "\\questionasset{" + alias + "}"
            old_html = render(snippet, [before])
            new_html = render(snippet, [after])
            if old_html != new_html or "未找到" in new_html or "未登记" in new_html:
                raise AssertionError("image preview HTML changed")
            checked += 1
        for draft_id, before in manifest["drafts_before"].items():
            stored = dict(current.execute("SELECT * FROM question_import_draft WHERE draft_id=?", (draft_id,)).fetchone())
            for field in before:
                if field not in {"content_hash", "updated_at"} and stored[field] != before[field]:
                    raise AssertionError("question content/review changed: " + field)
            old_bundle = get_draft_question(manifest["backup_path"], draft_id)
            new_bundle = get_draft_question(db_path, draft_id)
            old_issues = collect_asset_reference_issues(old_bundle, old_bundle["assets"])
            new_issues = collect_asset_reference_issues(new_bundle, new_bundle["assets"])
            if old_issues["has_blockers"]:
                validation_before.append(draft_id)
            if new_issues["has_blockers"]:
                validation_after.append(draft_id)
        if set(validation_after) - set(validation_before):
            raise AssertionError("new asset validation blockers")
        formal_tables = ("question", "question_asset", "paper_question", "book_exercise_question", "topic_question")
        for table in formal_tables:
            if table_digest(baseline, table) != table_digest(current, table):
                raise AssertionError("formal table changed: " + table)
        return {"status": "ok", "verified_assets": checked, "verified_drafts": len(manifest["drafts_before"]),
                "identical_image_preview_html": checked,
                "blockers_before": validation_before, "blockers_after": validation_after,
                "formal_tables_unchanged": list(formal_tables), "deleted_files": 0}
    finally:
        baseline.close()
        current.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data" / "mathcyclus.sqlite3"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    if args.manifest:
        manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
        result = verify(manifest, args.db)
    else:
        with tempfile.TemporaryDirectory(prefix="draft_media_rehearsal_") as directory:
            root = Path(directory)
            copy_db = str(root / "bank.sqlite3")
            source = connect_existing_database(args.db, readonly=True)
            destination = sqlite3.connect(copy_db)
            try:
                source.backup(destination)
            finally:
                source.close()
                destination.close()
            plan = build_draft_asset_relocation_plan(copy_db)
            manifest = apply_draft_asset_relocation(plan, backup_path=root / "before.sqlite3")
            result = verify(manifest, copy_db)
            result["reapply_candidates"] = len(build_draft_asset_relocation_plan(copy_db)["assets"])
            rollback_draft_asset_relocation(manifest, backup_path=root / "before_rollback.sqlite3")
            restored = connect_existing_database(copy_db, readonly=True)
            original = connect_existing_database(str(root / "before.sqlite3"), readonly=True)
            try:
                for table in ("question_import_draft_asset", "question_import_draft"):
                    if table_digest(restored, table) != table_digest(original, table):
                        raise AssertionError("rollback did not restore " + table)
            finally:
                restored.close()
                original.close()
            result["rollback_verified"] = True
            result["mode"] = "temporary_database_rehearsal"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
