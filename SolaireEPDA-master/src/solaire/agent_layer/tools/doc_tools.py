"""Document conversion tools: Word→Markdown, PDF→text, image→OCR."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult
from solaire.common.security import assert_within_project


def _resolve(ctx: InvocationContext, rel: str) -> Path:
    p = (ctx.project_root / rel).resolve()
    assert_within_project(ctx.project_root, p)
    return p


def tool_doc_convert_to_markdown(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or "")
    if not rel:
        return ToolResult(status="failed", error_message="path 参数必填")
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not p.is_file():
        return ToolResult(status="failed", error_message=f"文件不存在: {rel}")
    if shutil.which("pandoc") is None:
        return ToolResult(
            status="failed",
            error_message="系统未安装 pandoc，无法进行文档转换。请联系管理员安装 pandoc 后重试。",
        )
    try:
        result = subprocess.run(
            ["pandoc", str(p), "-t", "markdown", "--wrap=none"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            return ToolResult(status="failed", error_message=f"pandoc 转换失败: {result.stderr[:500]}")
        md = result.stdout
        out_rel = str(Path(rel).with_suffix(".md"))
        out_path = _resolve(ctx, out_rel)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(md, encoding="utf-8")
        return ToolResult(data={
            "source": rel,
            "output": out_rel,
            "chars": len(md),
            "preview": md[:2000],
        })
    except subprocess.TimeoutExpired:
        return ToolResult(status="failed", error_message="pandoc 转换超时（60秒）")
    except Exception as e:
        return ToolResult(status="failed", error_message=f"转换出错: {e}")


def tool_doc_extract_pdf_text(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
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
        import pdfplumber
    except ImportError:
        return ToolResult(
            status="failed",
            error_message="未安装 pdfplumber 库，无法提取 PDF 文本。请联系管理员执行 pip install pdfplumber。",
        )
    try:
        pages_text: list[str] = []
        with pdfplumber.open(str(p)) as pdf:
            for page in pdf.pages:
                text = page.extract_text() or ""
                pages_text.append(text)
        full = "\n\n---\n\n".join(pages_text)
        return ToolResult(data={
            "source": rel,
            "pages": len(pages_text),
            "chars": len(full),
            "content": full[:20000],
        })
    except Exception as e:
        return ToolResult(status="failed", error_message=f"PDF 提取失败: {e}")


def tool_doc_ocr_image(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    rel = str(args.get("path") or "")
    lang = str(args.get("lang") or "chi_sim+eng")
    if not rel:
        return ToolResult(status="failed", error_message="path 参数必填")
    try:
        p = _resolve(ctx, rel)
    except Exception as e:
        return ToolResult(status="failed", error_message=str(e))
    if not p.is_file():
        return ToolResult(status="failed", error_message=f"文件不存在: {rel}")
    try:
        from PIL import Image
        import pytesseract
    except ImportError:
        return ToolResult(
            status="failed",
            error_message="未安装 OCR 依赖（Pillow + pytesseract）。请联系管理员安装后重试。",
        )
    try:
        img = Image.open(str(p))
        text = pytesseract.image_to_string(img, lang=lang)
        return ToolResult(data={
            "source": rel,
            "lang": lang,
            "chars": len(text),
            "content": text[:20000],
        })
    except Exception as e:
        return ToolResult(status="failed", error_message=f"OCR 识别失败: {e}")
