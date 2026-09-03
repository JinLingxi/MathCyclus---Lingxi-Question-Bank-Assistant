"""Question asset helpers for images, scans, and future attachments."""

from __future__ import annotations

import hashlib
import mimetypes
import re
import shutil
import struct
from pathlib import Path

from services.database_service import (
    BASE_DIR,
    database_connection,
    existing_database_connection,
    readonly_database_connection,
    row_to_dict,
)
from services.revision_service import insert_question_revision_from_conn


PROJECT_ROOT = Path(BASE_DIR)
ASSET_ROOT = PROJECT_ROOT / "assets" / "questions"
ASSET_EDITABLE_FIELDS = {"role", "caption", "sort_order"}
INCLUDE_GRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^{}]+)\}",
    re.MULTILINE,
)
QUESTION_ASSET_PATTERN = re.compile(
    r"\\questionasset\{(?P<alias>[^{}]+)\}",
    re.MULTILINE,
)


def file_hash(path: str | Path) -> str:
    target = Path(path)
    digest = hashlib.sha256()
    with target.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def make_asset_id(question_id: str, role: str, source_path: str | Path) -> str:
    raw = f"{question_id}\u241f{role}\u241f{Path(source_path).name}\u241f{file_hash(source_path)}"
    return "A" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:14]


def question_asset_dir(question_id: str, asset_root: str | Path | None = None) -> Path:
    root = Path(asset_root) if asset_root is not None else ASSET_ROOT
    return root / question_id


def preferred_asset_alias(asset: dict) -> str:
    """Return the stable default alias used by \\questionasset placeholders."""
    file_path = str(asset.get("file_path") or "")
    alias = Path(file_path).stem
    if alias:
        return alias
    original_name = str(asset.get("original_file_name") or "")
    alias = Path(original_name).stem
    if alias:
        return alias
    return str(asset.get("asset_id") or "").strip()


def asset_placeholder(asset: dict) -> str:
    """Return a TeX placeholder that can be resolved during export."""
    alias = preferred_asset_alias(asset)
    if not alias:
        raise ValueError("资源缺少可用别名")
    return f"\\questionasset{{{alias}}}"


def asset_aliases(asset: dict) -> set[str]:
    """Return aliases that can identify a formal or draft asset in TeX placeholders."""
    aliases = {
        str(asset.get("asset_id") or ""),
        str(asset.get("draft_asset_id") or ""),
        str(asset.get("caption") or "").strip(),
    }
    for field in ["file_path", "source_path", "planned_file_path", "original_file_name"]:
        value = str(asset.get(field) or "").strip()
        if not value:
            continue
        path = Path(value)
        aliases.add(path.stem)
        aliases.add(path.name)
    return {alias for alias in aliases if alias}


def find_questionasset_refs(tex: str) -> list[str]:
    return [match.group("alias").strip() for match in QUESTION_ASSET_PATTERN.finditer(tex or "")]


def find_includegraphics_refs(tex: str) -> list[str]:
    return [match.group("path").strip() for match in INCLUDE_GRAPHICS_PATTERN.finditer(tex or "")]


def resolve_graphics_ref(ref: str, source_file: str | None = "", project_root: str | Path | None = None) -> Path | None:
    root = Path(project_root or PROJECT_ROOT)
    candidates: list[Path] = []
    ref_path = Path(str(ref or "").strip())
    if not str(ref_path):
        return None
    if ref_path.is_absolute():
        candidates.append(ref_path)
    else:
        if source_file:
            candidates.append((root / source_file).parent / ref_path)
        candidates.append(root / ref_path)
        candidates.append(root / "chapters" / ref_path)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_asset_record_path(
    asset: dict,
    project_root: str | Path | None = None,
    path_fields: tuple[str, ...] = ("file_path", "source_path", "planned_file_path"),
) -> Path | None:
    root = Path(project_root or PROJECT_ROOT)
    for field in path_fields:
        value = str(asset.get(field) or "").strip()
        if not value:
            continue
        path = Path(value)
        candidates = [path] if path.is_absolute() else [root / path]
        for candidate in candidates:
            if candidate.exists() and candidate.is_file():
                return candidate
    return None


def collect_asset_reference_issues(
    record: dict,
    assets: list[dict],
    *,
    project_root: str | Path | None = None,
    source_file: str | None = "",
    tex_fields: tuple[str, ...] = ("stem_tex", "answer_tex", "solution_tex", "canonical_tex", "normalized_tex"),
) -> dict[str, object]:
    """Check TeX image refs against registered formal or draft assets."""
    tex = "\n".join(str(record.get(field) or "") for field in tex_fields)
    include_refs = list(dict.fromkeys(find_includegraphics_refs(tex)))
    questionasset_refs = list(dict.fromkeys(find_questionasset_refs(tex)))
    asset_alias_map: dict[str, dict] = {}
    for asset in assets:
        for alias in asset_aliases(asset):
            asset_alias_map.setdefault(alias, asset)

    missing_includegraphics = []
    for ref in include_refs:
        resolved = resolve_graphics_ref(ref, source_file=source_file, project_root=project_root)
        if not resolved:
            missing_includegraphics.append({"ref": ref})

    unresolved_questionasset = [
        {
            "alias": alias,
            "known_asset_aliases": sorted(asset_alias_map.keys()),
        }
        for alias in questionasset_refs
        if alias not in asset_alias_map
    ]

    missing_asset_files = []
    unreferenced_assets = []
    for asset in assets:
        aliases = asset_aliases(asset)
        if not resolve_asset_record_path(asset, project_root=project_root):
            missing_asset_files.append(
                {
                    "asset_id": asset.get("asset_id") or asset.get("draft_asset_id") or "",
                    "role": asset.get("role") or "",
                    "path": asset.get("file_path") or asset.get("source_path") or asset.get("planned_file_path") or "",
                }
            )
        if questionasset_refs and not aliases.intersection(questionasset_refs):
            unreferenced_assets.append(
                {
                    "asset_id": asset.get("asset_id") or asset.get("draft_asset_id") or "",
                    "role": asset.get("role") or "",
                    "aliases": sorted(aliases),
                }
            )

    return {
        "includegraphics_refs": include_refs,
        "questionasset_refs": questionasset_refs,
        "missing_includegraphics": missing_includegraphics,
        "unresolved_questionasset": unresolved_questionasset,
        "missing_asset_files": missing_asset_files,
        "unreferenced_assets": unreferenced_assets,
        "has_blockers": bool(missing_includegraphics or unresolved_questionasset or missing_asset_files),
    }


def normalize_asset_alias(alias: str, fallback: str = "asset") -> str:
    """Normalize a user-facing alias used by \\questionasset{...}."""
    text = str(alias or "").strip()
    text = Path(text).stem if text else ""
    text = re.sub(r"[^0-9A-Za-z_\-]+", "_", text)
    text = re.sub(r"_+", "_", text).strip("._-")
    fallback_text = re.sub(r"[^0-9A-Za-z_\-]+", "_", str(fallback or "asset")).strip("._-")
    return (text or fallback_text or "asset")[:80]


def copy_asset_to_question_dir(
    question_id: str,
    source_path: str | Path,
    role: str = "problem",
    target_stem: str | None = None,
    asset_root: str | Path | None = None,
) -> Path:
    source = Path(source_path)
    target_dir = question_asset_dir(question_id, asset_root=asset_root)
    target_dir.mkdir(parents=True, exist_ok=True)

    safe_stem = normalize_asset_alias(target_stem or source.stem, fallback=role)
    base_name = f"{safe_stem}{source.suffix.lower()}"
    target = target_dir / base_name
    if target.exists() and file_hash(target) != file_hash(source):
        stem = target.stem
        suffix = source.suffix.lower()
        index = 2
        while True:
            candidate = target_dir / f"{stem}-{index}{suffix}"
            if not candidate.exists():
                target = candidate
                break
            index += 1

    if not target.exists():
        shutil.copy2(source, target)
    return target


def _stored_path(path: str | Path) -> str:
    target = Path(path).resolve()
    try:
        return target.relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return target.as_posix()


def _image_dimensions(path: str | Path) -> tuple[int | None, int | None]:
    target = Path(path)
    if target.suffix.lower() == ".png":
        try:
            with target.open("rb") as file:
                header = file.read(24)
            if header.startswith(b"\x89PNG\r\n\x1a\n") and header[12:16] == b"IHDR":
                width, height = struct.unpack(">II", header[16:24])
                return int(width), int(height)
        except Exception:
            pass

    try:
        from PIL import Image
    except Exception:
        return None, None

    try:
        with Image.open(target) as image:
            return int(image.width), int(image.height)
    except Exception:
        return None, None


def register_asset(
    db_path: str | None,
    question_id: str,
    source_path: str | Path,
    role: str = "problem",
    file_path: str | None = None,
    caption: str = "",
    sort_order: int = 0,
) -> str:
    """Insert or update an asset record and return `asset_id`."""
    source = Path(source_path)
    asset_id = make_asset_id(question_id, role, source)
    mime_type = mimetypes.guess_type(source.name)[0] or ""
    stored_path = file_path or _stored_path(source)
    digest = file_hash(source)

    with database_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO question_asset(
                asset_id, question_id, role, file_path, original_file_name,
                mime_type, file_hash, caption, sort_order
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                asset_id,
                question_id,
                role,
                stored_path,
                source.name,
                mime_type,
                digest,
                caption,
                sort_order,
            ),
        )
    return asset_id


def attach_asset_to_question(
    db_path: str | None,
    question_id: str,
    source_path: str | Path,
    *,
    role: str = "problem",
    alias: str = "",
    caption: str = "",
    sort_order: int | None = None,
    copy_file: bool = True,
    asset_root: str | Path | None = None,
) -> dict:
    """Attach an existing file to one question in an existing database."""
    safe_question_id = str(question_id or "").strip()
    safe_role = str(role or "problem").strip() or "problem"
    source = Path(source_path)
    if not safe_question_id:
        raise ValueError("question_id 不能为空")
    if not source.exists() or not source.is_file():
        raise FileNotFoundError(f"资源文件不存在：{source}")

    with existing_database_connection(db_path) as conn:
        question_exists = conn.execute(
            "SELECT 1 FROM question WHERE question_id = ?",
            (safe_question_id,),
        ).fetchone()
        if not question_exists:
            raise ValueError(f"题目不存在：{safe_question_id}")

        final_sort_order = sort_order
        if final_sort_order is None:
            row = conn.execute(
                """
                SELECT COALESCE(MAX(sort_order), 0) + 1
                FROM question_asset
                WHERE question_id = ? AND role = ?
                """,
                (safe_question_id, safe_role),
            ).fetchone()
            final_sort_order = int(row[0] or 1)

        target_alias = normalize_asset_alias(alias, fallback=f"{safe_role}_{int(final_sort_order):02d}")
        target = (
            copy_asset_to_question_dir(
                safe_question_id,
                source,
                safe_role,
                target_stem=target_alias,
                asset_root=asset_root,
            )
            if copy_file
            else source
        )
        asset_id = make_asset_id(safe_question_id, safe_role, target)
        mime_type = mimetypes.guess_type(target.name)[0] or ""
        width, height = _image_dimensions(target) if mime_type.startswith("image/") else (None, None)
        stored_path = _stored_path(target)
        digest = file_hash(target)

        before_asset = row_to_dict(
            conn.execute(
                "SELECT * FROM question_asset WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        )

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
                safe_question_id,
                safe_role,
                stored_path,
                source.name,
                mime_type,
                width,
                height,
                digest,
                caption,
                int(final_sort_order),
            ),
        )
        after_asset = row_to_dict(
            conn.execute(
                "SELECT * FROM question_asset WHERE asset_id = ?",
                (asset_id,),
            ).fetchone()
        )
        revision_id = insert_question_revision_from_conn(
            conn,
            question_id=safe_question_id,
            change_source="asset_attach",
            before={"question_asset": before_asset},
            after={"question_asset": after_asset},
            operator="asset_service",
            note=f"登记图片/附件资源：{asset_id}",
            changed_field_names=["question_asset"],
        )

    result = {
        "asset_id": asset_id,
        "question_id": safe_question_id,
        "role": safe_role,
        "file_path": stored_path,
        "source_path": _stored_path(source),
        "copied": bool(copy_file),
        "width": width,
        "height": height,
        "mime_type": mime_type,
        "sort_order": int(final_sort_order),
        "revision_id": revision_id,
        "caption": caption,
        "alias": preferred_asset_alias({"file_path": stored_path, "caption": caption or alias}),
    }
    result["placeholder"] = asset_placeholder(result)
    return result


def list_assets(db_path: str | None = None, question_id: str | None = None) -> list[dict]:
    """List assets, optionally filtered by question ID."""
    if question_id:
        sql = """
            SELECT *
            FROM question_asset
            WHERE question_id = ?
            ORDER BY role, sort_order, asset_id
        """
        params = (question_id,)
    else:
        sql = """
            SELECT *
            FROM question_asset
            ORDER BY question_id, role, sort_order, asset_id
        """
        params = ()

    with readonly_database_connection(db_path) as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


def get_asset(db_path: str | None, asset_id: str) -> dict:
    """Return one asset row by ID."""
    safe_asset_id = str(asset_id or "").strip()
    if not safe_asset_id:
        raise ValueError("asset_id 不能为空")
    with readonly_database_connection(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM question_asset WHERE asset_id = ?",
            (safe_asset_id,),
        ).fetchone()
    return row_to_dict(row)


def normalize_asset_updates(updates: dict) -> dict:
    """Validate and normalize editable question_asset fields."""
    if not isinstance(updates, dict):
        raise ValueError("updates 必须是字典")
    normalized = {}
    for field, value in updates.items():
        if field not in ASSET_EDITABLE_FIELDS:
            raise ValueError(f"不允许编辑资源字段：{field}")
        if field == "sort_order":
            normalized[field] = int(value or 0)
        elif field == "role":
            normalized[field] = str(value or "problem").strip() or "problem"
        elif field == "caption":
            normalized[field] = "" if value is None else str(value)
    return normalized


def update_asset_fields(
    db_path: str | None,
    asset_id: str,
    updates: dict,
    *,
    operator: str = "asset_service",
    note: str = "",
) -> dict:
    """Update editable asset metadata and record a question revision event."""
    safe_asset_id = str(asset_id or "").strip()
    if not safe_asset_id:
        raise ValueError("asset_id 不能为空")
    normalized = normalize_asset_updates(updates)
    if not normalized:
        return {"asset_id": safe_asset_id, "changed_fields": [], "revision_id": "", "before": {}, "after": {}}

    with existing_database_connection(db_path) as conn:
        before = row_to_dict(
            conn.execute(
                "SELECT * FROM question_asset WHERE asset_id = ?",
                (safe_asset_id,),
            ).fetchone()
        )
        if not before:
            raise KeyError(f"资源不存在：{safe_asset_id}")

        changed = [field for field, value in normalized.items() if before.get(field) != value]
        if not changed:
            return {"asset_id": safe_asset_id, "changed_fields": [], "revision_id": "", "before": before, "after": before}

        assignments = ", ".join(f"{field} = ?" for field in changed)
        params = [normalized[field] for field in changed]
        params.append(safe_asset_id)
        conn.execute(
            f"UPDATE question_asset SET {assignments} WHERE asset_id = ?",
            params,
        )
        after = row_to_dict(
            conn.execute(
                "SELECT * FROM question_asset WHERE asset_id = ?",
                (safe_asset_id,),
            ).fetchone()
        )
        revision_id = insert_question_revision_from_conn(
            conn,
            question_id=str(before.get("question_id") or ""),
            change_source="asset_update",
            before={"question_asset": before},
            after={"question_asset": after},
            operator=operator,
            note=note or f"更新图片/附件资源：{safe_asset_id}",
            changed_field_names=["question_asset"],
        )

    return {
        "asset_id": safe_asset_id,
        "changed_fields": changed,
        "revision_id": revision_id,
        "before": before,
        "after": after,
    }


def _safe_asset_file_for_delete(file_path: str) -> Path | None:
    if not file_path:
        return None
    candidate = Path(file_path)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    try:
        resolved = candidate.resolve()
        root = ASSET_ROOT.resolve()
        if resolved.is_file() and root in resolved.parents:
            return resolved
    except OSError:
        return None
    return None


def delete_asset(
    db_path: str | None,
    asset_id: str,
    *,
    delete_file: bool = False,
    operator: str = "asset_service",
    note: str = "",
) -> dict:
    """Remove an asset record; file deletion is opt-in and confined to assets/questions."""
    safe_asset_id = str(asset_id or "").strip()
    if not safe_asset_id:
        raise ValueError("asset_id 不能为空")

    deleted_file = ""
    with existing_database_connection(db_path) as conn:
        before = row_to_dict(
            conn.execute(
                "SELECT * FROM question_asset WHERE asset_id = ?",
                (safe_asset_id,),
            ).fetchone()
        )
        if not before:
            raise KeyError(f"资源不存在：{safe_asset_id}")

        conn.execute("DELETE FROM question_asset WHERE asset_id = ?", (safe_asset_id,))
        revision_id = insert_question_revision_from_conn(
            conn,
            question_id=str(before.get("question_id") or ""),
            change_source="asset_delete",
            before={"question_asset": before},
            after={"question_asset": None},
            operator=operator,
            note=note or f"移除图片/附件资源登记：{safe_asset_id}",
            changed_field_names=["question_asset"],
        )

    if delete_file:
        file_to_delete = _safe_asset_file_for_delete(str(before.get("file_path") or ""))
        if file_to_delete:
            file_to_delete.unlink()
            deleted_file = _stored_path(file_to_delete)

    return {
        "asset_id": safe_asset_id,
        "question_id": str(before.get("question_id") or ""),
        "revision_id": revision_id,
        "deleted_file": deleted_file,
    }
