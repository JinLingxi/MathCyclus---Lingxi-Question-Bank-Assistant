"""Detect and crop non-text visual regions from rendered document pages."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

from PIL import Image


def normalize_region_bbox(value: Any, width: int, height: int) -> list[int]:
    """Clamp a user-edited image rectangle to valid pixel coordinates."""
    try:
        raw = [int(round(float(item))) for item in value[:4]]
    except (TypeError, ValueError, IndexError):
        return []
    if len(raw) < 4:
        return []
    x0, y0, x1, y1 = raw
    x0, x1 = sorted((max(0, min(width, x0)), max(0, min(width, x1))))
    y0, y1 = sorted((max(0, min(height, y0)), max(0, min(height, y1))))
    if x1 - x0 < 2 or y1 - y0 < 2:
        return []
    return [x0, y0, x1, y1]


def opencv_available() -> bool:
    return importlib.util.find_spec("cv2") is not None


def _merge_boxes(boxes: list[list[int]], gap: int = 18) -> list[list[int]]:
    pending = [list(box) for box in boxes]
    merged: list[list[int]] = []
    while pending:
        current = pending.pop(0)
        changed = True
        while changed:
            changed = False
            remaining = []
            for candidate in pending:
                separated = (
                    candidate[2] + gap < current[0]
                    or current[2] + gap < candidate[0]
                    or candidate[3] + gap < current[1]
                    or current[3] + gap < candidate[1]
                )
                if separated:
                    remaining.append(candidate)
                    continue
                current = [
                    min(current[0], candidate[0]),
                    min(current[1], candidate[1]),
                    max(current[2], candidate[2]),
                    max(current[3], candidate[3]),
                ]
                changed = True
            pending = remaining
        merged.append(current)
    return sorted(merged, key=lambda box: (box[1], box[0]))


def detect_visual_regions(
    image_path: str | Path,
    *,
    text_boxes: list[list[float]] | None = None,
    min_area_ratio: float = 0.0015,
    max_area_ratio: float = 0.65,
) -> list[dict[str, Any]]:
    if not opencv_available():
        return []
    import cv2

    source = Path(image_path)
    image = cv2.imread(str(source), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError(f"无法读取页面图片：{source}")
    height, width = image.shape[:2]
    grayscale = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    binary = cv2.adaptiveThreshold(
        grayscale,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV,
        35,
        15,
    )
    for raw_box in text_boxes or []:
        if len(raw_box) < 4:
            continue
        x0, y0, x1, y1 = [int(round(value)) for value in raw_box[:4]]
        cv2.rectangle(binary, (max(0, x0 - 3), max(0, y0 - 3)), (min(width, x1 + 3), min(height, y1 + 3)), 0, -1)
    kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (7, 7))
    connected = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel, iterations=2)
    contours, _ = cv2.findContours(connected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    page_area = float(width * height)
    boxes = []
    for contour in contours:
        x, y, region_width, region_height = cv2.boundingRect(contour)
        area_ratio = (region_width * region_height) / page_area
        if area_ratio < min_area_ratio or area_ratio > max_area_ratio:
            continue
        if region_width < 32 or region_height < 24:
            continue
        boxes.append([x, y, x + region_width, y + region_height])
    return [
        {
            "bbox": box,
            "area_ratio": ((box[2] - box[0]) * (box[3] - box[1])) / page_area,
            "detector": "opencv_non_text_v1",
        }
        for box in _merge_boxes(boxes)
    ]


def crop_visual_regions(
    image_path: str | Path,
    regions: list[dict[str, Any]],
    output_dir: str | Path,
    *,
    name_prefix: str,
    margin: int = 12,
) -> list[dict[str, Any]]:
    source = Path(image_path)
    target_dir = Path(output_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with Image.open(source) as image:
        width, height = image.size
        outputs = []
        for index, region in enumerate(regions, start=1):
            bbox = region.get("bbox") or []
            if len(bbox) < 4:
                continue
            x0, y0, x1, y1 = [int(round(value)) for value in bbox[:4]]
            crop_box = [
                max(0, x0 - margin),
                max(0, y0 - margin),
                min(width, x1 + margin),
                min(height, y1 + margin),
            ]
            if crop_box[2] <= crop_box[0] or crop_box[3] <= crop_box[1]:
                continue
            filename = f"{name_prefix}_{index:02d}.png"
            target = target_dir / filename
            image.crop(tuple(crop_box)).save(target, format="PNG")
            outputs.append({**region, "crop_bbox": crop_box, "source_path": str(target), "original_file_name": filename})
    return outputs


def recrop_visual_region(
    image_path: str | Path,
    bbox: list[float] | tuple[float, ...],
    output_path: str | Path,
    *,
    margin: int = 0,
) -> dict[str, Any]:
    """Regenerate one crop after a reviewer adjusts its rectangle."""
    source = Path(image_path)
    target = Path(output_path)
    with Image.open(source) as image:
        width, height = image.size
        raw = normalize_region_bbox(bbox, width, height)
        if not raw:
            raise ValueError("裁剪框无效或区域过小")
        x0, y0, x1, y1 = raw
        crop_box = [max(0, x0 - margin), max(0, y0 - margin), min(width, x1 + margin), min(height, y1 + margin)]
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop(tuple(crop_box)).save(target, format="PNG")
        return {"bbox": raw, "crop_bbox": crop_box, "source_path": str(target), "width": crop_box[2] - crop_box[0], "height": crop_box[3] - crop_box[1]}


def merge_visual_regions(
    image_path: str | Path,
    regions: list[dict[str, Any]],
    output_path: str | Path,
    *,
    margin: int = 12,
) -> dict[str, Any]:
    """Merge selected regions from one page into a single ordered crop."""
    source = Path(image_path)
    target = Path(output_path)
    with Image.open(source) as image:
        width, height = image.size
        boxes = [normalize_region_bbox(item.get("bbox") or item.get("crop_bbox") or [], width, height) for item in regions]
        boxes = [box for box in boxes if box]
        if not boxes:
            raise ValueError("没有可合并的有效裁剪区域")
        x0 = max(0, min(box[0] for box in boxes) - margin)
        y0 = max(0, min(box[1] for box in boxes) - margin)
        x1 = min(width, max(box[2] for box in boxes) + margin)
        y1 = min(height, max(box[3] for box in boxes) + margin)
        target.parent.mkdir(parents=True, exist_ok=True)
        image.crop((x0, y0, x1, y1)).save(target, format="PNG")
        return {"bbox": [x0, y0, x1, y1], "source_path": str(target), "width": x1 - x0, "height": y1 - y0, "merged_count": len(boxes)}
