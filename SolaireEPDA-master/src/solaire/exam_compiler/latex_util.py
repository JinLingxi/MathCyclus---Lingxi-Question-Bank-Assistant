"""LaTeX escaping for plain-text metadata and path segments for \\graphicspath."""

from __future__ import annotations

import re
from pathlib import Path


def latex_escape_text(s: str) -> str:
    """Escape user-supplied plain text for LaTeX (metadata titles, school names, etc.)."""
    if not s:
        return ""
    out: list[str] = []
    for ch in s:
        if ch == "\\":
            out.append(r"\textbackslash{}")
        elif ch == "{":
            out.append(r"\{")
        elif ch == "}":
            out.append(r"\}")
        elif ch == "$":
            out.append(r"\$")
        elif ch == "&":
            out.append(r"\&")
        elif ch == "%":
            out.append(r"\%")
        elif ch == "#":
            out.append(r"\#")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        elif ch == "_":
            out.append(r"\_")
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        else:
            out.append(ch)
    return "".join(out)


def latex_escape_path_for_graphicspath(path: Path) -> str:
    """Single path component for \\graphicspath{{...}}; must end with /."""
    ap = path.resolve()
    try:
        s = ap.as_posix()
    except Exception:
        s = str(ap)
    if not s.endswith("/"):
        s = s + "/"
    # Escape LaTeX special chars that can appear in paths
    s = s.replace("\\", "/")
    out: list[str] = []
    for ch in s:
        if ch == "{":
            out.append(r"\{")
        elif ch == "}":
            out.append(r"\}")
        elif ch == "%":
            out.append(r"\%")
        elif ch == "#":
            out.append(r"\#")
        elif ch == "&":
            out.append(r"\&")
        elif ch == "~":
            out.append(r"\textasciitilde{}")
        elif ch == "^":
            out.append(r"\textasciicircum{}")
        elif ch == "$":
            out.append(r"\$")
        else:
            out.append(ch)
    return "".join(out)


def build_graphicspath_command(paths: list[Path]) -> str:
    """Full \\graphicspath{{p1/}{p2/}} line (no trailing newline required)."""
    if not paths:
        return ""
    parts = [latex_escape_path_for_graphicspath(p) for p in paths]
    inner = "}{".join(parts)
    return rf"\graphicspath{{{{{inner}}}}}"


# Labels: replace / with something safe for LaTeX \label
_re_label = re.compile(r"[^a-zA-Z0-9_.:-]+")


def latex_safe_label(qualified_id: str) -> str:
    return _re_label.sub("_", qualified_id.replace("/", "_"))
