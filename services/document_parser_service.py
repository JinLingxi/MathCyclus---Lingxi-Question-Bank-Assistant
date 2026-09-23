"""Normalize document parser outputs for batch question ingestion."""

from __future__ import annotations

import importlib.util
import json
import shutil
from pathlib import Path
from typing import Any

from services.mineru_cloud_service import mineru_cloud_available, mineru_cloud_config
from services.mineru_cloud_service import parse_pdf_to_directory


def mineru_availability() -> dict[str, Any]:
    executable = shutil.which("mineru") or shutil.which("magic-pdf") or ""
    module_name = "mineru" if importlib.util.find_spec("mineru") else "magic_pdf" if importlib.util.find_spec("magic_pdf") else ""
    return {
        "available": bool(executable or module_name),
        "executable": executable,
        "module": module_name,
    }


def available_document_parsers() -> list[dict[str, Any]]:
    mineru = mineru_availability()
    cloud = mineru_cloud_config()
    return [
        {
            "name": "mineru_cloud",
            "available": bool(cloud["configured"]),
            "detail": {"base_url": cloud["base_url"], "configured": cloud["configured"]},
            "capabilities": ["layout", "text", "formula", "image", "table", "ocr"],
        },
        {
            "name": "mineru",
            "available": mineru["available"],
            "detail": mineru,
            "capabilities": ["layout", "text", "formula", "image", "table"],
        },
        {
            "name": "pymupdf",
            "available": True,
            "detail": {},
            "capabilities": ["page_render", "text", "embedded_image", "coordinates"],
        },
    ]


def preferred_document_parser() -> str:
    if mineru_cloud_available():
        return "mineru_cloud"
    return "mineru" if mineru_availability()["available"] else "pymupdf"


def normalize_parser_mode(value: str | None) -> str:
    mode = str(value or "auto").strip().lower()
    aliases = {"自动": "auto", "云端": "cloud", "本地": "local", "mineru": "cloud", "pymupdf": "local"}
    mode = aliases.get(mode, mode)
    if mode not in {"auto", "cloud", "local"}:
        raise ValueError(f"不支持的文档解析模式：{value}")
    return mode


def parse_with_boundary(
    pdf_path: str | Path,
    output_dir: str | Path,
    *,
    mode: str = "auto",
) -> dict[str, Any]:
    """Run cloud parsing with an explicit local fallback boundary."""
    selected = normalize_parser_mode(mode)
    if selected == "local":
        return {"parser": "pymupdf", "fallback": False, "reason": "mode=local"}
    if not mineru_cloud_available():
        if selected == "cloud":
            raise RuntimeError("已选择云端 MinerU，但未配置 MINERU_API_TOKEN")
        return {"parser": "pymupdf", "fallback": True, "reason": "MinerU cloud is not configured"}
    try:
        result = parse_pdf_to_directory(pdf_path, output_dir)
        return {**result, "parser": "mineru_cloud", "fallback": False, "reason": "cloud_success"}
    except Exception as exc:
        if selected == "cloud":
            raise
        return {
            "parser": "pymupdf",
            "fallback": True,
            "reason": f"MinerU cloud failed: {type(exc).__name__}: {exc}",
        }


def find_mineru_content_list(output_root: str | Path) -> Path:
    root = Path(output_root)
    candidates = sorted(root.rglob("*_content_list.json")) + sorted(root.rglob("content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"未找到 MinerU content_list.json：{root}")
    return candidates[0]


def _bbox(value: Any) -> list[float]:
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return []
    return values[:4] if len(values) >= 4 else []


def normalize_mineru_content_list(payload: Any, *, output_root: str | Path = "") -> list[dict[str, Any]]:
    if not isinstance(payload, list):
        raise ValueError("MinerU content list 顶层必须是数组")
    root = Path(output_root) if output_root else None
    normalized = []
    for index, item in enumerate(payload, start=1):
        if not isinstance(item, dict):
            continue
        raw_type = str(item.get("type") or item.get("category_type") or item.get("block_type") or "unknown").lower()
        if raw_type in {"text", "title", "paragraph", "list"}:
            block_type = "text"
        elif raw_type in {"equation", "formula", "interline_equation", "inline_equation"}:
            block_type = "formula"
        elif raw_type in {"image", "figure", "picture"}:
            block_type = "image"
        elif raw_type in {"table"}:
            block_type = "table"
        else:
            block_type = raw_type or "unknown"
        page_number = int(item.get("page_idx", item.get("page_number", 0)) or 0) + (1 if "page_idx" in item else 0)
        source_path = str(item.get("img_path") or item.get("image_path") or item.get("path") or "").strip()
        resolved_path = ""
        if source_path and root is not None:
            candidate = (root / source_path).resolve()
            try:
                candidate.relative_to(root.resolve())
            except ValueError:
                candidate = Path()
            if candidate and candidate.is_file():
                resolved_path = str(candidate)
        normalized.append(
            {
                "block_id": str(item.get("id") or f"mineru_{index:05d}"),
                "type": block_type,
                "page_number": page_number,
                "bbox": _bbox(item.get("bbox") or item.get("box")),
                "text": str(item.get("text") or item.get("content") or "").strip(),
                "latex": str(item.get("latex") or item.get("equation") or "").strip(),
                "source_path": resolved_path or source_path,
                "raw": item,
            }
        )
    return normalized


def load_mineru_content_list(output_root: str | Path) -> dict[str, Any]:
    content_path = find_mineru_content_list(output_root)
    payload = json.loads(content_path.read_text(encoding="utf-8"))
    blocks = normalize_mineru_content_list(payload, output_root=content_path.parent)
    return {
        "parser": "mineru",
        "content_path": str(content_path),
        "blocks": blocks,
    }


def mineru_blocks_to_page_overrides(
    blocks: list[dict[str, Any]],
    *,
    job_dir: str | Path,
) -> dict[int, dict[str, Any]]:
    """Turn normalized MinerU blocks into the page shape used by PDF drafts."""
    root = Path(job_dir).resolve()
    pages: dict[int, dict[str, Any]] = {}
    for block in blocks:
        page_number = int(block.get("page_number") or 0)
        if page_number <= 0:
            continue
        page = pages.setdefault(page_number, {"lines": [], "images": []})
        block_type = str(block.get("type") or "")
        text = str(block.get("text") or block.get("latex") or "").strip()
        bbox = block.get("bbox") or []
        if block_type == "image":
            source = Path(str(block.get("source_path") or ""))
            if not source.is_absolute():
                source = (root / source).resolve()
            try:
                source.relative_to(root)
            except ValueError:
                source = Path()
            if source.is_file():
                target_dir = root / "mineru_assets"
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"{str(block.get('block_id') or 'figure')}.png"
                shutil.copy2(source, target)
                page["images"].append(
                    {
                        "block_id": block.get("block_id") or "",
                        "type": "mineru_image",
                        "page_number": page_number,
                        "bbox": bbox,
                        "pixel_bbox": [],
                        "source_path": target.relative_to(root).as_posix(),
                        "original_file_name": target.name,
                        "suggested_question_number": "",
                        "binding_confidence": 0,
                        "detector": "mineru_cloud",
                    }
                )
        elif text:
            page["lines"].append({"text": text, "bbox": bbox, "page_number": page_number})
    overrides: dict[int, dict[str, Any]] = {}
    for page_number, page in pages.items():
        overrides[page_number] = {
            "raw_text": "\n".join(str(line.get("text") or "") for line in page["lines"]).strip(),
            "layout_blocks": [
                {
                    "block_id": f"mineru_text_{page_number:03d}_{index:03d}",
                    "type": "text",
                    "bbox": line.get("bbox") or [],
                    "lines": [line],
                }
                for index, line in enumerate(page["lines"], start=1)
            ],
            "image_candidates": page["images"],
        }
    return overrides
