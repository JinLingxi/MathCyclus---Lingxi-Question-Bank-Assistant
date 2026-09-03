from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.build_source_release_package import tracked_cleanup_candidates


def powershell_quote(value: str) -> str:
    return '"' + value.replace("`", "``").replace('"', '`"') + '"'


def classify(path: str) -> str:
    if path.startswith("chapters/"):
        return "legacy_chapters"
    if path.startswith("Test Paper Group/导出文件/"):
        return "exported_papers"
    if path.startswith("data/") or path.endswith((".sqlite", ".sqlite3", ".db")):
        return "local_database"
    if path.startswith("db/seed/"):
        return "local_migration_seed"
    if path.startswith("assets/questions/"):
        return "question_assets"
    if path.startswith("reports/"):
        return "reports"
    if path.startswith("exports/") or path.startswith("cloze_exports/"):
        return "exports"
    if path.endswith(".pdf"):
        return "pdf"
    return "other"


def build_report() -> dict[str, Any]:
    candidates = tracked_cleanup_candidates()
    grouped: dict[str, list[str]] = {}
    for path in candidates:
        grouped.setdefault(classify(path), []).append(path)
    commands = [f"git rm --cached -- {powershell_quote(path)}" for path in candidates]
    return {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "warning" if candidates else "ok",
        "mode": "dry_run_only",
        "executes_git": False,
        "apply_available": True,
        "apply_requires": "--apply --confirm KEEP_LOCAL",
        "deletes_local_files": False,
        "local_files_kept": True,
        "tracked_cleanup_count": len(candidates),
        "tracked_cleanup_candidates": candidates,
        "grouped": grouped,
        "cleanup_commands": commands,
        "recommended_policy": "Use git rm --cached to remove private/generated legacy files from Git tracking while keeping the files on disk.",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Audit tracked private/generated files and print a safe Git cleanup plan."
    )
    parser.add_argument("--json", action="store_true", help="Print full JSON report.")
    parser.add_argument("--commands", action="store_true", help="Print full git rm --cached command list.")
    parser.add_argument("--apply", action="store_true", help="Run git rm --cached for all reported files.")
    parser.add_argument("--confirm", default="", help="Required value for --apply: KEEP_LOCAL.")
    return parser.parse_args()


def apply_cleanup(paths: list[str]) -> dict[str, Any]:
    if not paths:
        return {"returncode": 0, "stdout": "", "stderr": "", "removed_from_index_count": 0}
    completed = subprocess.run(
        ["git", "rm", "--cached", "--", *paths],
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "returncode": completed.returncode,
        "stdout": completed.stdout.strip(),
        "stderr": completed.stderr.strip(),
        "removed_from_index_count": len(paths) if completed.returncode == 0 else 0,
    }


def main() -> None:
    args = parse_args()
    report = build_report()
    if args.apply:
        if args.confirm != "KEEP_LOCAL":
            result = {
                **report,
                "status": "blocked",
                "apply_attempted": False,
                "apply_error": "Refusing to run without --confirm KEEP_LOCAL.",
            }
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else "status=blocked\napply_error=missing_confirm")
            raise SystemExit(2)
        apply_result = apply_cleanup(report["tracked_cleanup_candidates"])
        report = {
            **report,
            "status": "ok" if apply_result["returncode"] == 0 else "blocked",
            "apply_attempted": True,
            "apply_result": apply_result,
            "executes_git": True,
        }
        if args.json:
            print(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            print(f"status={report['status']}")
            print("mode=apply_cached_only")
            print("deletes_local_files=False")
            print(f"removed_from_index_count={apply_result['removed_from_index_count']}")
            print(f"returncode={apply_result['returncode']}")
            if apply_result["stderr"]:
                print("stderr:")
                print(apply_result["stderr"])
        if apply_result["returncode"] != 0:
            raise SystemExit(apply_result["returncode"])
        return

    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return

    print(f"status={report['status']}")
    print(f"mode={report['mode']}")
    print(f"executes_git={report['executes_git']}")
    print(f"apply_requires={report['apply_requires']}")
    print(f"deletes_local_files={report['deletes_local_files']}")
    print(f"tracked_cleanup_count={report['tracked_cleanup_count']}")
    for group, paths in sorted(report["grouped"].items()):
        print(f"{group}={len(paths)}")

    candidates = report["tracked_cleanup_candidates"]
    if candidates:
        print("")
        print("cleanup_preview:")
        for path in candidates[:12]:
            print(f"- {path}")
        if len(candidates) > 12:
            print(f"- ... {len(candidates) - 12} more")
        print("")
        print("Use --commands to print git rm --cached commands.")

    if args.commands:
        print("")
        print("commands:")
        for command in report["cleanup_commands"]:
            print(command)


if __name__ == "__main__":
    main()
