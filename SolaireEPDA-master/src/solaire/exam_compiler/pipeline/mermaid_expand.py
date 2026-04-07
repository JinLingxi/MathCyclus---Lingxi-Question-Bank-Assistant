"""Render ```mermaid fenced blocks to SVG via mmdr (mermaid-rs-renderer, pure Rust, no browser)."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

_MMDR_HINT = (
    "Mermaid 插图需要 mmdr（Rust 渲染器，无 Chromium/Node）。"
    "安装：cargo install mermaid-rs-renderer，并确保可执行文件 mmdr 在 PATH 中。"
    "说明见 docs/user/mermaid.md。"
)

# mmdr 默认 -w 1200 -H 800，画布过大；略小的画布更适合题库内嵌与 PDF。
_DEFAULT_MERMAID_WIDTH = 640
_DEFAULT_MERMAID_HEIGHT = 420


def _norm_for_hash(body: str) -> str:
    return body.strip().replace("\r\n", "\n")


def mermaid_stem(body: str, block_index: int) -> str:
    h = hashlib.sha256(_norm_for_hash(body).encode("utf-8")).hexdigest()[:16]
    return f"mermaid_{h}_{block_index}"


def _theme_font_family() -> str:
    """mmdr 默认使用 trebuchet/arial 等西文字体，中文在浏览器/PDF 中常显示为空白，需指定 CJK 字体栈。"""
    env = (os.environ.get("SOLAIRE_MERMAID_FONT_FAMILY") or "").strip()
    if env:
        return env
    system = platform.system()
    if system == "Windows":
        return "Microsoft YaHei UI, Microsoft YaHei, SimHei, sans-serif"
    if system == "Darwin":
        return "PingFang SC, Hiragino Sans GB, Heiti SC, sans-serif"
    return "Noto Sans CJK SC, Noto Sans SC, WenQuanYi Micro Hei, Source Han Sans SC, sans-serif"


def _parse_positive_int(name: str, default: int) -> int:
    raw = (os.environ.get(name) or "").strip()
    if not raw:
        return default
    try:
        v = int(raw, 10)
    except ValueError:
        return default
    return v if v > 0 else default


def _mmdr_theme_config_dict() -> dict[str, object]:
    return {
        "themeVariables": {
            "fontFamily": _theme_font_family(),
            "fontSize": 14,
        }
    }


def render_mermaid_to_svg_file(mermaid_body: str, svg_path: Path) -> None:
    """Run mmdr to produce SVG at svg_path."""
    mmdr = shutil.which("mmdr")
    if mmdr is None:
        raise RuntimeError(_MMDR_HINT + "（未在 PATH 中找到 mmdr）")

    width = _parse_positive_int("SOLAIRE_MERMAID_WIDTH", _DEFAULT_MERMAID_WIDTH)
    height = _parse_positive_int("SOLAIRE_MERMAID_HEIGHT", _DEFAULT_MERMAID_HEIGHT)

    svg_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tdir = Path(tmp)
        src = tdir / "diagram.mmd"
        src.write_text(mermaid_body.strip() + "\n", encoding="utf-8")
        tmp_out = tdir / "out.svg"
        cfg_path = tdir / "mmdr-theme.json"
        cfg_path.write_text(json.dumps(_mmdr_theme_config_dict(), ensure_ascii=False), encoding="utf-8")

        cmd = [
            mmdr,
            "-i",
            str(src),
            "-o",
            str(tmp_out),
            "-e",
            "svg",
            "-c",
            str(cfg_path),
            "-w",
            str(width),
            "-H",
            str(height),
        ]
        try:
            subprocess.run(
                cmd,
                check=True,
                capture_output=True,
                text=True,
                timeout=120,
            )
        except FileNotFoundError as e:
            raise RuntimeError(_MMDR_HINT) from e
        except subprocess.CalledProcessError as e:
            err = (e.stderr or e.stdout or str(e))[:800]
            raise RuntimeError(f"Mermaid 渲染失败（mmdr）：{err}") from e
        except subprocess.TimeoutExpired as e:
            raise RuntimeError("Mermaid 渲染超时（mmdr）") from e
        if not tmp_out.is_file():
            raise RuntimeError("Mermaid 渲染未生成 SVG 文件")
        svg_path.write_text(tmp_out.read_text(encoding="utf-8"), encoding="utf-8")
