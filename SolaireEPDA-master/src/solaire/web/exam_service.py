"""Exam YAML assembly, validation, and PDF export helpers."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any

import yaml

from solaire.exam_compiler.facade import (
    ExamConfig,
    ExamTemplate,
    LatexmkError,
    QuestionLibraryRef,
    SelectedSection,
    analyze_math_static_for_loaded,
    build_exam_pdfs,
    format_latexmk_failure_message,
    load_all_questions,
    load_template,
    precheck_exam_latex_build,
    resolve_template_yaml_path,
    validate_exam,
)
from solaire.exam_compiler.loaders.questions import LoadedQuestions

from solaire.web.library_discovery import discover_question_library_refs
from solaire.web.project_layout import ensure_project_layout
from solaire.web.security import assert_within_project, safe_filename_component, unique_child_dir

# Re-use result iteration for export conflict detection
from solaire.web.result_service import _iter_result_dirs, _load_exam_config


LIST_PROBE_NAME = "list.yaml"
BUILD_EXAM_NAME = "build.yaml"
BUILD_BACKUP_NAME = "build.yaml.before_export"
VALIDATE_EXAM_NAME = "validate.yaml"


def snapshot_build_yaml_before_export(project_root: Path) -> Path | None:
    """
    若已存在 .solaire/build.yaml，则复制为 build.yaml.before_export（覆盖旧备份）。
    在写入新组卷配置前调用，以便导出失败时恢复上一版选题。
    """
    ensure_project_layout(project_root)
    sol = project_root / ".solaire"
    build = sol / BUILD_EXAM_NAME
    backup = sol / BUILD_BACKUP_NAME
    if not build.is_file():
        return None
    shutil.copy2(build, backup)
    return backup


def restore_build_yaml_from_backup(project_root: Path, backup: Path | None) -> None:
    """将备份写回 .solaire/build.yaml（若备份存在）。"""
    if backup is None or not backup.is_file():
        return
    sol = project_root / ".solaire"
    build = sol / BUILD_EXAM_NAME
    shutil.copy2(backup, build)


def discard_build_yaml_backup(backup: Path | None) -> None:
    """导出成功后删除临时备份文件。"""
    if backup is not None and backup.is_file():
        backup.unlink()


def _is_missing_pdf_toolchain_message(msg: str) -> bool:
    """True when failure is due to latexmk/xelatex not installed or not on PATH."""
    lower = msg.lower()
    if "latexmk not found" in lower:
        return True
    if "xelatex" in lower and "not found" in lower:
        return True
    if "ensure latexmk is on path" in lower:
        return True
    if "install tex live" in lower or "install miktex" in lower:
        return True
    return False


def exam_export_error_detail_short(exc: Exception, *, max_len: int = 160) -> str:
    """HTTP 响应中的单行摘要；完整内容须写入服务端日志。"""
    msg = str(exc).strip().replace("\r\n", "\n")
    if _is_missing_pdf_toolchain_message(msg):
        return (
            "未检测到用于导出试卷的 PDF 排版组件。请先安装 MiKTeX 或 TeX Live，"
            "安装完成后重试导出；也可在组卷页使用「一键安装」尝试。"
        )
    first = msg.split("\n")[0].strip()
    if len(first) > max_len:
        first = first[:max_len] + "…"
    if not first:
        return "操作失败，请查看运行日志。"
    return first


def _exam_yaml_in_solaire(project_root: Path) -> Path:
    return project_root / ".solaire" / LIST_PROBE_NAME


def ensure_probe_list_yaml(project_root: Path) -> Path:
    """Regenerate probe exam with discovered question_libraries (题集 / namespaces)."""
    ensure_project_layout(project_root)
    solaire = project_root / ".solaire"
    solaire.mkdir(parents=True, exist_ok=True)
    probe = _exam_yaml_in_solaire(project_root)
    refs = discover_question_library_refs(project_root)
    body: dict[str, Any] = {
        "exam_id": "_list",
        "template_ref": "_dummy",
        "question_libraries": [{"path": r["path"], "namespace": r["namespace"]} for r in refs],
        "selected_items": [],
    }
    with probe.open("w", encoding="utf-8") as f:
        yaml.safe_dump(body, f, allow_unicode=True, sort_keys=False)
    return probe


def template_path_for_exam_under_solaire(_project_root: Path, template_relative: str) -> str:
    """Relative path from .solaire/*.yaml to project templates file."""
    rel = template_relative.replace("\\", "/").strip("/")
    return f"../{rel}"


def write_exam_yaml(
    project_root: Path,
    *,
    yaml_basename: str,
    exam_id: str,
    template_ref: str,
    template_relative: str,
    metadata: dict[str, Any],
    selected_items: list[SelectedSection],
) -> Path:
    solaire = project_root / ".solaire"
    solaire.mkdir(parents=True, exist_ok=True)
    out = solaire / yaml_basename
    refs = discover_question_library_refs(project_root)
    libs = [QuestionLibraryRef(path=r["path"], namespace=r["namespace"]) for r in refs]
    exam = ExamConfig(
        exam_id=exam_id,
        template_ref=template_ref,
        metadata=metadata,
        question_libraries=libs,
        template_path=template_path_for_exam_under_solaire(project_root, template_relative),
        selected_items=selected_items,
    )
    raw = exam.model_dump(mode="json")
    with out.open("w", encoding="utf-8") as f:
        yaml.safe_dump(raw, f, allow_unicode=True, sort_keys=False)
    return out


def write_build_exam_yaml(
    project_root: Path,
    *,
    exam_id: str,
    template_ref: str,
    template_relative: str,
    metadata: dict[str, Any],
    selected_items: list[SelectedSection],
) -> Path:
    return write_exam_yaml(
        project_root,
        yaml_basename=BUILD_EXAM_NAME,
        exam_id=exam_id,
        template_ref=template_ref,
        template_relative=template_relative,
        metadata=metadata,
        selected_items=selected_items,
    )


def find_export_conflict(project_root: Path, export_label: str, subject: str) -> dict[str, Any]:
    """If any result exam matches export_label + subject metadata, return its folder id (newest first)."""
    label = export_label.strip()
    subj = subject.strip()
    for exam_id, _dir_path, exam_yaml_path in _iter_result_dirs(project_root):
        try:
            exam = _load_exam_config(exam_yaml_path)
            meta = exam.metadata or {}
            if str(meta.get("export_label", "")).strip() == label and str(meta.get("subject", "")).strip() == subj:
                return {
                    "conflict": True,
                    "existing_exam_id": exam_id,
                    "existing_dir": exam_id,
                }
        except Exception:
            continue
    return {"conflict": False, "existing_exam_id": None, "existing_dir": None}


def load_exam_for_validation(exam_yaml: Path) -> tuple[ExamConfig, LoadedQuestions, ExamTemplate]:
    """Load exam YAML, questions, template; run structural validate_exam."""
    with exam_yaml.open(encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    exam = ExamConfig.model_validate(raw)
    libs = [(lib.namespace, lib.path) for lib in exam.question_libraries]
    loaded = load_all_questions(exam_yaml, libs)
    tmpl_path = resolve_template_yaml_path(exam_yaml, exam)
    template = load_template(tmpl_path)
    validate_exam(exam, template, loaded)
    return exam, loaded, template


def run_validate(project_root: Path, exam_yaml: Path) -> None:
    assert_within_project(project_root, exam_yaml)
    load_exam_for_validation(exam_yaml)


def run_latex_precheck(exam_yaml: Path) -> tuple[bool, str | None]:
    """Full hydrate → TeX → latexmk; returns (True, None) or (False, user-facing excerpt)."""
    try:
        precheck_exam_latex_build(exam_yaml)
    except LatexmkError as e:
        return False, format_latexmk_failure_message(e)
    return True, None


def run_validate_with_checks(
    project_root: Path,
    exam_yaml: Path,
    *,
    include_latex_check: bool = False,
    include_math_static: bool = True,
) -> dict[str, Any]:
    """
    Structural validation plus optional LaTeX precheck and math delimiter static analysis.
    """
    assert_within_project(project_root, exam_yaml)
    _exam, loaded, _tmpl = load_exam_for_validation(exam_yaml)
    out: dict[str, Any] = {
        "structure_ok": True,
        "latex_ok": None,
        "latex_error_excerpt": None,
        "math_warnings": [],
    }
    if include_math_static:
        out["math_warnings"] = analyze_math_static_for_loaded(loaded)
    if include_latex_check:
        ok, err = run_latex_precheck(exam_yaml)
        out["latex_ok"] = ok
        out["latex_error_excerpt"] = err
    return out


def export_pdfs(
    project_root: Path,
    *,
    exam_yaml: Path,
    export_label: str,
    subject: str,
    template: ExamTemplate | None = None,
    overwrite_result_dir: Path | None = None,
) -> tuple[Path, str, str]:
    """
    Build PDFs into a unique result subdir, then rename to localized filenames.

    When ``overwrite_result_dir`` is set, that directory (under project ``result/``)
    is cleared and reused instead of allocating a new slug.

    Returns (result_dir, student_pdf_name, teacher_pdf_name).
    """
    assert_within_project(project_root, exam_yaml)
    result_root = project_root / "result"
    result_root.mkdir(parents=True, exist_ok=True)
    slug_base = safe_filename_component(export_label)
    if overwrite_result_dir is not None:
        dest = overwrite_result_dir.resolve()
        assert_within_project(project_root, dest)
        if result_root.resolve() not in dest.parents and dest.resolve() != result_root.resolve():
            raise ValueError("overwrite_result_dir must be under result/")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True, exist_ok=True)
    else:
        dest = unique_child_dir(result_root, slug_base)
        dest.mkdir(parents=True, exist_ok=True)

    try:
        student_pdf, teacher_pdf = build_exam_pdfs(exam_yaml, out_dir=dest)
    except LatexmkError as e:
        raise RuntimeError(format_latexmk_failure_message(e)) from e

    stem = f"{safe_filename_component(export_label)}-{safe_filename_component(subject)}"
    s_name = f"{stem}-学生版.pdf"
    t_name = f"{stem}-教师版.pdf"
    s_new = dest / s_name
    t_new = dest / t_name
    shutil.move(str(student_pdf), s_new)
    shutil.move(str(teacher_pdf), t_new)

    # 保存 exam.yaml 副本到 result/，注入 score_per_item 供成绩分析使用
    if exam_yaml.is_file():
        with exam_yaml.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        exam_data = ExamConfig.model_validate(raw)
        if template is not None:
            sec_score_map = {s.section_id: s.score_per_item for s in template.sections}
            for sel in exam_data.selected_items:
                if sel.section_id in sec_score_map and sel.score_per_item is None:
                    sel.score_per_item = sec_score_map[sel.section_id]
        with (dest / "exam.yaml").open("w", encoding="utf-8") as f:
            yaml.safe_dump(exam_data.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)

    return dest, s_name, t_name
