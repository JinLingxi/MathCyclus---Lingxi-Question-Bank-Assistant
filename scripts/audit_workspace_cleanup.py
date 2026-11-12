"""Read-only workspace cleanup inventory; never deletes or rewrites source data."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKIP = {".git", ".venv", ".agents", "node_modules"}
TRANSIENT_SUFFIXES = {".pyc", ".pyo", ".aux", ".log", ".out", ".toc",
                      ".fls", ".fdb_latexmk", ".xdv", ".synctex.gz"}


def sha256(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main():
    files = []
    totals = defaultdict(lambda: {"files": 0, "bytes": 0})
    groups = defaultdict(lambda: {"files": 0, "bytes": 0})
    transient = []
    empty_test_dirs = []
    unreadable = []
    def walk_error(error):
        unreadable.append({"path": str(Path(error.filename).relative_to(ROOT)), "error": type(error).__name__})

    for directory, dirs, names in os.walk(ROOT, followlinks=False, onerror=walk_error):
        dirs[:] = [name for name in dirs
                   if name not in SKIP and not (Path(directory) / name).is_symlink()
                   and not (Path(directory) / name).is_junction()]
        for name in names:
            path = Path(directory) / name
            if path.is_symlink():
                continue
            rel = path.relative_to(ROOT)
            size = path.stat().st_size
            files.append((path, rel.as_posix(), size))
            top = rel.parts[0] if len(rel.parts) > 1 else "(root files)"
            totals[top]["files"] += 1
            totals[top]["bytes"] += size
            key = "/".join(rel.parts[:3]) if len(rel.parts) > 3 else rel.as_posix()
            if rel.parts[0] == "data":
                groups[key]["files"] += 1
                groups[key]["bytes"] += size
            # Only disposable compilation outputs outside retained task evidence.
            if ("__pycache__" in rel.parts and rel.parts[0] in
                    {"__pycache__", "scripts", "services", "utils", "components", "tests"}):
                transient.append({"path": rel.as_posix(), "bytes": size, "kind": "python_cache"})
            elif rel.parts[0] == "Test Paper Group" and path.suffix in TRANSIENT_SUFFIXES:
                transient.append({"path": rel.as_posix(), "bytes": size, "kind": "latex_auxiliary"})

    for path in ROOT.glob("mathcyclus_*"):
        try:
            if path.is_dir() and not path.is_junction() and not path.is_symlink() and not any(path.iterdir()):
                empty_test_dirs.append(path.relative_to(ROOT).as_posix())
        except OSError:
            # Unreadable is not evidence of emptiness.
            pass

    # Verify repeated source PDFs by bytes, not just by filename.
    source_sizes = defaultdict(list)
    for path, rel, size in files:
        if rel.startswith("data/") and path.name == "source.pdf":
            source_sizes[size].append((path, rel, size))
    duplicate_groups = defaultdict(list)
    for candidates in source_sizes.values():
        if len(candidates) < 2:
            continue
        for path, rel, size in candidates:
            duplicate_groups[(size, sha256(path))].append(rel)
    duplicates = [
        {"sha256": digest, "bytes_each": size, "copies": len(paths), "paths": paths,
         "redundant_bytes": size * (len(paths) - 1),
         "decision": "retain_until_task_paths_and_runtime_reads_are_migrated"}
        for (size, digest), paths in duplicate_groups.items() if len(paths) > 1
    ]
    duplicates.sort(key=lambda row: row["redundant_bytes"], reverse=True)

    db = ROOT / "data" / "mathcyclus.sqlite3"
    database = {"path": "data/mathcyclus.sqlite3", "counts": {}, "asset_path_roots": {}}
    if db.exists():
        conn = sqlite3.connect(db.as_uri() + "?mode=ro", uri=True)
        try:
            conn.execute("PRAGMA query_only=ON")
            for table in ("question", "question_asset", "question_import_draft", "question_import_draft_asset"):
                database["counts"][table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            for table, column in (("question_asset", "file_path"), ("question_import_draft_asset", "source_path")):
                counts = defaultdict(int)
                for (value,) in conn.execute(f'SELECT "{column}" FROM "{table}"'):
                    normalized = str(value or "").replace("\\", "/")
                    root_prefix = ROOT.as_posix().rstrip("/") + "/"
                    if normalized.lower().startswith(root_prefix.lower()):
                        normalized = normalized[len(root_prefix):]
                    label = "/".join(normalized.split("/")[:3]) if normalized else "(empty)"
                    if ":" in label:
                        label = "(external path)"
                    counts[label] += 1
                database["asset_path_roots"][table] = dict(counts)
        finally:
            conn.close()

    scripts = list((ROOT / "scripts").glob("*.py"))
    historical = [p.name for p in scripts if p.name.startswith(
        ("stage_", "record_", "prepare_", "audit_2009_", "fix", "payload", "import", "tmp_", "check"))]
    report = {
        "created_at": datetime.now().astimezone().isoformat(), "mode": "read_only_dry_run",
        "deleted_files": 0, "database": database,
        "directory_totals": dict(sorted(totals.items(), key=lambda item: -item[1]["bytes"])),
        "data_groups": dict(sorted(groups.items(), key=lambda item: -item[1]["bytes"])[:35]),
        "disposable_outputs": transient, "disposable_bytes": sum(row["bytes"] for row in transient),
        "empty_test_directories": empty_test_dirs,
        "unreadable_paths": unreadable,
        "identical_source_pdf_groups": duplicates,
        "potential_source_pdf_savings_bytes": sum(row["redundant_bytes"] for row in duplicates),
        "scripts_count": len(scripts), "historical_script_candidates": historical,
        "limitations": [
            "No unused-code claim is made from missing static references.",
            "PDF equality does not imply that an existing task path can be removed.",
            "Database metadata, JSON manifests and dynamic paths require a migration before deduplication.",
            "Backup retention and recovery usefulness were not evaluated; backups are retained.",
            "Caches may be in use; clean after stopping the application.",
        ],
    }
    target = ROOT / "reports" / "workspace_cleanup_audit_20261031.json"
    target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: report[key] for key in
                      ("mode", "deleted_files", "disposable_bytes", "empty_test_directories",
                       "potential_source_pdf_savings_bytes", "scripts_count")}, ensure_ascii=False))
    print("report=" + target.relative_to(ROOT).as_posix())


if __name__ == "__main__":
    main()
