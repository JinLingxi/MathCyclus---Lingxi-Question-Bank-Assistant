"""Read-only backup catalog and conservative retention recommendations.

No age, duplicate hash, or absence of references authorizes deletion. SQLite
snapshots are inspected with immutable read-only connections; files accompanied
by a nonempty WAL are marked for a separate consistent snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_snapshot(path: Path) -> dict:
    wal = path.with_name(path.name + "-wal")
    if wal.exists() and wal.stat().st_size:
        return {"status": "wal_present_requires_consistent_snapshot", "wal_bytes": wal.stat().st_size}
    connection = None
    try:
        connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro&immutable=1", uri=True)
        integrity = [row[0] for row in connection.execute("PRAGMA quick_check")]
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        counts = {table: connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
                  for table in ("question", "question_import_draft", "question_import_draft_asset")
                  if table in tables}
        foreign_key_issues = connection.execute("PRAGMA foreign_key_check").fetchall()
        return {"status": "ok" if integrity == ["ok"] and not foreign_key_issues else "review_required",
                "quick_check": integrity, "foreign_key_issue_count": len(foreign_key_issues),
                "counts": counts}
    except (sqlite3.Error, OSError) as exc:
        return {"status": "unreadable", "error": str(exc)}
    finally:
        if connection is not None:
            connection.close()


def audit_backups(project: Path) -> dict:
    project = project.resolve()
    entries, duplicates = [], defaultdict(list)
    for prefix in ("data/backups", ".backups"):
        base = project / prefix
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.is_symlink():
                continue
            before = path.stat()
            entry = {"path": path.relative_to(project).as_posix(), "bytes": before.st_size,
                     "mtime_ns": before.st_mtime_ns,
                     "modified_utc": datetime.fromtimestamp(before.st_mtime, timezone.utc).isoformat(),
                     "sha256": sha256_file(path)}
            if path.suffix == ".sqlite3":
                entry["snapshot"] = inspect_snapshot(path)
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                entry["retention"] = "retain_changed_during_audit"
            elif "source_pdf_migration" in path.parts or "draft_asset_storage" in path.parts:
                entry["retention"] = "protected_migration_rollback"
            elif prefix == ".backups":
                entry["retention"] = "historical_recovery_baseline_archive_candidate"
            else:
                entry["retention"] = "retain_pending_task_recovery_review"
            if path.name.endswith(("-wal", "-shm")):
                entry["retention"] = "retain_sqlite_sidecar_do_not_delete_separately"
            entries.append(entry)
            duplicates[(entry["bytes"], entry["sha256"])].append(entry["path"])
    # Include all history names in duplicate groups. Do not elect a deletable copy.
    duplicate_groups = [{"sha256": digest, "bytes_each": size, "paths": paths,
                         "identical_copy_bytes": size * (len(paths) - 1), "action": "retain_all_paths"}
                        for (size, digest), paths in duplicates.items() if len(paths) > 1]
    duplicate_groups.sort(key=lambda row: row["identical_copy_bytes"], reverse=True)
    return {"mode": "read_only_dry_run", "created_at": datetime.now().astimezone().isoformat(),
            "files": entries, "total_bytes": sum(row["bytes"] for row in entries),
            "duplicate_groups": duplicate_groups,
            "duplicate_bytes": sum(row["identical_copy_bytes"] for row in duplicate_groups),
            "deleted_files": 0, "limitations": [
                "Snapshot quick_check does not prove a full application restore.",
                "Database snapshots do not necessarily contain their external image/PDF resources.",
                "Duplicate content does not prove historical filenames are disposable.",
                "No automatic retention expiry or deletion is enabled."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = audit_backups(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    snapshots = [entry["snapshot"] for entry in report["files"] if "snapshot" in entry]
    print(json.dumps({"files": len(report["files"]), "total_bytes": report["total_bytes"],
                      "duplicate_bytes": report["duplicate_bytes"], "snapshots": len(snapshots),
                      "snapshots_ok": sum(row["status"] == "ok" for row in snapshots),
                      "deleted_files": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
