"""Smoke test for the local update helper.

The update helper is intentionally conservative.  This smoke only exercises
its dry-run path so release checks can verify the generated plan without
pulling GitHub, installing dependencies, writing reports, or touching user data.
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.update_local_installation import update_local_installation


def build_args(project_root: Path) -> argparse.Namespace:
    return argparse.Namespace(
        project_root=str(project_root),
        stamp="smoke_update_local_installation",
        apply=False,
        pull=True,
        allow_dirty=True,
        install_deps=True,
        run_checks=True,
        include_legacy_tex_backup=False,
        write_report=False,
        json=False,
    )


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_update_smoke_", dir=PROJECT_ROOT) as temp_dir:
        temp_root = Path(temp_dir)
        report = update_local_installation(build_args(temp_root))

    assert report["dry_run"] is True, report
    assert report["status"] in {"ok", "warning"}, report
    assert report["deletes_files"] is False, report
    assert report["overwrites_local_database"] is False, report
    assert not report["blockers"], report
    assert report["config_backup"]["dry_run"] is True, report
    assert report["config_backup"]["intended_for_git"] is False, report
    assert "report" not in report, report
    assert "json" not in report, report

    labels = [item["label"] for item in report["commands"]]
    assert "初始化/校验本地目录" in labels, labels
    assert "备份本地数据库和图片资源" in labels, labels
    assert "从 GitHub 拉取代码" in labels, labels
    assert "更新 Python 依赖" in labels, labels
    assert "检查/应用数据库 schema 迁移" in labels, labels
    assert "运行发布前快速检查" in labels, labels
    assert all(item["skipped"] for item in report["commands"]), report

    print("smoke_update_local_installation: status=ok")
    print("dry_run_only=true")
    print("writes_reports=false")
    print("deletes_files=false")
    print("overwrites_local_database=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
