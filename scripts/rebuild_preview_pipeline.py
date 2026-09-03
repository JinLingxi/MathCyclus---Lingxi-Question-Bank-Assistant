from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def run_step(name: str, command: list[str], dry_run: bool) -> dict[str, Any]:
    started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    if dry_run:
        return {
            "name": name,
            "command": command,
            "started_at": started_at,
            "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "skipped_by_pipeline_dry_run": True,
        }

    completed = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    return {
        "name": name,
        "command": command,
        "started_at": started_at,
        "finished_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "skipped_by_pipeline_dry_run": False,
    }


def command_text(command: list[str]) -> str:
    return " ".join(command)


def python_command(*args: str) -> list[str]:
    return [sys.executable, *args]


def build_steps(args: argparse.Namespace) -> list[tuple[str, list[str]]]:
    stamp = args.stamp
    initial_db = f"data/mathcyclus_preview_{stamp}.sqlite3"
    mapped_db = f"data/mathcyclus_preview_paper_mapped_{stamp}.sqlite3"
    corrected_db = f"data/mathcyclus_preview_paper_corrected_{stamp}.sqlite3"
    combined_db = f"data/mathcyclus_preview_combined_{stamp}.sqlite3"

    steps = [
        ("scan_tex_library", python_command("scripts/scan_tex_library.py", "--stamp", stamp)),
        ("migrate_tex_to_db", python_command("scripts/migrate_tex_to_db_dry_run.py", "--stamp", stamp)),
        (
            "apply_paper_mapping",
            python_command(
                "scripts/apply_paper_name_mapping_dry_run.py",
                "--source-db",
                initial_db,
                "--mapping",
                args.paper_mapping,
                "--stamp",
                stamp,
            ),
        ),
        (
            "apply_paper_question_corrections",
            python_command(
                "scripts/apply_paper_question_corrections_dry_run.py",
                "--source-db",
                mapped_db,
                "--corrections",
                args.paper_question_corrections,
                "--stamp",
                stamp,
            ),
        ),
        (
            "build_combined_preview",
            python_command(
                "scripts/build_combined_preview_db.py",
                "--source-db",
                corrected_db,
                "--output-db",
                combined_db,
                "--stamp",
                stamp,
                "--decisions",
                args.equivalence_decisions,
                "--draft-input",
                args.draft_input,
                "--draft-review",
                args.draft_review,
                "--tex-corrections",
                args.tex_corrections,
                "--book-input",
                args.book_input,
                "--topic-input",
                args.topic_input,
                "--report-stem",
                f"combined_preview_build_{stamp}",
            ),
        ),
        (
            "audit_combined_preview",
            python_command(
                "scripts/precommit_database_audit.py",
                "--db",
                combined_db,
                "--stamp",
                f"{stamp}_combined",
            ),
        ),
        (
            "audit_seed_review_status",
            python_command(
                "scripts/audit_seed_review_status.py",
                "--paper-mapping",
                args.paper_mapping,
                "--equivalence-decisions",
                args.equivalence_decisions,
                "--stamp",
                stamp,
            ),
        ),
        (
            "promotion_dry_run",
            python_command(
                "scripts/promote_preview_to_database.py",
                "--source-db",
                combined_db,
                "--stamp",
                f"{stamp}_promotion",
            ),
        ),
    ]

    if args.with_commit_preview:
        commit_db = f"data/mathcyclus_preview_combined_{stamp}_commit_preview.sqlite3"
        steps.extend(
            [
                (
                    "build_combined_commit_preview",
                    python_command(
                        "scripts/build_combined_preview_db.py",
                        "--source-db",
                        corrected_db,
                        "--output-db",
                        commit_db,
                        "--stamp",
                        stamp,
                        "--decisions",
                        args.equivalence_decisions,
                        "--draft-input",
                        args.draft_input,
                        "--draft-review",
                        args.draft_review,
                        "--tex-corrections",
                        args.tex_corrections,
                        "--book-input",
                        args.book_input,
                        "--topic-input",
                        args.topic_input,
                        "--report-stem",
                        f"combined_preview_build_{stamp}_commit_preview",
                        "--commit-ready-drafts",
                    ),
                ),
                (
                    "diff_commit_preview",
                    python_command(
                        "scripts/diff_preview_databases.py",
                        "--before-db",
                        combined_db,
                        "--after-db",
                        commit_db,
                        "--stamp",
                        f"{stamp}_commit_preview_delta",
                    ),
                ),
            ]
        )

    return steps


def write_report(report: dict[str, Any], md_path: Path, json_path: Path) -> None:
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    step_lines = "\n".join(
        f"| {index} | `{step['name']}` | `{step['returncode']}` | `{command_text(step['command'])}` |"
        for index, step in enumerate(report["steps"], start=1)
    )
    failed = [step for step in report["steps"] if step["returncode"] != 0]
    failure_text = "\n".join(
        f"- `{step['name']}`：`{step['stderr'].strip() or step['stdout'].strip() or '无输出'}`"
        for step in failed
    ) or "无"

    md_path.write_text(
        f"""# 预览库重建流水线报告

> 生成时间：{report['created_at']}  
> stamp：`{report['stamp']}`  
> 状态：`{report['status']}`  
> 执行模式：`{'dry_run' if report['pipeline_dry_run'] else 'run'}`  
> 说明：只串联 dry-run/审计脚本，不创建正式 SQLite，不修改旧 `.tex`。

## 步骤

| 序号 | 步骤 | 返回码 | 命令 |
| ---: | --- | ---: | --- |
{step_lines}

## 失败项

{failure_text}

## 产物规则

- SQLite 预览库写入 `data/`，默认被 `.gitignore` 忽略。
- CSV/JSON 报告默认被 `.gitignore` 忽略。
- Markdown 报告保留用于 Git 追踪。
- 人工 seed 表不会被覆盖。
- 正式库提升仍需单独运行 `scripts/promote_preview_to_database.py` 并显式确认。
""",
        encoding="utf-8",
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="一键串联预览库重建 dry-run/审计链路。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="本次流水线时间戳。")
    parser.add_argument("--pipeline-dry-run", action="store_true", help="只输出将要执行的命令，不真正运行。")
    parser.add_argument("--with-commit-preview", action="store_true", help="额外生成 ready 草稿提交预演库并做差异报告。")
    parser.add_argument("--paper-mapping", default="db/seed/paper_name_mapping.csv")
    parser.add_argument("--paper-question-corrections", default="db/seed/paper_question_corrections_20260902_final_review.csv")
    parser.add_argument("--equivalence-decisions", default="db/seed/equivalence_review_decisions_20260902_initial.csv")
    parser.add_argument("--draft-input", default="templates/ai_ocr_draft_import_example.json")
    parser.add_argument("--draft-review", default="db/seed/import_draft_review_20260902_warning_review.csv")
    parser.add_argument("--tex-corrections", default="db/seed/question_tex_corrections_20260902_final_review.csv")
    parser.add_argument("--book-input", default="templates/book_import_example.json")
    parser.add_argument("--topic-input", default="templates/topic_import_example.json")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    steps = []
    status = "ok"
    for name, command in build_steps(args):
        result = run_step(name, command, dry_run=args.pipeline_dry_run)
        steps.append(result)
        print(f"{name}: returncode={result['returncode']}")
        if result["stdout"].strip():
            print(result["stdout"].strip())
        if result["stderr"].strip():
            print(result["stderr"].strip(), file=sys.stderr)
        if result["returncode"] != 0:
            status = "failed"
            break

    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "stamp": args.stamp,
        "status": status,
        "pipeline_dry_run": args.pipeline_dry_run,
        "with_commit_preview": args.with_commit_preview,
        "steps": steps,
    }
    md_path = REPORTS_DIR / f"preview_pipeline_{args.stamp}.md"
    json_path = REPORTS_DIR / f"preview_pipeline_{args.stamp}.json"
    write_report(report, md_path, json_path)
    print(f"status={status}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")
    if status != "ok":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
