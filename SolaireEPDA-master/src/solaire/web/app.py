"""FastAPI application: project binding, questions, templates, validate, export."""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from pathlib import Path
from typing import Annotated, Any, Literal, Union

import yaml
from fastapi import Body, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from solaire.exam_compiler.facade import (
    EditorMetadataDefaultsBody,
    ExamConfig,
    QuestionGroupRecord,
    QuestionItem,
    SelectedSection,
    TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED,
    TemplateParsedResponse,
    load_all_questions,
    load_template,
    materialize_metadata_defaults_for_editor,
    strip_hydrate_fields,
)

from solaire.web import bundled_paths, help_docs, recent_projects, state, system_tools
from solaire.web.agent_api import router as agent_router
from solaire.web.bank_exchange import export_bank_exchange_zip, import_bank_exchange_zip
from solaire.web.result_service import (
    compute_statistics,
    delete_exam_result,
    delete_score_batch,
    find_exported_pdf_path,
    generate_score_template,
    get_exam_summary,
    get_score_analysis,
    import_scores,
    list_exam_results,
    open_pdf_with_default_app,
)
from solaire.edu_analysis.core import (
    delete_script_api,
    get_job,
    get_script_api,
    invoke_tool,
    list_jobs_api,
    list_scripts_api,
    list_tools,
    run_builtin,
    run_script_with_request_id,
    save_script_doc,
)
from solaire.edu_analysis.diagnosis import (
    class_heatmap_v1,
    knowledge_diagnosis_v1,
    student_knowledge_diagnosis_v1,
    teaching_suggestions_v1,
)
from solaire.web.bank_service import (
    collections_list,
    delete_question,
    expand_question_for_web,
    get_question_detail,
    import_merged_yaml,
    list_bank_entries,
    list_subjects,
    question_exists,
    save_bank_record,
    save_question,
    upload_bank_image,
)
from solaire.web.graph_service import (
    attach_file_to_node,
    bind_question_to_node,
    bind_questions_batch,
    count_nodes_by_kind,
    create_concept_node,
    create_node_relation,
    delete_concept_node,
    delete_node_relation,
    detach_file_link,
    generate_unique_node_id,
    get_concept_node,
    get_taxonomy,
    list_concept_nodes,
    list_file_links_for_node,
    list_node_relations,
    list_nodes_for_question,
    list_questions_for_node,
    list_resource_files,
    load_graph,
    set_taxonomy,
    unbind_question_from_node,
    unbind_questions_batch,
    update_concept_node,
)
from solaire.web.library_discovery import discover_question_library_refs
from solaire.web.draft_service import (
    delete_draft,
    draft_from_result,
    list_drafts,
    load_draft,
    persist_draft_document,
    save_draft,
    save_draft_after_export_failure,
)
from solaire.web.exam_service import (
    VALIDATE_EXAM_NAME,
    discard_build_yaml_backup,
    ensure_probe_list_yaml,
    exam_export_error_detail_short,
    export_pdfs,
    find_export_conflict,
    restore_build_yaml_from_backup,
    run_validate,
    snapshot_build_yaml_before_export,
    write_build_exam_yaml,
    write_exam_yaml,
)
from solaire.web.project_layout import ensure_project_layout
from solaire.web.security import (
    assert_within_project,
    content_disposition_attachment,
    safe_filename_component,
    safe_project_name,
    unique_child_dir,
)
from solaire.web.result_service import ResultServiceAdapter
from solaire.edu_analysis.ports import configure as _configure_edu_analysis

# 在模块加载时注入 edu_analysis 所需的数据访问实现，解除 edu_analysis 对 web 层的反向依赖
_configure_edu_analysis(result_port=ResultServiceAdapter())

def _require_root() -> Path:
    r = state.get_root()
    if r is None:
        raise HTTPException(status_code=400, detail="No project open; call POST /api/project/open first")
    return r


def _resolve_under_templates(root: Path, rel: str) -> Path:
    """Return resolved path; must live under project templates/."""
    rel = rel.strip().replace("\\", "/").lstrip("/")
    if not rel.lower().startswith("templates/"):
        raise HTTPException(status_code=400, detail="path must start with templates/")
    target = (root / rel).resolve()
    templates_root = (root / "templates").resolve()
    try:
        target.relative_to(templates_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="path must stay under templates/") from e
    assert_within_project(root, target)
    return target


app = FastAPI(title="Solaire Web", version="0.1.0")
app.include_router(agent_router, prefix="/api")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def _startup() -> None:
    state.init_from_env()


class ProjectOpenBody(BaseModel):
    root: str


class ProjectCreateBody(BaseModel):
    parent: str
    name: str
    template: Literal["empty", "math"] = "empty"


class RecentProjectRemoveBody(BaseModel):
    path: str


class SelectedSectionIn(BaseModel):
    section_id: str
    question_ids: list[str]
    score_per_item: float | None = None
    score_overrides: dict[str, float] | None = None


class ExamDraftBody(BaseModel):
    template_ref: str
    """Must match template_id inside the YAML file."""
    template_path: str = Field(..., description="Path relative to project root, e.g. templates/demo.yaml")
    selected_items: list[SelectedSectionIn]


class ExamExportBody(ExamDraftBody):
    export_label: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)
    metadata_title: str | None = None
    """When set, must match a result subdirectory name and its stored 试卷说明/科目."""
    overwrite_existing: str | None = None
    draft_ids_to_delete_on_success: list[str] | None = None
    """草稿 id 列表；导出成功后删除（如当前草稿或导出失败时自动保存的草稿）。"""


class ExamExportConflictBody(BaseModel):
    export_label: str = Field(..., min_length=1)
    subject: str = Field(..., min_length=1)


class ExamSaveDraftBody(BaseModel):
    draft_id: str | None = None
    name: str | None = None
    subject: str = ""
    export_label: str = ""
    template_ref: str = ""
    template_path: str = Field(..., min_length=1, description="Relative to project root")
    selected_items: list[SelectedSectionIn] = Field(default_factory=list)


class DraftFromResultBody(BaseModel):
    """载入历史试卷时是否写入 .solaire/drafts/；默认否。"""

    persist: bool = False


class OpenResultPdfBody(BaseModel):
    variant: str = "student"


class BankImportBody(BaseModel):
    yaml: str = Field(..., description="Merged questions YAML (questions: list)")
    target_subject: str = Field(..., min_length=1, description="科目目录名，如 数学")
    target_collection: str = Field(..., min_length=1, description="题集目录名，写入 resource/<科目>/<题集>/")


class BankExportBundleBody(BaseModel):
    """题集 namespace（科目/题集）；用 POST 传递，避免 GET 查询串中 / 的编码问题。"""

    namespace: str = Field(..., min_length=1)


BankRecordBody = Annotated[Union[QuestionItem, QuestionGroupRecord], Field(discriminator="type")]


class BankCreateBody(BaseModel):
    subject: str = Field(..., min_length=1)
    collection: str = Field(..., min_length=1)
    question: BankRecordBody


class BankRawFileBody(BaseModel):
    """Write YAML verbatim to resource/<path> (relative to resource/)."""

    path: str = Field(..., min_length=1, description="Relative path under resource/, e.g. 高考真题/questions.yaml")
    yaml: str = Field(..., description="Full file contents")


class GraphNodeCreateBody(BaseModel):
    id: str | None = Field(default=None, description="知识点标识；留空则根据父级与名称自动生成")
    parent_node_id: str | None = Field(default=None, description="父级知识点标识；留空时需手动填写 id")
    node_kind: str | None = Field(
        default=None,
        description="节点类型：知识点 concept / 技能 skill / 因果 causal",
    )
    canonical_name: str = Field(..., min_length=1, description="Canonical name")
    aliases: list[str] = Field(default_factory=list, description="Aliases")
    subject: str | None = Field(default=None, description="Subject/discipline")
    level: str | None = Field(default=None, description="Level/stage")
    description: str | None = Field(default=None, description="Short description")
    tags: list[str] = Field(default_factory=list, description="Tags")
    source: str | None = Field(default=None, description="Original source")
    layout_x: float | None = Field(default=None, description="画布坐标 X")
    layout_y: float | None = Field(default=None, description="画布坐标 Y")


class GraphRelationCreateBody(BaseModel):
    from_node_id: str = Field(..., min_length=1)
    to_node_id: str = Field(..., min_length=1)
    relation_type: str = Field(..., min_length=1)


class GraphBindingCreateBody(BaseModel):
    question_qualified_id: str = Field(..., min_length=1)
    node_id: str = Field(..., min_length=1)


class GraphBindingBatchBody(BaseModel):
    qualified_ids: list[str] = Field(default_factory=list, description="题目全限定 id 列表")


class GraphTaxonomyBody(BaseModel):
    subjects: list[str] = Field(default_factory=list)
    levels: list[str] = Field(default_factory=list)


class GraphFileLinkBody(BaseModel):
    node_id: str = Field(..., min_length=1)
    relative_path: str = Field(..., min_length=1, description="相对 resource/ 的文件路径")


class TemplateRawFileBody(BaseModel):
    """Read/write template YAML under templates/ (relative to project root)."""

    path: str = Field(..., min_length=1, description="Relative path under project root, e.g. templates/demo.yaml")
    yaml: str | None = Field(default=None, description="For PUT: full file contents")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/system/tex-status")
def api_tex_status() -> dict[str, Any]:
    """Detect latexmk / xelatex on PATH for PDF export."""
    return system_tools.tex_status()


@app.post("/api/system/tex-install")
def api_tex_install() -> dict[str, Any]:
    """Try to start MiKTeX install via winget (Windows)."""
    return system_tools.tex_install_miktex_via_winget()


@app.get("/api/help/index")
def api_help_index() -> dict[str, Any]:
    return help_docs.help_index()


@app.get("/api/help/page/{page_id}")
def api_help_page(page_id: str) -> dict[str, Any]:
    return help_docs.help_page(page_id)


@app.get("/api/help/asset/{rel_path:path}")
def api_help_asset(rel_path: str) -> FileResponse:
    """Static files under src/solaire_doc/assets/ (e.g. PrimeBrush example SVGs)."""
    target = help_docs.resolve_help_asset(rel_path)
    mt = "image/svg+xml" if target.suffix.lower() == ".svg" else None
    return FileResponse(target, media_type=mt)


@app.get("/api/resource/{rel_path:path}")
def serve_resource_file(rel_path: str) -> FileResponse:
    """Serve files under project resource/ (e.g. PrimeBrush SVG under …/image/)."""
    root = _require_root()
    resource = (root / "resource").resolve()
    rel = rel_path.strip().replace("\\", "/").lstrip("/")
    target = (resource / rel).resolve()
    try:
        target.relative_to(resource)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Path must stay under resource/") from e
    assert_within_project(root, target)
    if not target.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    mt = "image/svg+xml" if target.suffix.lower() == ".svg" else None
    return FileResponse(target, media_type=mt)


@app.get("/api/project/info")
def project_info() -> dict[str, Any]:
    r = state.get_root()
    return {"bound": r is not None, "root": str(r) if r else None}


@app.get("/api/recent-projects")
def api_recent_projects() -> dict[str, Any]:
    items = recent_projects.load_recent_projects()
    return {
        "items": [
            {"name": e.name, "path": e.path, "last_opened": e.last_opened}
            for e in items
        ]
    }


@app.post("/api/recent-projects/remove")
def api_recent_projects_remove(body: RecentProjectRemoveBody) -> dict[str, Any]:
    """Remove one entry from the persisted recent list (does not delete the project folder)."""
    p = body.path.strip()
    if not p:
        raise HTTPException(status_code=400, detail="路径不能为空")
    removed = recent_projects.remove_recent_project(p)
    return {"ok": True, "removed": removed}


def _pick_directory_dialog() -> str | None:
    """
    Open a native folder picker (Tk). Runs on the same machine as the API (localhost).
    Returns None if user cancelled or closed dialog without selection.
    """
    try:
        import tkinter as tk
        from tkinter import filedialog
    except ImportError as e:
        raise RuntimeError("TKINTER_UNAVAILABLE") from e

    root = tk.Tk()
    root.withdraw()
    try:
        root.attributes("-topmost", True)
    except tk.TclError:
        pass
    try:
        path = filedialog.askdirectory(mustexist=True)
    finally:
        root.destroy()
    return path or None


@app.post("/api/project/pick-open")
async def project_pick_open() -> dict[str, Any]:
    """
    Open OS folder dialog on the **server** machine, then bind that folder as project root.
    The browser cannot read arbitrary disk paths; this delegates to the local backend process.
    """
    try:
        path = await asyncio.to_thread(_pick_directory_dialog)
    except RuntimeError as e:
        if str(e) == "TKINTER_UNAVAILABLE":
            raise HTTPException(
                status_code=501,
                detail="当前 Python 环境未提供 Tk（tkinter），无法弹出系统选文件夹。请使用下方手动输入路径，"
                "或安装带 Tcl/Tk 的 Python；无图形界面环境（如部分 SSH）也不支持此功能。",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not path:
        raise HTTPException(status_code=400, detail="未选择文件夹或已取消")
    root = Path(path).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")
    ensure_project_layout(root)
    state.set_root(root)
    recent_projects.record_project_opened(root)
    return {"ok": True, "root": str(root)}


@app.post("/api/project/pick-parent")
async def project_pick_parent() -> dict[str, Any]:
    """Pick a parent directory for «新建项目» — same dialog as pick-open, returns path only."""
    try:
        path = await asyncio.to_thread(_pick_directory_dialog)
    except RuntimeError as e:
        if str(e) == "TKINTER_UNAVAILABLE":
            raise HTTPException(
                status_code=501,
                detail="当前 Python 环境未提供 Tk（tkinter），无法弹出系统选文件夹。请手动输入父目录路径。",
            ) from e
        raise HTTPException(status_code=500, detail=str(e)) from e
    if not path:
        raise HTTPException(status_code=400, detail="未选择文件夹或已取消")
    parent = Path(path).expanduser().resolve()
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {parent}")
    return {"ok": True, "path": str(parent)}


@app.post("/api/project/close")
def project_close() -> dict[str, Any]:
    """取消当前项目绑定，便于在界面中重新选择项目。"""
    state.clear_root()
    return {"ok": True}


@app.post("/api/project/open")
def project_open(body: ProjectOpenBody) -> dict[str, Any]:
    root = Path(body.root).expanduser().resolve()
    if not root.is_dir():
        raise HTTPException(status_code=400, detail=f"Not a directory: {root}")
    ensure_project_layout(root)
    state.set_root(root)
    recent_projects.record_project_opened(root)
    return {"ok": True, "root": str(root)}


@app.post("/api/project/create")
def project_create(body: ProjectCreateBody) -> dict[str, Any]:
    parent = Path(body.parent).expanduser().resolve()
    if not parent.is_dir():
        raise HTTPException(status_code=400, detail=f"Parent not a directory: {parent}")
    name = safe_project_name(body.name)
    root = unique_child_dir(parent, name)

    if body.template == "math":
        src = bundled_paths.resolve_math_project_template_dir()
        if src is None:
            raise HTTPException(
                status_code=503,
                detail="数学项目模板暂不可用，请使用完整安装包或联系管理员。",
            )
        shutil.copytree(src, root)
        ensure_project_layout(root)
    else:
        root.mkdir(parents=False)
        ensure_project_layout(root)
        readme = root / "templates" / "README.txt"
        readme.parent.mkdir(parents=True, exist_ok=True)
        readme.write_text("在此目录放置 template.yaml 与 LaTeX 基架（与 exam 解耦）。\n", encoding="utf-8")
    state.set_root(root)
    recent_projects.record_project_opened(root)
    return {"ok": True, "root": str(root)}


def _subject_collection_from_qualified_id(qid: str) -> tuple[str, str, str]:
    """Returns (subject, collection_name, full_namespace)."""
    parts = qid.split("/")
    if len(parts) >= 3:
        return parts[0], parts[1], "/".join(parts[:-1])
    if len(parts) == 2 and parts[0] == "main":
        return "main", "main", "main"
    if len(parts) == 2:
        return parts[0], "", parts[0]
    return (parts[0] if parts else "", "", parts[0] if parts else "")


@app.get("/api/questions")
def list_questions() -> dict[str, Any]:
    root = _require_root()
    probe = ensure_probe_list_yaml(root)
    refs = discover_question_library_refs(root)
    libs = [(r["namespace"], r["path"]) for r in refs]
    try:
        loaded = load_all_questions(probe, libs)
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail="题库路径不完整或已被移动，请检查项目下的题库目录后重试。",
        ) from e
    except OSError as e:
        raise HTTPException(
            status_code=400,
            detail="题库路径不完整或已被移动，请检查项目下的题库目录后重试。",
        ) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    items: list[dict[str, Any]] = []
    for qid, rec in sorted(loaded.by_qualified.items()):
        subj, coll_name, ns = _subject_collection_from_qualified_id(qid)
        if isinstance(rec, QuestionItem):
            q = strip_hydrate_fields(rec)
            try:
                q_disp = expand_question_for_web(root, ns, q)
            except Exception:
                # 插图展开失败（如 PrimeBrush 渲染异常）不应拖垮整表；列表页回退为未展开题干。
                q_disp = q
            content = q_disp.content or ""
            preview = content if len(content) <= 240 else content[:237] + "..."
            items.append(
                {
                    "id": q.id,
                    "qualified_id": qid,
                    "namespace": ns,
                    "collection": ns,
                    "subject": subj,
                    "collection_name": coll_name,
                    "type": q.type,
                    "content": content,
                    "content_preview": preview,
                    "answer": q_disp.answer,
                    "analysis": q_disp.analysis,
                    "group_id": None,
                    "group_member_qualified_ids": [],
                    "group_material": None,
                }
            )
        else:
            assert isinstance(rec, QuestionGroupRecord)
            content = rec.material or ""
            preview = content if len(content) <= 240 else content[:237] + "..."
            u = rec.unified
            display_type = u if isinstance(u, str) else "group"
            items.append(
                {
                    "id": rec.id,
                    "qualified_id": qid,
                    "namespace": ns,
                    "collection": ns,
                    "subject": subj,
                    "collection_name": coll_name,
                    "type": display_type,
                    "content": content,
                    "content_preview": preview,
                    "answer": "",
                    "analysis": "",
                    "group_id": rec.id,
                    "group_member_qualified_ids": [],
                    "group_material": rec.material,
                }
            )
    return {"questions": items}


@app.get("/api/templates")
def list_templates() -> dict[str, Any]:
    root = _require_root()
    templates_dir = root / "templates"
    if not templates_dir.is_dir():
        return {"templates": []}
    out: list[dict[str, Any]] = []
    for p in sorted(templates_dir.rglob("*.yaml")):
        rel = p.relative_to(root)
        rel_s = rel.as_posix()
        try:
            t = load_template(p)
        except Exception as e:
            out.append({"id": None, "path": rel_s, "error": str(e)})
            continue
        md = dict(t.metadata_defaults) if t.metadata_defaults else {}
        out.append(
            {
                "id": t.template_id,
                "path": rel_s,
                "layout": t.layout,
                "latex_base": t.latex_base,
                "metadata_defaults": md,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "type": s.type,
                        "required_count": s.required_count,
                        "score_per_item": s.score_per_item,
                        "describe": s.describe,
                    }
                    for s in t.sections
                ],
            }
        )
    return {"templates": [x for x in out if x.get("id")]}


@app.get("/api/templates/latex-bases")
def template_latex_bases() -> dict[str, Any]:
    """列出内置与项目 templates/ 下的 *.tex.j2 文件名，供模板工作台选择 latex_base。"""
    from solaire.exam_compiler.facade import list_shipped_latex_j2_names

    root = _require_root()
    shipped = list_shipped_latex_j2_names()
    proj_names: set[str] = set()
    td = root / "templates"
    if td.is_dir():
        for p in td.rglob("*.tex.j2"):
            proj_names.add(p.name)
    choices = sorted(set(shipped) | proj_names)
    return {
        "shipped": shipped,
        "in_project": sorted(proj_names),
        "choices": choices,
    }


@app.get("/api/templates/latex-metadata-ui")
def template_latex_metadata_ui(
    template_path: str = Query(
        ...,
        min_length=1,
        description="模板 YAML 相对项目根路径，如 templates/demo.yaml",
    ),
    latex_base: str = Query(..., min_length=1, description="与模板中 latex_base 一致，如 exam-zh-base.tex.j2"),
) -> dict[str, Any]:
    """
    读取与 ``latex_base`` 同 stem 的 ``*.metadata_ui.yaml``（模板目录优先，其次内置 latex 目录）。
    供模板工作台动态渲染 metadata_defaults 扩展字段，避免在前端写死键名。
    """
    from solaire.exam_compiler.facade import load_latex_metadata_ui_fields

    root = _require_root()
    tpl_yaml = (root / template_path).resolve()
    if not tpl_yaml.is_file():
        raise HTTPException(status_code=400, detail=f"Template YAML not found: {template_path}")
    assert_within_project(root, tpl_yaml)
    template_dir = tpl_yaml.parent
    try:
        fields, src, warnings = load_latex_metadata_ui_fields(template_dir, latex_base)
    except FileNotFoundError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    rel_source: str | None = None
    if src is not None:
        try:
            rel_source = src.relative_to(root).as_posix()
        except ValueError:
            rel_source = str(src)
    return {"fields": fields, "source": rel_source, "warnings": warnings}


@app.get("/api/templates/editor-metadata-defaults", response_model=EditorMetadataDefaultsBody)
def template_editor_metadata_defaults() -> EditorMetadataDefaultsBody:
    """Materialized metadata_defaults for an empty template (PDF nested defaults, margin_cm, flags)."""
    _require_root()
    return EditorMetadataDefaultsBody(metadata_defaults=materialize_metadata_defaults_for_editor({}))


@app.get("/api/templates/parsed", response_model=TemplateParsedResponse)
def template_parsed(path: str = Query(..., min_length=1, description="e.g. templates/demo.yaml")) -> TemplateParsedResponse:
    """Load template.yaml via ``load_template`` and return editor-ready metadata (materialized)."""
    root = _require_root()
    p = _resolve_under_templates(root, path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    try:
        t = load_template(p)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid template YAML: {e}") from e
    md_raw = dict(t.metadata_defaults) if t.metadata_defaults else {}
    md_full = materialize_metadata_defaults_for_editor(md_raw)
    return TemplateParsedResponse.from_exam_template(
        t,
        layout_builtin_keys=list(TEMPLATE_EDITOR_LAYOUT_BUILTIN_KEYS_ORDERED),
        materialized_metadata=md_full,
    )


@app.get("/api/templates/{template_id}/preview")
def template_preview(template_id: str) -> dict[str, Any]:
    root = _require_root()
    templates_dir = root / "templates"
    for p in templates_dir.rglob("*.yaml"):
        try:
            t = load_template(p)
        except Exception:
            continue
        if t.template_id == template_id:
            rel = p.relative_to(root).as_posix()
            md = dict(t.metadata_defaults) if t.metadata_defaults else {}
            return {
                "id": t.template_id,
                "path": rel,
                "latex_base": t.latex_base,
                "layout": t.layout,
                "metadata_defaults": md,
                "sections": [
                    {
                        "section_id": s.section_id,
                        "type": s.type,
                        "required_count": s.required_count,
                        "score_per_item": s.score_per_item,
                        "describe": s.describe,
                    }
                    for s in t.sections
                ],
            }
    raise HTTPException(status_code=404, detail=f"Template not found: {template_id}")


@app.get("/api/templates/raw")
def template_raw_get(path: str = Query(..., min_length=1, description="e.g. templates/demo.yaml")) -> dict[str, Any]:
    root = _require_root()
    p = _resolve_under_templates(root, path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    text = p.read_text(encoding="utf-8")
    return {"path": path.strip().replace("\\", "/"), "yaml": text}


@app.put("/api/templates/raw")
def template_raw_put(body: TemplateRawFileBody) -> dict[str, Any]:
    root = _require_root()
    if body.yaml is None:
        raise HTTPException(status_code=400, detail="yaml is required for PUT")
    p = _resolve_under_templates(root, body.path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.yaml, encoding="utf-8")
    try:
        load_template(p)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid template YAML: {e}") from e
    return {"ok": True}


@app.post("/api/templates/create")
def template_create(name: str = Query(..., min_length=1, description="File stem under templates/, e.g. my_exam")) -> dict[str, Any]:
    """Create a minimal valid template.yaml under templates/<name>.yaml if it does not exist."""
    root = _require_root()
    stem = safe_filename_component(name)
    if not stem.endswith(".yaml"):
        stem_path = f"templates/{stem}.yaml"
    else:
        stem_path = f"templates/{stem}"
    p = _resolve_under_templates(root, stem_path)
    if p.is_file():
        raise HTTPException(status_code=409, detail=f"Template already exists: {stem_path}")
    p.parent.mkdir(parents=True, exist_ok=True)
    minimal = {
        "template_id": stem.replace(".yaml", ""),
        "layout": "single_column",
        "latex_base": "exam-zh-base.tex.j2",
        "sections": [
            {
                "section_id": "一、考试说明",
                "type": "text",
                "required_count": 0,
                "score_per_item": 0,
                "describe": "（请在本节填写注意事项）",
            },
            {
                "section_id": "二、选择题",
                "type": "choice",
                "required_count": 1,
                "score_per_item": 5,
            },
        ],
    }
    text = yaml.safe_dump(minimal, allow_unicode=True, sort_keys=False)
    p.write_text(text, encoding="utf-8")
    load_template(p)
    rel = p.relative_to(root).as_posix()
    return {"ok": True, "path": rel}


@app.get("/api/bank/subjects")
def bank_subjects() -> dict[str, Any]:
    root = _require_root()
    return {"subjects": list_subjects(root)}


@app.get("/api/bank/collections")
def bank_collections() -> dict[str, Any]:
    root = _require_root()
    ensure_probe_list_yaml(root)
    return {"collections": collections_list(root)}


@app.get("/api/bank/items")
def bank_items() -> dict[str, Any]:
    root = _require_root()
    ensure_probe_list_yaml(root)
    return {"items": list_bank_entries(root)}


@app.get("/api/bank/items/{qualified_id:path}")
def bank_item_get(qualified_id: str) -> dict[str, Any]:
    root = _require_root()
    try:
        return get_question_detail(root, qualified_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/bank/items/{qualified_id:path}/image")
async def bank_item_upload_image(qualified_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    root = _require_root()
    try:
        body = await file.read()
        r = upload_bank_image(root, qualified_id, body, file.filename or "image.png")
        ensure_probe_list_yaml(root)
        return r
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.put("/api/bank/items/{qualified_id:path}")
def bank_item_put(qualified_id: str, body: BankRecordBody) -> dict[str, Any]:
    root = _require_root()
    try:
        save_bank_record(root, qualified_id, body)
        ensure_probe_list_yaml(root)
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/bank/items")
def bank_item_create(body: BankCreateBody) -> dict[str, Any]:
    root = _require_root()
    subj = body.subject.strip()
    coll = body.collection.strip()
    qualified_id = f"{subj}/{coll}/{body.question.id}"
    if question_exists(root, qualified_id):
        raise HTTPException(status_code=409, detail=f"题目已存在: {qualified_id}")
    try:
        save_bank_record(root, qualified_id, body.question)
        ensure_probe_list_yaml(root)
        return {"ok": True, "qualified_id": qualified_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileExistsError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e


@app.delete("/api/bank/items/{qualified_id:path}")
def bank_item_delete(
    qualified_id: str,
    storage_path: str | None = Query(
        None,
        description="题库列表/详情中的 resource 相对路径；提供时只删除该文件，避免题号在目录解析歧义时误删他处题目。",
    ),
) -> dict[str, Any]:
    root = _require_root()
    try:
        delete_question(root, qualified_id, storage_path)
        ensure_probe_list_yaml(root)
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.put("/api/bank/raw")
def bank_put_raw_file(body: BankRawFileBody) -> dict[str, Any]:
    """Save merged or any YAML file under resource/ (used when editing whole questions.yaml)."""
    root = _require_root()
    rel = body.path.strip().replace("\\", "/").lstrip("/")
    resource = (root / "resource").resolve()
    target = (resource / rel).resolve()
    try:
        target.relative_to(resource)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="Path must stay under resource/") from e
    assert_within_project(root, target)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(body.yaml, encoding="utf-8")
    ensure_probe_list_yaml(root)
    return {"ok": True}


@app.post("/api/bank/import")
def bank_import(body: BankImportBody) -> dict[str, Any]:
    root = _require_root()
    try:
        r = import_merged_yaml(
            root,
            body.yaml,
            body.target_subject.strip(),
            body.target_collection.strip(),
        )
        ensure_probe_list_yaml(root)
        return {"ok": True, **r}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/bank/import-bundle")
async def bank_import_bundle(
    file: UploadFile = File(...),
    target_subject: str = Form(...),
    target_collection: str = Form(...),
) -> dict[str, Any]:
    """Loose import: exchange ZIP (questions.yaml + image/ + optional manifest)."""
    root = _require_root()
    body = await file.read()
    try:
        r = import_bank_exchange_zip(root, body, target_subject.strip(), target_collection.strip())
        ensure_probe_list_yaml(root)
        return {"ok": True, **r}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


def _bank_export_bundle_response(namespace: str) -> Response:
    """Strict export: manifest.json + yaml/*.yaml + image/ (package-relative EMBED)."""
    root = _require_root()
    ns = namespace.strip()
    try:
        data, stem = export_bank_exchange_zip(root, ns)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    fn = f"{safe_filename_component(stem)}.bank.zip"
    return Response(
        content=data,
        media_type="application/zip",
        headers={"Content-Disposition": content_disposition_attachment(fn)},
    )


@app.get("/api/bank/export-bundle")
def bank_export_bundle_get(
    namespace: str = Query(..., description="题集 namespace，如 数学/模拟题"),
) -> Response:
    """GET 兼容；含 / 的 namespace 在部分代理上可能异常，请优先使用 POST。"""
    return _bank_export_bundle_response(namespace)


@app.post("/api/bank/export-bundle")
def bank_export_bundle_post(body: BankExportBundleBody) -> Response:
    """推荐：JSON body 传递 namespace，避免查询串编码问题。"""
    return _bank_export_bundle_response(body.namespace)


def _draft_to_sections(body: ExamDraftBody) -> list[SelectedSection]:
    out: list[SelectedSection] = []
    for s in body.selected_items:
        ov = s.score_overrides
        out.append(
            SelectedSection(
                section_id=s.section_id,
                question_ids=list(s.question_ids),
                score_per_item=s.score_per_item,
                score_overrides=dict(ov) if ov else None,
            )
        )
    return out


def _assert_overwrite_target(
    root: Path, result_exam_id: str, export_label: str, subject: str
) -> Path:
    """Return resolved result directory; raises HTTPException if invalid or metadata mismatch."""
    dest = (root / "result" / result_exam_id).resolve()
    assert_within_project(root, dest)
    exam_yaml = dest / "exam.yaml"
    if not exam_yaml.is_file():
        raise HTTPException(status_code=400, detail="覆盖目标不存在或缺少试卷配置")
    try:
        with exam_yaml.open(encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        exam = ExamConfig.model_validate(raw)
    except Exception as e:
        raise HTTPException(status_code=400, detail="无法读取已有试卷配置") from e
    meta = exam.metadata or {}
    if str(meta.get("export_label", "")).strip() != export_label.strip():
        raise HTTPException(status_code=400, detail="覆盖目标的试卷说明与当前不一致")
    if str(meta.get("subject", "")).strip() != subject.strip():
        raise HTTPException(status_code=400, detail="覆盖目标的学科与当前不一致")
    return dest


@app.post("/api/exam/validate")
def exam_validate(body: ExamDraftBody) -> dict[str, Any]:
    root = _require_root()
    tpl = (root / body.template_path).resolve()
    assert_within_project(root, tpl)
    sections = _draft_to_sections(body)
    exam_yaml = write_exam_yaml(
        root,
        yaml_basename=VALIDATE_EXAM_NAME,
        exam_id="validate",
        template_ref=body.template_ref,
        template_relative=body.template_path,
        metadata={},
        selected_items=sections,
    )
    try:
        run_validate(root, exam_yaml)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True}


def _exam_export_failure_detail(root: Path, body: ExamExportBody, exc: BaseException) -> dict[str, Any]:
    """Structured HTTP detail: message + optional draft_saved after restore."""
    log = logging.getLogger(__name__)
    doc: dict[str, Any] | None = None
    try:
        items = [s.model_dump(mode="json", exclude_none=True) for s in body.selected_items]
        doc = save_draft_after_export_failure(
            root,
            template_ref=body.template_ref,
            template_path=body.template_path,
            export_label=body.export_label,
            subject=body.subject,
            selected_items=items,
        )
    except Exception:
        log.exception("failed to save draft after export failure")

    msg = exam_export_error_detail_short(exc) if isinstance(exc, Exception) else str(exc).strip()
    if not msg:
        msg = "导出失败，请查看运行日志。"
    detail: dict[str, Any] = {"message": msg}
    if doc:
        detail["draft_saved"] = {"draft_id": doc["draft_id"], "name": str(doc.get("name") or "")}
    return detail


@app.post("/api/exam/export")
def exam_export(body: ExamExportBody) -> dict[str, Any]:
    root = _require_root()
    tpl = (root / body.template_path).resolve()
    assert_within_project(root, tpl)
    if not tpl.is_file():
        raise HTTPException(status_code=400, detail=f"Template file not found: {body.template_path}")

    title = body.metadata_title or body.export_label
    metadata: dict[str, Any] = {
        "title": title,
        "subject": body.subject,
        "export_label": body.export_label,
    }
    sections = _draft_to_sections(body)

    log = logging.getLogger(__name__)
    backup = snapshot_build_yaml_before_export(root)
    try:
        exam_yaml = write_build_exam_yaml(
            root,
            exam_id="web_export",
            template_ref=body.template_ref,
            template_relative=body.template_path,
            metadata=metadata,
            selected_items=sections,
        )
        run_validate(root, exam_yaml)
        template = load_template(tpl)
        overwrite_dest: Path | None = None
        if body.overwrite_existing:
            overwrite_dest = _assert_overwrite_target(
                root, body.overwrite_existing, body.export_label, body.subject
            )
        result_dir, s_name, t_name = export_pdfs(
            root,
            exam_yaml=exam_yaml,
            export_label=body.export_label,
            subject=body.subject,
            template=template,
            overwrite_result_dir=overwrite_dest,
        )
    except ValueError as e:
        restore_build_yaml_from_backup(root, backup)
        log.warning("exam export validation failed: %s", e)
        raise HTTPException(status_code=400, detail=_exam_export_failure_detail(root, body, e)) from e
    except FileNotFoundError as e:
        restore_build_yaml_from_backup(root, backup)
        log.warning("exam export file not found: %s", e)
        raise HTTPException(status_code=400, detail=_exam_export_failure_detail(root, body, e)) from e
    except RuntimeError as e:
        restore_build_yaml_from_backup(root, backup)
        log.exception("exam export PDF build failed")
        raise HTTPException(status_code=500, detail=_exam_export_failure_detail(root, body, e)) from e
    except Exception as e:
        restore_build_yaml_from_backup(root, backup)
        log.exception("exam export failed")
        raise HTTPException(status_code=500, detail=_exam_export_failure_detail(root, body, e)) from e
    else:
        discard_build_yaml_backup(backup)

    rel = result_dir.relative_to(root)
    to_delete = body.draft_ids_to_delete_on_success or []
    for raw_id in to_delete:
        did = str(raw_id).strip()
        if not did:
            continue
        try:
            delete_draft(root, did)
        except Exception:
            log.warning("delete draft after export success failed: %s", did)

    return {
        "ok": True,
        "result_dir": rel.as_posix(),
        "student_pdf": s_name,
        "teacher_pdf": t_name,
    }


@app.post("/api/exam/export/check-conflict")
def exam_export_check_conflict(body: ExamExportConflictBody) -> dict[str, Any]:
    root = _require_root()
    return find_export_conflict(root, body.export_label, body.subject)


@app.get("/api/exam/drafts")
def exam_drafts_list() -> dict[str, Any]:
    return {"drafts": list_drafts(_require_root())}


@app.post("/api/exam/drafts")
def exam_drafts_create(body: ExamSaveDraftBody) -> dict[str, Any]:
    root = _require_root()
    items = [s.model_dump(mode="json", exclude_none=True) for s in body.selected_items]
    try:
        doc = save_draft(
            root,
            draft_id=None,
            name=body.name,
            subject=body.subject,
            export_label=body.export_label,
            template_ref=body.template_ref,
            template_path=body.template_path,
            selected_items=items,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "draft": doc}


@app.get("/api/exam/drafts/{draft_id}")
def exam_drafts_get(draft_id: str) -> dict[str, Any]:
    return {"draft": load_draft(_require_root(), draft_id)}


@app.put("/api/exam/drafts/{draft_id}")
def exam_drafts_put(draft_id: str, body: ExamSaveDraftBody) -> dict[str, Any]:
    root = _require_root()
    items = [s.model_dump(mode="json", exclude_none=True) for s in body.selected_items]
    try:
        doc = save_draft(
            root,
            draft_id=draft_id,
            name=body.name,
            subject=body.subject,
            export_label=body.export_label,
            template_ref=body.template_ref,
            template_path=body.template_path,
            selected_items=items,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"ok": True, "draft": doc}


@app.delete("/api/exam/drafts/{draft_id}")
def exam_drafts_delete(draft_id: str) -> dict[str, Any]:
    delete_draft(_require_root(), draft_id)
    return {"ok": True}


@app.post("/api/exam/drafts/from-result/{exam_id}")
def exam_drafts_from_result(exam_id: str, body: DraftFromResultBody | None = None) -> dict[str, Any]:
    root = _require_root()
    doc = draft_from_result(root, exam_id)
    persist = bool(body.persist) if body else False
    if persist:
        persist_draft_document(root, doc)
    return {"ok": True, "draft": doc, "persisted": persist}


def _preview_text(s: str | None, n: int = 240) -> str:
    t = (s or "").replace("\n", " ").strip()
    return t if len(t) <= n else t[: n - 3] + "..."


@app.get("/api/graph/nodes")
def graph_nodes_list(
    node_kind: str | None = Query(None, description="按节点类型筛选：concept / skill / causal"),
) -> dict[str, Any]:
    root = _require_root()
    try:
        nodes = list_concept_nodes(root, node_kind=node_kind)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    return {"nodes": nodes, "kind_counts": count_nodes_by_kind(root)}


def _graph_node_payload(body: GraphNodeCreateBody) -> dict[str, Any]:
    d = body.model_dump(exclude_none=True)
    d.pop("parent_node_id", None)
    return d


@app.post("/api/graph/nodes")
def graph_nodes_create(body: GraphNodeCreateBody) -> dict[str, Any]:
    root = _require_root()
    try:
        node_id = (body.id or "").strip() or None
        parent = (body.parent_node_id or "").strip() or None
        payload = _graph_node_payload(body)
        if not node_id:
            if not parent:
                raise HTTPException(
                    status_code=400,
                    detail="请选择父级知识点以自动生成标识，或填写标识",
                )
            nid = generate_unique_node_id(root, parent, body.canonical_name)
            payload["id"] = nid
            create_concept_node(root, payload)
            create_node_relation(
                root,
                {"from_node_id": nid, "to_node_id": parent, "relation_type": "part_of"},
            )
            return {"ok": True, "node_id": nid}
        payload["id"] = node_id
        create_concept_node(root, payload)
        if parent:
            create_node_relation(
                root,
                {"from_node_id": node_id, "to_node_id": parent, "relation_type": "part_of"},
            )
        return {"ok": True, "node_id": node_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/graph/nodes/{node_id}")
def graph_nodes_get(node_id: str) -> dict[str, Any]:
    root = _require_root()
    try:
        return {"node": get_concept_node(root, node_id)}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.put("/api/graph/nodes/{node_id:path}")
def graph_nodes_update(node_id: str, body: GraphNodeCreateBody) -> dict[str, Any]:
    root = _require_root()
    try:
        existing = get_concept_node(root, node_id)
        incoming = _graph_node_payload(body)
        merged = {**existing, **incoming, "id": node_id}
        update_concept_node(root, node_id, merged)
        return {"ok": True}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/graph/relations")
def graph_relations_create(body: GraphRelationCreateBody) -> dict[str, Any]:
    root = _require_root()
    try:
        rel_id = create_node_relation(root, body.model_dump())
        return {"ok": True, "relation_id": rel_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/graph/relations")
def graph_relations_list() -> dict[str, Any]:
    root = _require_root()
    return {"relations": list_node_relations(root)}


@app.delete("/api/graph/relations/{relation_id}")
def graph_relations_delete(relation_id: str) -> dict[str, Any]:
    root = _require_root()
    delete_node_relation(root, relation_id)
    return {"ok": True}


@app.post("/api/graph/bindings")
def graph_bindings_create(body: GraphBindingCreateBody) -> dict[str, Any]:
    root = _require_root()
    try:
        bind_question_to_node(root, body.model_dump())
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/graph/bindings/unbind")
def graph_bindings_unbind(body: GraphBindingCreateBody) -> dict[str, Any]:
    root = _require_root()
    try:
        unbind_question_from_node(root, body.model_dump())
        return {"ok": True}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/graph/nodes/{node_id:path}/bind-batch")
def graph_nodes_bind_batch(node_id: str, body: GraphBindingBatchBody) -> dict[str, Any]:
    root = _require_root()
    try:
        return bind_questions_batch(root, node_id=node_id, qualified_ids=body.qualified_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/graph/nodes/{node_id:path}/unbind-batch")
def graph_nodes_unbind_batch(node_id: str, body: GraphBindingBatchBody = Body(...)) -> dict[str, Any]:
    root = _require_root()
    try:
        return unbind_questions_batch(root, node_id=node_id, qualified_ids=body.qualified_ids)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/graph/question-nodes")
def graph_question_nodes(qualified_id: str = Query(..., min_length=1)) -> dict[str, Any]:
    root = _require_root()
    nodes = list_nodes_for_question(root, qualified_id)
    return {
        "nodes": [
            {
                "id": n.id,
                "canonical_name": n.canonical_name,
                "node_kind": n.node_kind,
                "subject": n.subject,
            }
            for n in nodes
        ]
    }


@app.get("/api/graph/question-bindings-index")
def graph_question_bindings_index() -> dict[str, Any]:
    """单次返回「题目全限定 id → 已关联知识点节点」摘要，供题库列表展示标签。"""
    root = _require_root()
    state = load_graph(root)
    node_by_id = {n.id: n for n in state.nodes}
    acc: dict[str, list[dict[str, Any]]] = {}
    for b in state.bindings:
        n = node_by_id.get(b.node_id)
        if n is None:
            continue
        acc.setdefault(b.question_qualified_id, []).append(
            {"id": n.id, "canonical_name": n.canonical_name, "node_kind": n.node_kind}
        )
    for qid in list(acc.keys()):
        seen: set[str] = set()
        uniq: list[dict[str, Any]] = []
        for x in acc[qid]:
            nid = str(x.get("id") or "")
            if nid in seen:
                continue
            seen.add(nid)
            uniq.append(x)
        acc[qid] = uniq
    return {"index": acc}


@app.get("/api/graph/nodes/{node_id:path}/questions")
def graph_nodes_questions(node_id: str) -> dict[str, Any]:
    root = _require_root()
    qids = list_questions_for_node(root, node_id)
    questions: list[dict[str, Any]] = []
    for qid in qids:
        try:
            d = get_question_detail(root, qid)
        except FileNotFoundError:
            # 图谱绑定可能指向已删除题目；本阶段保持“跳过缺失题目”，不阻断列表。
            continue
        typ: str = "unknown"
        preview: str = ""
        if d.get("question") is not None:
            typ = d["question"].get("type") or "choice"
            preview = _preview_text(d.get("question_display", {}).get("content"))
        elif d.get("question_group") is not None:
            typ = "group"
            preview = _preview_text(d["question_group"].get("material"))
        questions.append(
            {
                "qualified_id": d.get("qualified_id") or qid,
                "type": typ,
                "content_preview": preview,
            }
        )
    return {"questions": questions}


@app.get("/api/graph/taxonomy")
def graph_taxonomy_get() -> dict[str, Any]:
    root = _require_root()
    return get_taxonomy(root)


@app.put("/api/graph/taxonomy")
def graph_taxonomy_put(body: GraphTaxonomyBody) -> dict[str, Any]:
    root = _require_root()
    set_taxonomy(root, subjects=body.subjects, levels=body.levels)
    return {"ok": True}


@app.get("/api/graph/resource-files")
def graph_resource_files_list(q: str = "", limit: int = Query(800, ge=1, le=5000)) -> dict[str, Any]:
    root = _require_root()
    return {"files": list_resource_files(root, q, limit=limit)}


@app.get("/api/graph/nodes/{node_id:path}/files")
def graph_node_files_list(node_id: str) -> dict[str, Any]:
    root = _require_root()
    return {"links": list_file_links_for_node(root, node_id)}


@app.delete("/api/graph/nodes/{node_id:path}")
def graph_nodes_delete(node_id: str) -> dict[str, Any]:
    root = _require_root()
    delete_concept_node(root, node_id)
    return {"ok": True}


@app.post("/api/graph/file-links")
def graph_file_links_create(body: GraphFileLinkBody) -> dict[str, Any]:
    root = _require_root()
    try:
        link_id = attach_file_to_node(root, body.node_id, body.relative_path)
        return {"ok": True, "link_id": link_id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/graph/file-links/{link_id}")
def graph_file_links_delete(link_id: str) -> dict[str, Any]:
    root = _require_root()
    detach_file_link(root, link_id)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Result / Score Analysis
# ---------------------------------------------------------------------------


class ScoresImportBody(BaseModel):
    batch_id: str | None = None  # optional, for overwrite


class AnalysisScriptBody(BaseModel):
    script_id: str | None = None
    name: str = Field(..., min_length=1)
    language: str = Field(default="python", min_length=1)
    code: str = Field(..., min_length=1)


class AnalysisRunBuiltinBody(BaseModel):
    builtin_id: str = Field(..., min_length=1)
    exam_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    recompute: bool = False
    request_id: str | None = None


class AnalysisRunScriptBody(BaseModel):
    script_id: str = Field(..., min_length=1)
    exam_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    request_id: str | None = None


class AnalysisRunFolderScriptBody(BaseModel):
    script_path: str = Field(..., min_length=1, description="Path relative to project analysis/")
    exam_id: str = Field(..., min_length=1)
    batch_id: str = Field(..., min_length=1)
    request_id: str | None = None


class AnalysisToolInvokeBody(BaseModel):
    arguments: dict[str, Any] = Field(default_factory=dict)


def _resolve_under_analysis(root: Path, rel: str) -> Path:
    analysis_root = (root / "analysis").resolve()
    analysis_root.mkdir(parents=True, exist_ok=True)
    normalized = rel.strip().replace("\\", "/").lstrip("/")
    target = (analysis_root / normalized).resolve()
    try:
        target.relative_to(analysis_root)
    except ValueError as e:
        raise HTTPException(status_code=400, detail="script_path must stay under analysis/") from e
    assert_within_project(root, target)
    return target


@app.get("/api/results")
def results_list() -> dict[str, Any]:
    """List all past exams from result/ directory (newest first)."""
    root = _require_root()
    return {"exams": list_exam_results(root)}


@app.get("/api/results/{exam_id}/pdf-file")
def results_pdf_file(
    exam_id: str,
    variant: str = Query("student", description="student 或 teacher"),
) -> FileResponse:
    """Serve exported PDF for in-browser viewing (inline disposition)."""
    root = _require_root()
    v = variant.strip().lower()
    if v not in ("student", "teacher"):
        raise HTTPException(status_code=400, detail="variant 须为 student 或 teacher")
    try:
        path = find_exported_pdf_path(root, exam_id, variant=v)  # type: ignore[arg-type]
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=path.name,
        content_disposition_type="inline",
    )


@app.post("/api/results/{exam_id}/open-pdf")
def results_open_pdf(
    exam_id: str,
    body: OpenResultPdfBody | None = Body(default=None),
) -> dict[str, Any]:
    """Open result PDF with the OS default application (local backend)."""
    root = _require_root()
    raw = (body.variant if body else "student").strip().lower()
    if raw not in ("student", "teacher"):
        raise HTTPException(status_code=400, detail="variant 须为 student 或 teacher")
    try:
        path = find_exported_pdf_path(root, exam_id, variant=raw)  # type: ignore[arg-type]
        open_pdf_with_default_app(path)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"无法通过系统打开文件: {e}") from e
    return {"ok": True}


@app.get("/api/results/{exam_id}/summary")
def results_summary(exam_id: str) -> dict[str, Any]:
    """Get exam detail: metadata, question list, existing score batches."""
    root = _require_root()
    try:
        return get_exam_summary(root, exam_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/results/{exam_id}/score-template")
def results_score_template(exam_id: str) -> Response:
    """Download CSV score template for the given exam."""
    root = _require_root()
    try:
        csv_content, filename = generate_score_template(root, exam_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    return Response(
        content=csv_content.encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": content_disposition_attachment(filename)},
    )


@app.post("/api/results/{exam_id}/scores")
async def results_scores_import(exam_id: str, file: UploadFile = File(...)) -> dict[str, Any]:
    """Import CSV/Excel score file. Returns batch summary + warnings."""
    root = _require_root()
    try:
        content = await file.read()
        result = import_scores(root, exam_id, content, file.filename or "scores.csv")
        return result
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/results/{exam_id}/scores")
def results_scores_list(exam_id: str) -> dict[str, Any]:
    """List all imported score batches for an exam."""
    root = _require_root()
    try:
        summary = get_exam_summary(root, exam_id)
        return {"batches": summary.get("score_batches", [])}
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/analysis/diagnosis/knowledge")
def analysis_diagnosis_knowledge(
    exam_id: str = Query(..., min_length=1),
    batch_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    root = _require_root()
    try:
        return knowledge_diagnosis_v1(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/analysis/diagnosis/student")
def analysis_diagnosis_student(
    exam_id: str = Query(..., min_length=1),
    batch_id: str = Query(..., min_length=1),
    student_id: str | None = Query(None, description="学号；不传则返回全班"),
) -> dict[str, Any]:
    root = _require_root()
    try:
        return student_knowledge_diagnosis_v1(root, exam_id, batch_id, student_id=student_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/analysis/diagnosis/class-heatmap")
def analysis_diagnosis_class_heatmap(
    exam_id: str = Query(..., min_length=1),
    batch_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    root = _require_root()
    try:
        return class_heatmap_v1(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/analysis/diagnosis/suggestions")
def analysis_diagnosis_suggestions(
    exam_id: str = Query(..., min_length=1),
    batch_id: str = Query(..., min_length=1),
) -> dict[str, Any]:
    root = _require_root()
    try:
        return teaching_suggestions_v1(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/results/{exam_id}/scores/{batch_id}")
def results_score_analysis(exam_id: str, batch_id: str) -> dict[str, Any]:
    """Get computed analysis for a score batch (per-question, per-node, per-student stats)."""
    root = _require_root()
    try:
        return get_score_analysis(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/results/{exam_id}/scores/{batch_id}/recompute")
def results_score_recompute(exam_id: str, batch_id: str) -> dict[str, Any]:
    """Force recompute statistics for a batch."""
    root = _require_root()
    try:
        return compute_statistics(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.delete("/api/results/{exam_id}")
def results_exam_delete(exam_id: str) -> dict[str, Any]:
    """Delete one exam result and all its score batches."""
    root = _require_root()
    try:
        return delete_exam_result(root, exam_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.delete("/api/results/{exam_id}/scores/{batch_id}")
def results_score_batch_delete(exam_id: str, batch_id: str) -> dict[str, Any]:
    """Delete one score batch under an exam."""
    root = _require_root()
    try:
        return delete_score_batch(root, exam_id, batch_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/analysis/tools")
def analysis_tools_list() -> dict[str, Any]:
    _require_root()
    return {"tools": list_tools()}


@app.post("/api/analysis/tools/{tool_name:path}")
def analysis_tool_invoke(tool_name: str, body: AnalysisToolInvokeBody) -> dict[str, Any]:
    root = _require_root()
    try:
        return invoke_tool(root, tool_name, body.arguments)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.get("/api/analysis/scripts")
def analysis_scripts_list() -> dict[str, Any]:
    root = _require_root()
    return list_scripts_api(root)


@app.post("/api/analysis/scripts")
def analysis_scripts_save(body: AnalysisScriptBody) -> dict[str, Any]:
    root = _require_root()
    try:
        return save_script_doc(
            root,
            script_id=body.script_id,
            name=body.name,
            language=body.language,
            code=body.code,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/analysis/scripts/{script_id}")
def analysis_script_get(script_id: str) -> dict[str, Any]:
    root = _require_root()
    try:
        return get_script_api(root, script_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.delete("/api/analysis/scripts/{script_id}")
def analysis_script_delete(script_id: str) -> dict[str, Any]:
    root = _require_root()
    try:
        return delete_script_api(root, script_id)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/analysis/jobs/builtin")
def analysis_job_run_builtin(body: AnalysisRunBuiltinBody) -> dict[str, Any]:
    root = _require_root()
    try:
        return run_builtin(
            root,
            builtin_id=body.builtin_id,
            exam_id=body.exam_id,
            batch_id=body.batch_id,
            recompute=body.recompute,
            request_id=body.request_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


@app.post("/api/analysis/jobs/script")
def analysis_job_run_script(body: AnalysisRunScriptBody) -> dict[str, Any]:
    root = _require_root()
    try:
        return run_script_with_request_id(
            root,
            script_id=body.script_id,
            exam_id=body.exam_id,
            batch_id=body.batch_id,
            request_id=body.request_id,
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.get("/api/analysis/folder-scripts")
def analysis_folder_scripts_list() -> dict[str, Any]:
    root = _require_root()
    analysis_root = (root / "analysis").resolve()
    analysis_root.mkdir(parents=True, exist_ok=True)
    scripts: list[dict[str, Any]] = []
    for p in sorted(analysis_root.rglob("*.py"), key=lambda x: x.stat().st_mtime, reverse=True):
        rel = p.relative_to(analysis_root).as_posix()
        scripts.append(
            {
                "path": rel,
                "name": p.name,
                "updated_at": p.stat().st_mtime,
            }
        )
    return {"scripts": scripts}


@app.post("/api/analysis/jobs/script-from-folder")
def analysis_job_run_script_from_folder(body: AnalysisRunFolderScriptBody) -> dict[str, Any]:
    root = _require_root()
    target = _resolve_under_analysis(root, body.script_path)
    if not target.is_file():
        raise HTTPException(status_code=404, detail=f"Script not found in analysis/: {body.script_path}")
    code = target.read_text(encoding="utf-8")
    saved = save_script_doc(root, name=f"folder:{target.name}", language="python", code=code)
    script_id = str(saved["script"]["script_id"])
    return run_script_with_request_id(
        root,
        script_id=script_id,
        exam_id=body.exam_id,
        batch_id=body.batch_id,
        request_id=body.request_id,
    )


@app.get("/api/analysis/jobs")
def analysis_jobs_list(limit: int = Query(50, ge=1, le=200)) -> dict[str, Any]:
    root = _require_root()
    return list_jobs_api(root, limit=limit)


@app.get("/api/analysis/jobs/{job_id}")
def analysis_job_get(job_id: str, include_output: bool = Query(True)) -> dict[str, Any]:
    root = _require_root()
    try:
        return get_job(root, job_id=job_id, include_output=include_output)
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e


@app.post("/api/graph/upload")
async def graph_upload_material(file: UploadFile = File(...)) -> dict[str, Any]:
    """上传资料到 resource/资料/uploads/，返回相对 resource/ 的路径。"""
    root = _require_root()
    resource = (root / "resource").resolve()
    dest_dir = (resource / "资料" / "uploads").resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)
    assert_within_project(root, dest_dir)
    raw_name = file.filename or "file"
    safe = safe_filename_component(raw_name) or "file"
    name = f"{uuid.uuid4().hex}_{safe}"
    target = (dest_dir / name).resolve()
    assert_within_project(root, target)
    content = await file.read()
    target.write_bytes(content)
    rel = target.relative_to(resource).as_posix()
    return {"ok": True, "relative_path": rel}
