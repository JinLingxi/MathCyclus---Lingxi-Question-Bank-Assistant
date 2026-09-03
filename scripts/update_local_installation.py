"""Safely update a local MathCyclus checkout.

This helper is intended for users who installed the project from GitHub and
want a repeatable upgrade command.  It is conservative by default:

- dry-run unless ``--apply`` is passed;
- never deletes local data;
- backs up local data before changing code when applying;
- refuses ``git pull`` on a dirty working tree unless explicitly allowed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_BACKUP_FILES = [
    ".env",
    "ocr_prompt.txt",
    ".streamlit/secrets.toml",
]

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def relative_to_root(path: Path, project_root: Path) -> str:
    try:
        return path.resolve().relative_to(project_root.resolve()).as_posix()
    except ValueError:
        return str(path)


def resolve_project_path(project_root: Path, value: str | Path) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path.resolve()
    return (project_root / path).resolve()


def ensure_inside_project(project_root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(project_root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径不在项目目录内：{path}") from exc


def command_to_text(command: list[str]) -> str:
    return subprocess.list2cmdline(command)


def run_command(
    command: list[str],
    *,
    project_root: Path,
    timeout: int = 600,
    dry_run: bool = False,
    label: str,
) -> dict[str, Any]:
    if dry_run:
        return {
            "label": label,
            "command": command,
            "command_text": command_to_text(command),
            "returncode": None,
            "ok": True,
            "skipped": True,
            "stdout_tail": "",
            "stderr_tail": "",
        }

    try:
        completed = subprocess.run(
            command,
            cwd=project_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=timeout,
        )
        return {
            "label": label,
            "command": command,
            "command_text": command_to_text(command),
            "returncode": completed.returncode,
            "ok": completed.returncode == 0,
            "skipped": False,
            "stdout_tail": (completed.stdout or "")[-4000:],
            "stderr_tail": (completed.stderr or "")[-4000:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "label": label,
            "command": command,
            "command_text": command_to_text(command),
            "returncode": -1,
            "ok": False,
            "skipped": False,
            "stdout_tail": (exc.stdout or "")[-4000:],
            "stderr_tail": "命令执行超时。",
        }
    except OSError as exc:
        return {
            "label": label,
            "command": command,
            "command_text": command_to_text(command),
            "returncode": -1,
            "ok": False,
            "skipped": False,
            "stdout_tail": "",
            "stderr_tail": str(exc),
        }


def git_available() -> bool:
    return shutil.which("git") is not None


def git_text(project_root: Path, args: list[str]) -> str:
    if not git_available():
        return ""
    completed = subprocess.run(
        ["git", *args],
        cwd=project_root,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        check=False,
    )
    return (completed.stdout or "").strip()


def git_snapshot(project_root: Path) -> dict[str, Any]:
    if not git_available():
        return {
            "available": False,
            "branch": "",
            "head": "",
            "upstream": "",
            "dirty_lines": [],
            "dirty": False,
        }
    dirty_lines = [line for line in git_text(project_root, ["status", "--short"]).splitlines() if line.strip()]
    return {
        "available": True,
        "branch": git_text(project_root, ["branch", "--show-current"]),
        "head": git_text(project_root, ["rev-parse", "--short", "HEAD"]),
        "upstream": git_text(project_root, ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"]),
        "dirty_lines": dirty_lines[:120],
        "dirty_count": len(dirty_lines),
        "dirty": bool(dirty_lines),
    }


def backup_config_files(project_root: Path, *, stamp: str, dry_run: bool) -> dict[str, Any]:
    backup_dir = project_root / "data" / "backups" / f"config_backup_{stamp}"
    ensure_inside_project(project_root, backup_dir)
    copied: list[str] = []
    missing: list[str] = []

    for relative in CONFIG_BACKUP_FILES:
        source = resolve_project_path(project_root, relative)
        ensure_inside_project(project_root, source)
        if not source.exists() or not source.is_file():
            missing.append(relative)
            continue
        target = backup_dir / relative.replace("/", "__").replace("\\", "__")
        ensure_inside_project(project_root, target)
        if not dry_run:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        copied.append(relative_to_root(target, project_root))

    return {
        "path": relative_to_root(backup_dir, project_root),
        "copied": copied,
        "missing": missing,
        "dry_run": dry_run,
        "contains_secrets": ".env" in CONFIG_BACKUP_FILES,
        "intended_for_git": False,
    }


def build_update_plan(args: argparse.Namespace, project_root: Path, stamp: str) -> list[dict[str, Any]]:
    python = sys.executable
    plan = [
        {
            "label": "初始化/校验本地目录",
            "command": [
                python,
                "scripts/init_local_workspace.py",
                "--strict-gitignore",
                *([] if args.apply else ["--dry-run"]),
            ],
        },
        {
            "label": "备份本地数据库和图片资源",
            "command": [
                python,
                "scripts/local_data_bundle.py",
                "export",
                "--stamp",
                stamp,
                *([] if args.apply else ["--dry-run"]),
                *(["--include-legacy-tex"] if args.include_legacy_tex_backup else []),
            ],
        },
    ]
    if args.pull:
        plan.append({"label": "从 GitHub 拉取代码", "command": ["git", "pull", "--ff-only"]})
    if args.install_deps:
        plan.append({"label": "更新 Python 依赖", "command": [python, "-m", "pip", "install", "-r", "requirements.txt"]})
    plan.append({"label": "更新后补齐本地目录", "command": [python, "scripts/init_local_workspace.py", "--strict-gitignore"]})
    plan.append(
        {
            "label": "检查/应用数据库 schema 迁移",
            "command": [
                python,
                "scripts/migrate_schema.py",
                *(["--apply"] if args.apply else []),
                "--stamp",
                stamp,
            ],
        }
    )
    if args.run_checks:
        plan.append({"label": "运行发布前快速检查", "command": [python, "scripts/release_readiness.py", "--skip-slow"]})
    return plan


def write_report(report: dict[str, Any], project_root: Path, stamp: str) -> tuple[Path, Path]:
    reports_dir = project_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / f"local_update_{stamp}.json"
    md_path = reports_dir / f"local_update_{stamp}.md"
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    result_rows = []
    for item in report["commands"]:
        marker = "SKIP" if item.get("skipped") else "PASS" if item.get("ok") else "FAIL"
        result_rows.append(
            f"| {item['label']} | `{marker}` | `{item.get('returncode')}` | `{item['command_text']}` |"
        )
    blockers = "\n".join(f"- {item}" for item in report["blockers"]) or "- 无"
    warnings = "\n".join(f"- {item}" for item in report["warnings"]) or "- 无"
    md_path.write_text(
        f"""# 本地版本更新报告

> 生成时间：{report['created_at']}  
> 状态：`{report['status']}`  
> dry-run：`{report['dry_run']}`  
> 项目目录：`{report['project_root']}`

## 阻塞项

{blockers}

## 提醒项

{warnings}

## 命令结果

| 步骤 | 结果 | 返回码 | 命令 |
| --- | --- | ---: | --- |
{chr(10).join(result_rows) or '| 无 | `SKIP` |  |  |'}

## 安全边界

- 不删除任何本地数据；
- 应用更新前先备份本地数据库和图片资源；
- `.env`、`data/`、`assets/questions/`、`reports/`、`exports/` 仍由 `.gitignore` 保护；
- `git pull` 使用 `--ff-only`，避免自动生成合并提交。
""",
        encoding="utf-8",
    )
    return md_path, json_path


def update_local_installation(args: argparse.Namespace) -> dict[str, Any]:
    project_root = resolve_project_path(PROJECT_ROOT, args.project_root)
    ensure_inside_project(PROJECT_ROOT, project_root)
    stamp = args.stamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    git = git_snapshot(project_root)
    blockers: list[str] = []
    warnings: list[str] = []

    if args.pull and not git["available"]:
        blockers.append("当前环境未检测到 git，不能执行 --pull。")
    if args.pull and git.get("dirty") and not args.allow_dirty:
        blockers.append("工作区存在未提交改动，默认拒绝 git pull；如确认可处理冲突，再加 --allow-dirty。")
    if args.pull and git["available"] and not git.get("upstream"):
        warnings.append("当前分支未检测到 upstream；git pull 可能需要手动指定远端分支。")
    if not args.pull:
        warnings.append("未启用 --pull；本次只做本地目录、备份和可选依赖/检查流程。")
    if not args.install_deps:
        warnings.append("未启用 --install-deps；如果 requirements.txt 更新，需要手动安装依赖。")
    if not args.apply:
        warnings.append("当前为 dry-run，不会写入备份、不会拉取代码、不会安装依赖。")

    commands: list[dict[str, Any]] = []
    execute_apply = args.apply and not blockers
    config_backup = backup_config_files(project_root, stamp=stamp, dry_run=not execute_apply)

    if blockers and args.apply:
        status = "blocked"
    else:
        for item in build_update_plan(args, project_root, stamp):
            command = item["command"]
            label = item["label"]
            dry_run = not execute_apply
            if label == "更新后补齐本地目录":
                dry_run = not execute_apply
            commands.append(run_command(command, project_root=project_root, dry_run=dry_run, label=label, timeout=1200))
        failed = [item for item in commands if not item["ok"]]
        status = "blocked" if failed or blockers else "warning" if warnings else "ok"

    report = {
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": status,
        "dry_run": not args.apply,
        "project_root": str(project_root),
        "stamp": stamp,
        "git": git,
        "blockers": blockers,
        "warnings": warnings,
        "config_backup": config_backup,
        "commands": commands,
        "deletes_files": False,
        "overwrites_local_database": False,
        "recommended_apply_command": (
            "python scripts/update_local_installation.py --apply --pull --install-deps --run-checks"
        ),
    }
    if args.write_report or args.apply:
        md_path, json_path = write_report(report, project_root, stamp)
        report["report"] = relative_to_root(md_path, project_root)
        report["json"] = relative_to_root(json_path, project_root)
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="安全更新本地 MathCyclus 安装。默认只 dry-run。")
    parser.add_argument("--project-root", default=str(PROJECT_ROOT), help="项目根目录。")
    parser.add_argument("--stamp", default="", help="备份和报告时间戳。")
    parser.add_argument("--apply", action="store_true", help="实际执行更新步骤；不加则只预览。")
    parser.add_argument("--pull", action="store_true", help="执行 git pull --ff-only。")
    parser.add_argument("--allow-dirty", action="store_true", help="允许在工作区有未提交改动时执行 pull。")
    parser.add_argument("--install-deps", action="store_true", help="执行 python -m pip install -r requirements.txt。")
    parser.add_argument("--run-checks", action="store_true", help="更新后运行 release_readiness.py --skip-slow。")
    parser.add_argument("--include-legacy-tex-backup", action="store_true", help="备份包中包含旧 chapters TeX 题源。")
    parser.add_argument("--write-report", action="store_true", help="dry-run 时也写入 reports/local_update_*.md/json。")
    parser.add_argument("--json", action="store_true", help="输出完整 JSON。")
    return parser.parse_args()


def print_summary(report: dict[str, Any]) -> None:
    print(f"status={report['status']}")
    print(f"dry_run={report['dry_run']}")
    print(f"git_dirty={report['git'].get('dirty')}")
    print(f"blockers={len(report['blockers'])}")
    print(f"warnings={len(report['warnings'])}")
    print(f"commands={len(report['commands'])}")
    if report.get("report"):
        print(f"report={report['report']}")
    if report.get("json"):
        print(f"json={report['json']}")


def main() -> None:
    args = parse_args()
    report = update_local_installation(args)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print_summary(report)
    if report["status"] == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
