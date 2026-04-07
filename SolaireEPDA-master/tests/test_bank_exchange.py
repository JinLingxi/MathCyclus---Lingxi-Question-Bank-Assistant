"""Tests for bank exchange ZIP export / import."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
import yaml

from solaire.exam_compiler.models import QuestionItem
from solaire.web.bank_exchange import export_bank_exchange_zip, import_bank_exchange_zip
from solaire.web.bank_service import import_merged_yaml


def _minimal_choice_q(embed: str) -> QuestionItem:
    return QuestionItem(
        id="q1",
        type="choice",
        content=embed,
        answer="A",
        analysis="",
        options={"A": "a", "B": "b", "C": "c", "D": "d"},
        metadata={},
    )


def test_export_import_round_trip(tmp_path: Path) -> None:
    root = tmp_path
    img_dir = root / "resource" / "数学" / "测试" / "image"
    img_dir.mkdir(parents=True)
    png = img_dir / "x.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01")
    rel = "数学/测试/image/x.png"
    q = _minimal_choice_q(f"题干 :::EMBED_IMG:{rel}:::")
    yml = yaml.safe_dump({"questions": [q.model_dump(mode="json")]}, allow_unicode=True, sort_keys=False)
    import_merged_yaml(root, yml, "数学", "测试")

    zdata, _stem = export_bank_exchange_zip(root, "数学/测试")
    assert b"manifest.json" in zdata
    assert b"yaml/" in zdata
    assert b"q1.yaml" in zdata

    r = import_bank_exchange_zip(root, zdata, "数学", "目标")
    assert r["written"] == 1
    assert r["namespace"] == "数学/目标"

    dest_img = root / "resource" / "数学" / "目标" / "image"
    assert dest_img.is_dir()
    assert any(dest_img.glob("*.png"))

    qfile = root / "resource" / "数学" / "目标" / "q1.yaml"
    assert qfile.is_file()
    raw = yaml.safe_load(qfile.read_text(encoding="utf-8"))
    content = raw["content"]
    assert ":::EMBED_IMG:" in content
    assert "数学/目标/image/" in content


def test_zip_slip_rejected(tmp_path: Path) -> None:
    root = tmp_path
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "questions.yaml",
            yaml.safe_dump(
                {"questions": [_minimal_choice_q("x").model_dump(mode="json")]}, allow_unicode=True, sort_keys=False
            ),
        )
        zf.writestr("evil/../outside.txt", b"no")
    with pytest.raises(ValueError, match="非法|越界|zip"):
        import_bank_exchange_zip(root, buf.getvalue(), "数", "学")


def test_groups_zip_round_trip(tmp_path: Path) -> None:
    root = tmp_path
    img_dir = root / "resource" / "数学" / "题组" / "image"
    img_dir.mkdir(parents=True)
    png = img_dir / "m.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01")
    rel = "数学/题组/image/m.png"
    yml = yaml.safe_dump(
        {
            "questions": [
                QuestionItem(
                    id="solo",
                    type="fill",
                    content="独立填空",
                    answer="答",
                    analysis="",
                    metadata={},
                ).model_dump(mode="json")
            ],
            "groups": [
                {
                    "group_id": "read1",
                    "material": f"材料 :::EMBED_IMG:{rel}:::",
                    "type": "choice",
                    "items": [
                        {
                            "content": "小题1",
                            "options": {"A": "a", "B": "b", "C": "c", "D": "d"},
                            "answer": "A",
                            "analysis": "",
                            "metadata": {},
                        },
                        {
                            "content": "小题2",
                            "options": {"A": "x", "B": "y", "C": "z", "D": "w"},
                            "answer": "B",
                            "analysis": "",
                            "metadata": {},
                        },
                    ],
                }
            ],
        },
        allow_unicode=True,
        sort_keys=False,
    )
    import_merged_yaml(root, yml, "数学", "题组")

    zdata, _stem = export_bank_exchange_zip(root, "数学/题组")
    r = import_bank_exchange_zip(root, zdata, "数学", "目标")
    assert r["written"] == 2
    target = root / "resource" / "数学" / "目标"
    assert (target / "solo.yaml").is_file()
    assert (target / "read1.yaml").is_file()
    raw_g = yaml.safe_load((target / "read1.yaml").read_text(encoding="utf-8"))
    assert raw_g["type"] == "group"
    assert raw_g["id"] == "read1"
    assert len(raw_g["items"]) == 2
    assert ":::EMBED_IMG:" in raw_g["material"]
    assert "数学/目标/image/" in raw_g["material"]


def test_loose_import_without_manifest(tmp_path: Path) -> None:
    root = tmp_path
    buf = io.BytesIO()
    img_rel = "image/a.png"
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(
            "questions.yaml",
            yaml.safe_dump(
                {
                    "questions": [
                        _minimal_choice_q(f":::EMBED_IMG:{img_rel}:::").model_dump(mode="json"),
                    ]
                },
                allow_unicode=True,
                sort_keys=False,
            ),
        )
        zf.writestr(img_rel, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01")
    r = import_bank_exchange_zip(root, buf.getvalue(), "宽", "松")
    assert r["written"] == 1
    assert not r.get("warnings") or isinstance(r["warnings"], list)
