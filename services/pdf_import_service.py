"""Create private, reviewable PDF import jobs without writing the question database."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import fitz
from PIL import Image, ImageStat


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JOBS_ROOT = PROJECT_ROOT / "data" / "imports" / "pdf_jobs"
JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,79}$")
SOURCE_TYPES = {"pdf_paper", "pdf_book", "pdf_topic", "pdf_misc"}
EDITABLE_CANDIDATE_FIELDS = {
    "review_status",
    "review_reason",
    "question_type",
    "question_type_id",
    "stem_tex",
    "choices",
    "answer_tex",
    "solution_tex",
    "difficulty",
    "tags",
    "note",
    "official_flag",
}
REVIEW_STATUSES = {"needs_review", "ready", "blocked", "rejected"}
QUESTION_START_PATTERN = re.compile(
    r"^\s*(?:第\s*)?([1-9]\d{0,2})\s*(?:题\s*[:：、.．]?|[、.．])\s*(.*)$"
)
QUESTION_SECTION_PATTERN = re.compile(
    r"^\s*(?:"
    r"[一二三四五六七八九十]+\s*[、.．]\s*(?:单项|多项)?(?:选择题|填空题|解答题|证明题)"
    r"|(?:section\s+)?[ivx]+\s*[.:]\s*(?:multiple\s+)?(?:choice|fill|solution|proof)"
    r")",
    re.IGNORECASE,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _append_pdf_import_event(
    payload: dict[str, Any],
    source_item_id: str,
    action: str,
    *,
    status: str = "ok",
    message: str = "",
    question_id: str = "",
    draft_id: str = "",
    operator: str = "pdf_import_ui",
) -> dict[str, Any]:
    """Append an immutable audit event to the PDF job payload."""
    event = {
        "event_id": uuid.uuid4().hex,
        "source_item_id": str(source_item_id or ""),
        "action": str(action),
        "status": str(status),
        "message": str(message or ""),
        "question_id": str(question_id or ""),
        "draft_id": str(draft_id or ""),
        "created_at": utc_now(),
        "operator": str(operator or "pdf_import_ui"),
    }
    payload.setdefault("audit_events", []).append(event)
    return event


def _save_pdf_import_state(job_dir: Path, manifest: dict[str, Any], payload: dict[str, Any]) -> None:
    payload["updated_at"] = utc_now()
    manifest["updated_at"] = payload["updated_at"]
    write_json(job_dir / "draft_payload.json", payload)
    write_json(job_dir / "job_manifest.json", manifest)
    write_import_report(
        job_dir / "import_report.md",
        job_id=str(payload.get("job_id") or job_dir.name),
        page_count=len(payload.get("pages") or []),
        drafts=payload.get("questions") or [],
        unassigned_blocks=payload.get("unassigned_blocks") or [],
    )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def validate_job_id(job_id: str) -> str:
    normalized = str(job_id or "").strip()
    if not JOB_ID_PATTERN.fullmatch(normalized):
        raise ValueError("job_id 只能包含字母、数字、下划线和连字符，且长度不能超过 80。")
    return normalized


def generate_job_id(source_pdf: str | Path) -> str:
    source_path = Path(source_pdf).resolve()
    digest = hashlib.sha256(str(source_path).encode("utf-8") + str(source_path.stat().st_size).encode("ascii")).hexdigest()[:8]
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"pdf_{stamp}_{digest}"


def ensure_inside(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"路径超出 PDF 导入目录：{path}") from exc


def resolve_job_dir(job_id: str, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> Path:
    root = Path(jobs_root).resolve()
    job_dir = root / validate_job_id(job_id)
    ensure_inside(root, job_dir)
    return job_dir


def write_json(path: Path, payload: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(path.suffix + ".tmp")
    temporary_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary_path.replace(path)


def read_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON 顶层必须是对象：{path}")
    return payload


def _bbox_list(value: Any) -> list[float]:
    try:
        values = [float(item) for item in value]
    except (TypeError, ValueError):
        return []
    return values[:4] if len(values) >= 4 else []


def _bbox_overlap_ratio(first: list[float], second: list[float]) -> float:
    if len(first) < 4 or len(second) < 4:
        return 0.0
    x0 = max(first[0], second[0])
    y0 = max(first[1], second[1])
    x1 = min(first[2], second[2])
    y1 = min(first[3], second[3])
    intersection = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    first_area = max(1.0, (first[2] - first[0]) * (first[3] - first[1]))
    return intersection / first_area


def _suggest_question_for_bbox(text_blocks: list[dict[str, Any]], bbox: list[float]) -> tuple[str, float]:
    if len(bbox) < 4:
        return "", 0.0
    numbered_lines = []
    for block in text_blocks:
        for line in block.get("lines") or []:
            marker = QUESTION_START_PATTERN.match(str(line.get("text") or ""))
            line_bbox = line.get("bbox") or []
            if marker and len(line_bbox) >= 4:
                numbered_lines.append({"question_number": marker.group(1), "bbox": line_bbox})
    image_y = bbox[1]
    preceding = [item for item in numbered_lines if item["bbox"][1] <= image_y]
    following = [item for item in numbered_lines if item["bbox"][1] > image_y]
    suggested = max(preceding, key=lambda item: item["bbox"][1], default=None)
    if suggested is not None:
        return str(suggested["question_number"]), 0.75
    suggested = min(following, key=lambda item: item["bbox"][1], default=None)
    return (str(suggested["question_number"]), 0.45) if suggested else ("", 0.0)


def _paper_question_marker_positions(pages: list[dict[str, Any]]) -> set[tuple[int, int]]:
    markers = []
    section_seen = False
    for page in pages:
        page_number = int(page.get("page_number") or 0)
        for line_index, raw_line in enumerate(str(page.get("raw_text") or "").splitlines()):
            line = raw_line.strip()
            if QUESTION_SECTION_PATTERN.match(line):
                section_seen = True
            marker = QUESTION_START_PATTERN.match(line)
            if marker:
                markers.append((page_number, line_index, int(marker.group(1)), section_seen))
    preferred_starts = [index for index, marker in enumerate(markers) if marker[2] == 1 and marker[3]]
    starts = preferred_starts or [index for index, marker in enumerate(markers) if marker[2] == 1]
    if not starts:
        return set()
    best: list[tuple[int, int, int, bool]] = []
    for start in starts:
        accepted = [markers[start]]
        expected = 2
        for marker in markers[start + 1 :]:
            number = marker[2]
            if number == 1:
                break
            if number == expected:
                accepted.append(marker)
                expected += 1
        if len(accepted) > len(best):
            best = accepted
    return {(page_number, line_index) for page_number, line_index, _, _ in best}


def _attach_question_crops(
    pages: list[dict[str, Any]],
    drafts: list[dict[str, Any]],
    job_dir: Path,
    scale: float,
    source_type: str,
) -> None:
    layout_pages = []
    page_lines: dict[int, list[dict[str, Any]]] = {}
    for page in pages:
        page_number = int(page.get("page_number") or 0)
        lines = [
            line
            for block in page.get("layout_blocks") or []
            for line in block.get("lines") or []
            if str(line.get("text") or "").strip()
        ]
        page_lines[page_number] = lines
        layout_pages.append({"page_number": page_number, "raw_text": "\n".join(str(line.get("text") or "") for line in lines)})
    accepted = _paper_question_marker_positions(layout_pages) if source_type == "pdf_paper" else set()
    markers = []
    for page in layout_pages:
        page_number = int(page["page_number"])
        for line_index, line in enumerate(page_lines.get(page_number) or []):
            match = QUESTION_START_PATTERN.match(str(line.get("text") or "").strip())
            if not match:
                continue
            if source_type == "pdf_paper" and accepted and (page_number, line_index) not in accepted:
                continue
            markers.append({"page_number": page_number, "bbox": line.get("bbox") or [], "number": match.group(1)})
    if len(markers) < len(drafts):
        return
    output_dir = job_dir / "question_crops"
    output_dir.mkdir(parents=True, exist_ok=True)
    page_map = {int(page.get("page_number") or 0): page for page in pages}
    for index, draft in enumerate(drafts):
        start = markers[index]
        following = markers[index + 1] if index + 1 < len(markers) else None
        end_page = int(following["page_number"]) if following else int(draft.get("extra", {}).get("page_end") or start["page_number"])
        crop_paths = []
        for page_number in range(int(start["page_number"]), end_page + 1):
            page = page_map.get(page_number) or {}
            image_path = job_dir / str(page.get("image_path") or "")
            if not image_path.is_file():
                continue
            with Image.open(image_path) as image:
                # Keep a dynamic margin above the marker. If the marker touches the
                # page edge, padding is added to the generated crop below.
                if page_number == start["page_number"] and len(start["bbox"]) >= 4:
                    marker_height = max(1.0, float(start["bbox"][3]) - float(start["bbox"][1]))
                    top_margin_points = max(14.0, min(30.0, marker_height * 0.9))
                    top = int(max(0, (float(start["bbox"][1]) - top_margin_points) * scale))
                else:
                    top = 0
                bottom = image.height
                if following and page_number == following["page_number"] and len(following["bbox"]) >= 4:
                    following_height = max(1.0, float(following["bbox"][3]) - float(following["bbox"][1]))
                    bottom_margin_points = max(8.0, min(18.0, following_height * 0.45))
                    bottom = int(max(top + 1, (float(following["bbox"][1]) - bottom_margin_points) * scale))
                if bottom <= top:
                    continue
                crop_name = f"question_{index + 1:03d}_page_{page_number:03d}.png"
                crop_path = output_dir / crop_name
                cropped = image.crop((0, top, image.width, min(image.height, bottom)))
                # A page-edge marker has no pixels above it. Add a real white
                # border so the vision model never receives text flush against
                # the image boundary.
                padding_x = max(8, int(8 * scale))
                padding_top = max(18, int(20 * scale)) if top == 0 else max(6, int(6 * scale))
                padding_bottom = max(10, int(10 * scale))
                padded = Image.new(
                    "RGB",
                    (
                        cropped.width + padding_x * 2,
                        cropped.height + padding_top + padding_bottom,
                    ),
                    "white",
                )
                padded.paste(cropped.convert("RGB"), (padding_x, padding_top))
                cropped = padded
                if ImageStat.Stat(cropped.convert("L")).var[0] <= 1:
                    continue
                cropped.save(crop_path, format="PNG")
                crop_paths.append(crop_path.relative_to(job_dir).as_posix())
        draft.setdefault("extra", {})["question_crop_paths"] = crop_paths


def _page_layout_blocks(page: fitz.Page, page_number: int, job_dir: Path, scale: float) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    layout = page.get_text("dict")
    text_blocks: list[dict[str, Any]] = []
    image_blocks: list[dict[str, Any]] = []
    page_assets_dir = job_dir / "extracted_assets"
    page_assets_dir.mkdir(parents=True, exist_ok=True)

    text_lines: list[dict[str, Any]] = []
    for block_index, block in enumerate(layout.get("blocks") or [], start=1):
        block_type = int(block.get("type") or 0)
        bbox = _bbox_list(block.get("bbox"))
        if block_type == 0:
            block_lines = []
            for line in block.get("lines") or []:
                line_text = "".join(str(span.get("text") or "") for span in line.get("spans") or []).strip()
                if not line_text:
                    continue
                line_bbox = _bbox_list(line.get("bbox"))
                line_record = {"text": line_text, "bbox": line_bbox}
                block_lines.append(line_record)
                text_lines.append(line_record)
            text_blocks.append(
                {
                    "block_id": f"p{page_number:03d}_text_{block_index:03d}",
                    "type": "text",
                    "bbox": bbox,
                    "text": "\n".join(item["text"] for item in block_lines),
                    "lines": block_lines,
                }
            )
        elif block_type == 1 and block.get("image"):
            extension = re.sub(r"[^a-z0-9]+", "", str(block.get("ext") or "png").lower()) or "png"
            image_name = f"page_{page_number:03d}_image_{len(image_blocks) + 1:02d}.{extension}"
            image_path = page_assets_dir / image_name
            image_path.write_bytes(block["image"])
            image_blocks.append(
                {
                    "block_id": f"p{page_number:03d}_image_{block_index:03d}",
                    "type": "image",
                    "page_number": page_number,
                    "bbox": bbox,
                    "pixel_bbox": [round(value * scale, 2) for value in bbox],
                    "source_path": f"extracted_assets/{image_name}",
                    "original_file_name": image_name,
                    "width": int(block.get("width") or 0),
                    "height": int(block.get("height") or 0),
                }
            )

    for image in image_blocks:
        suggested, confidence = _suggest_question_for_bbox(text_blocks, image.get("bbox") or [])
        image["suggested_question_number"] = suggested
        image["binding_confidence"] = confidence
    return text_blocks, image_blocks


def _page_vector_regions(
    page: fitz.Page,
    page_number: int,
    job_dir: Path,
    scale: float,
    text_blocks: list[dict[str, Any]],
    existing_images: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    try:
        drawings = page.get_drawings()
        regions = page.cluster_drawings(drawings=drawings, x_tolerance=6, y_tolerance=6)
    except Exception:
        return []
    page_rect = page.rect
    page_area = max(1.0, float(page_rect.width * page_rect.height))
    output_dir = job_dir / "crops"
    output_dir.mkdir(parents=True, exist_ok=True)
    outputs = []
    for region in regions:
        rect = fitz.Rect(region)
        area_ratio = float(rect.width * rect.height) / page_area
        if rect.width < 36 or rect.height < 24 or area_ratio < 0.001 or area_ratio > 0.65:
            continue
        bbox = [round(rect.x0, 2), round(rect.y0, 2), round(rect.x1, 2), round(rect.y1, 2)]
        if any(_bbox_overlap_ratio(bbox, item.get("bbox") or []) >= 0.65 for item in existing_images):
            continue
        clip = fitz.Rect(
            max(page_rect.x0, rect.x0 - 6),
            max(page_rect.y0, rect.y0 - 6),
            min(page_rect.x1, rect.x1 + 6),
            min(page_rect.y1, rect.y1 + 6),
        )
        image_name = f"page_{page_number:03d}_vector_{len(outputs) + 1:02d}.png"
        image_path = output_dir / image_name
        pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=clip, alpha=False)
        pixmap.save(image_path)
        suggested, confidence = _suggest_question_for_bbox(text_blocks, bbox)
        outputs.append(
            {
                "block_id": f"p{page_number:03d}_vector_{len(outputs) + 1:03d}",
                "type": "vector_region",
                "page_number": page_number,
                "bbox": bbox,
                "pixel_bbox": [round(value * scale, 2) for value in bbox],
                "source_path": image_path.relative_to(job_dir).as_posix(),
                "original_file_name": image_name,
                "width": pixmap.width,
                "height": pixmap.height,
                "suggested_question_number": suggested,
                "binding_confidence": confidence,
                "detector": "pymupdf_vector_v1",
            }
        )
    return outputs


def list_pdf_import_jobs(jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> list[dict[str, Any]]:
    root = Path(jobs_root).resolve()
    if not root.exists():
        return []
    jobs: list[dict[str, Any]] = []
    for job_dir in root.iterdir():
        if not job_dir.is_dir() or not JOB_ID_PATTERN.fullmatch(job_dir.name):
            continue
        manifest_path = job_dir / "job_manifest.json"
        if not manifest_path.is_file():
            continue
        try:
            manifest = read_json_object(manifest_path)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        document = manifest.get("document") if isinstance(manifest.get("document"), dict) else {}
        summary = manifest.get("draft_summary") if isinstance(manifest.get("draft_summary"), dict) else {}
        jobs.append(
            {
                "job_id": job_dir.name,
                "status": str(manifest.get("status") or "unknown"),
                "created_at": str(manifest.get("created_at") or ""),
                "updated_at": str(manifest.get("updated_at") or ""),
                "original_name": str(source.get("original_name") or "source.pdf"),
                "source_type": str(source.get("source_type") or "pdf_misc"),
                "page_count": int(document.get("page_count") or 0),
                "question_candidate_count": int(summary.get("question_candidate_count") or 0),
                "review_status_counts": dict(summary.get("review_status_counts") or {}),
            }
        )
    return sorted(jobs, key=lambda item: (item["updated_at"], item["job_id"]), reverse=True)


def load_pdf_import_job(job_id: str, jobs_root: str | Path = DEFAULT_JOBS_ROOT) -> dict[str, Any]:
    job_dir = resolve_job_dir(job_id, jobs_root)
    manifest_path = job_dir / "job_manifest.json"
    draft_path = job_dir / "draft_payload.json"
    if not manifest_path.is_file() or not draft_path.is_file():
        raise FileNotFoundError(f"PDF 导入任务文件不完整：{job_dir}")
    return {
        "job_dir": job_dir,
        "manifest": read_json_object(manifest_path),
        "draft_payload": read_json_object(draft_path),
    }


def refresh_pdf_import_source_metadata(
    job_id: str,
    source_metadata: dict[str, Any],
    *,
    db_path: str | Path | None = None,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Update PDF source metadata and rematch paper identity for every candidate."""
    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    normalized = {str(key): value for key, value in source_metadata.items() if value not in (None, "")}
    source = manifest.setdefault("source", {})
    existing_metadata = source.get("metadata") if isinstance(source.get("metadata"), dict) else {}
    existing_metadata.update(normalized)
    source["metadata"] = existing_metadata
    payload["source_metadata"] = dict(normalized)
    match_result: dict[str, Any] = {"status": "not_applicable", "candidates": []}
    if str(source.get("source_type") or payload.get("source_type") or "") == "pdf_paper":
        from services.paper_catalog_service import match_paper
        from services.paper_catalog_service import get_standard_paper

        from services.database_service import DEFAULT_DATABASE_PATH

        safe_db_path = str(db_path or DEFAULT_DATABASE_PATH)
        confirmed_standard_id = str(normalized.get("paper_standard_id") or "").strip()
        if confirmed_standard_id:
            selected = get_standard_paper(safe_db_path, confirmed_standard_id)
            match_result = {
                "status": "exact" if selected else "invalid",
                "selected": selected,
                "candidates": [selected] if selected else [],
            }
        else:
            match_result = match_paper(
                safe_db_path,
                year=normalized.get("year") or normalized.get("year_or_volume"),
                paper_series=str(normalized.get("paper_series") or "G"),
                track=str(normalized.get("track") or ""),
                paper_name=str(normalized.get("source_name") or ""),
            )
    questions = [item for item in payload.get("questions", []) if isinstance(item, dict)]
    for candidate in questions:
        extra = candidate.setdefault("extra", {})
        extra["source_metadata"] = dict(normalized)
        if normalized.get("year") or normalized.get("year_or_volume"):
            extra["detected_year"] = normalized.get("year") or normalized.get("year_or_volume")
        if normalized.get("source_name"):
            extra["detected_source"] = str(normalized["source_name"])
        if normalized.get("paper_series"):
            extra["paper_series"] = str(normalized["paper_series"])
        if normalized.get("track"):
            extra["track"] = str(normalized["track"])
        selected = match_result.get("selected") if isinstance(match_result.get("selected"), dict) else {}
        if match_result.get("status") == "exact" and selected.get("paper_standard_id"):
            extra["paper_standard_id"] = str(selected["paper_standard_id"])
            extra["paper_match_status"] = "exact"
        elif match_result.get("status"):
            extra["paper_match_status"] = str(match_result.get("status"))
        candidate["source_label"] = f"{normalized.get('source_name') or candidate.get('source_label') or ''} · 第 {extra.get('question_number') or '?'} 题"
    payload["updated_at"] = utc_now()
    manifest["updated_at"] = utc_now()
    manifest.setdefault("source", {})["last_match"] = {
        "status": match_result.get("status"),
        "selected": match_result.get("selected") or {},
        "candidates": match_result.get("candidates") or [],
    }
    write_json(job_dir / "draft_payload.json", payload)
    write_json(job_dir / "job_manifest.json", manifest)
    write_import_report(
        job_dir / "import_report.md",
        job_id=job_id,
        page_count=len(payload.get("pages") or []),
        drafts=questions,
        unassigned_blocks=payload.get("unassigned_blocks") or [],
    )
    return {
        "job_id": job_id,
        "match_status": match_result.get("status"),
        "selected": match_result.get("selected") or {},
        "candidates": match_result.get("candidates") or [],
        "question_count": len(questions),
    }


def validate_question_candidate(candidate: dict[str, Any]) -> dict[str, list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not str(candidate.get("stem_tex") or "").strip():
        errors.append("题干不能为空。")
    question_type_id = candidate.get("question_type_id")
    choices = candidate.get("choices") if isinstance(candidate.get("choices"), list) else []
    if question_type_id in {1, 2} and len(choices) < 2:
        errors.append("选择题至少需要两个选项。")
    if not str(candidate.get("answer_tex") or "").strip():
        warnings.append("答案尚未填写。")
    if not str(candidate.get("solution_tex") or "").strip():
        warnings.append("解析尚未填写。")
    return {"errors": errors, "warnings": warnings}


def update_pdf_question_candidate(
    job_id: str,
    source_item_id: str,
    updates: dict[str, Any],
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    questions = payload.get("questions")
    if not isinstance(questions, list):
        raise ValueError("draft_payload.json 缺少 questions 数组。")
    candidate = next(
        (item for item in questions if isinstance(item, dict) and item.get("source_item_id") == source_item_id),
        None,
    )
    previous_status = str(candidate.get("review_status") or "needs_review") if candidate else "needs_review"
    if candidate is None:
        raise KeyError(f"未找到 PDF 题目候选：{source_item_id}")

    unexpected = set(updates) - EDITABLE_CANDIDATE_FIELDS
    if unexpected:
        raise ValueError(f"包含不可编辑字段：{', '.join(sorted(unexpected))}")
    normalized_updates = dict(updates)
    if "review_status" in normalized_updates and normalized_updates["review_status"] not in REVIEW_STATUSES:
        raise ValueError(f"不支持的审核状态：{normalized_updates['review_status']}")
    if "choices" in normalized_updates:
        normalized_updates["choices"] = [str(item).strip() for item in normalized_updates["choices"] if str(item).strip()]
    if "tags" in normalized_updates:
        normalized_updates["tags"] = [str(item).strip() for item in normalized_updates["tags"] if str(item).strip()]
    if "difficulty" in normalized_updates:
        difficulty = normalized_updates["difficulty"]
        if difficulty in (None, ""):
            normalized_updates["difficulty"] = None
        else:
            difficulty = int(difficulty)
            if not 1 <= difficulty <= 5:
                raise ValueError("难度必须在 1 到 5 之间。")
            normalized_updates["difficulty"] = difficulty

    candidate.update(normalized_updates)
    validation = validate_question_candidate(candidate)
    if candidate.get("review_status") == "ready" and (validation["errors"] or validation["warnings"]):
        issues = validation["errors"] + validation["warnings"]
        raise ValueError("标记 ready 前需要处理：" + "；".join(issues))
    candidate["validation"] = {
        "status": "blocked" if validation["errors"] else "needs_review" if validation["warnings"] else "ready",
        **validation,
    }
    _append_pdf_import_event(
        payload,
        source_item_id,
        "candidate_saved",
        message=f"review_status={candidate.get('review_status')}",
    )
    if candidate.get("review_status") == "rejected" and previous_status != "rejected":
        _append_pdf_import_event(payload, source_item_id, "skipped", status="skipped", message="候选题被审核跳过")

    status_counts: dict[str, int] = {}
    for item in questions:
        status = str(item.get("review_status") or "needs_review") if isinstance(item, dict) else "needs_review"
        status_counts[status] = status_counts.get(status, 0) + 1
    summary = manifest.setdefault("draft_summary", {})
    summary["review_status_counts"] = status_counts
    _save_pdf_import_state(job_dir, manifest, payload)
    return {
        "job_id": job_id,
        "source_item_id": source_item_id,
        "review_status": candidate.get("review_status"),
        "validation": candidate["validation"],
        "writes_formal_database": False,
    }


def update_pdf_question_asset_crop(
    job_id: str,
    source_item_id: str,
    asset_index: int,
    bbox: list[float] | tuple[float, ...],
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Regenerate one candidate image after manual rectangle adjustment."""
    from services.image_region_service import recrop_visual_region

    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    candidate = next((item for item in payload.get("questions", []) if isinstance(item, dict) and item.get("source_item_id") == source_item_id), None)
    if candidate is None:
        raise KeyError(f"未找到 PDF 题目候选：{source_item_id}")
    assets = candidate.get("assets") if isinstance(candidate.get("assets"), list) else []
    if not 0 <= int(asset_index) < len(assets):
        raise IndexError("图片资源序号超出范围")
    asset = assets[int(asset_index)]
    page_number = int(asset.get("page_number") or candidate.get("extra", {}).get("page_start") or 1)
    page = next((item for item in payload.get("pages", []) if int(item.get("page_number") or 0) == page_number), None)
    if not page:
        raise KeyError(f"未找到图片所在页面：{page_number}")
    page_path = job_dir / str(page.get("image_path") or "")
    if not page_path.is_file():
        raise FileNotFoundError(f"页面图片不存在：{page_path}")
    output_path = job_dir / "crops" / "manual" / f"{str(asset.get('alias') or source_item_id)}.png"
    result = recrop_visual_region(page_path, bbox, output_path, margin=0)
    asset.update({
        "source_path": output_path.relative_to(job_dir).as_posix(),
        "original_file_name": output_path.name,
        "bbox": result["bbox"],
        "pixel_bbox": result["crop_bbox"],
        "binding_confidence": 1.0,
        "detector": "manual_crop",
        "review_status": "ready",
        "note": "人工调整裁剪框后生成。",
    })
    _append_pdf_import_event(payload, source_item_id, "crop_updated", message=f"asset_index={int(asset_index)}")
    _save_pdf_import_state(job_dir, manifest, payload)
    return {"job_id": job_id, "source_item_id": source_item_id, "asset_index": int(asset_index), "asset": asset}


def merge_pdf_question_assets(
    job_id: str,
    source_item_id: str,
    asset_indexes: list[int],
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    """Merge multiple candidate regions belonging to one PDF question."""
    from services.image_region_service import merge_visual_regions

    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    candidate = next((item for item in payload.get("questions", []) if isinstance(item, dict) and item.get("source_item_id") == source_item_id), None)
    if candidate is None:
        raise KeyError(f"未找到 PDF 题目候选：{source_item_id}")
    assets = candidate.get("assets") if isinstance(candidate.get("assets"), list) else []
    selected_indexes = sorted({int(index) for index in asset_indexes})
    if len(selected_indexes) < 2 or any(index < 0 or index >= len(assets) for index in selected_indexes):
        raise ValueError("至少选择两个有效图片区域才能合并")
    selected = [assets[index] for index in selected_indexes]
    page_numbers = {int(item.get("page_number") or 0) for item in selected}
    if len(page_numbers) != 1:
        raise ValueError("只能合并同一页上的图片区域")
    page_number = next(iter(page_numbers))
    page = next((item for item in payload.get("pages", []) if int(item.get("page_number") or 0) == page_number), None)
    if not page:
        raise KeyError(f"未找到图片所在页面：{page_number}")
    page_path = job_dir / str(page.get("image_path") or "")
    output_path = job_dir / "crops" / "manual" / f"{source_item_id}_merged.png"
    result = merge_visual_regions(page_path, selected, output_path)
    merged_asset = {
        "role": "problem", "source_path": output_path.relative_to(job_dir).as_posix(),
        "original_file_name": output_path.name, "caption": "merged_figure",
        "alias": f"{source_item_id}_merged", "sort_order": min(int(item.get("sort_order") or 0) for item in selected),
        "review_status": "ready", "page_number": page_number, "bbox": result["bbox"],
        "pixel_bbox": result["bbox"], "binding_confidence": 1.0, "detector": "manual_merge",
        "note": f"人工合并 {len(selected)} 个裁剪区域。",
    }
    first = selected_indexes[0]
    candidate["assets"] = [asset for index, asset in enumerate(assets) if index not in selected_indexes or index == first]
    candidate["assets"][next(index for index, asset in enumerate(candidate["assets"]) if asset is assets[first])] = merged_asset
    _append_pdf_import_event(payload, source_item_id, "assets_merged", message=f"merged_count={len(selected)}")
    _save_pdf_import_state(job_dir, manifest, payload)
    return {"job_id": job_id, "source_item_id": source_item_id, "asset": merged_asset, "merged_count": len(selected)}


def bulk_mark_pdf_candidates_ready(
    job_id: str,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> dict[str, Any]:
    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    questions = [item for item in payload.get("questions", []) if isinstance(item, dict)]
    ready_ids: list[str] = []
    skipped: list[dict[str, Any]] = []
    for candidate in questions:
        if candidate.get("review_status") == "rejected":
            _append_pdf_import_event(payload, str(candidate.get("source_item_id") or ""), "skipped", status="skipped", message="候选题已被审核跳过")
            continue
        validation = validate_question_candidate(candidate)
        candidate["validation"] = {
            "status": "blocked" if validation["errors"] else "needs_review" if validation["warnings"] else "ready",
            **validation,
        }
        if validation["errors"] or validation["warnings"]:
            skipped.append(
                {
                    "source_item_id": str(candidate.get("source_item_id") or ""),
                    "issues": validation["errors"] + validation["warnings"],
                }
            )
            continue
        candidate["review_status"] = "ready"
        ready_ids.append(str(candidate.get("source_item_id") or ""))
        _append_pdf_import_event(payload, str(candidate.get("source_item_id") or ""), "candidate_saved", message="review_status=ready")

    status_counts: dict[str, int] = {}
    for candidate in questions:
        status = str(candidate.get("review_status") or "needs_review")
        status_counts[status] = status_counts.get(status, 0) + 1
    manifest.setdefault("draft_summary", {})["review_status_counts"] = status_counts
    _save_pdf_import_state(job_dir, manifest, payload)
    return {
        "job_id": job_id,
        "ready_count": len(ready_ids),
        "ready_ids": ready_ids,
        "skipped_count": len(skipped),
        "skipped": skipped,
        "writes_formal_database": False,
    }


def commit_pdf_import_candidates(
    job_id: str,
    candidate_ids: list[str],
    *,
    db_path: str | Path,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
    operator: str = "pdf_import_ui",
) -> dict[str, Any]:
    """Commit selected reviewed PDF candidates through the normal draft pipeline.

    The PDF job remains the audit source. Each candidate first becomes a normal
    SQLite import draft, then uses the same commit path as manual/batch entry.
    Warnings such as missing answers remain review warnings; hard validation
    errors are isolated to that candidate and do not roll back earlier commits.
    """
    from services.import_service import commit_draft_to_question, create_manual_entry_draft

    loaded = load_pdf_import_job(job_id, jobs_root)
    job_dir = loaded["job_dir"]
    manifest = loaded["manifest"]
    payload = loaded["draft_payload"]
    wanted = [str(value or "").strip() for value in candidate_ids if str(value or "").strip()]
    if not wanted:
        raise ValueError("至少选择一个 PDF 题目候选")

    candidates = {
        str(item.get("source_item_id") or ""): item
        for item in payload.get("questions", [])
        if isinstance(item, dict)
    }
    committed: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failed: list[dict[str, Any]] = []
    is_retry = any(
        isinstance(item, dict)
        and str(item.get("source_item_id") or "") in wanted
        and item.get("commit_status") == "failed"
        for item in payload.get("questions", [])
    )
    _append_pdf_import_event(payload, "", "retry_started" if is_retry else "commit_started", message=f"candidate_count={len(wanted)}")
    for source_item_id in wanted:
        candidate = candidates.get(source_item_id)
        if not candidate:
            failed.append({"source_item_id": source_item_id, "error": "找不到 PDF 候选题"})
            continue
        if candidate.get("review_status") in {"rejected", "committed"}:
            _append_pdf_import_event(payload, source_item_id, "commit_skipped", status="skipped", message=f"review_status={candidate.get('review_status')}")
            skipped.append({"source_item_id": source_item_id, "status": candidate.get("review_status")})
            continue
        validation = validate_question_candidate(candidate)
        if validation["errors"]:
            _append_pdf_import_event(payload, source_item_id, "retry_failed" if is_retry else "commit_failed", status="failed", message="; ".join(validation["errors"]))
            failed.append({"source_item_id": source_item_id, "errors": validation["errors"]})
            candidate["commit_status"] = "failed"
            candidate["commit_error"] = "；".join(validation["errors"])
            continue

        extra = dict(candidate.get("extra") or {})
        source_metadata = dict(extra.get("source_metadata") or payload.get("source_metadata") or {})
        extra.update(
            {
                "source_kind": "试卷" if str(payload.get("source_type") or "") == "pdf_paper" else "教材",
                "detected_question_number": extra.get("question_number") or "",
                "detected_year": extra.get("detected_year") or source_metadata.get("year") or source_metadata.get("year_or_volume") or "",
                "detected_source": extra.get("detected_source") or source_metadata.get("source_name") or "",
                "paper_series": extra.get("paper_series") or source_metadata.get("paper_series") or "G",
                "track": extra.get("track") or source_metadata.get("track") or "",
            }
        )
        draft_assets = []
        for raw_asset in candidate.get("assets") or []:
            if not isinstance(raw_asset, dict):
                continue
            asset = dict(raw_asset)
            source_path = str(asset.get("source_path") or asset.get("file_path") or "").strip()
            if source_path and not Path(source_path).is_absolute():
                asset["source_path"] = str((job_dir / source_path).resolve())
            draft_assets.append(asset)
        draft_payload = {
            "source_item_id": source_item_id,
            "source_label": candidate.get("source_label") or source_item_id,
            "proposed_action": "insert",
            "review_status": "ready",
            "question_type_id": candidate.get("question_type_id"),
            "stem_tex": candidate.get("stem_tex") or "",
            "choices": candidate.get("choices") or [],
            "answer_tex": candidate.get("answer_tex") or "",
            "solution_tex": candidate.get("solution_tex") or "",
            "difficulty": candidate.get("difficulty"),
            "tags": candidate.get("tags") or [],
            "note": candidate.get("note") or "",
            "official_flag": candidate.get("official_flag") or False,
            "extra": extra,
            "assets": draft_assets,
        }
        try:
            draft_result = create_manual_entry_draft(
                str(db_path),
                draft_payload,
                source_path=f"pdf-import/{job_id}",
            )
            commit_result = commit_draft_to_question(
                str(db_path),
                draft_result["draft_id"],
                operator=operator,
                require_ready=False,
            )
            candidate["commit_status"] = "committed"
            candidate["draft_id"] = draft_result["draft_id"]
            candidate["question_id"] = commit_result.get("question_id") or ""
            candidate["review_status"] = "committed"
            candidate.pop("commit_error", None)
            committed.append({"source_item_id": source_item_id, **commit_result})
            _append_pdf_import_event(
                payload,
                source_item_id,
                "retry_succeeded" if is_retry else "commit_succeeded",
                question_id=str(candidate.get("question_id") or ""),
                draft_id=str(candidate.get("draft_id") or ""),
            )
        except Exception as exc:
            candidate["commit_status"] = "failed"
            candidate["commit_error"] = str(exc)
            failed.append({"source_item_id": source_item_id, "error": str(exc)})
            _append_pdf_import_event(payload, source_item_id, "retry_failed" if is_retry else "commit_failed", status="failed", message=str(exc))

    payload["updated_at"] = utc_now()
    manifest["updated_at"] = utc_now()
    manifest.setdefault("commit_summary", {})["last_result"] = {
        "committed": len(committed),
        "skipped": len(skipped),
        "failed": len(failed),
        "updated_at": payload["updated_at"],
    }
    write_json(job_dir / "draft_payload.json", payload)
    write_json(job_dir / "job_manifest.json", manifest)
    write_import_report(
        job_dir / "import_report.md",
        job_id=job_id,
        page_count=len(payload.get("pages") or []),
        drafts=payload.get("questions") or [],
        unassigned_blocks=payload.get("unassigned_blocks") or [],
    )
    return {
        "job_id": job_id,
        "committed": committed,
        "skipped": skipped,
        "failed": failed,
        "writes_formal_database": bool(committed),
    }


def list_pdf_import_failed_candidates(
    job_id: str,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
) -> list[dict[str, Any]]:
    loaded = load_pdf_import_job(job_id, jobs_root)
    return [
        item
        for item in loaded["draft_payload"].get("questions", [])
        if isinstance(item, dict) and item.get("commit_status") == "failed"
    ]


def retry_failed_pdf_import_candidates(
    job_id: str,
    candidate_ids: list[str] | None = None,
    *,
    db_path: str | Path,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
    operator: str = "pdf_import_ui",
) -> dict[str, Any]:
    failed = list_pdf_import_failed_candidates(job_id, jobs_root=jobs_root)
    failed_ids = [str(item.get("source_item_id") or "") for item in failed]
    selected = [str(value or "").strip() for value in (candidate_ids or failed_ids) if str(value or "").strip()]
    if not selected:
        return {
            "job_id": job_id,
            "committed": [],
            "skipped": [],
            "failed": [],
            "writes_formal_database": False,
        }
    return commit_pdf_import_candidates(
        job_id,
        [value for value in selected if value in failed_ids],
        db_path=db_path,
        jobs_root=jobs_root,
        operator=operator,
    )


def split_pages_into_question_drafts(
    pages: list[dict[str, Any]],
    *,
    source_type: str,
    source_metadata: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    drafts: list[dict[str, Any]] = []
    unassigned_blocks: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    sequence = 0
    image_candidates_by_page = {
        int(page.get("page_number") or 0): [
            dict(item) for item in page.get("image_candidates") or [] if isinstance(item, dict)
        ]
        for page in pages
    }
    accepted_paper_markers = _paper_question_marker_positions(pages) if source_type == "pdf_paper" else set()

    def finish_current() -> None:
        nonlocal current
        if not current:
            return
        raw_lines = current.pop("raw_lines")
        stem_lines = current.pop("stem_lines")
        raw_text = "\n".join(raw_lines).strip()
        stem_text = "\n".join(stem_lines).strip()
        page_numbers = sorted(current.pop("page_numbers"))
        question_number = str(current.get("extra", {}).get("question_number") or "")
        matched_images = []
        for page_number in page_numbers:
            page_images = image_candidates_by_page.get(page_number) or []
            exact_images = [
                item for item in page_images if str(item.get("suggested_question_number") or "") == question_number
            ]
            if exact_images:
                matched_images.extend(exact_images)
        assets = []
        for asset_index, image in enumerate(matched_images, start=1):
            caption = f"figure_{asset_index:02d}"
            alias = f"q{question_number}_figure_{asset_index:02d}"
            assets.append(
                {
                    "role": "problem",
                    "source_path": image.get("source_path") or "",
                    "original_file_name": image.get("original_file_name") or "",
                    "caption": caption,
                    "alias": alias,
                    "sort_order": asset_index,
                    "review_status": "needs_review",
                    "page_number": image.get("page_number"),
                    "bbox": image.get("bbox") or [],
                    "pixel_bbox": image.get("pixel_bbox") or [],
                    "source_block_id": image.get("block_id") or "",
                    "binding_confidence": image.get("binding_confidence") or 0,
                    "note": "由页面坐标自动绑定，入库前请确认归属和裁剪范围。",
                }
            )
        image_markers = [f"[IMAGE: {asset['alias']}]" for asset in assets]
        ordered_content = [item for item in current.pop("content_lines", []) if str(item.get("text") or "").strip()]
        marker_positions: dict[int, list[str]] = {}
        for asset in assets:
            image_page = int(asset.get("page_number") or 0)
            image_bbox = asset.get("bbox") or []
            insert_at = len(ordered_content)
            for line_index, line in enumerate(ordered_content):
                line_bbox = line.get("bbox") or []
                if int(line.get("page_number") or 0) == image_page and len(image_bbox) >= 4 and len(line_bbox) >= 4 and line_bbox[1] >= image_bbox[1]:
                    insert_at = line_index
                    break
            marker_positions.setdefault(insert_at, []).append(f"[IMAGE: {asset['alias']}]")
        ordered_parts: list[str] = []
        for line_index, line in enumerate(ordered_content):
            ordered_parts.extend(marker_positions.get(line_index, []))
            ordered_parts.append(str(line.get("text") or ""))
        ordered_parts.extend(marker_positions.get(len(ordered_content), []))
        stem_source_with_image_markers = "\n".join(ordered_parts).strip() or stem_text
        current.update(
            {
                "stem_tex": stem_text,
                "raw_source_text": raw_text,
                "extra": {
                    **current["extra"],
                    "page_start": page_numbers[0],
                    "page_end": page_numbers[-1],
                    "source_page_images": [f"pages/page_{number:03d}.png" for number in page_numbers],
                    "asset_candidate_count": len(assets),
                    "image_markers": image_markers,
                    "stem_source_with_image_markers": stem_source_with_image_markers,
                },
                "assets": assets,
            }
        )
        drafts.append(current)
        current = None

    for page in pages:
        page_number = int(page.get("page_number") or 0)
        preamble_lines: list[str] = []
        for line_index, raw_line in enumerate(str(page.get("raw_text") or "").splitlines()):
            line = raw_line.strip()
            if not line:
                continue
            marker = QUESTION_START_PATTERN.match(line)
            if source_type == "pdf_paper" and marker and accepted_paper_markers and (page_number, line_index) not in accepted_paper_markers:
                marker = None
            if marker:
                finish_current()
                sequence += 1
                question_number = marker.group(1)
                first_stem_line = marker.group(2).strip()
                current = {
                    "source_item_id": f"page_{page_number:03d}_q_{question_number}_{sequence:03d}",
                    "source_label": f"第 {question_number} 题 · PDF 第 {page_number} 页",
                    "proposed_action": "insert",
                    "review_status": "needs_review",
                    "review_reason": "题号为启发式切分；题型、选项、答案和解析仍需人工或 AI 校订。",
                    "question_type": "other",
                    "choices": [],
                    "answer_tex": "",
                    "solution_tex": "",
                    "difficulty": None,
                    "tags": [],
                    "note": "",
                    "official_flag": False,
                    "confidence": {"question_split": 0.8, "stem_tex": 0.45},
                    "validation": {
                        "status": "needs_review",
                        "warnings": ["题型、选项、答案和解析尚未识别。"],
                    },
                    "extra": {
                        "source_kind": source_type,
                        "source_metadata": dict(source_metadata or {}),
                        "question_number": question_number,
                        "splitter": "numbered_line_v1",
                    },
                    "assets": [],
                    "raw_lines": [line],
                    "stem_lines": [first_stem_line] if first_stem_line else [],
                    "content_lines": [
                        {"text": first_stem_line, "bbox": [], "page_number": page_number}
                    ] if first_stem_line else [],
                    "page_numbers": {page_number},
                }
            elif current:
                current["raw_lines"].append(line)
                current["stem_lines"].append(line)
                layout_lines = [
                    line_item
                    for block in page.get("layout_blocks") or []
                    for line_item in block.get("lines") or []
                    if str(line_item.get("text") or "").strip()
                ]
                line_bbox = layout_lines[line_index].get("bbox") or [] if line_index < len(layout_lines) else []
                current.setdefault("content_lines", []).append(
                    {"text": line, "bbox": line_bbox, "page_number": page_number}
                )
                current["page_numbers"].add(page_number)
            else:
                preamble_lines.append(line)
        if preamble_lines:
            unassigned_blocks.append(
                {
                    "page_number": page_number,
                    "reason": "text_before_first_question",
                    "raw_text": "\n".join(preamble_lines),
                }
            )
    finish_current()

    if drafts:
        return drafts, unassigned_blocks

    for page in pages:
        page_number = int(page.get("page_number") or 0)
        raw_text = str(page.get("raw_text") or "").strip()
        if not raw_text:
            continue
        page_assets = []
        for asset_index, image in enumerate(page.get("image_candidates") or [], start=1):
            page_assets.append(
                {
                    "role": "problem",
                    "source_path": image.get("source_path") or "",
                    "original_file_name": image.get("original_file_name") or "",
                    "caption": f"figure_{asset_index:02d}",
                    "alias": f"page_{page_number:03d}_figure_{asset_index:02d}",
                    "sort_order": asset_index,
                    "review_status": "needs_review",
                    "page_number": page_number,
                    "bbox": image.get("bbox") or [],
                    "pixel_bbox": image.get("pixel_bbox") or [],
                    "source_block_id": image.get("block_id") or "",
                    "binding_confidence": 0,
                    "note": "当前页面未识别题号，图片归属必须人工确认。",
                }
            )
        drafts.append(
            {
                "source_item_id": f"page_{page_number:03d}_unsegmented",
                "source_label": f"PDF 第 {page_number} 页 · 未识别题号",
                "proposed_action": "insert",
                "review_status": "needs_review",
                "review_reason": "未识别到可靠题号，暂按整页生成候选。",
                "question_type": "other",
                "stem_tex": raw_text,
                "choices": [],
                "answer_tex": "",
                "solution_tex": "",
                "difficulty": None,
                "tags": [],
                "note": "",
                "official_flag": False,
                "raw_source_text": raw_text,
                "confidence": {"question_split": 0.2, "stem_tex": 0.35},
                "validation": {
                    "status": "needs_review",
                    "warnings": ["未识别题号；题型、选项、答案和解析尚未识别。"],
                },
                "extra": {
                    "source_kind": source_type,
                    "source_metadata": dict(source_metadata or {}),
                    "question_number": "",
                    "page_start": page_number,
                    "page_end": page_number,
                    "source_page_images": [f"pages/page_{page_number:03d}.png"],
                    "asset_candidate_count": len(page_assets),
                    "splitter": "page_fallback_v1",
                },
                "assets": page_assets,
            }
        )
    return drafts, []


def write_import_report(
    path: Path,
    *,
    job_id: str,
    page_count: int,
    drafts: list[dict[str, Any]],
    unassigned_blocks: list[dict[str, Any]],
) -> None:
    numbered_count = sum(1 for item in drafts if item.get("extra", {}).get("question_number"))
    status_counts: dict[str, int] = {}
    for item in drafts:
        status = str(item.get("review_status") or "needs_review")
        status_counts[status] = status_counts.get(status, 0) + 1
    status_text = "，".join(f"{status}={count}" for status, count in sorted(status_counts.items())) or "无"
    lines = [
        "# PDF 导入草稿报告",
        "",
        f"- 任务：`{job_id}`",
        f"- PDF 页数：{page_count}",
        f"- 题目候选：{len(drafts)}",
        f"- 识别到题号：{numbered_count}",
        f"- 未归属文本块：{len(unassigned_blocks)}",
        f"- 审核状态：{status_text}",
        "- 正式数据库写入：否",
        "",
        "## 审核边界",
        "",
        "- 当前仅按题号行或整页进行启发式切分。",
        "- 题型、选项、答案、解析、公式和图片裁剪仍需后续识别与人工审核。",
        "- 所有候选均保持 `needs_review`，不会直接写入正式 `question` 表。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def create_pdf_import_job(
    source_pdf: str | Path,
    *,
    jobs_root: str | Path = DEFAULT_JOBS_ROOT,
    job_id: str | None = None,
    source_type: str = "pdf_misc",
    source_metadata: dict[str, Any] | None = None,
    render_dpi: int = 144,
    original_name: str | None = None,
    parser_mode: str = "auto",
) -> dict[str, Any]:
    source_path = Path(source_pdf).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"PDF 文件不存在：{source_path}")
    if source_path.suffix.lower() != ".pdf":
        raise ValueError(f"仅支持 PDF 文件：{source_path.name}")
    if source_type not in SOURCE_TYPES:
        raise ValueError(f"不支持的 PDF 来源类型：{source_type}")
    if not 72 <= int(render_dpi) <= 300:
        raise ValueError("render_dpi 必须在 72 到 300 之间。")
    normalized_metadata = dict(source_metadata or {})
    try:
        json.dumps(normalized_metadata, ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("source_metadata 必须可以序列化为 JSON。") from exc

    root = Path(jobs_root).resolve()
    resolved_job_id = validate_job_id(job_id or generate_job_id(source_path))
    job_dir = root / resolved_job_id
    ensure_inside(root, job_dir)
    if job_dir.exists():
        raise FileExistsError(f"PDF 导入任务已存在：{job_dir}")

    pages_dir = job_dir / "pages"
    pages_dir.mkdir(parents=True)
    copied_pdf = job_dir / "source.pdf"
    shutil.copy2(source_path, copied_pdf)
    created_at = utc_now()
    manifest_path = job_dir / "job_manifest.json"
    draft_path = job_dir / "draft_payload.json"
    report_path = job_dir / "import_report.md"
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "job_id": resolved_job_id,
        "status": "created",
        "created_at": created_at,
        "updated_at": created_at,
        "source": {
            "original_name": Path(original_name).name if original_name else source_path.name,
            "copied_path": "source.pdf",
            "size_bytes": copied_pdf.stat().st_size,
            "sha256": file_sha256(copied_pdf),
            "source_type": source_type,
            "metadata": normalized_metadata,
        },
        "parser": {
            "name": "pending",
            "version": fitz.VersionBind,
            "render_dpi": int(render_dpi),
            "mode": parser_mode,
        },
        "outputs": {
            "pages_directory": "pages",
            "extracted_assets_directory": "extracted_assets",
            "crops_directory": "crops",
            "question_crops_directory": "question_crops",
            "draft_payload": "draft_payload.json",
            "import_report": "import_report.md",
        },
        "writes_formal_database": False,
    }
    write_json(manifest_path, manifest)

    try:
        from services.document_parser_service import (
            load_mineru_content_list,
            mineru_blocks_to_page_overrides,
            normalize_parser_mode,
            parse_with_boundary,
        )

        normalized_parser_mode = normalize_parser_mode(parser_mode)
        parser_result = parse_with_boundary(
            copied_pdf,
            job_dir / "mineru_result",
            mode=normalized_parser_mode,
        )
        manifest["parser"] = {
            "name": parser_result.get("parser") or "pymupdf",
            "mode": normalized_parser_mode,
            "fallback": bool(parser_result.get("fallback")),
            "reason": parser_result.get("reason") or "",
            "render_dpi": int(render_dpi),
        }
        cloud_overrides: dict[int, dict[str, Any]] = {}
        if parser_result.get("parser") == "mineru_cloud":
            result_dirs = [item.get("output_dir") for item in parser_result.get("downloads") or []]
            content_root = next((Path(str(value)) for value in result_dirs if value and (Path(str(value)) / "content_list.json").exists()), None)
            if content_root is None:
                candidates = [Path(str(value)) for value in result_dirs if value]
                content_root = next((candidate for candidate in candidates if list(candidate.rglob("*_content_list.json"))), None)
            if content_root is None:
                if normalized_parser_mode == "cloud":
                    raise RuntimeError("MinerU 结果中没有 content_list.json")
                manifest["parser"].update({"name": "pymupdf", "fallback": True, "reason": "MinerU result missing content_list.json"})
            else:
                cloud_payload = load_mineru_content_list(content_root)
                cloud_overrides = mineru_blocks_to_page_overrides(cloud_payload["blocks"], job_dir=job_dir)
                if not cloud_overrides and normalized_parser_mode == "cloud":
                    raise RuntimeError("MinerU content_list.json 没有可用文本或图片块")
                if not cloud_overrides:
                    manifest["parser"].update({"name": "pymupdf", "fallback": True, "reason": "MinerU result has no usable blocks"})
        pages: list[dict[str, Any]] = []
        scale = int(render_dpi) / 72
        with fitz.open(copied_pdf) as document:
            document_metadata = {str(key): value for key, value in (document.metadata or {}).items()}
            for page_index, page in enumerate(document):
                page_number = page_index + 1
                image_name = f"page_{page_number:03d}.png"
                image_path = pages_dir / image_name
                pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                pixmap.save(image_path)
                raw_text = page.get_text("text")
                layout_blocks, image_candidates = _page_layout_blocks(
                    page,
                    page_number,
                    job_dir,
                    scale,
                )
                image_candidates.extend(
                    _page_vector_regions(
                        page,
                        page_number,
                        job_dir,
                        scale,
                        layout_blocks,
                        image_candidates,
                    )
                )
                from services.image_region_service import crop_visual_regions, detect_visual_regions, opencv_available

                if opencv_available():
                    text_pixel_boxes = [
                        [round(value * scale, 2) for value in line.get("bbox") or []]
                        for block in layout_blocks
                        for line in block.get("lines") or []
                        if len(line.get("bbox") or []) >= 4
                    ]
                    detected_regions = detect_visual_regions(image_path, text_boxes=text_pixel_boxes)
                    embedded_pixel_boxes = [item.get("pixel_bbox") or [] for item in image_candidates]
                    detected_regions = [
                        region
                        for region in detected_regions
                        if not any(
                            _bbox_overlap_ratio(region.get("bbox") or [], embedded_bbox) >= 0.65
                            for embedded_bbox in embedded_pixel_boxes
                        )
                    ]
                    cropped_regions = crop_visual_regions(
                        image_path,
                        detected_regions,
                        job_dir / "crops",
                        name_prefix=f"page_{page_number:03d}_region",
                    )
                    for region_index, region in enumerate(cropped_regions, start=1):
                        pixel_bbox = region.get("crop_bbox") or region.get("bbox") or []
                        page_bbox = [round(value / scale, 2) for value in pixel_bbox]
                        suggested, confidence = _suggest_question_for_bbox(layout_blocks, page_bbox)
                        region_path = Path(str(region.get("source_path") or ""))
                        image_candidates.append(
                            {
                                "block_id": f"p{page_number:03d}_opencv_{region_index:03d}",
                                "type": "detected_region",
                                "page_number": page_number,
                                "bbox": page_bbox,
                                "pixel_bbox": pixel_bbox,
                                "source_path": region_path.relative_to(job_dir).as_posix(),
                                "original_file_name": region_path.name,
                                "width": max(0, int(pixel_bbox[2] - pixel_bbox[0])) if len(pixel_bbox) >= 4 else 0,
                                "height": max(0, int(pixel_bbox[3] - pixel_bbox[1])) if len(pixel_bbox) >= 4 else 0,
                                "suggested_question_number": suggested,
                                "binding_confidence": confidence,
                                "detector": region.get("detector") or "opencv_non_text_v1",
                            }
                        )
                cloud_page = cloud_overrides.get(page_number)
                if cloud_page:
                    raw_text = cloud_page["raw_text"] or raw_text
                    layout_blocks = cloud_page["layout_blocks"] or layout_blocks
                    image_candidates = cloud_page["image_candidates"] or image_candidates
                pages.append(
                    {
                        "page_number": page_number,
                        "image_path": f"pages/{image_name}",
                        "image_width": pixmap.width,
                        "image_height": pixmap.height,
                        "raw_text": raw_text,
                        "text_char_count": len(raw_text),
                        "layout_blocks": layout_blocks,
                        "image_candidates": image_candidates,
                    }
                )

        question_drafts, unassigned_blocks = split_pages_into_question_drafts(
            pages,
            source_type=source_type,
            source_metadata=normalized_metadata,
        )
        _attach_question_crops(pages, question_drafts, job_dir, scale, source_type)
        draft_payload = {
            "schema_version": 1,
            "job_id": resolved_job_id,
            "status": "needs_review",
            "source_path": "source.pdf",
            "summary": f"PDF heuristic split; pages={len(pages)}; candidates={len(question_drafts)}",
            "source_type": source_type,
            "source_metadata": normalized_metadata,
            "pages": pages,
            "questions": question_drafts,
            "unassigned_blocks": unassigned_blocks,
            "writes_formal_database": False,
        }
        write_json(draft_path, draft_payload)
        write_import_report(
            report_path,
            job_id=resolved_job_id,
            page_count=len(pages),
            drafts=question_drafts,
            unassigned_blocks=unassigned_blocks,
        )
        manifest.update(
            {
                "status": "drafted",
                "updated_at": utc_now(),
                "document": {
                    "page_count": len(pages),
                    "metadata": document_metadata,
                },
                "draft_summary": {
                    "question_candidate_count": len(question_drafts),
                    "unassigned_block_count": len(unassigned_blocks),
                    "review_status": "needs_review",
                    "review_status_counts": {"needs_review": len(question_drafts)},
                },
            }
        )
        write_json(manifest_path, manifest)
    except Exception as exc:
        manifest.update(
            {
                "status": "failed",
                "updated_at": utc_now(),
                "error": {"type": type(exc).__name__, "message": str(exc)},
            }
        )
        write_json(manifest_path, manifest)
        raise

    return {
        "status": "drafted",
        "job_id": resolved_job_id,
        "job_dir": str(job_dir),
        "manifest_path": str(manifest_path),
        "draft_payload_path": str(draft_path),
        "import_report_path": str(report_path),
        "page_count": len(pages),
        "question_candidate_count": len(question_drafts),
        "writes_formal_database": False,
    }
