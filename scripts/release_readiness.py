from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = PROJECT_ROOT / "reports"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class CheckCommand:
    name: str
    command: list[str]
    warning_markers: tuple[str, ...] = ()
    fail_markers: tuple[str, ...] = ()


def relative_to_root(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="运行 MathCyclus 发布前总检查。")
    parser.add_argument("--stamp", default=datetime.now().strftime("%Y%m%d_%H%M%S"), help="报告时间戳。")
    parser.add_argument("--skip-slow", action="store_true", help="跳过较完整的 smoke，只保留编译和核心审计。")
    return parser.parse_args()


def build_commands(skip_slow: bool) -> list[CheckCommand]:
    python = sys.executable
    commands = [
        CheckCommand(
            "python_compile",
            [python, "-m", "compileall", "-q", "question_bank_app.py", "services", "scripts"],
        ),
        CheckCommand("rebuild_status_brief", [python, "scripts/rebuild_status.py", "--brief"]),
        CheckCommand(
            "precommit_database_audit",
            [python, "scripts/precommit_database_audit.py"],
            warning_markers=("status=warning",),
            fail_markers=("status=blocked",),
        ),
        CheckCommand("question_asset_audit", [python, "scripts/audit_question_assets.py"]),
        CheckCommand("smoke_statistics_service", [python, "scripts/smoke_statistics_service.py"]),
        CheckCommand("smoke_schema_migration_service", [python, "scripts/smoke_schema_migration_service.py"]),
        CheckCommand("smoke_local_workspace_tools", [python, "scripts/smoke_local_workspace_tools.py"]),
        CheckCommand("smoke_local_preferences_service", [python, "scripts/smoke_local_preferences_service.py"]),
        CheckCommand("smoke_topic_collection_service", [python, "scripts/smoke_topic_collection_service.py"]),
        CheckCommand("smoke_question_traceback_service", [python, "scripts/smoke_question_traceback_service.py"]),
        CheckCommand("smoke_draft_parse_service", [python, "scripts/smoke_draft_parse_service.py"]),
        CheckCommand("smoke_update_local_installation", [python, "scripts/smoke_update_local_installation.py"]),
        CheckCommand("smoke_source_release_package", [python, "scripts/smoke_source_release_package.py"]),
        CheckCommand(
            "audit_tracked_private_files",
            [python, "scripts/audit_tracked_private_files.py"],
            warning_markers=("status=warning",),
            fail_markers=("status=blocked",),
        ),
        CheckCommand("smoke_windows_launcher", [python, "scripts/smoke_windows_launcher.py"]),
        CheckCommand(
            "project_hygiene",
            [python, "scripts/check_project_hygiene.py"],
            warning_markers=("status=warning",),
            fail_markers=("status=blocked",),
        ),
    ]
    if not skip_slow:
        commands.extend(
            [
                CheckCommand("smoke_database_services", [python, "scripts/smoke_database_services.py"]),
                CheckCommand("smoke_question_edit_service", [python, "scripts/smoke_question_edit_service.py"]),
                CheckCommand("smoke_asset_service", [python, "scripts/smoke_asset_service.py"]),
                CheckCommand("smoke_source_relation_service", [python, "scripts/smoke_source_relation_service.py"]),
                CheckCommand("smoke_source_export_service", [python, "scripts/smoke_source_export_service.py"]),
                CheckCommand("smoke_manual_draft_service", [python, "scripts/smoke_manual_draft_service.py"]),
                CheckCommand("smoke_draft_commit_service", [python, "scripts/smoke_draft_commit_service.py"]),
                CheckCommand("smoke_sqlite_legacy_adapter", [python, "scripts/smoke_sqlite_legacy_adapter.py"]),
                CheckCommand("smoke_exam_selection_service", [python, "scripts/smoke_exam_selection_service.py"]),
                CheckCommand("smoke_legacy_exam_selection_service", [python, "scripts/smoke_legacy_exam_selection_service.py"]),
                CheckCommand("audit_sqlite_legacy_bridge", [python, "scripts/audit_sqlite_legacy_bridge.py"]),
                CheckCommand(
                    "audit_legacy_sqlite_consistency",
                    [python, "scripts/audit_legacy_sqlite_consistency.py"],
                    warning_markers=("status=warning",),
                    fail_markers=("status=blocked",),
                ),
            ]
        )
    return commands


def run_command(item: CheckCommand) -> dict[str, Any]:
    completed = subprocess.run(
        item.command,
        cwd=PROJECT_ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        check=False,
    )
    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    warning = any(marker in stdout or marker in stderr for marker in item.warning_markers)
    marker_failed = any(marker in stdout or marker in stderr for marker in item.fail_markers)
    return {
        "name": item.name,
        "command": item.command,
        "returncode": completed.returncode,
        "ok": completed.returncode == 0 and not marker_failed,
        "warning": warning,
        "marker_failed": marker_failed,
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
    }


def format_output_tail(text: str, *, max_lines: int = 12) -> str:
    lines = [line for line in text.splitlines() if line.strip()]
    if not lines:
        return "（无输出）"
    return "\n".join(lines[-max_lines:])


def write_reports(report: dict[str, Any], stamp: str) -> tuple[Path, Path]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    json_path = REPORTS_DIR / f"release_readiness_{stamp}.json"
    md_path = REPORTS_DIR / f"release_readiness_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    result_lines = []
    detail_sections = []
    for item in report["results"]:
        marker = "PASS" if item["ok"] and not item["warning"] else "WARN" if item["ok"] else "FAIL"
        result_lines.append(
            f"| `{item['name']}` | `{marker}` | `{item['returncode']}` | `{item['warning']}` | `{item['marker_failed']}` |"
        )
        if marker != "PASS":
            stdout_tail = format_output_tail(item["stdout_tail"])
            stderr_tail = format_output_tail(item["stderr_tail"])
            detail_sections.append(
                f"""### `{item['name']}`

- 结果：`{marker}`
- warning marker：`{item['warning']}`
- fail marker：`{item['marker_failed']}`

stdout：

```text
{stdout_tail}
```

stderr：

```text
{stderr_tail}
```
"""
            )
    detail_text = "\n".join(detail_sections) if detail_sections else "- 无"
    md_path.write_text(
        f"""# 发布前总检查报告

> 生成时间：{report['created_at']}  
> 状态：`{report['status']}`  
> 失败：`{report['failed_count']}`  
> 警告：`{report['warning_count']}`  
> 说明：脚本只运行编译、审计和 smoke，不提交 Git，不修改旧 `.tex` 题库。

## 检查结果

| 检查 | 结果 | 返回码 | warning marker | fail marker |
| --- | --- | ---: | --- | --- |
{chr(10).join(result_lines)}

## 异常明细

{detail_text}

## 判断口径

- `ok`：所有命令通过，且没有需要人工确认的 warning。
- `warning`：命令通过，但存在提交前需要人工确认的项目卫生或数据口径提示。
- `blocked`：至少一个命令失败，不建议提交或推送。
""",
        encoding="utf-8",
    )
    return md_path, json_path


def main() -> None:
    args = parse_args()
    results = [run_command(item) for item in build_commands(args.skip_slow)]
    failed = [item for item in results if not item["ok"]]
    warnings = [item for item in results if item["ok"] and item["warning"]]
    status = "blocked" if failed else "warning" if warnings else "ok"
    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "failed_count": len(failed),
        "warning_count": len(warnings),
        "results": results,
    }
    md_path, json_path = write_reports(report, args.stamp)
    print(f"status={status}")
    print(f"failed={len(failed)}")
    print(f"warnings={len(warnings)}")
    print(f"report={relative_to_root(md_path)}")
    print(f"json={relative_to_root(json_path)}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
