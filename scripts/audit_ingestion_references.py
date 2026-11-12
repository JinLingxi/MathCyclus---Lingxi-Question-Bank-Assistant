"""Conservative read-only reference map for ingestion directories.

Checks persisted text/JSON and source documents; deliberately never labels an
unreferenced directory safe to delete because paths can be built dynamically.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {".py", ".md", ".tex", ".json", ".csv", ".sql", ".ps1", ".bat", ".cjs"}
EXCLUDED = {".git", ".venv", ".agents", ".codex", ".aws", "__pycache__", "node_modules"}


def normalized(value: str) -> str:
    # JSON stored inside text has doubled slashes. Collapse only separators.
    return re.sub(r"/+", "/", str(value).replace("\\", "/")).casefold()


def literal_directory_matches(text: str, names: list[str]) -> list[str]:
    # Avoid normalizing megabytes of embedded OCR/base64 content when none of
    # the directory names occurs; underscores survive both JSON escaping and
    # Windows path separators.
    folded = str(text).casefold()
    candidates = [name for name in names if name.casefold() in folded]
    if not candidates:
        return []
    value = normalized(text)
    matches = []
    for name in candidates:
        escaped = re.escape(name.casefold())
        # Require a directory boundary to avoid 2024_restart vs 2024_restart_v2.
        if re.search(r"(?<![\w-])" + escaped + r"(?![\w-])", value):
            matches.append(name)
    return matches


def file_directory_matches(path: Path, names: list[str]) -> list[str]:
    """Scan large OCR/JSON payloads with bounded memory and overlap at edges."""
    found = set()
    overlap = max((len(name) for name in names), default=0) + 4
    tail = ""
    with path.open("r", encoding="utf-8-sig", errors="replace") as source:
        while chunk := source.read(1024 * 1024):
            value = tail + chunk
            # Exclude the final overlap until the next read, so the look-ahead
            # boundary is never inferred from an artificial chunk end.
            cutoff = max(0, len(value) - overlap)
            for name in literal_directory_matches(value, names):
                pattern = re.compile(r"(?<![\w-])" + re.escape(name.casefold()) + r"(?![\w-])")
                if any(match.end() < cutoff for match in pattern.finditer(value.casefold())):
                    found.add(name)
            tail = value[max(0, cutoff - overlap):]
        found.update(literal_directory_matches(tail, names))
    return sorted(found)


def audit(project: Path) -> dict:
    project = project.resolve()
    imports = project / "data" / "imports"
    directories = sorted(path for path in imports.iterdir()
                         if path.is_dir() and not path.is_symlink() and not path.is_junction())
    names = [path.name for path in directories]
    evidence = defaultdict(lambda: {"database": [], "external_text": [], "internal_text": [],
                                    "database_count": 0, "external_text_count": 0, "internal_text_count": 0})
    totals = {name: {"files": 0, "logical_bytes": 0} for name in names}
    issues = []

    def add(name, kind, item):
        evidence[name][kind + "_count"] += 1
        if len(evidence[name][kind]) < 40:
            evidence[name][kind].append(item)

    database = project / "data" / "mathcyclus.sqlite3"
    database_counts = {}
    if database.exists():
        conn = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        conn.execute("PRAGMA query_only=ON")
        try:
            tables = [row[0] for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                escaped = table.replace('"', '""')
                columns = [row[1] for row in conn.execute(f'PRAGMA table_info("{escaped}")')]
                if table in {"question", "question_import_draft", "question_import_draft_asset"}:
                    database_counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{escaped}"').fetchone()[0]
                # Inspect all text-valued cells, including nested JSON serialized
                # in events, revisions and import reports.
                for index, row in enumerate(conn.execute(f'SELECT * FROM "{escaped}"')):
                    hits = defaultdict(list)
                    for column, value in zip(columns, row):
                        if isinstance(value, str):
                            for name in literal_directory_matches(value, names):
                                hits[name].append(column)
                    for name, matched_columns in hits.items():
                        identity = {column: row[columns.index(column)] for column in columns[:2]
                                    if column.endswith("_id")}
                        add(name, "database", {"table": table, "row_index": index,
                                              "identity": identity, "columns": matched_columns})
        finally:
            conn.close()

    # Scan only known project text roots and public root source/docs. Reports and
    # historical backups provide evidence but are not inferred as runtime use.
    for directory, dirs, files in os.walk(project, followlinks=False,
                                           onerror=lambda exc: issues.append({"kind": "unreadable_directory",
                                                                              "path": str(exc.filename)})):
        dirs[:] = [name for name in dirs if name not in EXCLUDED
                   and not (Path(directory) / name).is_symlink()
                   and not (Path(directory) / name).is_junction()]
        for filename in files:
            path = Path(directory) / filename
            rel = path.relative_to(project)
            if path.is_symlink():
                continue
            try:
                size = path.stat().st_size
                inside_name = rel.parts[2] if len(rel.parts) > 3 and rel.parts[:2] == ("data", "imports") else None
                if inside_name in totals:
                    totals[inside_name]["files"] += 1
                    totals[inside_name]["logical_bytes"] += size
                if path.suffix.lower() not in TEXT_SUFFIXES:
                    continue
                # Own audit outputs are not independent evidence of use.
                if rel.parts[0] == "reports" and path.name.startswith("ingestion_reference"):
                    continue
                matches = (file_directory_matches(path, names) if size > 16 * 1024 * 1024
                           else literal_directory_matches(path.read_text(encoding="utf-8-sig", errors="replace"), names))
                for name in matches:
                    kind = "internal_text" if inside_name == name else "external_text"
                    category = ("audit_or_backup" if rel.parts[0] in {"reports", ".backups"}
                                or rel.parts[:2] == ("data", "backups") else "project_or_task")
                    add(name, kind, {"path": rel.as_posix(), "category": category})
            except OSError as exc:
                issues.append({"kind": "unreadable_file", "path": rel.as_posix(), "error": type(exc).__name__})
    rows = []
    for name in names:
        entry = evidence[name]
        has_evidence = bool(entry["database_count"] or entry["external_text_count"])
        rows.append({"directory": "data/imports/" + name, **totals[name], **entry,
                     "decision": "retain_referenced" if has_evidence else "manual_review_no_static_evidence",
                     "delete_authorized": False})
    return {"created_at": datetime.now().astimezone().isoformat(), "mode": "read_only",
            "database_counts": database_counts, "directories": rows, "scan_issues": issues,
            "deleted_files": 0, "limitations": [
                "Literal references can include historical evidence, not only live callers.",
                "Dynamic joins, relative paths, external scripts and unsaved UI sessions are not exhaustively resolved.",
                "Logical byte totals include shared hard-linked PDFs; they are not reclaimable physical bytes.",
                "Only the first 40 evidence examples per directory and category are included; counts are complete.",
                "No static matches is never permission to delete a directory."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    report = audit(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"directories": len(report["directories"]),
                      "decisions": dict(Counter(row["decision"] for row in report["directories"])),
                      "scan_issues": len(report["scan_issues"]), "deleted_files": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
