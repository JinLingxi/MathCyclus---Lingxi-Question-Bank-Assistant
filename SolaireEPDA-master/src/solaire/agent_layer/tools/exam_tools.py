"""Exam / template tools via exam_compiler facade + web exam_service glue."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.common.security import assert_within_project
from solaire.exam_compiler.facade import SelectedSection, load_template
from solaire.web.exam_service import (
    VALIDATE_EXAM_NAME,
    export_pdfs,
    run_validate,
    run_validate_with_checks,
    write_build_exam_yaml,
    write_exam_yaml,
)


def _sections_from_args(args: dict[str, Any]) -> list[SelectedSection]:
    raw = args.get("selected_items") or []
    out: list[SelectedSection] = []
    for s in raw:
        if not isinstance(s, dict):
            continue
        sid = str(s.get("section_id") or "").strip()
        qids = s.get("question_ids") or []
        if sid and isinstance(qids, list):
            spi = s.get("score_per_item")
            score_per_item: float | None
            try:
                score_per_item = float(spi) if spi is not None else None
            except (TypeError, ValueError):
                score_per_item = None
            so = s.get("score_overrides")
            score_overrides: dict[str, float] | None = None
            if isinstance(so, dict) and so:
                try:
                    score_overrides = {str(k): float(v) for k, v in so.items()}
                except (TypeError, ValueError):
                    score_overrides = None
            out.append(
                SelectedSection(
                    section_id=sid,
                    question_ids=[str(x) for x in qids],
                    score_per_item=score_per_item,
                    score_overrides=score_overrides,
                )
            )
    return out


def tool_list_templates(ctx: InvocationContext, _args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    templates_dir = root / "templates"
    if not templates_dir.is_dir():
        return ToolResult(status="succeeded", data={"templates": []})
    out: list[dict[str, Any]] = []
    for p in sorted(templates_dir.rglob("*.yaml")):
        rel = p.relative_to(root).as_posix()
        try:
            t = load_template(p)
        except Exception as e:
            out.append({"id": None, "path": rel, "error": str(e)})
            continue
        md = dict(t.metadata_defaults) if t.metadata_defaults else {}
        out.append(
            {
                "id": t.template_id,
                "path": rel,
                "layout": t.layout,
                "latex_base": t.latex_base,
                "metadata_defaults": md,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "type": s.type,
                        "required_count": s.required_count,
                        "score_per_item": s.score_per_item,
                    }
                    for s in t.sections
                ],
            }
        )
    return ToolResult(status="succeeded", data={"templates": [x for x in out if x.get("id")]})


def tool_template_preview(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    rel = str(args.get("template_path") or "").strip()
    if not rel:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="template_path required")
    p = (root / rel).resolve()
    assert_within_project(root, p)
    if not p.is_file():
        return ToolResult(status="failed", error_code="not_found", error_message="模板文件不存在")
    try:
        t = load_template(p)
    except Exception as e:
        return ToolResult(status="failed", error_code="runtime_error", error_message=str(e))
    return ToolResult(
        status="succeeded",
        data={
            "id": t.template_id,
            "path": rel,
            "sections": [s.model_dump(mode="json") for s in t.sections],
            "metadata_defaults": dict(t.metadata_defaults) if t.metadata_defaults else {},
        },
    )


def tool_validate_paper(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    template_ref = str(args.get("template_ref") or "").strip()
    template_path = str(args.get("template_path") or "").strip()
    if not template_ref or not template_path:
        return ToolResult(
            status="failed",
            error_code="invalid_arguments",
            error_message="template_ref 与 template_path 必填",
        )
    include_latex_check = bool(args.get("include_latex_check"))
    include_math_static = args.get("include_math_static")
    if include_math_static is None:
        include_math_static = True
    else:
        include_math_static = bool(include_math_static)
    tpl = (root / template_path).resolve()
    try:
        assert_within_project(root, tpl)
    except Exception as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    sections = _sections_from_args(args)
    exam_yaml = write_exam_yaml(
        root,
        yaml_basename=VALIDATE_EXAM_NAME,
        exam_id="validate",
        template_ref=template_ref,
        template_relative=template_path,
        metadata={},
        selected_items=sections,
    )
    try:
        extra = run_validate_with_checks(
            root,
            exam_yaml,
            include_latex_check=include_latex_check,
            include_math_static=include_math_static,
        )
    except ValueError as e:
        return ToolResult(status="failed", error_code="validation_failed", error_message=str(e))
    data: dict[str, Any] = {
        "ok": True,
        "exam_yaml": exam_yaml.relative_to(root).as_posix(),
        "structure_ok": extra.get("structure_ok"),
        "math_warnings": extra.get("math_warnings") or [],
    }
    if include_latex_check:
        data["latex_ok"] = extra.get("latex_ok")
        data["latex_error_excerpt"] = extra.get("latex_error_excerpt")
    else:
        data["latex_ok"] = None
        data["latex_note"] = "未进行版式编译试跑；导出前可开启 include_latex_check。"
    return ToolResult(status="succeeded", data=data)


def tool_export_paper(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    root = ctx.project_root
    template_ref = str(args.get("template_ref") or "").strip()
    template_path = str(args.get("template_path") or "").strip()
    export_label = str(args.get("export_label") or "").strip()
    subject = str(args.get("subject") or "").strip()
    if not all([template_ref, template_path, export_label, subject]):
        return ToolResult(
            status="failed",
            error_code="invalid_arguments",
            error_message="template_ref、template_path、export_label、subject 必填",
        )
    tpl = (root / template_path).resolve()
    try:
        assert_within_project(root, tpl)
    except Exception as e:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message=str(e))
    if not tpl.is_file():
        return ToolResult(status="failed", error_code="not_found", error_message="模板文件不存在")
    title = args.get("metadata_title") or export_label
    metadata: dict[str, Any] = {
        "title": str(title),
        "subject": subject,
        "export_label": export_label,
    }
    sections = _sections_from_args(args)
    exam_yaml = write_build_exam_yaml(
        root,
        exam_id="agent_export",
        template_ref=template_ref,
        template_relative=template_path,
        metadata=metadata,
        selected_items=sections,
    )
    try:
        run_validate(root, exam_yaml)
    except ValueError as e:
        return ToolResult(status="failed", error_code="validation_failed", error_message=str(e))
    template = load_template(tpl)
    try:
        result_dir, s_name, t_name = export_pdfs(
            root,
            exam_yaml=exam_yaml,
            export_label=export_label,
            subject=subject,
            template=template,
        )
    except FileNotFoundError as e:
        return ToolResult(status="failed", error_code="not_found", error_message=str(e))
    except RuntimeError as e:
        return ToolResult(status="failed", error_code="runtime_error", error_message=str(e))
    rel = result_dir.relative_to(root).as_posix()
    return ToolResult(
        status="succeeded",
        data={
            "ok": True,
            "result_dir": rel,
            "student_pdf": s_name,
            "teacher_pdf": t_name,
        },
    )
