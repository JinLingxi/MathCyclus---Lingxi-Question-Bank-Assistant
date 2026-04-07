"""Draft persistence: unique names and export-failure drafts."""

from __future__ import annotations

from pathlib import Path

import pytest

from solaire.web.draft_service import save_draft, save_draft_after_export_failure
from solaire.web.project_layout import ensure_project_layout


def test_save_draft_duplicate_display_name_rejected(tmp_path: Path) -> None:
    root = tmp_path
    ensure_project_layout(root)
    save_draft(
        root,
        draft_id=None,
        name="我的草稿",
        subject="数学",
        export_label="期中",
        template_ref="t",
        template_path="templates/x.yaml",
        selected_items=[],
    )
    with pytest.raises(ValueError, match="草稿名称已存在"):
        save_draft(
            root,
            draft_id=None,
            name="我的草稿",
            subject="数学",
            export_label="期中",
            template_ref="t",
            template_path="templates/x.yaml",
            selected_items=[],
        )


def test_same_name_allowed_when_updating_same_draft(tmp_path: Path) -> None:
    root = tmp_path
    ensure_project_layout(root)
    doc = save_draft(
        root,
        draft_id=None,
        name="唯一",
        subject="数学",
        export_label="期中",
        template_ref="t",
        template_path="templates/x.yaml",
        selected_items=[],
    )
    did = doc["draft_id"]
    doc2 = save_draft(
        root,
        draft_id=did,
        name="唯一",
        subject="数学",
        export_label="期中",
        template_ref="t",
        template_path="templates/x.yaml",
        selected_items=[],
    )
    assert doc2["name"] == "唯一"


def test_auto_generated_name_gets_suffix_when_collision(tmp_path: Path) -> None:
    root = tmp_path
    ensure_project_layout(root)
    save_draft(
        root,
        draft_id=None,
        name=None,
        subject="数学",
        export_label="期中",
        template_ref="t",
        template_path="templates/x.yaml",
        selected_items=[],
    )
    doc = save_draft(
        root,
        draft_id=None,
        name=None,
        subject="数学",
        export_label="期中",
        template_ref="t",
        template_path="templates/x.yaml",
        selected_items=[],
    )
    assert doc["name"] == "期中 · 数学 (2)"


def test_export_failure_draft_names_are_unique(tmp_path: Path) -> None:
    root = tmp_path
    ensure_project_layout(root)
    items: list[dict] = []
    d1 = save_draft_after_export_failure(
        root,
        template_ref="t",
        template_path="templates/x.yaml",
        export_label="期中",
        subject="数学",
        selected_items=items,
    )
    d2 = save_draft_after_export_failure(
        root,
        template_ref="t",
        template_path="templates/x.yaml",
        export_label="期中",
        subject="数学",
        selected_items=items,
    )
    assert d1["draft_id"] != d2["draft_id"]
    assert d1["name"] != d2["name"]
    assert "（导出失败）" in d1["name"]
    assert "（导出失败）" in d2["name"]
