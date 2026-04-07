"""Host-level helpers for TeX / PDF toolchain detection (Windows-focused)."""

from __future__ import annotations

import shutil
import subprocess
import sys
from typing import Any


def tex_status() -> dict[str, Any]:
    """Return whether latexmk / xelatex are discoverable on PATH."""
    latexmk = shutil.which("latexmk")
    xelatex = shutil.which("xelatex")
    winget: str | None = None
    if sys.platform == "win32":
        winget = shutil.which("winget")
    ready = latexmk is not None and xelatex is not None
    return {
        "platform": sys.platform,
        "latexmk_on_path": latexmk is not None,
        "xelatex_on_path": xelatex is not None,
        "winget_on_path": winget is not None if sys.platform == "win32" else None,
        "pdf_engine_ready": ready,
    }


def tex_install_miktex_via_winget() -> dict[str, Any]:
    """Start winget install for MiKTeX (non-blocking). Windows only."""
    if sys.platform != "win32":
        return {"ok": False, "message": "当前系统不支持此一键安装，请按页面说明手动安装 PDF 排版组件。"}
    winget = shutil.which("winget")
    if not winget:
        return {
            "ok": False,
            "message": "未找到系统自带的应用安装器，请从 MiKTeX 官网下载安装包手动安装。",
        }
    cmd = [
        winget,
        "install",
        "MiKTeX.MiKTeX",
        "--accept-source-agreements",
        "--accept-package-agreements",
    ]
    try:
        subprocess.Popen(
            cmd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
    except OSError as e:
        return {"ok": False, "message": f"无法启动安装流程：{e}"}
    return {
        "ok": True,
        "message": "已尝试启动安装程序，请按系统提示完成安装；完成后可点击「重新检测」。",
    }
