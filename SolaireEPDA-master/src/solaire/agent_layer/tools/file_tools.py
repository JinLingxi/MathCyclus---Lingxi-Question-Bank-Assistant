"""Project-internal file tools: read, write, edit, list, search."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.agent_layer.plan_document import PLAN_MD_FRONTMATTER
from solaire.common.security import assert_within_project

# 计划模式：仅允许落盘到该目录（与 Cursor 类 harness 一致）
_AGENT_PLANS_SEGMENTS = (".solaire", "agent", "plans")


def _normalize_rel(rel: str) -> str:
    return str(rel).replace("\\", "/").strip()


def _is_under_agent_plans(project_root: Path, rel: str) -> bool:
    """项目内相对路径是否位于 .solaire/agent/plans/ 下（含该目录本身下的文件）。"""
    raw = _normalize_rel(rel)
    if not raw or ".." in raw.split("/"):
        return False
    try:
        p = (project_root / raw).resolve()
        assert_within_project(project_root, p)
        plans_root = (project_root.joinpath(*_AGENT_PLANS_SEGMENTS)).resolve()
        if p == plans_root:
            return False
        return plans_root in p.parents or p.parent == plans_root
    except Exception:
        return False


def _plan_mode_write_path_ok(ctx: InvocationContext, rel: str) -> bool:
    if ctx.session is None or not ctx.session.plan_mode_active:
        return True
    return _is_under_agent_plans(ctx.project_root, rel)


def _validate_plan_markdown_harness(content: str) -> tuple[bool, str]:
    """计划模式落盘的 *.md：YAML --- 围栏 + name/overview/todos（对齐 Cursor 等 plan 文件形态）。"""
    text = content.lstrip("\ufeff")
    m = PLAN_MD_FRONTMATTER.match(text)
    if not m:
        return False, "须以 YAML 围栏开头：首行 ---，中间为 YAML，再以独占一行的 --- 结束，随后为正文"
    fm = m.group("fm")
    if "name:" not in fm:
        return False, "YAML 围栏内须包含 name 字段"
    if "overview:" not in fm:
        return False, "YAML 围栏内须包含 overview 字段"
    if "todos" not in fm:
        return False, "YAML 围栏内须包含 todos 字段（任务列表，含 id/content/status 等）"
    return True, ""


def _resolve(ctx: InvocationContext, rel: str) -> Path:
    p = (ctx.project_root / rel).resolve()
    assert_within_project(ctx.project_root, p)
    return p


def tool_file_read(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or "")
    if not rel:
        return ToolResult(status="failed", error_message="path 参数必填")
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not p.is_file():
        return ToolResult(status="failed", error_message=f"文件不存在: {rel}")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"读取失败: {e}")
    offset = int(args.get("offset") or 0)
    limit = args.get("limit")
    lines = text.splitlines(keepends=True)
    total = len(lines)
    if offset > 0:
        lines = lines[offset:]
    if limit is not None:
        lines = lines[: int(limit)]
    content = "".join(lines)
    return ToolResult(data={"path": rel, "total_lines": total, "content": content})


def tool_file_write(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or "")
    content = args.get("content")
    if not rel:
        return ToolResult(status="failed", error_message="path 参数必填")
    if content is None:
        return ToolResult(status="failed", error_message="content 参数必填")
    if not _plan_mode_write_path_ok(ctx, rel):
        return ToolResult(
            status="failed",
            error_message="计划模式下仅允许写入项目内 `.solaire/agent/plans/` 目录下的文件",
        )
    body = str(content)
    if ctx.session and ctx.session.plan_mode_active and _normalize_rel(rel).lower().endswith(".md"):
        ok, err = _validate_plan_markdown_harness(body)
        if not ok:
            return ToolResult(status="failed", error_message=err)
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"写入失败: {e}")
    return ToolResult(data={"path": rel, "bytes_written": len(str(content).encode("utf-8"))})


def tool_file_edit(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or "")
    old_string = args.get("old_string")
    new_string = args.get("new_string")
    if not rel:
        return ToolResult(status="failed", error_message="path 参数必填")
    if old_string is None or new_string is None:
        return ToolResult(status="failed", error_message="old_string 和 new_string 参数必填")
    old_string = str(old_string)
    new_string = str(new_string)
    if old_string == new_string:
        return ToolResult(status="failed", error_message="old_string 与 new_string 相同，无需替换")
    if not _plan_mode_write_path_ok(ctx, rel):
        return ToolResult(
            status="failed",
            error_message="计划模式下仅允许编辑项目内 `.solaire/agent/plans/` 目录下的文件",
        )
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not p.is_file():
        return ToolResult(status="failed", error_message=f"文件不存在: {rel}")
    try:
        text = p.read_text(encoding="utf-8")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"读取失败: {e}")
    count = text.count(old_string)
    if count == 0:
        return ToolResult(status="failed", error_message="未找到匹配的 old_string")
    if count > 1 and not args.get("replace_all"):
        return ToolResult(
            status="failed",
            error_message=f"old_string 在文件中出现 {count} 次，请提供更多上下文使其唯一，或设置 replace_all=true",
        )
    result = text.replace(old_string, new_string) if args.get("replace_all") else text.replace(old_string, new_string, 1)
    if ctx.session and ctx.session.plan_mode_active and _normalize_rel(rel).lower().endswith(".md"):
        ok, err = _validate_plan_markdown_harness(result)
        if not ok:
            return ToolResult(status="failed", error_message=err)
    try:
        p.write_text(result, encoding="utf-8")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"写入失败: {e}")
    return ToolResult(data={"path": rel, "replacements": count if args.get("replace_all") else 1})


def tool_file_list(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or ".")
    pattern = str(args.get("pattern") or "*")
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not p.is_dir():
        return ToolResult(status="failed", error_message=f"目录不存在: {rel}")
    entries: list[dict[str, Any]] = []
    try:
        for item in sorted(p.iterdir()):
            if not fnmatch.fnmatch(item.name, pattern):
                continue
            try:
                assert_within_project(ctx.project_root, item)
            except Exception:
                continue
            rel_path = str(item.relative_to(ctx.project_root)).replace("\\", "/")
            entries.append({
                "name": item.name,
                "path": rel_path,
                "is_dir": item.is_dir(),
                "size": item.stat().st_size if item.is_file() else None,
            })
            if len(entries) >= 200:
                break
    except Exception as e:
        return ToolResult(status="failed", error_message=f"列目录失败: {e}")
    return ToolResult(data={"path": rel, "entries": entries, "count": len(entries)})


def tool_file_search(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    pattern_str = str(args.get("pattern") or "")
    rel = str(args.get("path") or ".")
    if not pattern_str:
        return ToolResult(status="failed", error_message="pattern 参数必填")
    try:
        regex = re.compile(pattern_str, re.IGNORECASE if args.get("ignore_case") else 0)
    except re.error as e:
        return ToolResult(status="failed", error_message=f"正则语法错误: {e}")
    try:
        base = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not base.exists():
        return ToolResult(status="failed", error_message=f"路径不存在: {rel}")
    matches: list[dict[str, Any]] = []
    max_matches = int(args.get("max_matches") or 50)
    files_to_search: list[Path] = []
    if base.is_file():
        files_to_search = [base]
    else:
        for root_dir, _dirs, files in os.walk(base):
            rd = Path(root_dir)
            for skip in (".git", "__pycache__", "node_modules", ".solaire"):
                if skip in _dirs:
                    _dirs.remove(skip)
            for fname in files:
                fp = rd / fname
                try:
                    assert_within_project(ctx.project_root, fp)
                except Exception:
                    continue
                files_to_search.append(fp)
                if len(files_to_search) > 5000:
                    break
            if len(files_to_search) > 5000:
                break
    for fp in files_to_search:
        if len(matches) >= max_matches:
            break
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        for line_no, line in enumerate(text.splitlines(), 1):
            if regex.search(line):
                rp = str(fp.relative_to(ctx.project_root)).replace("\\", "/")
                matches.append({"file": rp, "line": line_no, "text": line.rstrip()[:300]})
                if len(matches) >= max_matches:
                    break
    return ToolResult(data={"pattern": pattern_str, "matches": matches, "count": len(matches)})
