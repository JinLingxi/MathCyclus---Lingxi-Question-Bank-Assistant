"""Export helpers for converting structured question records back to TeX."""

from __future__ import annotations

import json
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from services.choice_format_service import wrap_choice_item
from services.database_service import readonly_database_connection, row_to_dict
from services.question_db_service import QuestionListFilters, count_questions, get_question, list_questions
from services.asset_service import list_assets


INCLUDE_GRAPHICS_PATTERN = re.compile(
    r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^{}]+)\}",
    re.MULTILINE,
)
QUESTION_ASSET_PATTERN = re.compile(
    r"\\questionasset\{(?P<alias>[^{}]+)\}",
    re.MULTILINE,
)
INVALID_FILENAME_PATTERN = re.compile(r'[<>:"/\\|?*\x00-\x1f]+')
SOURCE_KIND_LABELS = {
    "paper": "试卷",
    "book": "教材",
    "topic": "专题",
}


def _json_list(value: str) -> list[str]:
    try:
        parsed = json.loads(value or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def format_choice_item(choice: str) -> str:
    """Return one TeX argument for ``\\choice{...}``.

    Existing migrated choices are usually stored as ``{...}``; future editors
    may store only the inner TeX. Both forms export as ``\\choice{{...}}``.
    """
    return wrap_choice_item(choice)


def _format_choices(choices: list[str]) -> str:
    if not choices:
        return ""
    choice_items = [format_choice_item(choice) for choice in choices]
    choice_items = [choice_item for choice_item in choice_items if choice_item]
    if not choice_items:
        return ""
    lines = ["\\begin{choices}"]
    for choice_item in choice_items:
        lines.append(f"\\choice{{{choice_item}}}")
    lines.append("\\end{choices}")
    return "\n".join(lines)


def _text(value: Any) -> str:
    return str(value or "").strip()


def _normalize_source_kind(source_kind: str) -> str:
    kind = _text(source_kind).lower()
    if kind not in SOURCE_KIND_LABELS:
        raise ValueError(f"unsupported source kind: {source_kind}")
    return kind


def sanitize_tex_filename_component(value: str, fallback: str = "sqlite_export") -> str:
    """Return a filesystem-safe, readable filename component."""
    cleaned = INVALID_FILENAME_PATTERN.sub("_", _text(value))
    cleaned = re.sub(r"\s+", "_", cleaned).strip("._ ")
    return (cleaned or fallback)[:120]


def _join_number_and_sub_number(number: Any, sub_number: Any) -> str:
    number_text = _text(number)
    sub_text = _text(sub_number)
    if not sub_text:
        return number_text
    if not number_text:
        return sub_text
    if f"({sub_text})" in number_text or f"（{sub_text}）" in number_text:
        return number_text
    return f"{number_text}({sub_text})"


def _paper_source_label(source: dict) -> str:
    bits = [
        _text(source.get("year")),
        _text(source.get("track")),
        _text(source.get("paper_name") or source.get("source_name")),
    ]
    return " ".join(bit for bit in bits if bit) or _text(source.get("paper_id")) or "试卷导出"


def _book_source_label(source: dict) -> str:
    bits = [
        _text(source.get("title")),
        _text(source.get("grade")),
        _text(source.get("volume")),
    ]
    return " ".join(bit for bit in bits if bit) or _text(source.get("book_id")) or "教材导出"


def _topic_source_label(source: dict) -> str:
    bits = [
        _text(source.get("module_name")),
        _text(source.get("name")),
    ]
    return " · ".join(bit for bit in bits if bit) or _text(source.get("topic_id")) or "专题导出"


def source_export_label(source_kind: str, source: dict) -> str:
    """Return a human-readable source label for export UI and reports."""
    kind = _normalize_source_kind(source_kind)
    if kind == "paper":
        return _paper_source_label(source)
    if kind == "book":
        return _book_source_label(source)
    return _topic_source_label(source)


def source_export_default_filename(source_kind: str, source: dict) -> str:
    """Return the default `.tex` filename for a source export."""
    kind = _normalize_source_kind(source_kind)
    if kind == "topic" and _text(source.get("file_name")):
        filename = sanitize_tex_filename_component(_text(source.get("file_name")), "topic_export")
        return filename if filename.lower().endswith(".tex") else f"{filename}.tex"
    prefix = SOURCE_KIND_LABELS[kind]
    label = source_export_label(kind, source)
    return sanitize_tex_filename_component(f"{prefix}_{label}", f"{kind}_export") + ".tex"


def _book_position_label(relation: dict) -> str:
    bits = []
    page_number = relation.get("page_number")
    if page_number not in (None, ""):
        bits.append(f"p{page_number}")
    for key in ("column_name", "exercise_number"):
        value = _text(relation.get(key))
        if value:
            bits.append(value)
    sub_number = _text(relation.get("sub_number"))
    if sub_number:
        bits.append(f"({sub_number})")
    return " ".join(bits)


def _topic_position_label(relation: dict) -> str:
    bits = []
    group_name = _text(relation.get("group_name"))
    if group_name:
        bits.append(group_name)
    sort_order = relation.get("sort_order")
    if sort_order not in (None, ""):
        bits.append(f"#{sort_order}")
    return " · ".join(bits)


def _source_position_label(source_kind: str, relation: dict) -> str:
    kind = _normalize_source_kind(source_kind)
    if kind == "paper":
        return _join_number_and_sub_number(relation.get("question_number"), relation.get("sub_number"))
    if kind == "book":
        return _book_position_label(relation)
    return _topic_position_label(relation)


def _apply_source_context(source_kind: str, question: dict, source: dict, relation: dict) -> dict:
    """Overlay relation-specific source metadata before rendering legacy TeX."""
    kind = _normalize_source_kind(source_kind)
    merged = dict(question)
    if kind == "paper":
        merged.update(
            {
                "detected_year": source.get("year") if source.get("year") is not None else question.get("detected_year"),
                "paper_series": source.get("paper_series") or question.get("paper_series") or "G",
                "track": source.get("track") or question.get("track") or "",
                "paper_name": source.get("paper_name") or question.get("paper_name") or "",
                "detected_source": source.get("paper_name") or source.get("source_name") or question.get("detected_source") or "",
                "detected_question_number": _join_number_and_sub_number(
                    relation.get("question_number"),
                    relation.get("sub_number"),
                )
                or question.get("detected_question_number")
                or "",
                "question_number": relation.get("question_number") or question.get("question_number") or "",
                "sub_number": relation.get("sub_number") or question.get("sub_number") or "",
            }
        )
    elif kind == "book":
        merged.update(
            {
                "detected_year": source.get("volume") or source.get("grade") or question.get("detected_year") or "",
                "paper_series": "BK",
                "detected_source": _book_source_label(source),
                "detected_question_number": _book_position_label(relation),
                "detected_topic": relation.get("section_title") or relation.get("column_name") or question.get("detected_topic") or "",
            }
        )
    else:
        merged.update(
            {
                "paper_series": "TP",
                "detected_source": _topic_source_label(source),
                "detected_question_number": _topic_position_label(relation),
                "detected_topic": relation.get("group_name") or source.get("name") or question.get("detected_topic") or "",
            }
        )
    return merged


def question_to_legacy_tex(question: dict) -> str:
    """Render a database question as the current legacy TeX file format."""
    if not question:
        raise ValueError("question is empty")

    tags = "，".join(_json_list(question.get("tags_json", "[]")))
    choices = _json_list(question.get("choices_json", "[]"))
    difficulty = question.get("difficulty")
    difficulty_text = "" if difficulty is None else str(difficulty)

    year = question.get("detected_year") or ""
    category = question.get("paper_series") or "G"
    source = question.get("detected_source") or ""
    number = question.get("detected_question_number") or ""
    topic = question.get("detected_topic") or question.get("detected_chapter") or ""

    stem = (question.get("stem_tex") or "").strip()
    choices_tex = _format_choices(choices)
    problem_body = stem
    if choices_tex:
        problem_body = f"{stem}\n{choices_tex}" if stem else choices_tex

    parts = [
        "% === Begin Label Data ===",
        f"% ID: {question.get('legacy_id') or question.get('question_id') or ''}",
        f"% 难度星级: {difficulty_text}",
        f"% 标签: {tags}",
        f"% 备注: {question.get('note') or ''}",
        f"% 组卷引用次数: {question.get('usage_count') or 0}",
        "% === End  Label Data ===",
        "",
        f"\\begin{{problem}}{{{year}}}{{{category}}}{{{source}}}{{{number}}}{{{topic}}}",
        problem_body,
        "\\end{problem}",
        "",
        "\\begin{answer}",
        (question.get("answer_tex") or "").strip(),
        "\\end{answer}",
        "",
        "\\begin{solutions}",
        (question.get("solution_tex") or "").strip(),
        "\\end{solutions}",
        "",
    ]
    return "\n".join(parts)


def find_includegraphics_refs(tex: str) -> list[str]:
    """Return includegraphics paths referenced in TeX."""
    return [match.group("path").strip() for match in INCLUDE_GRAPHICS_PATTERN.finditer(tex or "")]


def find_questionasset_refs(tex: str) -> list[str]:
    """Return questionasset aliases referenced in TeX."""
    return [match.group("alias").strip() for match in QUESTION_ASSET_PATTERN.finditer(tex or "")]


def asset_aliases(asset: dict) -> set[str]:
    """Return aliases that can identify one asset in TeX placeholders."""
    file_path = asset.get("file_path") or ""
    original_name = asset.get("original_file_name") or ""
    aliases = {
        str(asset.get("asset_id") or ""),
        str(asset.get("caption") or "").strip(),
        Path(file_path).stem,
        Path(file_path).name,
    }
    if original_name:
        aliases.add(Path(original_name).stem)
        aliases.add(Path(original_name).name)
    return {alias for alias in aliases if alias}


def find_asset_by_alias(assets: list[dict], alias: str) -> dict:
    """Find a question asset by asset_id, file stem, or file name."""
    for asset in assets:
        if alias in asset_aliases(asset):
            return asset
    return {}


def resolve_graphics_ref(ref: str, source_file: str | None, project_root: str | Path) -> Path | None:
    """Resolve an includegraphics reference against common legacy locations."""
    root = Path(project_root)
    candidates: list[Path] = []
    ref_path = Path(ref)
    if ref_path.is_absolute():
        candidates.append(ref_path)
    else:
        if source_file:
            candidates.append((root / source_file).parent / ref)
        candidates.append(root / ref)
        candidates.append(root / "chapters" / ref)

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def resolve_asset_path(asset: dict, project_root: str | Path) -> Path | None:
    """Resolve a question_asset file path."""
    file_path = asset.get("file_path") or ""
    if not file_path:
        return None
    path = Path(file_path)
    candidates = [path] if path.is_absolute() else [Path(project_root) / path]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def collect_graphics_export_status(question: dict, project_root: str | Path) -> list[dict[str, str]]:
    """Inspect includegraphics references and report whether source files exist."""
    tex = question_to_legacy_tex(question)
    source_file = question.get("legacy_file_path") or ""
    rows = []
    for ref in find_includegraphics_refs(tex):
        resolved = resolve_graphics_ref(ref, source_file, project_root)
        rows.append(
            {
                "ref": ref,
                "type": "includegraphics",
                "status": "found" if resolved else "missing",
                "resolved_path": str(resolved) if resolved else "",
            }
        )
    return rows


def collect_asset_placeholder_export_status(
    question: dict,
    project_root: str | Path,
    db_path: str | None = None,
) -> list[dict[str, str]]:
    """Inspect questionasset placeholders and report whether they map to real assets."""
    tex = question_to_legacy_tex(question)
    question_id = question.get("question_id") or ""
    assets = list_assets(db_path, question_id=question_id) if db_path else []
    rows: list[dict[str, str]] = []
    for alias in find_questionasset_refs(tex):
        asset = find_asset_by_alias(assets, alias)
        resolved = resolve_asset_path(asset, project_root) if asset else None
        rows.append(
            {
                "ref": alias,
                "type": "questionasset",
                "status": "found" if resolved else "missing",
                "resolved_path": str(resolved) if resolved else "",
                "asset_id": asset.get("asset_id", "") if asset else "",
            }
        )
    return rows


def copy_graphics_for_export(
    question: dict,
    output_tex: str,
    output_dir: str | Path,
    project_root: str | Path,
    figures_dir_name: str = "figures",
) -> tuple[str, list[dict[str, str]]]:
    """Copy resolvable includegraphics files and rewrite refs for exported TeX."""
    output_directory = Path(output_dir)
    figures_dir = output_directory / figures_dir_name
    source_file = question.get("legacy_file_path") or ""
    copied: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        ref = match.group("path").strip()
        resolved = resolve_graphics_ref(ref, source_file, project_root)
        if not resolved:
            copied.append({"ref": ref, "status": "missing", "output_path": ""})
            return match.group(0)

        figures_dir.mkdir(parents=True, exist_ok=True)
        target_name = resolved.name
        target = figures_dir / target_name
        if target.exists() and target.resolve() != resolved.resolve():
            stem = resolved.stem
            suffix = resolved.suffix
            index = 2
            while True:
                candidate = figures_dir / f"{stem}-{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                index += 1

        shutil.copy2(resolved, target)
        new_ref = f"{figures_dir_name}/{target.name}"
        copied.append({"ref": ref, "status": "copied", "output_path": new_ref})
        return match.group(0).replace(ref, new_ref)

    rewritten = INCLUDE_GRAPHICS_PATTERN.sub(replace, output_tex)
    return rewritten, copied


def copy_questionassets_for_export(
    question: dict,
    output_tex: str,
    output_dir: str | Path,
    project_root: str | Path,
    db_path: str | None = None,
    figures_dir_name: str = "figures",
) -> tuple[str, list[dict[str, str]]]:
    """Replace questionasset placeholders with includegraphics commands and copy assets."""
    output_directory = Path(output_dir)
    figures_dir = output_directory / figures_dir_name
    question_id = question.get("question_id") or ""
    assets = list_assets(db_path, question_id=question_id) if db_path else []
    copied: list[dict[str, str]] = []

    def replace(match: re.Match[str]) -> str:
        alias = match.group("alias").strip()
        asset = find_asset_by_alias(assets, alias)
        resolved = resolve_asset_path(asset, project_root) if asset else None
        if not resolved:
            copied.append({"ref": alias, "type": "questionasset", "status": "missing", "output_path": ""})
            return match.group(0)

        figures_dir.mkdir(parents=True, exist_ok=True)
        target = figures_dir / resolved.name
        if target.exists() and target.resolve() != resolved.resolve():
            stem = resolved.stem
            suffix = resolved.suffix
            index = 2
            while True:
                candidate = figures_dir / f"{stem}-{index}{suffix}"
                if not candidate.exists():
                    target = candidate
                    break
                index += 1
        shutil.copy2(resolved, target)
        new_ref = f"{figures_dir_name}/{target.name}"
        copied.append(
            {
                "ref": alias,
                "type": "questionasset",
                "status": "copied",
                "output_path": new_ref,
                "asset_id": asset.get("asset_id", ""),
            }
        )
        return f"\\includegraphics{{{new_ref}}}"

    rewritten = QUESTION_ASSET_PATTERN.sub(replace, output_tex)
    return rewritten, copied


def list_source_export_options(db_path: str | None, source_kind: str, limit: int = 500) -> list[dict]:
    """Return selectable paper/book/topic sources with linked-question counts."""
    kind = _normalize_source_kind(source_kind)
    safe_limit = max(1, min(int(limit or 500), 1000))
    with readonly_database_connection(db_path) as conn:
        if kind == "paper":
            rows = conn.execute(
                """
                SELECT
                    p.paper_id,
                    p.year,
                    p.paper_series,
                    p.track,
                    p.paper_name,
                    p.source_name,
                    COUNT(pq.paper_question_id) AS question_count
                FROM paper p
                LEFT JOIN paper_question pq ON pq.paper_id = p.paper_id
                GROUP BY p.paper_id
                HAVING question_count > 0
                ORDER BY p.year DESC, p.paper_name, p.track
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        elif kind == "book":
            rows = conn.execute(
                """
                SELECT
                    b.book_id,
                    b.title,
                    b.publisher,
                    b.edition,
                    b.grade,
                    b.volume,
                    b.curriculum_version,
                    COUNT(beq.book_exercise_question_id) AS question_count
                FROM book b
                LEFT JOIN book_exercise_question beq ON beq.book_id = b.book_id
                GROUP BY b.book_id
                HAVING question_count > 0
                ORDER BY b.title, b.grade, b.volume
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT
                    t.topic_id,
                    t.module_id,
                    t.name,
                    t.file_name,
                    tm.name AS module_name,
                    COUNT(tq.topic_question_id) AS question_count
                FROM topic t
                LEFT JOIN topic_module tm ON tm.module_id = t.module_id
                LEFT JOIN topic_question tq ON tq.topic_id = t.topic_id
                GROUP BY t.topic_id
                HAVING question_count > 0
                ORDER BY tm.sort_order, tm.name, t.name
                LIMIT ?
                """,
                (safe_limit,),
            ).fetchall()

    options = [dict(row) for row in rows]
    for option in options:
        option["source_kind"] = kind
        option["label"] = f"{source_export_label(kind, option)} · {option.get('question_count') or 0} 题"
    return options


def _get_source_export_source(conn, source_kind: str, source_id: str) -> dict:
    kind = _normalize_source_kind(source_kind)
    if kind == "paper":
        source = row_to_dict(conn.execute("SELECT * FROM paper WHERE paper_id = ?", (source_id,)).fetchone())
    elif kind == "book":
        source = row_to_dict(conn.execute("SELECT * FROM book WHERE book_id = ?", (source_id,)).fetchone())
    else:
        source = row_to_dict(
            conn.execute(
                """
                SELECT t.*, tm.name AS module_name
                FROM topic t
                LEFT JOIN topic_module tm ON tm.module_id = t.module_id
                WHERE t.topic_id = ?
                """,
                (source_id,),
            ).fetchone()
        )
    if not source:
        raise KeyError(f"{SOURCE_KIND_LABELS[kind]}来源不存在：{source_id}")
    return source


def _list_source_export_relations(
    conn,
    source_kind: str,
    source_id: str,
    *,
    section_id: str = "",
    group_name: str = "",
) -> list[dict]:
    kind = _normalize_source_kind(source_kind)
    if kind == "paper":
        rows = conn.execute(
            """
            SELECT
                pq.*,
                p.year,
                p.paper_series,
                p.track,
                p.paper_name,
                p.source_name
            FROM paper_question pq
            JOIN paper p ON p.paper_id = pq.paper_id
            WHERE pq.paper_id = ?
            ORDER BY pq.display_order, pq.question_number, pq.sub_number, pq.question_id
            """,
            (source_id,),
        ).fetchall()
    elif kind == "book":
        clauses = ["beq.book_id = ?"]
        params: list[Any] = [source_id]
        if section_id:
            clauses.append("beq.section_id = ?")
            params.append(section_id)
        rows = conn.execute(
            f"""
            SELECT
                beq.*,
                s.title AS section_title,
                s.sort_order AS section_sort_order
            FROM book_exercise_question beq
            LEFT JOIN book_section s ON s.section_id = beq.section_id
            WHERE {" AND ".join(clauses)}
            ORDER BY s.sort_order, beq.display_order, beq.page_number, beq.exercise_number, beq.sub_number, beq.question_id
            """,
            params,
        ).fetchall()
    else:
        clauses = ["tq.topic_id = ?"]
        params = [source_id]
        if group_name:
            clauses.append("tq.group_name = ?")
            params.append(group_name)
        rows = conn.execute(
            f"""
            SELECT tq.*
            FROM topic_question tq
            WHERE {" AND ".join(clauses)}
            ORDER BY tq.group_name, tq.sort_order, tq.topic_question_id
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def get_source_export_bundle(
    db_path: str | None,
    source_kind: str,
    source_id: str,
    *,
    section_id: str = "",
    group_name: str = "",
) -> dict:
    """Return source metadata and full questions in export order."""
    kind = _normalize_source_kind(source_kind)
    safe_source_id = _text(source_id)
    if not safe_source_id:
        raise ValueError(f"{SOURCE_KIND_LABELS[kind]}来源 ID 不能为空")

    with readonly_database_connection(db_path) as conn:
        source = _get_source_export_source(conn, kind, safe_source_id)
        relations = _list_source_export_relations(
            conn,
            kind,
            safe_source_id,
            section_id=_text(section_id),
            group_name=_text(group_name),
        )

    items = []
    for relation in relations:
        question_id = _text(relation.get("question_id"))
        if not question_id:
            continue
        question = get_question(db_path, question_id)
        if not question:
            continue
        source_context = source
        if kind == "paper":
            source_context = {**source, **{key: relation.get(key) for key in ("year", "paper_series", "track", "paper_name", "source_name")}}
        question = _apply_source_context(kind, question, source_context, relation)
        items.append(
            {
                "question_id": question_id,
                "relation": relation,
                "position_label": _source_position_label(kind, relation),
                "question": question,
            }
        )

    return {
        "source_kind": kind,
        "source_kind_label": SOURCE_KIND_LABELS[kind],
        "source_id": safe_source_id,
        "source": source,
        "source_label": source_export_label(kind, source),
        "section_id": _text(section_id),
        "group_name": _text(group_name),
        "question_count": len(items),
        "items": items,
    }


def _source_export_header(bundle: dict, generated_at: str) -> str:
    source_kind_label = bundle.get("source_kind_label") or SOURCE_KIND_LABELS.get(bundle.get("source_kind"), "来源")
    rows = [
        "% === MathCyclus SQLite Source Export ===",
        f"% Source Kind: {source_kind_label}",
        f"% Source ID: {bundle.get('source_id') or ''}",
        f"% Source Label: {bundle.get('source_label') or ''}",
        f"% Question Count: {bundle.get('question_count') or 0}",
        f"% Generated At: {generated_at}",
        "% This file is generated from SQLite and does not modify legacy source files.",
        "% === End Export Metadata ===",
    ]
    section_id = _text(bundle.get("section_id"))
    group_name = _text(bundle.get("group_name"))
    if section_id or group_name:
        rows.insert(4, f"% Source Filter: section_id={section_id}; group_name={group_name}")
    return "\n".join(rows)


def export_source_to_tex(
    db_path: str | None,
    source_kind: str,
    source_id: str,
    output_path: str | Path,
    *,
    project_root: str | Path | None = None,
    section_id: str = "",
    group_name: str = "",
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> dict[str, Any]:
    """Export all questions linked to one paper/book/topic into one TeX file."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    bundle = get_source_export_bundle(
        db_path,
        source_kind,
        source_id,
        section_id=section_id,
        group_name=group_name,
    )
    if not bundle["items"]:
        raise ValueError(f"{bundle['source_kind_label']}来源没有可导出的题目：{source_id}")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections = [_source_export_header(bundle, generated_at), ""]
    graphics_rows: list[dict[str, str]] = []
    if bundle["source_kind"] == "topic":
        problem_intro = _text(bundle.get("source", {}).get("problem_intro_tex"))
        if problem_intro:
            sections.append("% --- Topic Problem Intro ---")
            sections.append(problem_intro)
            sections.append("")

    for index, item in enumerate(bundle["items"], start=1):
        question = item["question"]
        question_id = item["question_id"]
        position = item.get("position_label") or str(index)
        tex = question_to_legacy_tex(question).rstrip()

        if copy_graphics:
            tex, graphics = copy_graphics_for_export(question, tex, target.parent, root)
        else:
            graphics = collect_graphics_export_status(question, root)

        if resolve_questionassets:
            tex, asset_placeholders = copy_questionassets_for_export(
                question,
                tex,
                target.parent,
                root,
                db_path=db_path,
            )
        else:
            asset_placeholders = collect_asset_placeholder_export_status(question, root, db_path)

        for graphic in graphics + asset_placeholders:
            graphics_rows.append({"question_id": question_id, **graphic})

        sections.append(f"% --- {index}. {position} · {question_id} ---")
        sections.append(tex)
        sections.append("")

    if bundle["source_kind"] == "topic":
        answer_intro = _text(bundle.get("source", {}).get("answer_intro_tex"))
        if answer_intro:
            sections.append("% --- Topic Answer Intro ---")
            sections.append(answer_intro)
            sections.append("")

    target.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return {
        "source_kind": bundle["source_kind"],
        "source_kind_label": bundle["source_kind_label"],
        "source_id": bundle["source_id"],
        "source_label": bundle["source_label"],
        "question_count": bundle["question_count"],
        "output_path": str(target),
        "graphics": graphics_rows,
        "questions": [
            {
                "question_id": item["question_id"],
                "position_label": item.get("position_label") or "",
            }
            for item in bundle["items"]
        ],
    }


def export_paper_to_tex(
    db_path: str | None,
    paper_id: str,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Export one paper and all linked questions into one TeX file."""
    return export_source_to_tex(db_path, "paper", paper_id, output_path, **kwargs)


def export_book_to_tex(
    db_path: str | None,
    book_id: str,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Export one book or one book section into one TeX file."""
    return export_source_to_tex(db_path, "book", book_id, output_path, **kwargs)


def export_topic_to_tex(
    db_path: str | None,
    topic_id: str,
    output_path: str | Path,
    **kwargs: Any,
) -> dict[str, Any]:
    """Export one topic or one topic group into one TeX file."""
    return export_source_to_tex(db_path, "topic", topic_id, output_path, **kwargs)


def _filters_for_export_page(filters: QuestionListFilters, limit: int, offset: int) -> QuestionListFilters:
    return QuestionListFilters(
        keyword=filters.keyword,
        year=filters.year,
        chapter=filters.chapter,
        source=filters.source,
        question_number=filters.question_number,
        question_type_id=filters.question_type_id,
        difficulty=filters.difficulty,
        limit=limit,
        offset=offset,
    )


def filter_export_label(filters: QuestionListFilters | None = None) -> str:
    """Return a compact human label for one filter export."""
    filters = filters or QuestionListFilters()
    parts = []
    if filters.keyword:
        parts.append(f"关键词={filters.keyword}")
    if filters.year is not None:
        parts.append(f"年份={filters.year}")
    if filters.chapter:
        parts.append(f"板块={filters.chapter}")
    if filters.source:
        parts.append(f"来源={filters.source}")
    if filters.question_number:
        parts.append(f"题号={filters.question_number}")
    if filters.question_type_id is not None:
        parts.append(f"题型ID={filters.question_type_id}")
    if filters.difficulty is not None:
        parts.append(f"难度={filters.difficulty}")
    return "；".join(parts) if parts else "全部题目"


def filter_export_default_filename(filters: QuestionListFilters | None = None) -> str:
    """Return a readable default filename for a filtered combined export."""
    return sanitize_tex_filename_component(f"SQLite筛选导出_{filter_export_label(filters)}", "sqlite_filter_export") + ".tex"


def safe_legacy_export_relative_path(question: dict) -> Path:
    """Return a safe relative path that mirrors the legacy TeX location."""
    question_id = _text(question.get("question_id")) or "question"
    raw_path = _text(question.get("legacy_file_path"))
    if not raw_path:
        return Path("unmapped") / f"{sanitize_tex_filename_component(question_id)}.tex"

    normalized = raw_path.replace("\\", "/").lstrip("/")
    candidate = Path(normalized)
    if candidate.is_absolute() or any(part in ("", ".", "..") for part in candidate.parts):
        return Path("unmapped") / f"{sanitize_tex_filename_component(question_id)}.tex"
    if candidate.suffix.lower() != ".tex":
        candidate = candidate.with_suffix(".tex")
    return candidate


def get_filtered_export_bundle(
    db_path: str | None,
    filters: QuestionListFilters | None = None,
    *,
    max_questions: int = 500,
    start_offset: int = 0,
) -> dict[str, Any]:
    """Return full questions matching filters without rendering previews."""
    filters = filters or QuestionListFilters()
    total = count_questions(db_path, filters)
    safe_start_offset = max(0, int(start_offset or 0))
    available = max(0, total - safe_start_offset)
    safe_max = int(max_questions or 0)
    export_limit = available if safe_max <= 0 else min(available, max(1, safe_max))

    items: list[dict[str, Any]] = []
    fetched = 0
    while fetched < export_limit:
        page_limit = min(100, export_limit - fetched)
        page_filters = _filters_for_export_page(filters, page_limit, safe_start_offset + fetched)
        rows = list_questions(db_path, page_filters)
        if not rows:
            break
        for row in rows:
            question_id = _text(row.get("question_id"))
            if not question_id:
                continue
            question = get_question(db_path, question_id)
            if not question:
                continue
            items.append(
                {
                    "question_id": question_id,
                    "relation": row,
                    "position_label": str(safe_start_offset + len(items) + 1),
                    "question": question,
                }
            )
        fetched += len(rows)

    return {
        "source_kind": "filter",
        "source_kind_label": "筛选",
        "source_id": "",
        "source_label": filter_export_label(filters),
        "total": total,
        "start_offset": safe_start_offset,
        "question_count": len(items),
        "truncated": safe_start_offset + len(items) < total,
        "items": items,
    }


def _filter_export_header(bundle: dict, generated_at: str) -> str:
    return "\n".join(
        [
            "% === MathCyclus SQLite Filter Export ===",
            f"% Filter: {bundle.get('source_label') or '全部题目'}",
            f"% Total Matched: {bundle.get('total') or 0}",
            f"% Exported Questions: {bundle.get('question_count') or 0}",
            f"% Start Offset: {bundle.get('start_offset') or 0}",
            f"% Truncated: {bool(bundle.get('truncated'))}",
            f"% Generated At: {generated_at}",
            "% This file is generated from SQLite and does not modify legacy source files.",
            "% === End Export Metadata ===",
        ]
    )


def export_filtered_questions_to_tex(
    db_path: str | None,
    filters: QuestionListFilters | None,
    output_path: str | Path,
    *,
    project_root: str | Path | None = None,
    max_questions: int = 500,
    start_offset: int = 0,
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> dict[str, Any]:
    """Export questions matching filters into one ordered TeX file."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    bundle = get_filtered_export_bundle(
        db_path,
        filters,
        max_questions=max_questions,
        start_offset=start_offset,
    )
    if not bundle["items"]:
        raise ValueError("当前筛选条件没有可导出的题目")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sections = [_filter_export_header(bundle, generated_at), ""]
    graphics_rows: list[dict[str, str]] = []

    for index, item in enumerate(bundle["items"], start=1):
        question = item["question"]
        question_id = item["question_id"]
        tex = question_to_legacy_tex(question).rstrip()

        if copy_graphics:
            tex, graphics = copy_graphics_for_export(question, tex, target.parent, root)
        else:
            graphics = collect_graphics_export_status(question, root)

        if resolve_questionassets:
            tex, asset_placeholders = copy_questionassets_for_export(
                question,
                tex,
                target.parent,
                root,
                db_path=db_path,
            )
        else:
            asset_placeholders = collect_asset_placeholder_export_status(question, root, db_path)

        for graphic in graphics + asset_placeholders:
            graphics_rows.append({"question_id": question_id, **graphic})

        position = item.get("position_label") or str(index)
        sections.append(f"% --- {index}. {position} · {question_id} ---")
        sections.append(tex)
        sections.append("")

    target.write_text("\n".join(sections).rstrip() + "\n", encoding="utf-8")
    return {
        "source_kind": "filter",
        "source_kind_label": "筛选",
        "source_id": "",
        "source_label": bundle["source_label"],
        "total": bundle["total"],
        "start_offset": bundle["start_offset"],
        "question_count": bundle["question_count"],
        "truncated": bundle["truncated"],
        "output_path": str(target),
        "graphics": graphics_rows,
        "questions": [
            {
                "question_id": item["question_id"],
                "position_label": item.get("position_label") or "",
            }
            for item in bundle["items"]
        ],
    }


def export_legacy_tree_to_tex(
    db_path: str | None,
    output_dir: str | Path,
    filters: QuestionListFilters | None = None,
    *,
    project_root: str | Path | None = None,
    max_questions: int = 0,
    start_offset: int = 0,
    copy_graphics: bool = False,
    resolve_questionassets: bool = False,
) -> dict[str, Any]:
    """Export matching questions as one file per question, mirroring legacy paths."""
    root = Path(project_root) if project_root is not None else Path(__file__).resolve().parents[1]
    target_root = Path(output_dir)
    target_root.mkdir(parents=True, exist_ok=True)
    bundle = get_filtered_export_bundle(
        db_path,
        filters,
        max_questions=max_questions,
        start_offset=start_offset,
    )
    if not bundle["items"]:
        raise ValueError("当前条件没有可导出的题目")

    exported: list[dict[str, Any]] = []
    graphics_rows: list[dict[str, str]] = []
    used_paths: set[Path] = set()

    for item in bundle["items"]:
        question = item["question"]
        question_id = item["question_id"]
        rel_path = safe_legacy_export_relative_path(question)
        target = target_root / rel_path
        if target in used_paths:
            target = target.with_name(f"{target.stem}_{sanitize_tex_filename_component(question_id)}{target.suffix}")
            rel_path = target.relative_to(target_root)
        used_paths.add(target)

        tex = question_to_legacy_tex(question)
        if copy_graphics:
            tex, graphics = copy_graphics_for_export(question, tex, target.parent, root)
        else:
            graphics = collect_graphics_export_status(question, root)
        if resolve_questionassets:
            tex, asset_placeholders = copy_questionassets_for_export(
                question,
                tex,
                target.parent,
                root,
                db_path=db_path,
            )
        else:
            asset_placeholders = collect_asset_placeholder_export_status(question, root, db_path)

        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(tex.rstrip() + "\n", encoding="utf-8")
        row = {
            "question_id": question_id,
            "legacy_file_path": _text(question.get("legacy_file_path")),
            "output_path": str(target),
            "relative_output_path": rel_path.as_posix(),
            "graphics": graphics + asset_placeholders,
        }
        exported.append(row)
        for graphic in graphics + asset_placeholders:
            graphics_rows.append({"question_id": question_id, **graphic})

    return {
        "source_kind": "legacy_tree",
        "source_kind_label": "旧目录结构",
        "source_id": "",
        "source_label": bundle["source_label"],
        "total": bundle["total"],
        "start_offset": bundle["start_offset"],
        "question_count": len(exported),
        "truncated": bundle["truncated"],
        "output_dir": str(target_root),
        "graphics": graphics_rows,
        "files": exported,
    }


def export_question_to_tex(db_path: str, question_id: str, output_path: str | Path) -> str:
    """Export one question from SQLite to a TeX file and return the output path."""
    question = get_question(db_path, question_id)
    if not question:
        raise KeyError(f"question not found: {question_id}")
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(question_to_legacy_tex(question), encoding="utf-8")
    return str(target)
