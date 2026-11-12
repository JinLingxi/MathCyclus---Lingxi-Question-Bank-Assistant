"""Create a static maintenance-script catalog without executing any script."""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HISTORICAL_PREFIXES = ("stage_", "record_", "prepare_", "payload", "fix", "tmp_", "import0",
                       "import1", "import2", "import3", "import4", "import5", "import6",
                       "import7", "import8", "import9")
WRITE_METHODS = {"write_text", "write_bytes", "unlink", "rmdir", "remove", "rmtree",
                 "replace", "rename", "move", "copy", "copy2", "copyfile", "executescript",
                 "commit", "save"}


def catalog(project: Path) -> dict:
    scripts = sorted((project / "scripts").glob("*.py"))
    texts = {}
    for directory in ("scripts", "services", "utils", "components", "docs"):
        for path in (project / directory).rglob("*"):
            if path.suffix in {".py", ".md", ".json", ".bat", ".ps1"} and path.is_file():
                texts[path.relative_to(project).as_posix()] = path.read_text(encoding="utf-8-sig", errors="replace")
    for path in project.glob("*"):
        if path.is_file() and path.suffix in {".py", ".md", ".bat"}:
            texts[path.name] = path.read_text(encoding="utf-8-sig", errors="replace")
    rows = []
    for path in scripts:
        relative = path.relative_to(project).as_posix()
        text = texts[relative]
        mentions = [name for name, source in texts.items() if name != relative
                    and (path.name in source or "scripts." + path.stem in source)]
        signals, sql_writes, main_guard, imports, error = [], False, False, [], ""
        try:
            tree = ast.parse(text)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module:
                    imports.append(node.module)
                elif isinstance(node, ast.Import):
                    imports.extend(alias.name for alias in node.names)
                elif isinstance(node, ast.Call):
                    name = node.func.attr if isinstance(node.func, ast.Attribute) else (
                        node.func.id if isinstance(node.func, ast.Name) else "")
                    if name in WRITE_METHODS:
                        signals.append(name)
                    if name in {"execute", "executemany", "executescript"} and node.args:
                        argument = node.args[0]
                        if isinstance(argument, ast.Constant) and isinstance(argument.value, str):
                            sql_writes |= argument.value.lstrip().upper().startswith(
                                ("UPDATE", "INSERT", "DELETE", "REPLACE", "ALTER", "DROP", "CREATE"))
                elif isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id == "__name__":
                    main_guard = True
            title = (ast.get_docstring(tree) or "").splitlines()
        except SyntaxError as exc:
            error = str(exc)
            title = []
        historical = path.name.startswith(HISTORICAL_PREFIXES)
        if path.name.startswith(("smoke_", "test_", "check_project_", "audit_", "verify_")):
            category = "verification_and_audit"
        elif historical:
            category = "historical_task_candidate"
        elif path.name.startswith(("backup_", "migrate_", "local_", "build_", "init_", "update_")):
            category = "operational_tool"
        else:
            category = "manual_review"
        rows.append({"path": relative, "category": category, "description": title[0] if title else "",
                     "referenced_by": mentions, "imports": sorted(set(imports)),
                     "write_signals": sorted(set(signals)), "literal_sql_writes": sql_writes,
                     "has_main_guard": main_guard, "parse_error": error,
                     "action": "retain_current_path_pending_manual_review"})
    return {"mode": "static_read_only", "created_at": datetime.now().astimezone().isoformat(),
            "scripts": rows, "categories": dict(Counter(row["category"] for row in rows)),
            "moved_files": 0, "deleted_files": 0, "limitations": [
                "Literal references are evidence of use, absence is not evidence of non-use.",
                "AST write signals are conservative hints, not a security audit or safe-to-run verdict.",
                "No scripts are imported or executed by this catalog.",
                "Historical scripts may depend on their original relative paths."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = catalog(ROOT)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({"scripts": len(report["scripts"]), "categories": report["categories"],
                      "parse_errors": sum(bool(row["parse_error"]) for row in report["scripts"]),
                      "moved_files": 0, "deleted_files": 0}, ensure_ascii=False))


if __name__ == "__main__":
    main()
