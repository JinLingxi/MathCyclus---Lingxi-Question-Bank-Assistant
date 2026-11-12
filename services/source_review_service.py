"""Bind a human crop review to its source, region and image bytes."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from services.asset_service import file_hash

CHECKS = ("complete_figure", "readable_labels", "no_foreign_content", "correct_anchor")


def _region(extra: dict) -> dict:
    region = extra.get("source_region")
    if not isinstance(region, dict):
        raise ValueError("缺少 source_region 来源与裁剪位置")
    page = region.get("page_index")
    box = region.get("box")
    if type(page) is not int or page < 0:
        raise ValueError("page_index 必须是从零开始的页码")
    if not isinstance(box, (list, tuple)) or len(box) != 4:
        raise ValueError("box 必须是四个有限坐标")
    if any(type(v) not in (int, float) or not math.isfinite(v) for v in box):
        raise ValueError("box 必须是四个有限坐标")
    if box[0] >= box[2] or box[1] >= box[3]:
        raise ValueError("裁剪范围无效")
    source = str(region.get("source_path") or "").strip()
    if not source:
        raise ValueError("缺少原始来源文件")
    coordinate_space = region.get("coordinate_space", "pdf_points")
    if coordinate_space not in {"pdf_points", "page_pixels"}:
        raise ValueError("不支持的裁剪坐标单位")
    anchor_id = str(region.get("anchor_id") or "").strip()
    if not anchor_id:
        raise ValueError("缺少题目归属 anchor_id")
    return {"source_path": source, "page_index": page, "box": [float(v) for v in box],
            "coordinate_space": coordinate_space, "anchor_id": anchor_id}


def _binding(crop_path: str | Path, extra: dict, project_root: str | Path) -> str:
    region = _region(extra)
    source = Path(region["source_path"])
    if not source.is_absolute():
        source = Path(project_root) / source
    payload = {"region": region, "source_sha256": file_hash(source),
               "crop_sha256": file_hash(crop_path)}
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def make_source_review(crop_path: str | Path, extra: dict, *, project_root: str | Path,
                       reviewer: str, checks: dict) -> dict:
    """Record supplied human observations; hashes do not establish visual quality."""
    if not str(reviewer).strip() or set(checks) != set(CHECKS):
        raise ValueError("需要复核人和完整四项观察记录")
    if any(type(checks[key]) is not bool for key in CHECKS):
        raise ValueError("复核项必须是布尔值")
    return {"version": 1, "reviewer": str(reviewer).strip(),
            "checks": dict(checks), "binding": _binding(crop_path, extra, project_root)}


def validate_source_review(crop_path: str | Path, extra: dict, *, project_root: str | Path) -> dict:
    review = extra.get("source_review")
    if review is None:
        return {"status": "unrecorded", "reason": "尚未登记绑定来源的配图复核"}
    try:
        if not isinstance(review, dict) or type(review.get("version")) is not int or review["version"] != 1:
            raise ValueError("不支持的配图复核记录格式")
        checks = review.get("checks")
        if (not str(review.get("reviewer") or "").strip() or not isinstance(checks, dict)
                or set(checks) != set(CHECKS) or any(type(checks[k]) is not bool for k in CHECKS)):
            raise ValueError("配图复核记录不完整")
        if review.get("binding") != _binding(crop_path, extra, project_root):
            return {"status": "stale", "reason": "来源、裁剪范围或图片内容已变化，需重新复核"}
        failed = [key for key in CHECKS if not checks[key]]
        return {"status": "failed" if failed else "verified", "failed_checks": failed}
    except (OSError, ValueError, TypeError) as exc:
        return {"status": "invalid", "reason": str(exc)}
