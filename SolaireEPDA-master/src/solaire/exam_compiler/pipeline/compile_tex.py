"""Invoke latexmk for XeLaTeX builds."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


class LatexmkError(RuntimeError):
    pass


# 仅匹配 work_dir 根目录下的常见中间件；不递归子目录（避免误删题图等资源目录里的同名扩展名）。
_LATEX_INTERMEDIATE_GLOBS: tuple[str, ...] = (
    "*.aux",
    "*.log",
    "*.out",
    "*.toc",
    "*.fdb_latexmk",
    "*.fls",
    "*.xdv",
    "*.synctex.gz",
    "*.nav",
    "*.snm",
    "*.bcf",
    "*.run.xml",
    "*.bbl",
    "*.blg",
)


def clean_latex_intermediates(workdir: Path) -> None:
    """
    删除上一次编译留下的中间文件，避免与当前导言区不一致时读入陈旧 .aux 导致
    ``Undefined control sequence``（例如 ``\\pgfsyspdfmark``）。
    """
    workdir = workdir.resolve()
    if not workdir.is_dir():
        return
    for pattern in _LATEX_INTERMEDIATE_GLOBS:
        for p in workdir.glob(pattern):
            if p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass


def format_latexmk_failure_message(exc: LatexmkError, *, max_chars: int = 12_000) -> str:
    """
    供 Web/API 返回用户可读摘要：保留输出末尾，避免整段日志过长难以在 UI 中展示。
    """
    raw = str(exc).strip()
    if len(raw) <= max_chars:
        body = raw
    else:
        omitted = len(raw) - max_chars
        body = f"…（已省略前 {omitted} 字符）…\n\n{raw[-max_chars:]}"
    return "PDF 编译失败（XeLaTeX / latexmk）。以下为输出摘要：\n\n" + body


def run_latexmk(workdir: Path, tex_file: Path, *, timeout: float = 300.0) -> None:
    """Run latexmk in ``workdir`` on ``tex_file`` (filename only, must live under workdir)."""
    workdir = workdir.resolve()
    tex_file = tex_file.resolve()
    if tex_file.parent != workdir:
        raise ValueError("tex_file must be directly under workdir")
    name = tex_file.name
    cmd = [
        "latexmk",
        "-xelatex",
        "-interaction=nonstopmode",
        "-halt-on-error",
        name,
    ]
    try:
        subprocess.run(
            cmd,
            cwd=workdir,
            check=True,
            timeout=timeout,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError as e:
        raise LatexmkError(
            "latexmk not found. Install TeX Live or MiKTeX and ensure latexmk is on PATH."
        ) from e
    except subprocess.CalledProcessError as e:
        log = (e.stderr or "") + "\n" + (e.stdout or "")
        raise LatexmkError(f"latexmk failed for {name}:\n{log}") from e
    except subprocess.TimeoutExpired as e:
        raise LatexmkError(f"latexmk timed out for {name}") from e


def copy_pdf_if_exists(src_dir: Path, stem: str, dest_dir: Path) -> Path:
    pdf = src_dir / f"{stem}.pdf"
    if not pdf.is_file():
        raise FileNotFoundError(f"Expected PDF not found: {pdf}")
    dest_dir.mkdir(parents=True, exist_ok=True)
    out = dest_dir / pdf.name
    shutil.copy2(pdf, out)
    return out
