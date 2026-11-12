"""Archive historical task script sources and local script dependencies without moving originals."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import tempfile
import zipfile
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from scripts.catalog_maintenance_scripts import catalog

ROOT = Path(__file__).resolve().parents[1]


def build_plan(project: Path) -> dict:
    inventory = catalog(project)
    rows = {row["path"]: row for row in inventory["scripts"]}
    seeds = {path for path, row in rows.items() if row["category"] == "historical_task_candidate"}
    # Use both imports and literal mentions conservatively; preserve dependency
    # source even when a mention is documentation rather than an executable call.
    graph = defaultdict(set)
    for dependency, row in rows.items():
        for caller in row["referenced_by"]:
            if caller in rows:
                graph[caller].add(dependency)
    for caller, row in rows.items():
        for module in row["imports"]:
            parts = module.split(".")
            local_name = parts[1] if parts[0] == "scripts" and len(parts) > 1 else parts[0]
            dependency = "scripts/" + local_name + ".py"
            if dependency in rows:
                graph[caller].add(dependency)
    selected = set(seeds)
    pending = list(seeds)
    while pending:
        caller = pending.pop()
        for dependency in graph[caller]:
            if dependency not in selected:
                selected.add(dependency)
                pending.append(dependency)
    entries = []
    for relative in sorted(selected):
        raw = (project / relative).read_bytes()
        ast.parse(raw, filename=relative)  # Parse only; never import task scripts.
        row = rows[relative]
        entries.append({"path": relative, "sha256": hashlib.sha256(raw).hexdigest(),
                        "bytes": len(raw), "historical_candidate": relative in seeds,
                        "local_script_dependencies": sorted(graph[relative]),
                        "referenced_by": row["referenced_by"], "write_signals": row["write_signals"],
                        "literal_sql_writes": row["literal_sql_writes"],
                        "action": "archived_copy_original_path_retained"})
    return {"version": 1, "created_at": datetime.now().astimezone().isoformat(),
            "historical_candidates": len(seeds), "dependency_sources": len(selected - seeds),
            "entries": entries, "moved_files": 0, "deleted_files": 0,
            "limitations": [
                "Archive includes script sources only, not PDFs, databases, external modules or run credentials.",
                "Literal dependency graph is conservative and cannot resolve all dynamic calls.",
                "Candidates are not declared obsolete or safe to execute.",
                "All original scripts retain paths; replay requires original inputs and a disposable database copy."]}


def archive_sources(project: Path, output: Path, *, apply=False) -> dict:
    if output.exists():
        raise FileExistsError(output)
    plan = build_plan(project)
    if not apply:
        return {**plan, "mode": "dry_run"}
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(prefix=".scripts-", suffix=".tmp", dir=output.parent)
    os.close(descriptor)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("script_manifest.json", json.dumps(plan, ensure_ascii=False, indent=2))
            for item in plan["entries"]:
                raw = (project / item["path"]).read_bytes()
                if hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("历史脚本在归档期间变化")
                archive.writestr(item["path"], raw)
        with zipfile.ZipFile(temporary) as archive:
            for item in plan["entries"]:
                raw = archive.read(item["path"])
                if len(raw) != item["bytes"] or hashlib.sha256(raw).hexdigest() != item["sha256"]:
                    raise ValueError("归档内容校验失败")
                ast.parse(raw, filename=item["path"])
                if hashlib.sha256((project / item["path"]).read_bytes()).hexdigest() != item["sha256"]:
                    raise ValueError("原脚本变化，停止发布")
        os.link(temporary, output)
        return {**plan, "mode": "apply", "archive": output.as_posix(),
                "archive_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
                "verified_sources": len(plan["entries"])}
    finally:
        temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.report.exists():
        raise FileExistsError(args.report)
    report = archive_sources(ROOT, args.archive, apply=args.apply)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in
                      ("mode", "historical_candidates", "dependency_sources", "moved_files", "deleted_files")},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
