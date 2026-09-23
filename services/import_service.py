"""Import-batch and draft-question helpers for safe AI/OCR ingestion."""

from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import shutil
from difflib import SequenceMatcher
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from services.database_service import BASE_DIR, database_connection, existing_database_connection, readonly_database_connection, row_to_dict
from services.revision_service import insert_question_revision_from_conn


PROJECT_ROOT = Path(BASE_DIR)

REQUIRED_DRAFT_FIELDS = ("stem_tex",)
ALLOWED_PROPOSED_ACTIONS = {"insert", "update", "skip"}
ALLOWED_REVIEW_STATUS = {"needs_review", "ready", "blocked", "approved", "committed", "rejected", "sample"}
DRAFT_EDITABLE_COLUMNS = {
    "source_item_id",
    "source_label",
    "proposed_action",
    "target_question_id",
    "question_type_id",
    "stem_tex",
    "choices_json",
    "answer_tex",
    "solution_tex",
    "difficulty",
    "tags_json",
    "note",
    "official_flag",
    "raw_source_text",
    "extra_json",
}
DRAFT_UPDATE_ALIASES = {
    "choices": "choices_json",
    "tags": "tags_json",
    "extra": "extra_json",
}
DRAFT_ASSET_EDITABLE_COLUMNS = {
    "role",
    "source_path",
    "planned_file_path",
    "original_file_name",
    "caption",
    "sort_order",
    "review_status",
    "note",
    "extra_json",
}
VALID_DRAFT_ASSET_ROLES = {"problem", "answer", "solution", "source", "thumbnail"}
QUESTION_TYPE_NAMES = {
    "single_choice": 1,
    "single": 1,
    "choice": 1,
    "单选题": 1,
    "单项选择题": 1,
    "选择题": 1,
    "multiple_choice": 2,
    "multiple": 2,
    "多选题": 2,
    "多项选择题": 2,
    "fill_blank": 3,
    "blank": 3,
    "填空题": 3,
    "solution": 4,
    "proof": 4,
    "解答题": 4,
    "证明题": 4,
    "true_false": 6,
    "判断": 6,
    "判断题": 6,
    "other": 5,
    "其他": 5,
}


@dataclass(frozen=True)
class DraftAssetInput:
    role: str = "problem"
    source_path: str = ""
    planned_file_path: str = ""
    original_file_name: str = ""
    caption: str = ""
    sort_order: int = 0
    note: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DraftQuestionInput:
    source_item_id: str = ""
    source_label: str = ""
    proposed_action: str = "insert"
    target_question_id: str = ""
    review_status: str = "needs_review"
    review_reason: str = ""
    question_type_id: int | None = None
    question_type: str = ""
    stem_tex: str = ""
    choices: list[str] = field(default_factory=list)
    answer_tex: str = ""
    solution_tex: str = ""
    difficulty: int | None = None
    tags: list[str] = field(default_factory=list)
    note: str = ""
    official_flag: bool = False
    raw_source_text: str = ""
    normalized_tex: str = ""
    confidence: dict[str, Any] = field(default_factory=dict)
    validation: dict[str, Any] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)
    assets: list[DraftAssetInput] = field(default_factory=list)


def stable_id(prefix: str, *values: object, length: int = 14) -> str:
    raw = "\u241f".join("" if value is None else str(value) for value in values)
    return prefix + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:length]


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def parse_json_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, dict):
        return [str(value[key]).strip() for key in sorted(value) if str(value[key]).strip()]
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return []
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return [item.strip() for item in stripped.replace("，", ",").split(",") if item.strip()]
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return []


def coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return False
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "y", "是", "官方"}
    return bool(value)


def parse_json_object(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
        except json.JSONDecodeError:
            return {"raw": value}
        if isinstance(parsed, dict):
            return parsed
    return {"value": value}


def coerce_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_question_type_id(value: Any, question_type: str = "") -> int:
    numeric_value = coerce_int(value)
    if numeric_value in QUESTION_TYPE_NAMES.values():
        return int(numeric_value)
    return QUESTION_TYPE_NAMES.get((question_type or "").strip(), 5)


def normalize_draft_question(data: dict[str, Any]) -> DraftQuestionInput:
    assets = [
        DraftAssetInput(
            role=str(item.get("role") or "problem").strip(),
            source_path=str(item.get("source_path") or item.get("path") or "").strip(),
            planned_file_path=str(item.get("planned_file_path") or "").strip(),
            original_file_name=str(item.get("original_file_name") or "").strip(),
            caption=str(item.get("caption") or "").strip(),
            sort_order=coerce_int(item.get("sort_order")) or 0,
            note=str(item.get("note") or "").strip(),
            extra=parse_json_object(item.get("extra") or item.get("extra_json")),
        )
        for item in data.get("assets", []) or []
        if isinstance(item, dict)
    ]
    question_type = str(data.get("question_type") or data.get("type") or "").strip()
    return DraftQuestionInput(
        source_item_id=str(data.get("source_item_id") or data.get("source_id") or "").strip(),
        source_label=str(data.get("source_label") or data.get("label") or "").strip(),
        proposed_action=str(data.get("proposed_action") or "insert").strip(),
        target_question_id=str(data.get("target_question_id") or data.get("question_id") or "").strip(),
        review_status=str(data.get("review_status") or "needs_review").strip(),
        review_reason=str(data.get("review_reason") or "").strip(),
        question_type_id=normalize_question_type_id(data.get("question_type_id"), question_type),
        question_type=question_type,
        stem_tex=str(data.get("stem_tex") or data.get("stem") or "").strip(),
        choices=parse_json_list(data.get("choices") or data.get("choices_json")),
        answer_tex=str(data.get("answer_tex") or data.get("answer") or "").strip(),
        solution_tex=str(data.get("solution_tex") or data.get("solution") or "").strip(),
        difficulty=coerce_int(data.get("difficulty")),
        tags=parse_json_list(data.get("tags") or data.get("tags_json")),
        note=str(data.get("note") or "").strip(),
        official_flag=coerce_bool(data.get("official_flag") if "official_flag" in data else data.get("official")),
        raw_source_text=str(data.get("raw_source_text") or data.get("raw_source") or "").strip(),
        normalized_tex=str(data.get("normalized_tex") or "").strip(),
        confidence=parse_json_object(data.get("confidence") or data.get("confidence_json")),
        validation=parse_json_object(data.get("validation") or data.get("validation_json")),
        extra=parse_json_object(data.get("extra") or data.get("extra_json")),
        assets=assets,
    )


def _draft_reference_issues(draft: DraftQuestionInput) -> dict[str, Any]:
    from services.asset_service import collect_asset_reference_issues

    record = {
        "stem_tex": draft.stem_tex,
        "answer_tex": draft.answer_tex,
        "solution_tex": draft.solution_tex,
        "canonical_tex": draft.normalized_tex,
        "normalized_tex": draft.normalized_tex,
    }
    assets = [dict(asset.__dict__) for asset in draft.assets]
    source_file = str(draft.extra.get("legacy_file_path") or draft.extra.get("source_file") or "").strip()
    return collect_asset_reference_issues(
        record,
        assets,
        project_root=PROJECT_ROOT,
        source_file=source_file,
    )


def validate_draft_question(draft: DraftQuestionInput) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    if draft.proposed_action not in ALLOWED_PROPOSED_ACTIONS:
        errors.append(f"proposed_action 不支持：{draft.proposed_action}")
    if draft.review_status not in ALLOWED_REVIEW_STATUS:
        errors.append(f"review_status 不支持：{draft.review_status}")
    if draft.proposed_action == "update" and not draft.target_question_id:
        errors.append("update 草稿必须提供 target_question_id")
    if not draft.stem_tex:
        errors.append("缺少 stem_tex")
    if draft.difficulty is not None and not 1 <= draft.difficulty <= 5:
        warnings.append("difficulty 建议在 1-5 之间")
    if draft.question_type_id == QUESTION_TYPE_NAMES["single_choice"] and len(draft.choices) < 2:
        warnings.append("单选题选项少于 2 个")
    if not draft.answer_tex:
        warnings.append("缺少 answer_tex")
    if not draft.solution_tex:
        warnings.append("缺少 solution_tex")

    asset_issues = _draft_reference_issues(draft)
    if asset_issues.get("missing_includegraphics"):
        errors.append("存在缺失 includegraphics 图片引用")
    if asset_issues.get("unresolved_questionasset"):
        errors.append("存在未登记 questionasset 图片引用")
    if asset_issues.get("missing_asset_files"):
        errors.append("存在缺失的图片资源文件")
    if asset_issues.get("unreferenced_assets"):
        warnings.append("存在已登记但未被引用的图片资源")

    asset_warnings = []
    for asset in draft.assets:
        if not asset.source_path:
            asset_warnings.append("存在空 source_path 的资产草稿")
    warnings.extend(asset_warnings)

    status = "blocked" if errors else "ready" if not warnings else "needs_review"
    return {
        "status": status,
        "errors": errors,
        "warnings": warnings,
    }


def make_batch_id(import_type: str, source_path: str, stamp: str) -> str:
    return stable_id("IB", import_type, source_path, stamp)


def make_draft_id(batch_id: str, index: int, draft: DraftQuestionInput) -> str:
    return stable_id("D", batch_id, index, draft.source_item_id, draft.stem_tex[:120])


def make_draft_asset_id(draft_id: str, index: int, asset: DraftAssetInput) -> str:
    return stable_id("DA", draft_id, index, asset.role, asset.source_path)


def create_import_batch(
    db_path: str | None,
    import_type: str,
    source_path: str,
    mode: str,
    stamp: str,
    summary: str = "",
) -> str:
    batch_id = make_batch_id(import_type, source_path, stamp)
    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO import_batch(
                batch_id, import_type, source_path, mode, started_at, summary
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                import_type,
                source_path,
                mode,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                summary,
            ),
        )
    return batch_id


def finish_import_batch(db_path: str | None, batch_id: str, summary: str = "") -> None:
    """Mark an import batch as finished."""
    with database_connection(db_path) as conn:
        conn.execute(
            """
            UPDATE import_batch
            SET finished_at = ?, summary = CASE WHEN ? != '' THEN ? ELSE summary END
            WHERE batch_id = ?
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                summary,
                summary,
                batch_id,
            ),
        )


def insert_draft_question(
    db_path: str | None,
    batch_id: str,
    draft: DraftQuestionInput,
    index: int,
) -> tuple[str, dict[str, Any]]:
    validation = validate_draft_question(draft)
    draft_id = make_draft_id(batch_id, index, draft)
    source_label = draft.source_label or draft.source_item_id or f"item-{index}"

    with database_connection(db_path) as conn:
        target_question_id = draft.target_question_id or None
        extra_json = dict(draft.extra)
        if target_question_id:
            target_exists = conn.execute(
                "SELECT 1 FROM question WHERE question_id = ?",
                (target_question_id,),
            ).fetchone()
            if not target_exists:
                validation["errors"].append(f"target_question_id 不存在：{target_question_id}")
                validation["status"] = "blocked"
                extra_json["unresolved_target_question_id"] = target_question_id
                target_question_id = None

        review_status = draft.review_status
        review_reason = draft.review_reason
        if validation["errors"]:
            review_status = "blocked"
            review_reason = "；".join(validation["errors"])
        elif validation["warnings"] and review_status == "ready":
            review_status = "needs_review"
            review_reason = "；".join(validation["warnings"])
        elif not review_reason and validation["warnings"]:
            review_reason = "；".join(validation["warnings"])

        validation_json = {**draft.validation, "draft_validation": validation}
        conn.execute(
            """
            INSERT OR REPLACE INTO question_import_draft(
                draft_id, batch_id, source_item_id, source_label, proposed_action,
                target_question_id, review_status, review_reason, question_type_id,
                stem_tex, choices_json, answer_tex, solution_tex, difficulty,
                tags_json, note, official_flag, raw_source_text, normalized_tex,
                confidence_json, validation_json, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_id,
                batch_id,
                draft.source_item_id,
                source_label,
                draft.proposed_action,
                target_question_id,
                review_status,
                review_reason,
                draft.question_type_id,
                draft.stem_tex,
                compact_json(draft.choices),
                draft.answer_tex,
                draft.solution_tex,
                draft.difficulty,
                compact_json(draft.tags),
                draft.note,
                1 if draft.official_flag else 0,
                draft.raw_source_text,
                draft.normalized_tex,
                compact_json(draft.confidence),
                compact_json(validation_json),
                compact_json(extra_json),
            ),
        )
        conn.execute("DELETE FROM question_import_draft_asset WHERE draft_id = ?", (draft_id,))
        for asset_index, asset in enumerate(draft.assets, start=1):
            source = Path(asset.source_path)
            mime_type = mimetypes.guess_type(source.name)[0] or ""
            conn.execute(
                """
                INSERT INTO question_import_draft_asset(
                    draft_asset_id, draft_id, role, source_path, planned_file_path,
                    original_file_name, mime_type, file_hash, caption, sort_order,
                    review_status, note, extra_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    make_draft_asset_id(draft_id, asset_index, asset),
                    draft_id,
                    asset.role,
                    asset.source_path,
                    asset.planned_file_path,
                    asset.original_file_name or source.name,
                    mime_type,
                    "",
                    asset.caption,
                    asset.sort_order or asset_index,
                    "needs_review",
                    asset.note,
                    compact_json(asset.extra),
                ),
            )
    return draft_id, validation


def insert_report_item(
    db_path: str | None,
    batch_id: str,
    index: int,
    source_file: str,
    question_id: str | None,
    status: str,
    reason: str,
    detail: str,
) -> str:
    item_id = stable_id("IRI", batch_id, index, source_file, status, reason)
    with database_connection(db_path) as conn:
        safe_question_id = question_id
        if safe_question_id:
            exists = conn.execute(
                "SELECT 1 FROM question WHERE question_id = ?",
                (safe_question_id,),
            ).fetchone()
            if not exists:
                safe_question_id = None
        conn.execute(
            """
            INSERT OR REPLACE INTO import_report_item(
                item_id, batch_id, source_file, question_id, status, reason, detail
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (item_id, batch_id, source_file, safe_question_id, status, reason, detail),
        )
    return item_id


def _get_draft_question_from_conn(conn, draft_id: str) -> dict:
    row = conn.execute(
        """
        SELECT *
        FROM question_import_draft
        WHERE draft_id = ?
        """,
        (draft_id,),
    ).fetchone()
    if not row:
        return {}
    assets = conn.execute(
        """
        SELECT *
        FROM question_import_draft_asset
        WHERE draft_id = ?
        ORDER BY role, sort_order, draft_asset_id
        """,
        (draft_id,),
    ).fetchall()
    result = dict(row)
    result["assets"] = [dict(asset) for asset in assets]
    return result


def get_draft_question(db_path: str | None, draft_id: str) -> dict:
    """Return one draft question with its draft assets."""
    with readonly_database_connection(db_path) as conn:
        return _get_draft_question_from_conn(conn, draft_id)


def list_ready_draft_ids(db_path: str | None, batch_id: str = "") -> list[str]:
    """Return draft IDs that are eligible for commit preview."""
    clauses = ["review_status IN ('ready', 'approved')"]
    params: list[object] = []
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT draft_id
            FROM question_import_draft
            WHERE {' AND '.join(clauses)}
            ORDER BY created_at, draft_id
            """,
            params,
        ).fetchall()
    return [str(row[0]) for row in rows]


def find_paper_position_conflict(db_path: str | None, extra: dict[str, Any]) -> list[dict[str, Any]]:
    """Find existing questions occupying the same paper/year/question position."""
    if str(extra.get("source_kind") or "").strip() != "试卷":
        return []
    question_number = str(extra.get("detected_question_number") or "").strip()
    if not question_number:
        return []
    sub_number = str(extra.get("sub_number") or "").strip()
    paper_standard_id = str(extra.get("paper_standard_id") or "").strip()
    with readonly_database_connection(db_path) as conn:
        paper_id = ""
        if paper_standard_id:
            row = conn.execute(
                "SELECT paper_id FROM paper_standard_catalog WHERE paper_standard_id = ?",
                (paper_standard_id,),
            ).fetchone()
            paper_id = str(row["paper_id"] or "") if row and row["paper_id"] else ""
        if not paper_id:
            year = _coerce_year(extra.get("detected_year"))
            paper_name = str(extra.get("detected_source") or "").strip()
            series = str(extra.get("paper_series") or "G").strip()
            track = str(extra.get("track") or "").strip()
            row = conn.execute(
                """
                SELECT paper_id FROM paper
                WHERE ((year = ?) OR (year IS NULL AND ? IS NULL))
                  AND paper_series = ? AND track = ? AND (paper_name = ? OR source_name = ?)
                LIMIT 1
                """,
                (year, year, series, track, paper_name, paper_name),
            ).fetchone()
            paper_id = str(row["paper_id"] or "") if row else ""
        if not paper_id:
            return []
        rows = conn.execute(
            """
            SELECT pq.question_id, pq.question_number, pq.sub_number,
                   p.year, p.paper_name, p.source_name
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.paper_id = ? AND pq.question_number = ? AND pq.sub_number = ?
            ORDER BY pq.question_id
            """,
            (paper_id, question_number, sub_number),
        ).fetchall()
    return [dict(row) for row in rows]


def find_question_content_matches(
    db_path: str | None,
    stem_tex: str,
    *,
    similarity_threshold: float = 0.88,
    max_results: int = 3,
) -> list[dict[str, Any]]:
    """Find SQLite questions with exactly equal or highly similar statements."""
    from services.question_service import normalize_question_text

    normalized = normalize_question_text(stem_tex)
    if not normalized:
        return []
    matches: list[dict[str, Any]] = []
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute("SELECT question_id, stem_tex FROM question WHERE stem_tex != ''").fetchall()
    for row in rows:
        candidate = normalize_question_text(str(row["stem_tex"] or ""))
        if not candidate:
            continue
        if candidate == normalized:
            matches.append({"question_id": str(row["question_id"]), "kind": "exact", "score": 1.0})
            continue
        score = SequenceMatcher(None, normalized, candidate, autojunk=False).ratio()
        if score >= similarity_threshold:
            matches.append({"question_id": str(row["question_id"]), "kind": "similar", "score": round(score, 4)})
    matches.sort(key=lambda item: (item["kind"] != "exact", -float(item["score"]), item["question_id"]))
    return matches[:max_results]


def next_question_id(db_path: str | None) -> str:
    """Allocate the next Q000001-style ID from the current database state."""
    pattern = re.compile(r"^Q(\d+)$")
    max_number = 0
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute("SELECT question_id FROM question WHERE question_id LIKE 'Q%'").fetchall()
    for row in rows:
        match = pattern.match(str(row[0]))
        if match:
            max_number = max(max_number, int(match.group(1)))
    return f"Q{max_number + 1:06d}"


def update_draft_review_status(
    db_path: str | None,
    draft_id: str,
    review_status: str,
    review_reason: str = "",
) -> None:
    """Update draft review status after a commit preview decision."""
    if review_status not in ALLOWED_REVIEW_STATUS:
        raise ValueError(f"unsupported review_status: {review_status}")
    with database_connection(db_path) as conn:
        draft = _get_draft_question_from_conn(conn, draft_id)
        if not draft:
            raise KeyError(f"草稿不存在：{draft_id}")
        validation = validate_draft_question(_draft_row_to_input(draft))
        if review_status in {"ready", "approved"} and validation.get("status") != "ready":
            raise ValueError("图片引用或字段校验未通过，不能标记为 ready/approved")
        conn.execute(
            """
            UPDATE question_import_draft
            SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            (review_status, review_reason, draft_id),
        )


def summarize_batch(db_path: str | None, batch_id: str) -> dict[str, Any]:
    with readonly_database_connection(db_path) as conn:
        batch = conn.execute(
            "SELECT * FROM import_batch WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        draft_rows = conn.execute(
            """
            SELECT review_status, COUNT(*)
            FROM question_import_draft
            WHERE batch_id = ?
            GROUP BY review_status
            """,
            (batch_id,),
        ).fetchall()
        report_rows = conn.execute(
            """
            SELECT status, COUNT(*)
            FROM import_report_item
            WHERE batch_id = ?
            GROUP BY status
            """,
            (batch_id,),
        ).fetchall()
        asset_count = conn.execute(
            """
            SELECT COUNT(*)
            FROM question_import_draft_asset da
            JOIN question_import_draft d ON d.draft_id = da.draft_id
            WHERE d.batch_id = ?
            """,
            (batch_id,),
        ).fetchone()[0]
    return {
        "batch": dict(batch) if batch else {},
        "draft_status_counts": {str(row[0]): int(row[1]) for row in draft_rows},
        "report_status_counts": {str(row[0]): int(row[1]) for row in report_rows},
        "draft_asset_count": int(asset_count),
    }


def list_import_report_items(
    db_path: str | None = None,
    *,
    batch_id: str = "",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List persisted batch decisions for the review workspace."""
    safe_limit = max(1, min(int(limit or 100), 500))
    clauses: list[str] = []
    params: list[Any] = []
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            f"SELECT * FROM import_report_item {where} ORDER BY created_at DESC, item_id DESC LIMIT ?",
            params + [safe_limit],
        ).fetchall()
    return [dict(row) for row in rows]


def list_import_batches(db_path: str | None = None, limit: int = 20) -> list[dict]:
    safe_limit = max(1, min(int(limit or 20), 100))
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                ib.*,
                COUNT(d.draft_id) AS draft_count
            FROM import_batch ib
            LEFT JOIN question_import_draft d ON d.batch_id = ib.batch_id
            GROUP BY ib.batch_id
            ORDER BY ib.started_at DESC, ib.batch_id DESC
            LIMIT ?
            """,
            (safe_limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_draft_questions(
    db_path: str | None = None,
    batch_id: str = "",
    review_status: str = "",
    limit: int = 50,
    offset: int = 0,
    exclude_sample: bool = False,
) -> list[dict]:
    safe_limit = max(1, min(int(limit or 50), 200))
    safe_offset = max(0, int(offset or 0))
    clauses: list[str] = []
    params: list[object] = []
    if batch_id:
        clauses.append("d.batch_id = ?")
        params.append(batch_id)
    if review_status:
        clauses.append("d.review_status = ?")
        params.append(review_status)
    if exclude_sample:
        clauses.append("d.review_status <> 'sample'")
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    params.extend([safe_limit, safe_offset])

    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            f"""
            SELECT
                d.draft_id,
                d.batch_id,
                d.source_item_id,
                d.source_label,
                d.proposed_action,
                d.target_question_id,
                d.review_status,
                d.review_reason,
                d.question_type_id,
                d.difficulty,
                d.tags_json,
                d.note,
                d.official_flag,
                substr(d.stem_tex, 1, 180) AS stem_preview,
                COUNT(da.draft_asset_id) AS asset_count
            FROM question_import_draft d
            LEFT JOIN question_import_draft_asset da ON da.draft_id = d.draft_id
            {where_sql}
            GROUP BY d.draft_id
            ORDER BY d.created_at DESC, d.draft_id
            LIMIT ? OFFSET ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def count_draft_questions(
    db_path: str | None = None,
    batch_id: str = "",
    review_status: str = "",
    exclude_sample: bool = False,
) -> int:
    clauses: list[str] = []
    params: list[object] = []
    if batch_id:
        clauses.append("batch_id = ?")
        params.append(batch_id)
    if review_status:
        clauses.append("review_status = ?")
        params.append(review_status)
    if exclude_sample:
        clauses.append("review_status <> 'sample'")
    where_sql = "WHERE " + " AND ".join(clauses) if clauses else ""
    with readonly_database_connection(db_path) as conn:
        return int(conn.execute(f"SELECT COUNT(*) FROM question_import_draft {where_sql}", params).fetchone()[0])


def draft_status_summary(db_path: str | None = None) -> dict[str, int]:
    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT review_status, COUNT(*)
            FROM question_import_draft
            GROUP BY review_status
            """
        ).fetchall()
    return dict(Counter({str(row[0]): int(row[1]) for row in rows}))


def create_manual_entry_draft(
    db_path: str | None,
    data: dict[str, Any],
    *,
    source_path: str = "streamlit/manual-entry",
    stamp: str = "",
) -> dict[str, Any]:
    """Create one manual-entry draft batch without writing formal questions."""
    final_stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    source_label = str(data.get("source_label") or data.get("source_item_id") or "手动录入草稿").strip()
    batch_id = create_import_batch(
        db_path,
        import_type="streamlit_manual_entry",
        source_path=source_path,
        mode="manual_draft",
        stamp=final_stamp,
        summary=source_label,
    )
    draft_payload = dict(data)
    draft_payload["source_label"] = source_label
    draft = normalize_draft_question(draft_payload)
    draft_id, validation = insert_draft_question(db_path, batch_id, draft, index=1)
    finish_import_batch(
        db_path,
        batch_id,
        summary=f"manual draft {draft_id} status={validation.get('status')}",
    )
    return {
        "batch_id": batch_id,
        "draft_id": draft_id,
        "validation": validation,
        "draft": get_draft_question(db_path, draft_id),
    }


def create_manual_entry_drafts(
    db_path: str | None,
    items: list[dict[str, Any]],
    *,
    source_path: str = "streamlit/manual-entry/batch",
    mode: str = "manual_drafts",
    stamp: str = "",
    summary: str = "",
) -> dict[str, Any]:
    """Create one manual-entry batch containing multiple draft questions."""
    if not items:
        raise ValueError("草稿列表不能为空")
    final_stamp = stamp or datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    batch_summary = summary or f"manual drafts {len(items)} items"
    batch_id = create_import_batch(
        db_path,
        import_type="streamlit_manual_entry",
        source_path=source_path,
        mode=mode,
        stamp=final_stamp,
        summary=batch_summary,
    )
    results: list[dict[str, Any]] = []
    status_counts: Counter[str] = Counter()
    for index, item in enumerate(items, start=1):
        draft_payload = dict(item)
        source_label = str(
            draft_payload.get("source_label")
            or draft_payload.get("source_item_id")
            or f"手动录入草稿 {index}"
        ).strip()
        draft_payload["source_label"] = source_label
        draft = normalize_draft_question(draft_payload)
        draft_id, validation = insert_draft_question(db_path, batch_id, draft, index=index)
        persisted_draft = get_draft_question(db_path, draft_id)
        status = str(persisted_draft.get("review_status") or validation.get("status") or "needs_review")
        status_counts[status] += 1
        results.append(
            {
                "index": index,
                "draft_id": draft_id,
                "validation": validation,
                "draft": persisted_draft,
            }
        )
    finish_import_batch(
        db_path,
        batch_id,
        summary=f"manual drafts {len(results)} status={dict(status_counts)}",
    )
    return {
        "batch_id": batch_id,
        "draft_count": len(results),
        "status_counts": dict(status_counts),
        "results": results,
    }


def _safe_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _safe_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if not value:
        return []
    try:
        parsed = json.loads(str(value))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _coerce_year(value: Any) -> int | None:
    if value in (None, ""):
        return None
    text = str(value).strip()
    match = re.search(r"\d{4}", text)
    if not match:
        return None
    return int(match.group(0))


def _display_order_from_number(value: Any) -> int:
    match = re.search(r"\d+", str(value or ""))
    return int(match.group(0)) if match else 0


def _draft_extra(draft: dict[str, Any]) -> dict[str, Any]:
    return _safe_json_object(draft.get("extra_json"))


def _draft_preview_question(question_id: str, draft: dict[str, Any], base: dict[str, Any] | None = None) -> dict[str, Any]:
    extra = _draft_extra(draft)
    tags = _safe_json_list(draft.get("tags_json"))
    default_topic = tags[0] if tags else ""
    question = dict(base or {})
    question.update(
        {
            "question_id": question_id,
            "question_type_id": draft.get("question_type_id"),
            "stem_tex": draft.get("stem_tex") or "",
            "choices_json": draft.get("choices_json") or "[]",
            "answer_tex": draft.get("answer_tex") or "",
            "solution_tex": draft.get("solution_tex") or "",
            "difficulty": draft.get("difficulty"),
            "tags_json": draft.get("tags_json") or "[]",
            "note": draft.get("note") or "",
            "official_flag": draft.get("official_flag") or 0,
            "raw_source_tex": draft.get("raw_source_text") or "",
            "normalized_status": "draft_committed",
            "legacy_id": question.get("legacy_id") or "",
            "legacy_file_path": question.get("legacy_file_path") or ("" if question_id == "DRAFT" else f"sqlite_committed/{question_id}.tex"),
            "usage_count": question.get("usage_count") or 0,
            "detected_year": _coerce_year(extra.get("detected_year")),
            "paper_series": extra.get("paper_series") or "G",
            "detected_source": extra.get("detected_source") or draft.get("source_label") or "",
            "detected_question_number": extra.get("detected_question_number") or "",
            "detected_topic": extra.get("detected_topic") or default_topic,
            "detected_chapter": extra.get("detected_topic") or default_topic,
        }
    )
    from services.export_service import question_to_legacy_tex

    question["canonical_tex"] = question_to_legacy_tex(question)
    return question


def draft_to_preview_question(draft: dict[str, Any], question_id: str = "DRAFT") -> dict[str, Any]:
    """Convert a draft row into a question-like payload for preview/export UI."""
    return _draft_preview_question(question_id, draft)


def _draft_row_to_input(draft: dict[str, Any]) -> DraftQuestionInput:
    return DraftQuestionInput(
        source_item_id=str(draft.get("source_item_id") or ""),
        source_label=str(draft.get("source_label") or ""),
        proposed_action=str(draft.get("proposed_action") or "insert"),
        target_question_id=str(draft.get("target_question_id") or ""),
        review_status=str(draft.get("review_status") or "needs_review"),
        review_reason=str(draft.get("review_reason") or ""),
        question_type_id=normalize_question_type_id(draft.get("question_type_id")),
        stem_tex=str(draft.get("stem_tex") or ""),
        choices=_safe_json_list(draft.get("choices_json")),
        answer_tex=str(draft.get("answer_tex") or ""),
        solution_tex=str(draft.get("solution_tex") or ""),
        difficulty=coerce_int(draft.get("difficulty")),
        tags=_safe_json_list(draft.get("tags_json")),
        note=str(draft.get("note") or ""),
        official_flag=coerce_bool(draft.get("official_flag")),
        raw_source_text=str(draft.get("raw_source_text") or ""),
        normalized_tex=str(draft.get("normalized_tex") or ""),
        confidence=_safe_json_object(draft.get("confidence_json")),
        validation=_safe_json_object(draft.get("validation_json")),
        extra=_safe_json_object(draft.get("extra_json")),
        assets=[
            DraftAssetInput(
                role=str(asset.get("role") or "problem"),
                source_path=str(asset.get("source_path") or ""),
                planned_file_path=str(asset.get("planned_file_path") or ""),
                original_file_name=str(asset.get("original_file_name") or ""),
                caption=str(asset.get("caption") or ""),
                sort_order=coerce_int(asset.get("sort_order")) or 0,
                note=str(asset.get("note") or ""),
                extra=_safe_json_object(asset.get("extra_json")),
            )
            for asset in draft.get("assets", []) or []
        ],
    )


def _normalize_draft_update_field(field: str, value: Any) -> tuple[str, Any]:
    column = DRAFT_UPDATE_ALIASES.get(field, field)
    if column not in DRAFT_EDITABLE_COLUMNS:
        raise ValueError(f"不支持修改草稿字段：{field}")
    if column in {
        "source_item_id",
        "source_label",
        "stem_tex",
        "answer_tex",
        "solution_tex",
        "note",
        "raw_source_text",
    }:
        return column, str(value or "").strip()
    if column == "target_question_id":
        text = str(value or "").strip()
        return column, text or None
    if column == "proposed_action":
        action = str(value or "insert").strip()
        if action not in ALLOWED_PROPOSED_ACTIONS:
            raise ValueError(f"不支持 proposed_action：{action}")
        return column, action
    if column == "question_type_id":
        return column, normalize_question_type_id(value)
    if column == "difficulty":
        return column, coerce_int(value)
    if column == "official_flag":
        return column, 1 if coerce_bool(value) else 0
    if column in {"choices_json", "tags_json"}:
        return column, compact_json(parse_json_list(value))
    if column == "extra_json":
        return column, compact_json(parse_json_object(value))
    return column, value


def _ensure_draft_editable_from_conn(conn, draft_id: str) -> dict[str, Any]:
    draft = _get_draft_question_from_conn(conn, draft_id)
    if not draft:
        raise KeyError(f"草稿不存在：{draft_id}")
    if str(draft.get("review_status") or "") == "committed":
        raise ValueError("已入库草稿不能继续修改")
    return draft


def _review_status_after_draft_edit(draft: dict[str, Any], validation: dict[str, Any]) -> tuple[str, str]:
    current_status = str(draft.get("review_status") or "needs_review")
    current_reason = str(draft.get("review_reason") or "")
    errors = validation.get("errors") or []
    warnings = validation.get("warnings") or []
    if errors:
        return "blocked", "；".join(str(item) for item in errors)
    if current_status in {"blocked", "rejected"}:
        return "needs_review", "；".join(str(item) for item in warnings)
    if current_status in {"ready", "approved"} and warnings:
        return "needs_review", "；".join(str(item) for item in warnings)
    if warnings and not current_reason:
        return current_status, "；".join(str(item) for item in warnings)
    return current_status, current_reason


def update_draft_question_fields(
    db_path: str | None,
    draft_id: str,
    updates: dict[str, Any],
    *,
    operator: str = "streamlit_ui",
) -> dict[str, Any]:
    """Update editable fields on one uncommitted draft and refresh validation/preview TeX."""
    safe_draft_id = str(draft_id or "").strip()
    if not safe_draft_id:
        raise ValueError("draft_id 不能为空")
    if not updates:
        return {"draft_id": safe_draft_id, "changed_fields": [], "validation": {}, "draft": {}}

    normalized_updates = dict(_normalize_draft_update_field(field, value) for field, value in updates.items())
    with existing_database_connection(db_path) as conn:
        draft = _ensure_draft_editable_from_conn(conn, safe_draft_id)

        candidate = dict(draft)
        candidate.update(normalized_updates)
        if candidate.get("proposed_action") == "update" and candidate.get("target_question_id"):
            target_exists = conn.execute(
                "SELECT 1 FROM question WHERE question_id = ?",
                (candidate.get("target_question_id"),),
            ).fetchone()
            if not target_exists:
                candidate["target_question_id"] = None

        validation = validate_draft_question(_draft_row_to_input(candidate))
        if candidate.get("proposed_action") == "update" and normalized_updates.get("target_question_id") and not candidate.get("target_question_id"):
            validation["errors"].append(f"target_question_id 不存在：{normalized_updates.get('target_question_id')}")
            validation["status"] = "blocked"

        preview_question = _draft_preview_question("DRAFT", candidate)
        candidate["normalized_tex"] = preview_question.get("canonical_tex") or ""
        validation_json = _safe_json_object(candidate.get("validation_json"))
        validation_json["draft_validation"] = validation
        validation_json["last_manual_update"] = {
            "operator": operator,
            "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        candidate["validation_json"] = compact_json(validation_json)
        candidate["review_status"], candidate["review_reason"] = _review_status_after_draft_edit(candidate, validation)

        update_columns = sorted(
            set(normalized_updates)
            | {"normalized_tex", "validation_json", "review_status", "review_reason"}
        )
        changed_fields = [column for column in update_columns if draft.get(column) != candidate.get(column)]
        if changed_fields:
            assignments = ", ".join(f"{column} = ?" for column in update_columns)
            conn.execute(
                f"""
                UPDATE question_import_draft
                SET {assignments}, updated_at = CURRENT_TIMESTAMP
                WHERE draft_id = ?
                """,
                [candidate.get(column) for column in update_columns] + [safe_draft_id],
            )
        return {
            "draft_id": safe_draft_id,
            "changed_fields": changed_fields,
            "validation": validation,
            "draft": _get_draft_question_from_conn(conn, safe_draft_id),
        }


def _resolve_draft_asset_source(path_text: str) -> Path:
    source = Path(str(path_text or "").strip())
    return source if source.is_absolute() else PROJECT_ROOT / source


def _draft_asset_file_hash(path_text: str) -> str:
    source = _resolve_draft_asset_source(path_text)
    if not source.exists() or not source.is_file():
        return ""
    digest = hashlib.sha256()
    with source.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalize_draft_asset_payload(data: dict[str, Any], default_sort_order: int = 1) -> dict[str, Any]:
    role = str(data.get("role") or "problem").strip() or "problem"
    if role not in VALID_DRAFT_ASSET_ROLES:
        raise ValueError(f"不支持草稿资源 role：{role}")
    source_path = str(data.get("source_path") or data.get("path") or "").strip()
    if not source_path:
        raise ValueError("草稿资源路径不能为空")
    source = Path(source_path)
    review_status = str(data.get("review_status") or "needs_review").strip()
    if review_status not in ALLOWED_REVIEW_STATUS:
        raise ValueError(f"不支持资源 review_status：{review_status}")
    return {
        "role": role,
        "source_path": source_path,
        "planned_file_path": str(data.get("planned_file_path") or "").strip(),
        "original_file_name": str(data.get("original_file_name") or source.name).strip(),
        "mime_type": mimetypes.guess_type(source.name)[0] or "",
        "file_hash": _draft_asset_file_hash(source_path),
        "caption": str(data.get("caption") or "").strip(),
        "sort_order": coerce_int(data.get("sort_order")) or default_sort_order,
        "review_status": review_status,
        "note": str(data.get("note") or "").strip(),
        "extra_json": compact_json(parse_json_object(data.get("extra") or data.get("extra_json"))),
    }


def _get_draft_asset_from_conn(conn, draft_asset_id: str) -> dict[str, Any]:
    return row_to_dict(
        conn.execute(
            "SELECT * FROM question_import_draft_asset WHERE draft_asset_id = ?",
            (draft_asset_id,),
        ).fetchone()
    )


def add_draft_asset(
    db_path: str | None,
    draft_id: str,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Append one asset reference to an uncommitted draft."""
    safe_draft_id = str(draft_id or "").strip()
    if not safe_draft_id:
        raise ValueError("draft_id 不能为空")
    with existing_database_connection(db_path) as conn:
        _ensure_draft_editable_from_conn(conn, safe_draft_id)
        next_sort_order = int(
            conn.execute(
                "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM question_import_draft_asset WHERE draft_id = ?",
                (safe_draft_id,),
            ).fetchone()[0]
            or 1
        )
        payload = _normalize_draft_asset_payload(data, default_sort_order=next_sort_order)
        asset_input = DraftAssetInput(
            role=payload["role"],
            source_path=payload["source_path"],
            planned_file_path=payload["planned_file_path"],
            original_file_name=payload["original_file_name"],
            caption=payload["caption"],
            sort_order=payload["sort_order"],
            note=payload["note"],
            extra=parse_json_object(payload["extra_json"]),
        )
        draft_asset_id = make_draft_asset_id(safe_draft_id, int(payload["sort_order"]), asset_input)
        while _get_draft_asset_from_conn(conn, draft_asset_id):
            payload["sort_order"] = int(payload["sort_order"]) + 1
            asset_input = DraftAssetInput(
                role=payload["role"],
                source_path=payload["source_path"],
                planned_file_path=payload["planned_file_path"],
                original_file_name=payload["original_file_name"],
                caption=payload["caption"],
                sort_order=payload["sort_order"],
                note=payload["note"],
                extra=parse_json_object(payload["extra_json"]),
            )
            draft_asset_id = make_draft_asset_id(safe_draft_id, int(payload["sort_order"]), asset_input)
        conn.execute(
            """
            INSERT INTO question_import_draft_asset(
                draft_asset_id, draft_id, role, source_path, planned_file_path,
                original_file_name, mime_type, file_hash, caption, sort_order,
                review_status, note, extra_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                draft_asset_id,
                safe_draft_id,
                payload["role"],
                payload["source_path"],
                payload["planned_file_path"],
                payload["original_file_name"],
                payload["mime_type"],
                payload["file_hash"],
                payload["caption"],
                payload["sort_order"],
                payload["review_status"],
                payload["note"],
                payload["extra_json"],
            ),
        )
        conn.execute("UPDATE question_import_draft SET updated_at = CURRENT_TIMESTAMP WHERE draft_id = ?", (safe_draft_id,))
        return {
            "draft_id": safe_draft_id,
            "draft_asset_id": draft_asset_id,
            "asset": _get_draft_asset_from_conn(conn, draft_asset_id),
        }


def update_draft_asset_fields(
    db_path: str | None,
    draft_asset_id: str,
    updates: dict[str, Any],
) -> dict[str, Any]:
    """Update one draft asset reference before the draft is committed."""
    safe_asset_id = str(draft_asset_id or "").strip()
    if not safe_asset_id:
        raise ValueError("draft_asset_id 不能为空")
    normalized_updates = {}
    for field, value in updates.items():
        if field not in DRAFT_ASSET_EDITABLE_COLUMNS:
            raise ValueError(f"不支持修改草稿资源字段：{field}")
        if field == "role":
            role = str(value or "problem").strip() or "problem"
            if role not in VALID_DRAFT_ASSET_ROLES:
                raise ValueError(f"不支持草稿资源 role：{role}")
            normalized_updates[field] = role
        elif field == "source_path":
            source_path = str(value or "").strip()
            if not source_path:
                raise ValueError("草稿资源路径不能为空")
            normalized_updates[field] = source_path
            normalized_updates["mime_type"] = mimetypes.guess_type(Path(source_path).name)[0] or ""
            normalized_updates["file_hash"] = _draft_asset_file_hash(source_path)
        elif field == "sort_order":
            normalized_updates[field] = coerce_int(value) or 1
        elif field == "review_status":
            review_status = str(value or "needs_review").strip()
            if review_status not in ALLOWED_REVIEW_STATUS:
                raise ValueError(f"不支持资源 review_status：{review_status}")
            normalized_updates[field] = review_status
        elif field == "extra_json":
            normalized_updates[field] = compact_json(parse_json_object(value))
        else:
            normalized_updates[field] = str(value or "").strip()
    if "source_path" in normalized_updates and "original_file_name" not in normalized_updates:
        normalized_updates["original_file_name"] = Path(normalized_updates["source_path"]).name

    with existing_database_connection(db_path) as conn:
        asset = _get_draft_asset_from_conn(conn, safe_asset_id)
        if not asset:
            raise KeyError(f"草稿资源不存在：{safe_asset_id}")
        _ensure_draft_editable_from_conn(conn, str(asset.get("draft_id") or ""))
        changed_fields = [field for field, value in normalized_updates.items() if asset.get(field) != value]
        if changed_fields:
            assignments = ", ".join(f"{field} = ?" for field in sorted(normalized_updates))
            conn.execute(
                f"""
                UPDATE question_import_draft_asset
                SET {assignments}
                WHERE draft_asset_id = ?
                """,
                [normalized_updates[field] for field in sorted(normalized_updates)] + [safe_asset_id],
            )
            conn.execute(
                "UPDATE question_import_draft SET updated_at = CURRENT_TIMESTAMP WHERE draft_id = ?",
                (asset.get("draft_id"),),
            )
        return {
            "draft_id": str(asset.get("draft_id") or ""),
            "draft_asset_id": safe_asset_id,
            "changed_fields": changed_fields,
            "asset": _get_draft_asset_from_conn(conn, safe_asset_id),
        }


def delete_draft_asset(db_path: str | None, draft_asset_id: str) -> dict[str, Any]:
    """Remove one draft asset reference. The source file itself is not deleted."""
    safe_asset_id = str(draft_asset_id or "").strip()
    if not safe_asset_id:
        raise ValueError("draft_asset_id 不能为空")
    with existing_database_connection(db_path) as conn:
        asset = _get_draft_asset_from_conn(conn, safe_asset_id)
        if not asset:
            raise KeyError(f"草稿资源不存在：{safe_asset_id}")
        _ensure_draft_editable_from_conn(conn, str(asset.get("draft_id") or ""))
        conn.execute("DELETE FROM question_import_draft_asset WHERE draft_asset_id = ?", (safe_asset_id,))
        conn.execute(
            "UPDATE question_import_draft SET updated_at = CURRENT_TIMESTAMP WHERE draft_id = ?",
            (asset.get("draft_id"),),
        )
        return {
            "draft_id": str(asset.get("draft_id") or ""),
            "draft_asset_id": safe_asset_id,
            "deleted": True,
            "source_path": asset.get("source_path") or "",
        }


def _question_snapshot_from_conn(conn, question_id: str) -> dict[str, Any]:
    return row_to_dict(conn.execute("SELECT * FROM question WHERE question_id = ?", (question_id,)).fetchone())


def _next_question_id_from_conn(conn) -> str:
    max_number = 0
    for row in conn.execute("SELECT question_id FROM question WHERE question_id LIKE 'Q%'").fetchall():
        value = str(row[0])
        if value.startswith("Q") and value[1:].isdigit():
            max_number = max(max_number, int(value[1:]))
    return f"Q{max_number + 1:06d}"


def _insert_question_from_draft_conn(conn, question: dict[str, Any]) -> None:
    conn.execute(
        """
        INSERT INTO question(
            question_id, question_type_id, stem_tex, choices_json, answer_tex,
            solution_tex, difficulty, tags_json, note, official_flag,
            canonical_tex, raw_source_tex, normalized_status, legacy_id,
            legacy_file_path, usage_count
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            question["question_id"],
            question.get("question_type_id"),
            question.get("stem_tex") or "",
            question.get("choices_json") or "[]",
            question.get("answer_tex") or "",
            question.get("solution_tex") or "",
            question.get("difficulty"),
            question.get("tags_json") or "[]",
            question.get("note") or "",
            question.get("official_flag") or 0,
            question.get("canonical_tex") or "",
            question.get("raw_source_tex") or "",
            question.get("normalized_status") or "draft_committed",
            question.get("legacy_id") or "",
            question.get("legacy_file_path") or "",
            question.get("usage_count") or 0,
        ),
    )
    conn.execute("INSERT OR IGNORE INTO question_analysis(question_id) VALUES (?)", (question["question_id"],))


def _update_question_from_draft_conn(conn, question_id: str, draft: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    before = _question_snapshot_from_conn(conn, question_id)
    if not before:
        raise KeyError(f"目标题目不存在：{question_id}")
    after = _draft_preview_question(question_id, draft, base=before)
    conn.execute(
        """
        UPDATE question
        SET
            question_type_id = ?,
            stem_tex = ?,
            choices_json = ?,
            answer_tex = ?,
            solution_tex = ?,
            difficulty = ?,
            tags_json = ?,
            note = ?,
            official_flag = ?,
            canonical_tex = ?,
            raw_source_tex = ?,
            normalized_status = ?,
            updated_at = CURRENT_TIMESTAMP,
            last_manual_edit_at = CURRENT_TIMESTAMP
        WHERE question_id = ?
        """,
        (
            after.get("question_type_id"),
            after.get("stem_tex") or "",
            after.get("choices_json") or "[]",
            after.get("answer_tex") or "",
            after.get("solution_tex") or "",
            after.get("difficulty"),
            after.get("tags_json") or "[]",
            after.get("note") or "",
            after.get("official_flag") or 0,
            after.get("canonical_tex") or "",
            after.get("raw_source_tex") or "",
            "draft_committed",
            question_id,
        ),
    )
    return before, _question_snapshot_from_conn(conn, question_id)


def _upsert_legacy_map_from_draft_conn(conn, question_id: str, question: dict[str, Any], draft: dict[str, Any]) -> str:
    extra = _draft_extra(draft)
    legacy_file_path = str(question.get("legacy_file_path") or "").strip() or f"sqlite_committed/{question_id}.tex"
    content_hash = hashlib.sha256(str(question.get("canonical_tex") or "").encode("utf-8")).hexdigest()
    conn.execute(
        """
        INSERT INTO legacy_question_map(
            question_id, legacy_id, legacy_file_path, content_hash,
            detected_chapter, detected_year, detected_source,
            detected_question_number, detected_topic, scan_status, scan_note
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(question_id) DO UPDATE SET
            legacy_id = excluded.legacy_id,
            legacy_file_path = excluded.legacy_file_path,
            content_hash = excluded.content_hash,
            detected_chapter = excluded.detected_chapter,
            detected_year = excluded.detected_year,
            detected_source = excluded.detected_source,
            detected_question_number = excluded.detected_question_number,
            detected_topic = excluded.detected_topic,
            scan_status = excluded.scan_status,
            scan_note = excluded.scan_note,
            updated_at = CURRENT_TIMESTAMP
        """,
        (
            question_id,
            question.get("legacy_id") or question_id,
            legacy_file_path,
            content_hash,
            extra.get("detected_topic") or question.get("detected_chapter") or "",
            _coerce_year(extra.get("detected_year") or question.get("detected_year")),
            extra.get("detected_source") or question.get("detected_source") or draft.get("source_label") or "",
            extra.get("detected_question_number") or question.get("detected_question_number") or "",
            extra.get("detected_topic") or question.get("detected_topic") or "",
            "sqlite_committed",
            f"draft_id={draft.get('draft_id') or ''}",
        ),
    )
    return legacy_file_path


def _upsert_paper_link_from_draft_conn(conn, question_id: str, draft: dict[str, Any]) -> str:
    extra = _draft_extra(draft)
    if extra.get("source_kind") != "试卷":
        return ""
    standard_paper = None
    standard_id = str(extra.get("paper_standard_id") or "").strip()
    if standard_id:
        try:
            standard_paper = conn.execute(
                """
                SELECT paper_standard_id, paper_id, year, paper_series, track, paper_name, source_name
                FROM paper_standard_catalog
                WHERE paper_standard_id = ? AND status IN ('confirmed', 'active')
                """,
                (standard_id,),
            ).fetchone()
        except Exception:
            standard_paper = None

    paper_name = str(
        (standard_paper["paper_name"] if standard_paper else None)
        or extra.get("detected_source")
        or draft.get("source_label")
        or ""
    ).strip()
    if not paper_name:
        return ""
    year = _coerce_year(standard_paper["year"] if standard_paper else extra.get("detected_year"))
    paper_series = str(
        (standard_paper["paper_series"] if standard_paper else None)
        or extra.get("paper_series")
        or "G"
    ).strip()
    track = str((standard_paper["track"] if standard_paper else None) or extra.get("track") or "").strip()
    question_number = str(extra.get("detected_question_number") or "").strip()
    sub_number = str(extra.get("sub_number") or "").strip()
    linked_paper_id = str(standard_paper["paper_id"] if standard_paper else "").strip()
    if linked_paper_id:
        final_paper_id = linked_paper_id
    else:
        paper_id = stable_id("P", year or "", paper_series, track, paper_name)
        conn.execute(
            """
            INSERT INTO paper(paper_id, year, paper_series, track, paper_name, source_name, description)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(year, paper_series, track, paper_name) DO UPDATE SET
                source_name = CASE WHEN excluded.source_name != '' THEN excluded.source_name ELSE paper.source_name END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (paper_id, year, paper_series, track, paper_name, paper_name, "streamlit 草稿提交自动关联"),
        )
        row = conn.execute(
            """
            SELECT paper_id
            FROM paper
            WHERE
                ((year = ?) OR (year IS NULL AND ? IS NULL))
                AND paper_series = ?
                AND track = ?
                AND paper_name = ?
            """,
            (year, year, paper_series, track, paper_name),
        ).fetchone()
        final_paper_id = str(row["paper_id"] if row else paper_id)
        if standard_id:
            conn.execute(
                """
                UPDATE paper_standard_catalog
                SET paper_id = ?, updated_at = CURRENT_TIMESTAMP
                WHERE paper_standard_id = ? AND paper_id IS NULL
                """,
                (final_paper_id, standard_id),
            )
    paper_question_id = stable_id("PQ", final_paper_id, question_id, question_number, sub_number)
    conn.execute(
        """
        INSERT OR IGNORE INTO paper_question(
            paper_question_id, paper_id, question_id, question_number,
            sub_number, display_order, origin_tex, location_tex
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            paper_question_id,
            final_paper_id,
            question_id,
            question_number,
            sub_number,
            _display_order_from_number(question_number),
            draft.get("normalized_tex") or "",
            "",
        ),
    )
    return paper_question_id


def _copy_draft_assets_to_question_conn(
    conn,
    draft: dict[str, Any],
    question_id: str,
    *,
    copy_files: bool = True,
    created_paths: list[Path] | None = None,
) -> dict[str, Any]:
    from services.asset_service import _image_dimensions, _stored_path, copy_asset_to_question_dir, file_hash, make_asset_id

    inserted = []
    skipped = []
    for index, asset in enumerate(draft.get("assets") or [], start=1):
        source_text = str(asset.get("planned_file_path") or asset.get("source_path") or "").strip()
        if not source_text:
            skipped.append({"source_path": "", "reason": "empty_path"})
            continue
        source = Path(source_text)
        if not source.is_absolute():
            source = PROJECT_ROOT / source
        if not source.exists() or not source.is_file():
            skipped.append({"source_path": source_text, "reason": "file_missing"})
            continue
        role = str(asset.get("role") or "problem").strip() or "problem"
        asset_extra = asset.get("extra") if isinstance(asset.get("extra"), dict) else {}
        target_stem = str(asset.get("alias") or asset_extra.get("alias") or "").strip() or None
        target = copy_asset_to_question_dir(question_id, source, role, target_stem=target_stem) if copy_files else source
        if copy_files and target != source and target.exists() and created_paths is not None:
            created_paths.append(target)
        mime_type = mimetypes.guess_type(target.name)[0] or str(asset.get("mime_type") or "")
        width, height = _image_dimensions(target) if mime_type.startswith("image/") else (None, None)
        asset_id = make_asset_id(question_id, role, target)
        conn.execute(
            """
            INSERT OR REPLACE INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name,
                mime_type, width, height, file_hash, caption, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                question_id,
                role,
                _stored_path(target),
                asset.get("original_file_name") or source.name,
                mime_type,
                width,
                height,
                file_hash(target),
                asset.get("caption") or "",
                int(asset.get("sort_order") or index),
            ),
        )
        inserted.append({"asset_id": asset_id, "file_path": _stored_path(target), "role": role})
    return {"inserted": inserted, "skipped": skipped}


def _upsert_book_link_from_draft_conn(conn, question_id: str, draft: dict[str, Any]) -> str:
    """Persist教材 metadata captured by manual, same-book, or PDF entry."""
    extra = _draft_extra(draft)
    if extra.get("source_kind") != "教材":
        return ""
    title = str(extra.get("book_title") or draft.get("source_label") or extra.get("detected_source") or "").strip()
    if not title:
        return ""
    publisher = str(extra.get("book_publisher") or "").strip()
    edition = str(extra.get("book_edition") or "").strip()
    grade = str(extra.get("book_grade") or "").strip()
    volume = str(extra.get("book_volume") or extra.get("year_or_volume") or "").strip()
    curriculum = str(extra.get("book_curriculum_version") or "").strip()
    book = conn.execute(
        """
        SELECT book_id FROM book
        WHERE title = ? AND publisher = ? AND edition = ? AND grade = ?
          AND volume = ? AND curriculum_version = ?
        """,
        (title, publisher, edition, grade, volume, curriculum),
    ).fetchone()
    if book:
        book_id = str(book["book_id"])
    else:
        book_id = stable_id("B", title, publisher, edition, grade, volume, curriculum)
        conn.execute(
            """
            INSERT INTO book(book_id, title, publisher, edition, grade, volume, curriculum_version, description)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (book_id, title, publisher, edition, grade, volume, curriculum, str(extra.get("book_description") or "")),
        )
    section_title = str(extra.get("book_column_name") or extra.get("book_section_title") or "").strip()
    section_id = ""
    if section_title:
        section = conn.execute(
            "SELECT section_id FROM book_section WHERE book_id = ? AND title = ? AND parent_section_id IS NULL",
            (book_id, section_title),
        ).fetchone()
        if section:
            section_id = str(section["section_id"])
        else:
            section_id = stable_id("BS", book_id, "", section_title)
            conn.execute(
                "INSERT INTO book_section(section_id, book_id, title, section_level, sort_order) VALUES (?, ?, ?, 1, 0)",
                (section_id, book_id, section_title),
            )
    page_number = coerce_int(extra.get("book_page_number"))
    exercise_number = str(extra.get("book_exercise_number") or extra.get("detected_question_number") or "").strip()
    sub_number = str(extra.get("sub_number") or "").strip()
    column_name = section_title
    existing = conn.execute(
        """
        SELECT book_exercise_question_id FROM book_exercise_question
        WHERE book_id = ? AND question_id = ? AND ((section_id = ?) OR (section_id IS NULL AND ? = ''))
          AND ((page_number = ?) OR (page_number IS NULL AND ? IS NULL))
          AND column_name = ? AND exercise_number = ? AND sub_number = ?
        """,
        (book_id, question_id, section_id or None, section_id, page_number, page_number, column_name, exercise_number, sub_number),
    ).fetchone()
    link_id = str(existing["book_exercise_question_id"]) if existing else stable_id(
        "BEQ", book_id, section_id, question_id, page_number or "", column_name, exercise_number, sub_number
    )
    conn.execute(
        """
        INSERT INTO book_exercise_question(
            book_exercise_question_id, book_id, section_id, question_id, page_number,
            column_name, exercise_number, sub_number, display_order, source_note
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(book_exercise_question_id) DO UPDATE SET
            section_id = excluded.section_id, page_number = excluded.page_number,
            column_name = excluded.column_name, exercise_number = excluded.exercise_number,
            sub_number = excluded.sub_number, display_order = excluded.display_order,
            source_note = excluded.source_note, updated_at = CURRENT_TIMESTAMP
        """,
        (link_id, book_id, section_id or None, question_id, page_number, column_name, exercise_number, sub_number,
         _display_order_from_number(exercise_number), str(extra.get("book_source_note") or "")),
    )
    return link_id


def _upsert_topic_link_from_draft_conn(conn, question_id: str, draft: dict[str, Any]) -> str:
    """Persist专题 metadata captured by manual or document entry."""
    extra = _draft_extra(draft)
    if extra.get("source_kind") != "专题":
        return ""
    topic_name = str(extra.get("topic_name") or extra.get("detected_source") or draft.get("source_label") or "").strip()
    if not topic_name:
        return ""
    module_name = str(extra.get("topic_module") or "未分类专题").strip() or "未分类专题"
    module_id = stable_id("TM", module_name)
    conn.execute(
        "INSERT INTO topic_module(module_id, name) VALUES (?, ?) ON CONFLICT(name) DO NOTHING",
        (module_id, module_name),
    )
    topic_id = stable_id("T", module_id, topic_name)
    conn.execute(
        """
        INSERT INTO topic(topic_id, module_id, name, file_name, description, extra_json)
        VALUES (?, ?, ?, ?, ?, ?)
        ON CONFLICT(module_id, name) DO UPDATE SET updated_at = CURRENT_TIMESTAMP
        """,
        (topic_id, module_id, topic_name, str(extra.get("topic_file_name") or ""), str(extra.get("topic_description") or ""), "{}"),
    )
    row = conn.execute(
        "SELECT topic_id FROM topic WHERE module_id = ? AND name = ?",
        (module_id, topic_name),
    ).fetchone()
    topic_id = str(row["topic_id"] if row else topic_id)
    group_name = str(extra.get("topic_group") or "").strip()
    existing = conn.execute(
        "SELECT topic_question_id FROM topic_question WHERE topic_id = ? AND question_id = ? AND group_name = ?",
        (topic_id, question_id, group_name),
    ).fetchone()
    link_id = str(existing["topic_question_id"]) if existing else stable_id("TQ", topic_id, question_id, group_name)
    if existing:
        conn.execute(
            "UPDATE topic_question SET topic_note = ?, updated_at = CURRENT_TIMESTAMP WHERE topic_question_id = ?",
            (str(extra.get("topic_note") or draft.get("note") or ""), link_id),
        )
    else:
        next_order = int(conn.execute(
            "SELECT COALESCE(MAX(sort_order), 0) + 1 FROM topic_question WHERE topic_id = ? AND group_name = ?",
            (topic_id, group_name),
        ).fetchone()[0] or 1)
        conn.execute(
            """
            INSERT INTO topic_question(topic_question_id, topic_id, question_id, group_name, sort_order, topic_note)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (link_id, topic_id, question_id, group_name, next_order, str(extra.get("topic_note") or draft.get("note") or "")),
        )
    return link_id


def _link_draft_to_existing_question_conn(conn, draft: dict[str, Any], question_id: str, *, operator: str, report_index: int) -> dict[str, Any]:
    """Reuse an existing question and attach this draft's source relation."""
    safe_question_id = str(question_id or "").strip()
    if not conn.execute("SELECT 1 FROM question WHERE question_id = ?", (safe_question_id,)).fetchone():
        raise ValueError(f"待复用题目不存在：{safe_question_id}")
    before = _question_snapshot_from_conn(conn, safe_question_id)
    paper_link_id = _upsert_paper_link_from_draft_conn(conn, safe_question_id, draft)
    book_link_id = _upsert_book_link_from_draft_conn(conn, safe_question_id, draft)
    topic_link_id = _upsert_topic_link_from_draft_conn(conn, safe_question_id, draft)
    after = _question_snapshot_from_conn(conn, safe_question_id)
    revision_id = insert_question_revision_from_conn(
        conn,
        question_id=safe_question_id,
        change_source="source_relation_edit",
        before={"question": before},
        after={"question": after, "paper_link_id": paper_link_id, "book_link_id": book_link_id, "topic_link_id": topic_link_id},
        operator=operator,
        note=f"复用已有题目，draft_id={draft.get('draft_id') or ''}",
        changed_field_names=[field for field, value in {"paper_link_id": paper_link_id, "book_link_id": book_link_id, "topic_link_id": topic_link_id}.items() if value],
    )
    conn.execute(
        "UPDATE question_import_draft SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP WHERE draft_id = ?",
        ("committed", f"已复用已有题目：{safe_question_id}", str(draft.get("draft_id") or "")),
    )
    report_id = _insert_report_item_from_conn(
        conn,
        str(draft.get("batch_id") or ""),
        report_index,
        str(draft.get("draft_id") or ""),
        safe_question_id,
        "linked",
        f"复用已有题目 {safe_question_id}",
        compact_json({"draft_id": draft.get("draft_id"), "question_id": safe_question_id, "paper_link_id": paper_link_id, "book_link_id": book_link_id, "topic_link_id": topic_link_id}),
    )
    return {"draft_id": draft.get("draft_id"), "status": "linked", "question_id": safe_question_id, "revision_id": revision_id, "report_id": report_id, "source_link_id": paper_link_id, "book_link_id": book_link_id, "topic_link_id": topic_link_id}


def link_draft_to_existing_question(
    db_path: str | None,
    draft_id: str,
    existing_question_id: str,
    *,
    operator: str = "streamlit_batch_link_existing",
) -> dict[str, Any]:
    """Attach an uncommitted draft's source relation to an existing question."""
    safe_draft_id = str(draft_id or "").strip()
    safe_question_id = str(existing_question_id or "").strip()
    if not safe_draft_id or not safe_question_id:
        raise ValueError("draft_id and existing_question_id are required")
    with existing_database_connection(db_path) as conn:
        draft = _get_draft_question_from_conn(conn, safe_draft_id)
        if not draft:
            raise KeyError(f"draft not found: {safe_draft_id}")
        if str(draft.get("review_status") or "") == "committed":
            raise ValueError("draft has already been processed")
        with conn:
            return _link_draft_to_existing_question_conn(
                conn, draft, safe_question_id, operator=operator, report_index=1
            )


def record_draft_review_event(
    db_path: str | None,
    draft_id: str,
    *,
    status: str,
    reason: str = "",
    operator: str = "streamlit_batch_review",
    existing_question_id: str = "",
) -> dict[str, Any]:
    """Persist a review decision in both the draft and the import report."""
    safe_draft_id = str(draft_id or "").strip()
    if not safe_draft_id:
        raise ValueError("draft_id is required")
    with existing_database_connection(db_path) as conn:
        draft = _get_draft_question_from_conn(conn, safe_draft_id)
        if not draft:
            raise KeyError(f"draft not found: {safe_draft_id}")
        with conn:
            conn.execute(
                """
                UPDATE question_import_draft
                SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE draft_id = ?
                """,
                (status, reason, safe_draft_id),
            )
            report_status = "linked" if status == "linked" else "skipped" if status == "rejected" else status
            report_id = _insert_report_item_from_conn(
                conn,
                str(draft.get("batch_id") or ""),
                1,
                safe_draft_id,
                str(existing_question_id or "") or None,
                report_status,
                reason or status,
                compact_json({
                    "draft_id": safe_draft_id,
                    "operator": operator,
                    "status": status,
                    "reason": reason,
                    "existing_question_id": str(existing_question_id or ""),
                    "reviewed_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }),
            )
        return {"draft_id": safe_draft_id, "status": status, "report_id": report_id}


def _insert_report_item_from_conn(
    conn,
    batch_id: str,
    index: int,
    source_file: str,
    question_id: str | None,
    status: str,
    reason: str,
    detail: str,
) -> str:
    item_id = stable_id("IRI", batch_id, index, source_file, status, reason)
    safe_question_id = question_id
    if safe_question_id:
        exists = conn.execute("SELECT 1 FROM question WHERE question_id = ?", (safe_question_id,)).fetchone()
        if not exists:
            safe_question_id = None
    conn.execute(
        """
        INSERT OR REPLACE INTO import_report_item(
            item_id, batch_id, source_file, question_id, status, reason, detail
        )
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (item_id, batch_id, source_file, safe_question_id, status, reason, detail),
    )
    return item_id


def commit_draft_to_question(
    db_path: str | None,
    draft_id: str,
    *,
    operator: str = "streamlit_ui",
    require_ready: bool = True,
    copy_assets: bool = True,
) -> dict[str, Any]:
    """Commit one ready/approved draft into the formal question tables."""
    safe_draft_id = str(draft_id or "").strip()
    if not safe_draft_id:
        raise ValueError("draft_id 不能为空")

    with existing_database_connection(db_path) as conn:
        draft = _get_draft_question_from_conn(conn, safe_draft_id)
        if not draft:
            raise KeyError(f"草稿不存在：{safe_draft_id}")
        review_status = str(draft.get("review_status") or "")
        if require_ready and review_status not in {"ready", "approved"}:
            raise ValueError(f"草稿状态必须是 ready/approved，当前为：{review_status}")
        validation = validate_draft_question(_draft_row_to_input(draft))
        if require_ready and validation.get("status") != "ready":
            detail_parts = []
            detail_parts.extend(str(item) for item in validation.get("errors") or [])
            detail_parts.extend(str(item) for item in validation.get("warnings") or [])
            raise ValueError("草稿图片引用/字段校验未通过：" + "；".join(detail_parts or ["未知原因"]))
        if validation.get("errors"):
            raise ValueError("草稿字段校验未通过：" + "；".join(str(item) for item in validation["errors"]))

        proposed_action = str(draft.get("proposed_action") or "insert").strip()
        if proposed_action == "skip":
            with conn:
                conn.execute(
                    """
                    UPDATE question_import_draft
                    SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
                    WHERE draft_id = ?
                    """,
                    ("rejected", "用户确认跳过", safe_draft_id),
                )
                report_id = _insert_report_item_from_conn(
                    conn,
                    str(draft.get("batch_id") or ""),
                    1,
                    safe_draft_id,
                    None,
                    "skipped",
                    "用户确认跳过",
                    compact_json({"draft_id": safe_draft_id, "status": "skipped"}),
                )
            return {
                "draft_id": safe_draft_id,
                "status": "skipped",
                "question_id": "",
                "revision_id": "",
                "asset_count": 0,
                "asset_skipped_count": 0,
                "source_link_id": "",
                "report_id": report_id,
                "message": "草稿已标记为 rejected",
            }

        with conn:
            if proposed_action == "update":
                question_id = str(draft.get("target_question_id") or "").strip()
                if not question_id:
                    raise ValueError("update 草稿缺少 target_question_id")
                before, after = _update_question_from_draft_conn(conn, question_id, draft)
                question_for_meta = _draft_preview_question(question_id, draft, base=after)
            elif proposed_action == "insert":
                question_id = _next_question_id_from_conn(conn)
                question_for_meta = _draft_preview_question(question_id, draft)
                _insert_question_from_draft_conn(conn, question_for_meta)
                before = {}
                after = _question_snapshot_from_conn(conn, question_id)
            else:
                raise ValueError(f"不支持 proposed_action：{proposed_action}")

            legacy_file_path = _upsert_legacy_map_from_draft_conn(conn, question_id, question_for_meta, draft)
            paper_question_id = _upsert_paper_link_from_draft_conn(conn, question_id, draft)
            book_link_id = _upsert_book_link_from_draft_conn(conn, question_id, draft)
            topic_link_id = _upsert_topic_link_from_draft_conn(conn, question_id, draft)
            asset_result = _copy_draft_assets_to_question_conn(conn, draft, question_id, copy_files=copy_assets)
            revision_id = insert_question_revision_from_conn(
                conn,
                question_id=question_id,
                change_source="draft_commit",
                before=before,
                after=_question_snapshot_from_conn(conn, question_id),
                operator=operator,
                note=f"draft_id={safe_draft_id}",
            )
            conn.execute(
                """
                UPDATE question_import_draft
                SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
                WHERE draft_id = ?
                """,
                ("committed", f"已提交为正式题：{question_id}", safe_draft_id),
            )
            report_id = _insert_report_item_from_conn(
                conn,
                str(draft.get("batch_id") or ""),
                1,
                safe_draft_id,
                question_id,
                "committed",
                f"{proposed_action} -> {question_id}",
                compact_json(
                    {
                        "draft_id": safe_draft_id,
                        "question_id": question_id,
                        "revision_id": revision_id,
                        "legacy_file_path": legacy_file_path,
                        "paper_question_id": paper_question_id,
                        "book_link_id": book_link_id,
                        "topic_link_id": topic_link_id,
                        "assets": asset_result,
                    }
                ),
            )

    return {
        "draft_id": safe_draft_id,
        "status": "updated" if proposed_action == "update" else "inserted",
        "question_id": question_id,
        "revision_id": revision_id,
        "asset_count": len(asset_result["inserted"]),
        "asset_skipped_count": len(asset_result["skipped"]),
        "asset_skipped": asset_result["skipped"],
        "source_link_id": paper_question_id,
        "book_link_id": book_link_id,
        "topic_link_id": topic_link_id,
        "legacy_file_path": legacy_file_path,
        "report_id": report_id,
        "message": f"草稿已提交为正式题：{question_id}",
    }


def _commit_draft_to_question_conn(
    conn,
    draft: dict[str, Any],
    *,
    operator: str,
    copy_assets: bool,
    report_index: int,
    created_asset_paths: list[Path] | None = None,
) -> dict[str, Any]:
    """Commit a validated draft using the caller's transaction."""
    safe_draft_id = str(draft.get("draft_id") or "").strip()
    proposed_action = str(draft.get("proposed_action") or "insert").strip()
    reuse_question_id = str(draft.get("_reuse_question_id") or "").strip()
    if reuse_question_id and proposed_action == "insert":
        return _link_draft_to_existing_question_conn(
            conn, draft, reuse_question_id, operator=operator, report_index=report_index
        )
    if proposed_action == "skip":
        conn.execute(
            """
            UPDATE question_import_draft
            SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
            WHERE draft_id = ?
            """,
            ("rejected", "用户确认跳过", safe_draft_id),
        )
        report_id = _insert_report_item_from_conn(
            conn, str(draft.get("batch_id") or ""), report_index, safe_draft_id,
            None, "skipped", "用户确认跳过", compact_json({"draft_id": safe_draft_id}),
        )
        return {"draft_id": safe_draft_id, "status": "skipped", "question_id": "", "revision_id": "", "report_id": report_id}

    if proposed_action == "update":
        question_id = str(draft.get("target_question_id") or "").strip()
        if not question_id:
            raise ValueError("update 草稿缺少 target_question_id")
        before, after = _update_question_from_draft_conn(conn, question_id, draft)
        question_for_meta = _draft_preview_question(question_id, draft, base=after)
    elif proposed_action == "insert":
        question_id = _next_question_id_from_conn(conn)
        question_for_meta = _draft_preview_question(question_id, draft)
        _insert_question_from_draft_conn(conn, question_for_meta)
        before, after = {}, _question_snapshot_from_conn(conn, question_id)
    else:
        raise ValueError(f"不支持 proposed_action：{proposed_action}")

    legacy_file_path = _upsert_legacy_map_from_draft_conn(conn, question_id, question_for_meta, draft)
    paper_question_id = _upsert_paper_link_from_draft_conn(conn, question_id, draft)
    book_link_id = _upsert_book_link_from_draft_conn(conn, question_id, draft)
    topic_link_id = _upsert_topic_link_from_draft_conn(conn, question_id, draft)
    asset_result = _copy_draft_assets_to_question_conn(
        conn, draft, question_id, copy_files=copy_assets, created_paths=created_asset_paths
    )
    revision_id = insert_question_revision_from_conn(
        conn, question_id=question_id, change_source="draft_commit",
        before=before, after=_question_snapshot_from_conn(conn, question_id),
        operator=operator, note=f"draft_id={safe_draft_id}",
    )
    conn.execute(
        """
        UPDATE question_import_draft
        SET review_status = ?, review_reason = ?, updated_at = CURRENT_TIMESTAMP
        WHERE draft_id = ?
        """,
        ("committed", f"已提交为正式题：{question_id}", safe_draft_id),
    )
    report_id = _insert_report_item_from_conn(
        conn, str(draft.get("batch_id") or ""), report_index, safe_draft_id,
        question_id, "committed", f"{proposed_action} -> {question_id}",
        compact_json({"draft_id": safe_draft_id, "question_id": question_id, "revision_id": revision_id, "assets": asset_result, "book_link_id": book_link_id, "topic_link_id": topic_link_id}),
    )
    return {
        "draft_id": safe_draft_id,
        "status": "updated" if proposed_action == "update" else "inserted",
        "question_id": question_id,
        "revision_id": revision_id,
        "asset_count": len(asset_result["inserted"]),
        "asset_skipped_count": len(asset_result["skipped"]),
        "asset_skipped": asset_result["skipped"],
        "source_link_id": paper_question_id,
        "book_link_id": book_link_id,
        "topic_link_id": topic_link_id,
        "legacy_file_path": legacy_file_path,
        "report_id": report_id,
        "message": f"草稿已提交为正式题：{question_id}",
    }


def commit_drafts_to_questions(
    db_path: str | None,
    draft_ids: list[str],
    *,
    operator: str = "streamlit_batch_import",
    require_ready: bool = False,
    copy_assets: bool = True,
) -> dict[str, Any]:
    """Preflight and commit a group of drafts in one transaction."""
    safe_ids = [str(value or "").strip() for value in draft_ids if str(value or "").strip()]
    if not safe_ids:
        raise ValueError("draft_ids 不能为空")
    with existing_database_connection(db_path) as conn:
        drafts = []
        validation_errors: list[dict[str, Any]] = []
        warnings: list[dict[str, Any]] = []
        seen_source_items: set[str] = set()
        seen_stems: dict[str, str] = {}
        seen_paper_positions: dict[tuple[str, str, str], str] = {}
        for index, draft_id in enumerate(safe_ids, start=1):
            draft = _get_draft_question_from_conn(conn, draft_id)
            if not draft:
                validation_errors.append({"draft_id": draft_id, "index": index, "errors": ["草稿不存在"]})
                continue
            status = str(draft.get("review_status") or "")
            if status == "committed":
                validation_errors.append({"draft_id": draft_id, "index": index, "errors": ["草稿已经提交过"]})
                continue
            if require_ready and status not in {"ready", "approved"}:
                validation_errors.append({"draft_id": draft_id, "index": index, "errors": [f"草稿状态必须是 ready/approved，当前为：{status}"]})
                continue
            validation = validate_draft_question(_draft_row_to_input(draft))
            if validation.get("errors"):
                validation_errors.append({"draft_id": draft_id, "index": index, "errors": list(validation["errors"])})
            if validation.get("warnings"):
                warnings.append({"draft_id": draft_id, "index": index, "warnings": list(validation["warnings"])})
            source_item_id = str(draft.get("source_item_id") or "").strip()
            if source_item_id and source_item_id in seen_source_items:
                warnings.append({"draft_id": draft_id, "index": index, "warnings": ["本批 source_item_id 重复"]})
            if source_item_id:
                seen_source_items.add(source_item_id)
            from services.question_service import normalize_question_text

            normalized_stem = normalize_question_text(str(draft.get("stem_tex") or ""))
            if normalized_stem:
                previous_draft_id = seen_stems.get(normalized_stem)
                if previous_draft_id:
                    warnings.append({"draft_id": draft_id, "index": index, "warnings": [f"题干与本批草稿相同：{previous_draft_id}；是否同一来源请人工确认"]})
                else:
                    existing_question = conn.execute(
                        "SELECT question_id, stem_tex FROM question WHERE stem_tex IS NOT NULL AND stem_tex != ?",
                        ("",),
                    ).fetchall()
                    target_question_id = str(draft.get("target_question_id") or "").strip()
                    for question_row in existing_question:
                        if str(question_row[0]) == target_question_id:
                            continue
                        if normalize_question_text(str(question_row[1] or "")) == normalized_stem:
                            warnings.append({"draft_id": draft_id, "index": index, "warnings": [f"题干与正式题目 {question_row[0]} 相同；来源位置未确认，不自动阻断"]})
                            break
                    seen_stems[normalized_stem] = draft_id
            extra = _draft_extra(draft)
            if extra.get("source_kind") == "试卷":
                question_number = str(extra.get("detected_question_number") or "").strip()
                paper_standard_id = str(extra.get("paper_standard_id") or "").strip()
                paper_identity = paper_standard_id or "|".join(
                    str(extra.get(key) or "").strip()
                    for key in ("detected_year", "paper_series", "track", "detected_source")
                )
                position_key = (paper_identity, question_number, str(extra.get("sub_number") or "").strip())
                if paper_identity and question_number:
                    previous_draft_id = seen_paper_positions.get(position_key)
                    if previous_draft_id:
                        validation_errors.append({"draft_id": draft_id, "index": index, "errors": [f"本批试卷位置冲突：与草稿 {previous_draft_id} 使用相同题号 {question_number}"]})
                    else:
                        seen_paper_positions[position_key] = draft_id
                if question_number and paper_standard_id:
                    paper_row = conn.execute(
                        "SELECT paper_id FROM paper_standard_catalog WHERE paper_standard_id = ?",
                        (paper_standard_id,),
                    ).fetchone()
                    if paper_row and conn.execute(
                        "SELECT 1 FROM paper_question WHERE paper_id = ? AND question_number = ? AND sub_number = ? LIMIT 1",
                        (paper_row["paper_id"], question_number, str(extra.get("sub_number") or "")),
                    ).fetchone():
                        # An existing source position is a reusable relation, not a
                        # duplicate question. The conflict is resolved below by
                        # linking the draft to the occupying question.
                        pass
                source_conflicts = find_paper_position_conflict(db_path, extra)
                if source_conflicts:
                    draft["_reuse_question_id"] = str(source_conflicts[0].get("question_id") or "")
                    warnings.append({"draft_id": draft_id, "index": index, "warnings": [f"将复用已有题目：{draft['_reuse_question_id']}，仅新增来源关系"]})
            drafts.append((index, draft))

        if validation_errors:
            return {"status": "blocked", "committed": [], "skipped": [], "failed": [], "validation_errors": validation_errors, "warnings": warnings, "message": "本批预检未通过，未写入正式题库"}

        created_asset_paths: list[Path] = []
        current_draft_id = ""
        current_index = 0
        try:
            results = []
            for index, draft in drafts:
                current_index = index
                current_draft_id = str(draft.get("draft_id") or "")
                results.append(
                    _commit_draft_to_question_conn(
                        conn, draft, operator=operator, copy_assets=copy_assets,
                        report_index=index, created_asset_paths=created_asset_paths,
                    )
                )
            batch_ids = {str(draft.get("batch_id") or "") for _, draft in drafts if draft.get("batch_id")}
            summary = compact_json({"committed": len(results), "warnings": len(warnings)})
            for batch_id in batch_ids:
                conn.execute("UPDATE import_batch SET finished_at = ?, summary = ? WHERE batch_id = ?", (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), summary, batch_id))
            return {
                "status": "committed", "committed": [item for item in results if item.get("status") in {"inserted", "updated"}],
                "skipped": [item for item in results if item.get("status") == "skipped"], "failed": [],
                "validation_errors": [], "warnings": warnings, "results": results,
                "question_ids": [str(item.get("question_id") or "") for item in results if item.get("question_id")],
                "revision_ids": [str(item.get("revision_id") or "") for item in results if item.get("revision_id")],
                "message": f"整批提交完成：{len(results)} 条，其中 {len(warnings)} 条提醒",
            }
        except Exception as exc:
            conn.rollback()
            for asset_path in created_asset_paths:
                try:
                    asset_path.unlink(missing_ok=True)
                except OSError:
                    pass
            for asset_path in created_asset_paths:
                try:
                    asset_path.parent.rmdir()
                except OSError:
                    pass
            return {
                "status": "failed", "committed": [], "skipped": [],
                "failed": [{"draft_id": current_draft_id, "index": current_index, "error": str(exc)}],
                "validation_errors": [], "warnings": warnings,
                "message": f"整批提交失败，已回滚：{exc}",
            }
