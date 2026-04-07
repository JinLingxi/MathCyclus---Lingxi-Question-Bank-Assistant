"""选择题选项排布启发式：单行 / 双行（两列）/ 每行一项。"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

# 粗略「视觉单位」阈值，按正文宽度约一行 80–90 单位调参（非精确排版）
_ONELINE_TOTAL = 82.0
_ONELINE_MAX_SINGLE = 44.0
_ROW_PAIR_TOTAL = 88.0  # 同一行放两个选项时，两者单位之和上限
_GRID_MAX_SINGLE = 115.0  # 超过则不再用双行表，改为一项一行（避免单元格内折行过多）

# 视觉权重常数（相对单位）
_DELIM = 0.32  # \(\{\) \(\}\) ( ) [ ] 等定界符，几乎不占排版宽度
_GROUP_SKIN = 0.12  # 纯分组 `{...}` 外壳
_FRAC_OVERHEAD = 0.75  # \frac 等分数线与间距
_SQRT_OVERHEAD = 0.9
_TEXT_WRAPPER_SKIN = 0.2  # \mathrm \text 等外壳
_GENERIC_CMD = 0.85  # 其它单段数学命令如 \pi \alpha
_SPACE_CMD_WEIGHT = 0.28  # \, \quad 等


_CMD_FRAC = frozenset({"frac", "dfrac", "tfrac", "cfrac"})
_TEXT_WRAPPERS = frozenset(
    {"mathrm", "mathit", "mathbf", "textbf", "textrm", "text", "operatorname", "boldsymbol"}
)
_SPACE_CMDS = frozenset({",", ";", ":", "!", "quad", "qquad"})
# 单字符命令名（反斜杠后一字）
_SINGLE_CHAR_CMD_DELIMS = frozenset({"(", ")", "[", "]", "{", "}"})


def _read_command_name(s: str, i: int) -> tuple[str, int]:
    r"""反斜杠已跳过，从 s[i] 起读命令名；`\{` 等返回单字符。"""
    n = len(s)
    if i >= n:
        return "", i
    c = s[i]
    if not c.isalpha():
        return c, i + 1
    j = i
    while j < n and s[j].isalpha():
        j += 1
    return s[i:j], j


def _read_braced(s: str, i: int) -> tuple[str, int]:
    """s[i] 为 `{`，返回 (内部子串, `}` 后下标)。"""
    n = len(s)
    if i >= n or s[i] != "{":
        return "", i
    depth = 1
    j = i + 1
    start = j
    while j < n and depth:
        if s[j] == "\\":
            j += 1
            if j < n:
                j += 1
            continue
        if s[j] == "{":
            depth += 1
        elif s[j] == "}":
            depth -= 1
            if depth == 0:
                return s[start:j], j + 1
        j += 1
    return s[start:j], j


def _skip_optional_square(s: str, i: int) -> int:
    """跳过可选 `[ ... ]`（支持嵌套）。"""
    n = len(s)
    if i >= n or s[i] != "[":
        return i
    depth = 1
    j = i + 1
    while j < n and depth:
        if s[j] == "\\":
            j += 2 if j + 1 < n else 2
            continue
        if s[j] == "[":
            depth += 1
        elif s[j] == "]":
            depth -= 1
        j += 1
    return j


def _segment_weight(s: str, start: int, end: int) -> float:
    """对 s[start:end] 求视觉权重（不含数学模式外壳 `$`）。"""
    w = 0.0
    i = start
    n = min(end, len(s))
    while i < n:
        c = s[i]
        if c == "\\":
            cmd, j = _read_command_name(s, i + 1)
            if cmd in _CMD_FRAC:
                k = _skip_optional_square(s, j)
                a, k = _read_braced(s, k)
                b, k = _read_braced(s, k)
                w += _FRAC_OVERHEAD + _weight_core(a) + _weight_core(b)
                i = k
                continue
            if cmd == "sqrt":
                k = _skip_optional_square(s, j)
                if k < n and s[k] == "{":
                    inner, k = _read_braced(s, k)
                    w += _SQRT_OVERHEAD + _weight_core(inner)
                else:
                    w += _SQRT_OVERHEAD + 0.55
                    k = k + 1 if k < n else k
                i = k
                continue
            if cmd in _TEXT_WRAPPERS:
                k = j
                if k < n and s[k] == "{":
                    inner, k = _read_braced(s, k)
                    w += _TEXT_WRAPPER_SKIN + _weight_core(inner)
                else:
                    w += _GENERIC_CMD
                i = k
                continue
            if cmd in _SPACE_CMDS:
                w += _SPACE_CMD_WEIGHT
                i = j
                continue
            if cmd in _SINGLE_CHAR_CMD_DELIMS or cmd in ("lvert", "rvert", "Vert"):
                w += _DELIM
                i = j
                continue
            if cmd == "," and j == i + 1:  # `\,`
                w += _SPACE_CMD_WEIGHT
                i = j
                continue
            w += _GENERIC_CMD
            i = j
            continue
        if c == "{":
            inner, j = _read_braced(s, i)
            w += _GROUP_SKIN * 2 + _weight_core(inner)
            i = j
            continue
        if c in "()[]":
            w += _DELIM
            i += 1
            continue
        if c in "^_":
            w += 0.32
            i += 1
            if i < n and s[i] == "{":
                inner, i = _read_braced(s, i)
                w += _weight_core(inner)
            elif i < n:
                w += 0.48
                i += 1
            continue
        if c.isspace():
            w += 0.18
            i += 1
            continue
        o = ord(c)
        if o > 126:
            w += 2.0
        elif c.isdigit():
            w += 0.52
        elif c in ",.;:":
            w += 0.32
        else:
            w += 1.0
        i += 1
    return w


def _weight_core(s: str) -> float:
    return _segment_weight(s, 0, len(s))


def option_visual_weight(s: str) -> float:
    """
    估计选项在试卷一行中的占用（相对单位）。

    - 定界符 ``\\{`` ``\\}`` ``( ) [ ]`` 等只计极低权重。
    - 分组 ``{...}`` 主要计内部，外壳几乎不计。
    - 容器命令 ``\\frac`` ``\\dfrac``、``\\sqrt{...}``、``\\mathrm{...}`` 等按内部子内容累计，外加很小常数。
    """
    t = s.strip()
    if len(t) >= 2 and t[0] == "$" and t[-1] == "$":
        return _weight_core(t[1:-1])
    return _weight_core(t)


def infer_choice_layout(options: dict[str, str]) -> str:
    """
    返回 ``inline_one_line`` | ``grid_two_rows`` | ``stack``。

    - **inline_one_line**：整行横排，项间 ``\\quad``。
    - **grid_two_rows**：双行两列表格（四选典型为 2×2；三选为 AB / C）。
    - **stack**：传统 ``enumerate``，一项一行。
    """
    if not options:
        return "stack"
    letters = [k for k, _ in sorted(options.items())]
    texts = [options[k] for k in letters]
    m = len(letters)
    widths = [option_visual_weight(t) for t in texts]
    max_w = max(widths)
    sep = 4.0
    total = sum(widths) + sep * max(0, m - 1)

    if m <= 1:
        return "stack"

    one_line_ok = total <= _ONELINE_TOTAL and max_w <= _ONELINE_MAX_SINGLE
    if one_line_ok:
        return "inline_one_line"

    if max_w > _GRID_MAX_SINGLE:
        return "stack"

    if m == 2:
        if widths[0] + widths[1] + sep <= _ROW_PAIR_TOTAL:
            return "grid_two_rows"
        return "stack"

    if m == 3:
        if widths[0] + widths[1] + sep <= _ROW_PAIR_TOTAL:
            return "grid_two_rows"
        return "stack"

    if m == 4:
        row0 = widths[0] + widths[1] + sep
        row1 = widths[2] + widths[3] + sep
        if row0 <= _ROW_PAIR_TOTAL and row1 <= _ROW_PAIR_TOTAL:
            return "grid_two_rows"
        return "stack"

    if m > 4:
        return "stack"

    return "stack"


_VALID_FORCED_LAYOUTS = frozenset({"inline_one_line", "grid_two_rows", "stack"})


def resolve_choice_layout(
    metadata: Mapping[str, Any] | None,
    options: dict[str, str] | None,
) -> str:
    """
    合并后 ``metadata`` 中 ``choice_layout_mode`` 可覆盖启发式：

    - ``auto``（默认）：同 :func:`infer_choice_layout`
    - ``inline_one_line`` / ``grid_two_rows`` / ``stack``：强制该版式（全体选择题）
    - 别名：``inline`` → ``inline_one_line``；``grid`` / ``two_rows`` → ``grid_two_rows``；
      ``vertical`` / ``enumerate`` → ``stack``
    """
    meta = metadata or {}
    raw = meta.get("choice_layout_mode", "auto")
    if isinstance(raw, str):
        m = raw.strip().lower().replace("-", "_")
        aliases = {
            "inline": "inline_one_line",
            "grid": "grid_two_rows",
            "two_rows": "grid_two_rows",
            "vertical": "stack",
            "enumerate": "stack",
        }
        m = aliases.get(m, m)
        if m in _VALID_FORCED_LAYOUTS:
            return m
    if options:
        return infer_choice_layout(options)
    return "stack"


def choice_option_pairs(options: dict[str, str]) -> list[tuple[str, str]]:
    """按字母序 (A,B,...) 的 (选项字母, 原文) 列表，供模板渲染。"""
    return list(sorted(options.items()))
