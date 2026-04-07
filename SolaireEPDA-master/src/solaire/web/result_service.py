"""Result exam management: history listing, score template, import, and statistics.

Exports exam.yaml to result/{exam_name}/ during PDF export (see exam_service.export_pdfs).
This module provides history browsing, score template generation, CSV/Excel import,
and fuzzy-statistics computation linked to the knowledge graph.
"""

from __future__ import annotations

import csv
import io
import json
import math
import os
import platform
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import yaml

from solaire.exam_compiler.facade import ExamConfig, SelectedSection
from solaire.knowledge_forge import load_graph
from solaire.web.security import assert_within_project


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _safe_float(val: str | None, default: float | None = None) -> float | None:
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        return default


# ---------------------------------------------------------------------------
# Data models (plain dicts for JSON serialization)
# ---------------------------------------------------------------------------

class ExamQuestion:
    """Flattened question from selected_items."""

    section_idx: int
    section_id: str
    question_in_section: int  # 1-based
    question_id: str
    score_per_item: float

    def csv_header(self) -> str:
        return f"{self.section_idx}.{self.question_in_section}"


# ---------------------------------------------------------------------------
# Core service functions
# ---------------------------------------------------------------------------

def _iter_result_dirs(project_root: Path):
    """Yield (exam_id, dir_path, exam_yaml_path) for result subdirs that have exam.yaml."""
    result_root = (project_root / "result").resolve()
    if not result_root.is_dir():
        return
    assert_within_project(project_root, result_root)
    for d in sorted(result_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not d.is_dir():
            continue
        exam_yaml = d / "exam.yaml"
        if exam_yaml.is_file():
            yield d.name, d, exam_yaml


def _load_exam_config(exam_yaml_path: Path) -> ExamConfig:
    with exam_yaml_path.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return ExamConfig.model_validate(raw)


def _safe_result_exam_id(exam_id: str) -> str:
    s = exam_id.strip().replace("\\", "/")
    if not s or "/" in s or ".." in s or s.startswith("."):
        raise ValueError("无效的考试目录标识")
    return Path(s).name


def find_exported_pdf_path(
    project_root: Path,
    exam_id: str,
    *,
    variant: Literal["student", "teacher"],
) -> Path:
    """Return path to student or teacher PDF under result/{exam_id}/ (export naming uses 学生版 / 教师版)."""
    eid = _safe_result_exam_id(exam_id)
    d = (project_root / "result" / eid).resolve()
    assert_within_project(project_root, d)
    if not d.is_dir():
        raise FileNotFoundError(f"未找到考试结果目录: {eid}")
    marker = "学生版" if variant == "student" else "教师版"
    for p in sorted(d.glob("*.pdf")):
        if marker in p.name:
            return p
    raise FileNotFoundError(f"目录中未找到含「{marker}」的 PDF")


def open_pdf_with_default_app(path: Path) -> None:
    """Open a PDF with the OS default handler (local backend only)."""
    target = path.resolve()
    if not target.is_file():
        raise FileNotFoundError(str(target))
    system = platform.system()
    if system == "Windows":
        os.startfile(str(target))  # type: ignore[attr-defined]
    elif system == "Darwin":
        subprocess.run(["open", str(target)], check=False)
    else:
        subprocess.run(["xdg-open", str(target)], check=False)


def _flatten_questions(exam: ExamConfig) -> list[ExamQuestion]:
    """Flatten selected_items to ordered ExamQuestion list."""
    questions: list[ExamQuestion] = []
    for sec_idx, section in enumerate(exam.selected_items, start=1):
        overrides = section.score_overrides or {}
        default_sec = section.score_per_item if section.score_per_item is not None else 5.0
        for qi, qid in enumerate(section.question_ids, start=1):
            if qid in overrides:
                spc = float(overrides[qid])
            else:
                spc = float(default_sec)
            q = ExamQuestion()
            q.section_idx = sec_idx
            q.section_id = section.section_id
            q.question_in_section = qi
            q.question_id = qid
            q.score_per_item = spc
            questions.append(q)
    return questions


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def list_exam_results(project_root: Path) -> list[dict[str, Any]]:
    """Return list of past exams (newest first) with basic metadata."""
    exams: list[dict[str, Any]] = []
    for exam_id, dir_path, exam_yaml_path in _iter_result_dirs(project_root):
        mtime = datetime.fromtimestamp(dir_path.stat().st_mtime, tz=timezone.utc)
        try:
            exam = _load_exam_config(exam_yaml_path)
            meta = exam.metadata or {}
            questions = _flatten_questions(exam)
            score_batches = _list_score_batches(dir_path)
            exams.append({
                "exam_id": exam_id,
                "exam_title": meta.get("title", exam_id),
                "subject": meta.get("subject"),
                "export_label": meta.get("export_label"),
                "template_ref": exam.template_ref,
                "question_count": len(questions),
                "section_count": len(exam.selected_items),
                "score_batch_count": len(score_batches),
                "has_score": len(score_batches) > 0,
                "latest_batch_id": score_batches[0]["batch_id"] if score_batches else None,
                "result_dir": exam_id,
                "mtime": mtime.isoformat(),
            })
        except Exception:
            # 旧版目录结构或不完整exam.yaml，降级显示
            exams.append({
                "exam_id": exam_id,
                "exam_title": exam_id,
                "subject": None,
                "export_label": exam_id,
                "template_ref": None,
                "question_count": 0,
                "section_count": 0,
                "score_batch_count": 0,
                "has_score": False,
                "latest_batch_id": None,
                "result_dir": exam_id,
                "mtime": mtime.isoformat(),
            })
    return exams


def get_exam_summary(project_root: Path, exam_id: str) -> dict[str, Any]:
    """Return exam detail: metadata + question list with scores."""
    result_root = (project_root / "result").resolve()
    dir_path = result_root / exam_id
    assert_within_project(project_root, dir_path)
    if not dir_path.is_dir():
        raise FileNotFoundError(f"Exam not found: {exam_id}")

    exam_yaml = dir_path / "exam.yaml"
    if not exam_yaml.is_file():
        raise FileNotFoundError(f"exam.yaml not found for: {exam_id}")

    exam = _load_exam_config(exam_yaml)
    meta = exam.metadata or {}
    questions = _flatten_questions(exam)
    score_batches = _list_score_batches(dir_path)

    return {
        "exam_id": exam_id,
        "exam_title": meta.get("title", exam_id),
        "subject": meta.get("subject"),
        "export_label": meta.get("export_label"),
        "template_ref": exam.template_ref,
        "questions": [
            {
                "idx": q.section_idx,
                "section_id": q.section_id,
                "question_in_section": q.question_in_section,
                "question_id": q.question_id,
                "score_per_item": q.score_per_item,
                "header": q.csv_header(),
            }
            for q in questions
        ],
        "section_count": len(exam.selected_items),
        "question_count": len(questions),
        "score_batches": score_batches,
        "result_dir": exam_id,
    }


def generate_score_template(project_root: Path, exam_id: str) -> tuple[str, str]:
    """
    Generate a score CSV template for the given exam.
    Returns (csv_content, suggested_filename).
    """
    summary = get_exam_summary(project_root, exam_id)
    questions = summary["questions"]

    buf = io.StringIO()
    # Header row
    headers = ["姓名", "学号"] + [q["header"] for q in questions]
    writer = csv.writer(buf)
    writer.writerow(headers)

    # Example hint row (填入实际成绩)
    hint_row = ["张三", "001"] + ["" for _ in questions]
    writer.writerow(hint_row)

    # Second example
    writer.writerow(["李四", "002"])

    csv_content = buf.getvalue()
    title_slug = (summary.get("exam_title") or exam_id).replace("/", "-")
    subject_slug = (summary.get("subject") or "").replace("/", "-")
    date_str = datetime.now(timezone.utc).strftime("%Y%m%d")
    filename = f"成绩表_{title_slug}_{subject_slug}_{date_str}.csv"
    return csv_content, filename


def _list_score_batches(result_dir: Path) -> list[dict[str, Any]]:
    scores_dir = result_dir / "scores"
    if not scores_dir.is_dir():
        return []
    batches: list[dict[str, Any]] = []
    for bd in sorted(scores_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not bd.is_dir():
            continue
        scores_csv = bd / "scores.csv"
        analysis_json = bd / "analysis.json"
        mtime = datetime.fromtimestamp(bd.stat().st_mtime, tz=timezone.utc)
        student_count = 0
        question_count = 0
        if analysis_json.is_file():
            try:
                with analysis_json.open(encoding="utf-8") as f:
                    data = json.load(f)
                    student_count = data.get("student_count", 0)
                    question_count = data.get("question_count", 0)
            except Exception:
                pass
        elif scores_csv.is_file():
            try:
                with scores_csv.open(encoding="utf-8") as f:
                    reader = csv.reader(f)
                    rows = list(reader)
                    student_count = max(0, len(rows) - 1)  # subtract header
                    if rows:
                        question_count = max(0, len(rows[0]) - 2)
            except Exception:
                pass
        batches.append({
            "batch_id": bd.name,
            "imported_at": mtime.isoformat(),
            "student_count": student_count,
            "question_count": question_count,
        })
    return batches


def import_scores(
    project_root: Path,
    exam_id: str,
    file_bytes: bytes,
    filename: str,
) -> dict[str, Any]:
    """
    Parse uploaded CSV/Excel, validate, save to result/scores/{batch_id}/.
    Returns batch summary + unbound question warnings.
    """
    result_root = (project_root / "result").resolve()
    dir_path = result_root / exam_id
    assert_within_project(project_root, dir_path)

    exam_yaml = dir_path / "exam.yaml"
    if not exam_yaml.is_file():
        raise FileNotFoundError(f"exam.yaml not found for: {exam_id}")

    exam = _load_exam_config(exam_yaml)
    questions = _flatten_questions(exam)
    question_headers = [q.csv_header() for q in questions]

    # Parse CSV or Excel into row-based data
    raw_rows: list[list[str]]
    is_excel = filename.lower().endswith((".xlsx", ".xls"))
    if is_excel:
        try:
            import openpyxl
            from io import BytesIO as _BytesIO
            wb = openpyxl.load_workbook(_BytesIO(file_bytes))
            ws = wb.active
            raw_rows = [[str(v) if v is not None else "" for v in row] for row in ws.iter_rows(values_only=True)]
        except ImportError:
            raise ValueError("Excel 文件需要安装 openpyxl：pip install openpyxl") from None
    else:
        try:
            text = file_bytes.decode("utf-8-sig")  # handle BOM
        except UnicodeDecodeError:
            text = file_bytes.decode("gbk", errors="replace")
        reader = csv.reader(io.StringIO(text))
        raw_rows = list(reader)

    if len(raw_rows) < 2:
        raise ValueError("文件必须包含表头行和至少一行数据")

    header = [h.strip() for h in raw_rows[0]]
    data_rows = raw_rows[1:]

    # Build column index lookup
    # Primary: exact header match (after strip)
    header_to_idx: dict[str, int] = {h: i for i, h in enumerate(header)}
    # Score columns (non-name/id)
    score_col_indices: list[int] = [i for i, h in enumerate(header) if h not in ("姓名", "学号")]

    col_name = next((i for i, h in enumerate(header) if h.strip() == "姓名"), -1)
    col_id = next((i for i, h in enumerate(header) if h.strip() == "学号"), -1)

    # Missing header diagnostics
    missing_headers: list[str] = []
    for h in header:
        if h in ("姓名", "学号"):
            continue
        if h not in question_headers:
            # 部分匹配：允许列头有空格
            matched = [qh for qh in question_headers if qh == h.strip()]
            if not matched:
                missing_headers.append(h)

    # Parse students
    students: list[dict[str, Any]] = []
    position_fallback_used = False
    for ri, row in enumerate(data_rows, start=2):
        if not row or all(not str(c).strip() for c in row):
            continue
        name = str(row[col_name]).strip() if col_name >= 0 and col_name < len(row) else f"学生{ri-1}"
        student_id = str(row[col_id]).strip() if col_id >= 0 and col_id < len(row) else ""

        scores: list[float | None] = []
        for qi, q in enumerate(questions):
            raw_score: str | None = None
            if q.csv_header() in header_to_idx:
                idx = header_to_idx[q.csv_header()]
                raw_score = str(row[idx]).strip() if idx < len(row) else None
            elif qi < len(score_col_indices):
                # Fallback: use positional match when header doesn't align exactly
                idx = score_col_indices[qi]
                raw_score = str(row[idx]).strip() if idx < len(row) else None
                position_fallback_used = True
            scores.append(_safe_float(raw_score))

        students.append({"name": name, "student_id": student_id, "scores": scores})

    if not students:
        raise ValueError("文件中没有找到有效学生数据")

    # Create batch dir
    batch_id = uuid.uuid4().hex
    scores_dir = dir_path / "scores" / batch_id
    scores_dir.mkdir(parents=True, exist_ok=True)

    # Save canonical CSV
    csv_path = scores_dir / "scores.csv"
    if is_excel:
        # Save openpyxl rows as CSV
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerows(raw_rows)
        csv_text = buf.getvalue()
    else:
        try:
            csv_text = file_bytes.decode("utf-8-sig")
        except UnicodeDecodeError:
            csv_text = file_bytes.decode("gbk", errors="replace")
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        f.write(csv_text)

    # Import warnings
    warnings: list[dict[str, str]] = []
    if missing_headers:
        warnings.append({
            "type": "missing_columns",
            "message": f"以下列头在模板中未找到：{', '.join(missing_headers)}，相关列的得分可能无法正确计算",
        })
    if position_fallback_used:
        warnings.append({
            "type": "position_fallback",
            "message": "部分列头与模板不完全匹配，已按列顺序映射。请检查得分是否对应正确的题目。",
        })

    # Save placeholder analysis (will be completed by compute_statistics)
    analysis_path = scores_dir / "analysis.json"
    placeholder: dict[str, Any] = {
        "batch_id": batch_id,
        "exam_id": exam_id,
        "student_count": len(students),
        "question_count": len(questions),
        "imported_at": _now_utc().isoformat(),
        "warnings": warnings,
        "question_stats": [],
        "node_stats": [],
        "student_stats": [],
    }
    with analysis_path.open("w", encoding="utf-8") as f:
        json.dump(placeholder, f, ensure_ascii=False, indent=2)

    return {
        "batch_id": batch_id,
        "student_count": len(students),
        "question_count": len(questions),
        "warnings": warnings,
        "missing_headers": missing_headers,
    }


def delete_score_batch(project_root: Path, exam_id: str, batch_id: str) -> dict[str, Any]:
    """Delete one imported score batch directory under result/{exam_id}/scores/{batch_id}."""
    result_root = (project_root / "result").resolve()
    batch_dir = (result_root / exam_id / "scores" / batch_id).resolve()
    assert_within_project(project_root, batch_dir)
    if not batch_dir.is_dir():
        raise FileNotFoundError(f"Score batch not found: {batch_id}")
    shutil.rmtree(batch_dir)
    return {"ok": True, "exam_id": exam_id, "batch_id": batch_id}


def delete_exam_result(project_root: Path, exam_id: str) -> dict[str, Any]:
    """Delete one exam result directory under result/{exam_id}."""
    result_root = (project_root / "result").resolve()
    exam_dir = (result_root / exam_id).resolve()
    assert_within_project(project_root, exam_dir)
    if not exam_dir.is_dir():
        raise FileNotFoundError(f"Exam not found: {exam_id}")
    shutil.rmtree(exam_dir)
    return {"ok": True, "exam_id": exam_id}


def compute_statistics(
    project_root: Path,
    exam_id: str,
    batch_id: str,
) -> dict[str, Any]:
    """
    Load scores for a batch, compute per-question / per-student / per-node stats.
    Fuzzy scoring: score_ratio = actual / score_per_item (0~1 float).
    Node error rate = 1 - fuzzy_AND(score_ratios of bound questions).
    """
    result_root = (project_root / "result").resolve()
    dir_path = result_root / exam_id
    assert_within_project(project_root, dir_path)

    exam_yaml = dir_path / "exam.yaml"
    if not exam_yaml.is_file():
        raise FileNotFoundError(f"exam.yaml not found for: {exam_id}")

    # Load exam structure
    exam = _load_exam_config(exam_yaml)
    questions = _flatten_questions(exam)

    # Load scores
    scores_csv = dir_path / "scores" / batch_id / "scores.csv"
    if not scores_csv.is_file():
        raise FileNotFoundError(f"Scores not found: {batch_id}")

    with scores_csv.open(encoding="utf-8") as f:
        raw_text = f.read()

    reader = csv.reader(io.StringIO(raw_text))
    rows = list(reader)
    header = [h.strip() for h in rows[0]]
    data_rows = rows[1:]

    header_lower = [h.strip().lower() for h in header]
    col_name = header_lower.index("姓名") if "姓名" in header_lower else -1
    col_id = header_lower.index("学号") if "学号" in header_lower else -1

    # Primary: exact header match
    header_to_idx = {h: i for i, h in enumerate(header) if h not in ("姓名", "学号")}

    # Fallback: position-based mapping for score columns
    # (useful when Excel re-saves headers with extra spaces or encoding differences)
    score_col_indices: list[int] = [i for i, h in enumerate(header) if h not in ("姓名", "学号")]

    students: list[dict[str, Any]] = []
    column_warnings: list[str] = []
    for ri, row in enumerate(data_rows):
        if not row or all(not c.strip() for c in row):
            continue
        name = row[col_name].strip() if col_name >= 0 else f"学生{ri+1}"
        student_id = row[col_id].strip() if col_id >= 0 else ""
        scores: list[float | None] = []
        matched_by_position = False
        for qi, q in enumerate(questions):
            raw = None
            if q.csv_header() in header_to_idx:
                idx = header_to_idx[q.csv_header()]
                raw = row[idx].strip() if idx < len(row) else None
            elif qi < len(score_col_indices):
                # Fallback: use positional match when header doesn't align exactly
                idx = score_col_indices[qi]
                raw = row[idx].strip() if idx < len(row) else None
                matched_by_position = True
            scores.append(_safe_float(raw))
        if matched_by_position and not column_warnings:
            column_warnings.append(
                f"部分列头与模板不完全匹配，已按顺序位置映射。如得分异常请检查列顺序是否与模板一致。"
            )
        students.append({"name": name, "student_id": student_id, "scores": scores})

    if not students:
        raise ValueError("No student data found")

    # Per-question statistics
    n_students = len(students)
    question_stats: list[dict[str, Any]] = []
    for qi, q in enumerate(questions):
        answered = [s["scores"][qi] for s in students if s["scores"][qi] is not None]
        # Diagnostic: first student's raw CSV value for this question
        first_raw = students[0]["scores"][qi] if students and qi < len(students[0]["scores"]) else None
        if not answered:
            err_rate = None
            avg_score = None
            fuzzy_score = None
        else:
            avg_score = sum(answered) / len(answered)
            # Score ratio (fuzzy membership: 0=wrong, 1=full correct)
            fuzzy_scores = [min(max(s / q.score_per_item, 0.0), 1.0) for s in answered]
            fuzzy_score = sum(fuzzy_scores) / len(fuzzy_scores)
            correct_count = sum(1 for s in answered if s >= q.score_per_item * 0.5)
            err_rate = 1.0 - correct_count / len(answered)
        question_stats.append({
            "question_id": q.question_id,
            "header": q.csv_header(),
            "section_id": q.section_id,
            "score_per_item": q.score_per_item,
            "answered_count": len(answered),
            "error_rate": err_rate,
            "avg_score_ratio": fuzzy_score,  # fuzzy membership 0~1
            "avg_raw_score": avg_score,
            # Diagnostic: what was actually read from CSV (first student)
            "first_csv_raw": first_raw,
        })

    # Per-student statistics
    total_score = sum(q.score_per_item for q in questions)
    student_stats: list[dict[str, Any]] = []
    raw_totals: list[tuple[int, float]] = []  # (index, total)
    for si, st in enumerate(students):
        valid_scores = [(q, st["scores"][qi] or 0.0) for qi, q in enumerate(questions)]
        raw_total = sum(s for _, s in valid_scores)
        score_ratio = raw_total / total_score if total_score > 0 else 0.0
        # Fuzzy total score: use weighted average of question fuzzy memberships
        fuzzy_total = 0.0
        if questions:
            fuzzy_total = sum(
                min(max((st["scores"][qi] or 0.0) / q.score_per_item, 0.0), 1.0)
                for qi, q in enumerate(questions)
                if q.score_per_item > 0
            ) / len(questions)
        student_stats.append({
            "name": st["name"],
            "student_id": st["student_id"],
            "raw_total": round(raw_total, 2),
            "score_ratio": round(score_ratio, 4),
            "fuzzy_score": round(fuzzy_total, 4),  # fuzzy aggregation 0~1
        })
        raw_totals.append((si, raw_total))

    # Rank students by score_ratio descending
    ranked = sorted(raw_totals, key=lambda x: x[1], reverse=True)
    rank_map: dict[int, int] = {idx: rank + 1 for rank, (idx, _) in enumerate(ranked)}
    for st in student_stats:
        idx = next(i for i, s in enumerate(students) if s["name"] == st["name"] and s["student_id"] == st["student_id"])
        st["rank"] = rank_map.get(idx, 0)
        st["class_rank"] = st["rank"]
        st["total_in_class"] = len(students)

    # Per-knowledge-node statistics (fuzzy)
    # Build node -> questions mapping by scanning all bindings
    # question_ids in exam.yaml are full qualified IDs (namespace/short_id)
    node_question_map: dict[str, list[str]] = {}
    try:
        state = load_graph(project_root)
        exam_qids = {q.question_id for q in questions}
        for binding in state.bindings:
            qid = binding.question_qualified_id
            if qid in exam_qids:
                node_question_map.setdefault(binding.node_id, []).append(qid)
    except Exception:
        pass

    # Compute node-level fuzzy error rate
    node_stats: list[dict[str, Any]] = []
    for node_id, bound_qids in node_question_map.items():
        if not bound_qids:
            continue
        # Fuzzy AND: mastery = min(score_ratios of all bound questions)
        # Error rate = 1 - mastery
        min_fuzzy = 1.0
        for qid in bound_qids:
            for qi, q in enumerate(questions):
                if q.question_id == qid:
                    answered = [s["scores"][qi] for s in students if s["scores"][qi] is not None]
                    if answered:
                        fuzzy_ratios = [min(max(s / q.score_per_item, 0.0), 1.0) for s in answered]
                        avg_fuzzy = sum(fuzzy_ratios) / len(fuzzy_ratios)
                        min_fuzzy = min(min_fuzzy, avg_fuzzy)
                    break
        mastery = min_fuzzy if min_fuzzy < 1.0 else 1.0
        error_rate = 1.0 - mastery
        node_stats.append({
            "node_id": node_id,
            "bound_question_count": len(bound_qids),
            "bound_questions": bound_qids,
            "mastery_fuzzy": round(mastery, 4),  # fuzzy membership 0~1
            "error_rate": round(error_rate, 4),
        })

    # Warn about unbound questions (compare full qualified IDs)
    unbound_warnings: list[dict[str, str]] = []
    bound_qids_flat: set[str] = set()
    try:
        state = load_graph(project_root)
        exam_qids = {q.question_id for q in questions}
        for b in state.bindings:
            if b.question_qualified_id in exam_qids:
                bound_qids_flat.add(b.question_qualified_id)
    except Exception:
        pass

    for q in questions:
        if q.question_id not in bound_qids_flat:
            unbound_warnings.append({
                "question_id": q.question_id,
                "header": q.csv_header(),
                "section_id": q.section_id,
                "message": f"第{q.csv_header()}题（{q.question_id}）未绑定知识点节点，请在知识图谱页面绑定后再查看节点统计",
            })

    # Save computed analysis
    analysis_path = dir_path / "scores" / batch_id / "analysis.json"
    student_mastery_rows: list[dict[str, Any]] = []
    for st in students:
        ratios: list[float | None] = []
        for qi, q in enumerate(questions):
            raw_s = st["scores"][qi] if qi < len(st["scores"]) else None
            if raw_s is None:
                ratios.append(None)
            elif q.score_per_item and q.score_per_item > 0:
                ratios.append(round(min(max(raw_s / q.score_per_item, 0.0), 1.0), 4))
            else:
                ratios.append(None)
        student_mastery_rows.append(
            {"name": st["name"], "student_id": st["student_id"], "ratios": ratios},
        )
    analysis_data = {
        "batch_id": batch_id,
        "exam_id": exam_id,
        "student_count": len(students),
        "question_count": len(questions),
        "imported_at": _now_utc().isoformat(),
        "warnings": unbound_warnings,
        "question_order": [q.question_id for q in questions],
        "student_mastery_rows": student_mastery_rows,
        "question_stats": question_stats,
        "node_stats": node_stats,
        "student_stats": student_stats,
        "class_avg_ratio": round(sum(s["score_ratio"] for s in student_stats) / len(student_stats), 4) if student_stats else 0,
        "class_avg_fuzzy": round(sum(s["fuzzy_score"] for s in student_stats) / len(student_stats), 4) if student_stats else 0,
    }
    with analysis_path.open("w", encoding="utf-8") as f:
        json.dump(analysis_data, f, ensure_ascii=False, indent=2)

    return analysis_data


def get_score_analysis(project_root: Path, exam_id: str, batch_id: str) -> dict[str, Any]:
    """Return cached analysis for a score batch (recompute if stale)."""
    result_root = (project_root / "result").resolve()
    dir_path = result_root / exam_id
    assert_within_project(project_root, dir_path)
    analysis_path = dir_path / "scores" / batch_id / "analysis.json"
    if not analysis_path.is_file():
        return compute_statistics(project_root, exam_id, batch_id)
    with analysis_path.open(encoding="utf-8") as f:
        data = json.load(f)
    # If cache missing fields needed for学情诊断视图，重算
    if "warnings" not in data or "student_mastery_rows" not in data or "question_order" not in data:
        return compute_statistics(project_root, exam_id, batch_id)
    return data


class ResultServiceAdapter:
    """Adapter that implements edu_analysis.ports.ResultDataPort using result_service functions.

    web 层在应用启动时将此类实例注入 edu_analysis：
        from solaire.edu_analysis.ports import configure
        configure(result_port=ResultServiceAdapter())
    """

    def list_exam_results(self, project_root: Path) -> list[dict[str, Any]]:
        return list_exam_results(project_root)

    def compute_statistics(
        self, project_root: Path, exam_id: str, batch_id: str
    ) -> dict[str, Any]:
        return compute_statistics(project_root, exam_id, batch_id)

    def get_score_analysis(
        self, project_root: Path, exam_id: str, batch_id: str
    ) -> dict[str, Any]:
        return get_score_analysis(project_root, exam_id, batch_id)
