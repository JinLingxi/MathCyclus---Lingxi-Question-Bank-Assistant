"""build.yaml backup before export / restore on failure."""

from __future__ import annotations

from pathlib import Path

from solaire.web.exam_service import (
    BUILD_BACKUP_NAME,
    BUILD_EXAM_NAME,
    discard_build_yaml_backup,
    restore_build_yaml_from_backup,
    snapshot_build_yaml_before_export,
)


def test_snapshot_restore_discard(tmp_path: Path) -> None:
    sol = tmp_path / ".solaire"
    sol.mkdir(parents=True)
    build = sol / BUILD_EXAM_NAME
    build.write_text("old-content", encoding="utf-8")

    backup = snapshot_build_yaml_before_export(tmp_path)
    assert backup is not None
    assert backup.name == BUILD_BACKUP_NAME
    assert backup.read_text(encoding="utf-8") == "old-content"

    build.write_text("new-content", encoding="utf-8")
    restore_build_yaml_from_backup(tmp_path, backup)
    assert build.read_text(encoding="utf-8") == "old-content"

    discard_build_yaml_backup(backup)
    assert not backup.is_file()
    assert build.read_text(encoding="utf-8") == "old-content"


def test_snapshot_returns_none_when_no_build_yaml(tmp_path: Path) -> None:
    (tmp_path / ".solaire").mkdir(parents=True)
    assert snapshot_build_yaml_before_export(tmp_path) is None
