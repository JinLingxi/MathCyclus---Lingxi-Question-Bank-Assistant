"""HTTP routes for M3 Agent Harness (SSE chat, sessions, memory, confirm, upload, prompts)."""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from solaire.agent_layer.guardrails import (
    SAFETY_MODE_CHOICES,
    list_safety_modes_public,
    load_safety_mode,
    save_safety_mode,
)
from solaire.agent_layer.llm.llm_overrides import load_overrides_raw, mask_api_key, save_overrides_raw
from solaire.agent_layer.llm.router import load_llm_settings
from solaire.agent_layer.memory import list_topic_filenames, read_index, read_topic, write_index, write_topic
from solaire.agent_layer.cancel_signal import clear_cancel, request_cancel
from solaire.agent_layer.orchestrator import iter_agent_turn_sse
from solaire.agent_layer.skills import list_skills_public
from solaire.agent_layer.session import create_session, delete_session, list_sessions, load_session
from solaire.knowledge_forge import load_graph
from solaire.web import state
from solaire.web.result_service import list_exam_results

router = APIRouter(prefix="/agent", tags=["agent"])


def _require_root() -> Path:
    r = state.get_root()
    if r is None:
        raise HTTPException(status_code=400, detail="未打开项目")
    return r


def _project_ctx(root: Path) -> dict[str, Any]:
    try:
        exams = list_exam_results(root)
        exam_summary = f"{len(exams)} 场考试记录" if exams else "暂无考试结果"
    except Exception:
        exam_summary = "考试列表暂不可用"
    template_count = 0
    td = root / "templates"
    if td.is_dir():
        template_count = len(list(td.rglob("*.yaml")))
    try:
        g = load_graph(root)
        node_count = len(g.nodes)
    except Exception:
        node_count = 0
    return {
        "project_label": root.name,
        "exam_summary": exam_summary,
        "template_count": template_count,
        "graph_node_count": node_count,
    }


class AgentPageContextBody(BaseModel):
    """教师当前前端界面上下文（由 Web 传入，注入系统提示）。"""

    current_page: str | None = None
    selected_resource_type: str | None = None
    selected_resource_id: str | None = None
    summary: str | None = None


class FileAttachment(BaseModel):
    path: str
    mime_type: str | None = None
    original_name: str | None = None


class AgentChatBody(BaseModel):
    session_id: str | None = None
    message: str | None = None
    mode: str = Field(default="execute", description="execute 或 suggest")
    confirm_action_id: str | None = None
    confirm_accepted: bool | None = None
    page_context: AgentPageContextBody | None = None
    skill_id: str | None = Field(default=None, description="内置技能标识，收窄工具与指引")
    file_attachments: list[FileAttachment] | None = Field(default=None, description="附件文件列表")
    execution_plan_path: str | None = Field(
        default=None,
        description="教师批准执行的计划文件项目内相对路径（与 exit_plan_mode 一致）",
    )


class MemoryPutBody(BaseModel):
    content: str = Field(..., description="完整文件内容")


class LLMSettingsPutBody(BaseModel):
    """写入项目内覆盖；字段为 None 表示不修改该项。"""

    main_model: str | None = None
    fast_model: str | None = None
    base_url: str | None = None
    api_key: str | None = None
    clear_api_key_override: bool = False
    max_tokens: int | None = None


class SafetyModePutBody(BaseModel):
    mode: str = Field(..., description="moderato / allegro / vivace / prestissimo")


@router.get("/config")
def agent_config() -> dict[str, Any]:
    root = state.get_root()
    s = load_llm_settings(root)
    return {
        "llm_configured": bool(s.api_key),
        "main_model": s.main_model,
        "fast_model": s.fast_model,
        "base_url_set": bool(s.base_url),
        "safety_mode": load_safety_mode(root),
    }


@router.get("/llm-settings")
def agent_llm_settings_get() -> dict[str, Any]:
    root = state.get_root()
    eff = load_llm_settings(root)
    raw = load_overrides_raw(root) if root is not None else {}
    return {
        "persist_available": root is not None,
        "main_model": eff.main_model,
        "fast_model": eff.fast_model,
        "base_url": eff.base_url or "",
        "llm_configured": bool(eff.api_key),
        "api_key_masked": mask_api_key(eff.api_key),
        "has_project_api_key_override": bool(raw.get("api_key")),
        "max_tokens": eff.max_tokens,
    }


@router.put("/llm-settings")
def agent_llm_settings_put(body: LLMSettingsPutBody) -> dict[str, Any]:
    root = _require_root()
    current = load_overrides_raw(root)
    if body.clear_api_key_override:
        current.pop("api_key", None)
    if body.api_key is not None and body.api_key.strip():
        current["api_key"] = body.api_key.strip()
    if body.main_model is not None:
        if body.main_model.strip() == "":
            current.pop("main_model", None)
        else:
            current["main_model"] = body.main_model.strip()
    if body.fast_model is not None:
        if body.fast_model.strip() == "":
            current.pop("fast_model", None)
        else:
            current["fast_model"] = body.fast_model.strip()
    if body.base_url is not None:
        if body.base_url.strip() == "":
            current.pop("base_url", None)
        else:
            current["base_url"] = body.base_url.strip()
    if body.max_tokens is not None:
        if body.max_tokens <= 0:
            current.pop("max_tokens", None)
        else:
            current["max_tokens"] = str(body.max_tokens)
    save_overrides_raw(root, current)
    return {"ok": True}


@router.get("/safety-mode")
def agent_safety_mode_get() -> dict[str, Any]:
    root = state.get_root()
    return {
        "persist_available": root is not None,
        "mode": load_safety_mode(root),
        "options": list_safety_modes_public(),
    }


@router.put("/safety-mode")
def agent_safety_mode_put(body: SafetyModePutBody) -> dict[str, Any]:
    root = _require_root()
    mode = str(body.mode).strip().lower()
    if mode not in SAFETY_MODE_CHOICES:
        raise HTTPException(status_code=400, detail="无效策略模式")
    save_safety_mode(root, mode)
    return {"ok": True}


@router.get("/skills")
def agent_skills_list() -> dict[str, Any]:
    root = state.get_root()
    return {"skills": list_skills_public(root)}


@router.get("/sessions")
def agent_sessions_list() -> dict[str, Any]:
    root = _require_root()
    return {"sessions": list_sessions(root)}


@router.post("/sessions")
def agent_sessions_create() -> dict[str, Any]:
    root = _require_root()
    s = create_session(root)
    return {"session_id": s.session_id, "created_at": s.created_at}


@router.get("/sessions/{session_id}")
def agent_session_get(session_id: str) -> dict[str, Any]:
    root = _require_root()
    s = load_session(root, session_id)
    if s is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"session": s.model_dump(mode="json")}


@router.delete("/sessions/{session_id}")
def agent_session_delete(session_id: str) -> dict[str, Any]:
    root = _require_root()
    ok = delete_session(root, session_id)
    if not ok:
        raise HTTPException(status_code=404, detail="会话不存在")
    return {"ok": True}


@router.post("/sessions/{session_id}/cancel")
def agent_session_cancel(session_id: str) -> dict[str, Any]:
    root = _require_root()
    if load_session(root, session_id) is None:
        raise HTTPException(status_code=404, detail="会话不存在")
    request_cancel(session_id)
    return {"ok": True}


@router.get("/memory")
def agent_memory_index() -> dict[str, Any]:
    root = _require_root()
    return {"content": read_index(root)}


@router.put("/memory")
def agent_memory_index_put(body: MemoryPutBody) -> dict[str, Any]:
    root = _require_root()
    write_index(root, body.content)
    return {"ok": True}


@router.get("/memory/topics")
def agent_memory_topics_list() -> dict[str, Any]:
    root = _require_root()
    return {"topics": list_topic_filenames(root)}


@router.get("/memory/{topic:path}")
def agent_memory_topic_get(topic: str) -> dict[str, Any]:
    root = _require_root()
    if not topic.endswith(".md"):
        topic = f"{topic}.md"
    return {"topic": topic, "content": read_topic(root, topic)}


@router.put("/memory/{topic:path}")
def agent_memory_topic_put(topic: str, body: MemoryPutBody) -> dict[str, Any]:
    root = _require_root()
    if not topic.endswith(".md"):
        topic = f"{topic}.md"
    write_topic(root, topic, body.content)
    return {"ok": True, "topic": topic}


# --- Phase 2: File upload ---

_ALLOWED_UPLOAD_SUFFIXES = {
    ".txt", ".md", ".yaml", ".yml", ".csv", ".json", ".xml",
    ".docx", ".doc", ".pdf", ".png", ".jpg", ".jpeg", ".gif",
}
_MAX_UPLOAD_SIZE = 10 * 1024 * 1024  # 10 MB


@router.post("/upload")
async def agent_upload(file: UploadFile = File(...), session_id: str | None = None) -> dict[str, Any]:
    root = _require_root()
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")
    suffix = Path(file.filename).suffix.lower()
    if suffix not in _ALLOWED_UPLOAD_SUFFIXES:
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {suffix}")
    content = await file.read()
    if len(content) > _MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件大小超过 10MB 限制")
    sid = session_id or uuid.uuid4().hex[:12]
    upload_dir = root / ".solaire" / "uploads" / sid
    upload_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(file.filename).name
    dest = upload_dir / safe_name
    counter = 0
    while dest.exists():
        counter += 1
        dest = upload_dir / f"{dest.stem}_{counter}{dest.suffix}"
    dest.write_bytes(content)
    rel_path = str(dest.relative_to(root)).replace("\\", "/")
    return {
        "ok": True,
        "path": rel_path,
        "mime_type": file.content_type,
        "original_name": file.filename,
        "size": len(content),
    }


# --- Phase 5: System prompt overrides ---

class PromptOverridePutBody(BaseModel):
    content: str = Field(..., description="系统提示覆盖内容（Markdown 格式）")


@router.get("/prompt-overrides")
def agent_prompt_overrides_get() -> dict[str, Any]:
    root = _require_root()
    p = root / ".solaire" / "agent" / "system_prompt_overrides.md"
    content = ""
    if p.is_file():
        try:
            content = p.read_text(encoding="utf-8")
        except Exception:
            pass
    return {"content": content}


@router.put("/prompt-overrides")
def agent_prompt_overrides_put(body: PromptOverridePutBody) -> dict[str, Any]:
    root = _require_root()
    p = root / ".solaire" / "agent" / "system_prompt_overrides.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body.content, encoding="utf-8")
    return {"ok": True}


@router.post("/chat")
async def agent_chat(body: AgentChatBody) -> StreamingResponse:
    root = _require_root()
    s = load_session(root, body.session_id) if body.session_id else None
    if s is None:
        if body.session_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        s = create_session(root)
    if (body.message is None or not str(body.message).strip()) and body.confirm_action_id is None:
        raise HTTPException(status_code=400, detail="message 或 confirm_action_id 必填其一")

    clear_cancel(s.session_id)

    ctx = _project_ctx(root)
    if body.page_context is not None:
        ctx = {**ctx, "page_context": body.page_context.model_dump(exclude_none=True)}
    if body.skill_id is not None and str(body.skill_id).strip():
        ctx = {**ctx, "_skill_id": str(body.skill_id).strip()}
    if body.execution_plan_path is not None and str(body.execution_plan_path).strip():
        ctx = {**ctx, "_execution_plan_path": str(body.execution_plan_path).strip()}

    user_msg = body.message.strip() if body.message else None
    if body.file_attachments and user_msg:
        attachment_lines = ["\n\n📎 附件文件："]
        for att in body.file_attachments:
            name = att.original_name or Path(att.path).name
            attachment_lines.append(f"- `{att.path}`（{name}，{att.mime_type or '未知类型'}）")
        attachment_lines.append("请根据文件类型选择合适的工具处理（如 file.read、doc.convert_to_markdown 等）。")
        user_msg += "\n".join(attachment_lines)

    async def gen():
        import json as _json

        yield f"event: session\ndata: {_json.dumps({'session_id': s.session_id}, ensure_ascii=False)}\n\n"
        async for chunk in iter_agent_turn_sse(
            root,
            s,
            user_message=user_msg,
            project_ctx=ctx,
            mode=body.mode,
            confirm_action_id=body.confirm_action_id,
            confirm_accepted=body.confirm_accepted,
        ):
            yield chunk

    return StreamingResponse(gen(), media_type="text/event-stream")
