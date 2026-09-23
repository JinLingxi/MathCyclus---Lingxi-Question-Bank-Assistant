"""Smoke test the unified per-question editor across batch entry modes."""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from streamlit.testing.v1 import AppTest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FORMAL_DB = PROJECT_ROOT / "data" / "mathcyclus.sqlite3"
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


SAMPLE_TEX = r"""
\begin{problem}{2016}{G}{统一烟测试卷}{1}{集合}
已知集合 $A=\{1,2\}$。
\end{problem}
\begin{answer}$2$\end{answer}
\begin{solutions}直接计算。\end{solutions}

\begin{problem}{2016}{G}{统一烟测试卷}{2}{函数}
函数 $f(x)=x$ 的图象是
\begin{choices}
\choice{直线}
\choice{圆}
\end{choices}
\end{problem}
\begin{answer}A\end{answer}
\begin{solutions}一次函数图象为直线。\end{solutions}
""".strip()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else ""


def main() -> int:
    before = sha256(FORMAL_DB)
    app = AppTest.from_string(
        "from question_bank_app import render_sqlite_manual_draft_entry\nrender_sqlite_manual_draft_entry()",
        default_timeout=30,
    ).run()
    checks = {"initial_render": not app.exception}
    mode_radio = next(item for item in app.radio if item.label == "录入方式")
    for mode in ["批量试题录入", "同卷试题录入", "同书试题录入"]:
        mode_radio.set_value(mode)
        app.run(timeout=30)
        batch_tex = next(item for item in app.text_area if item.label == "批量 TeX 内容")
        batch_tex.set_value(SAMPLE_TEX)
        app.run(timeout=30)
        checks[f"{mode}_render"] = not app.exception
        stem_count = len([item for item in app.text_area if item.label == "题干 TeX"])
        type_count = len([item for item in app.selectbox if item.label == "题型"])
        topic_count = len([item for item in app.multiselect if item.label == "知识板块"])
        note_count = len([item for item in app.text_input if item.label == "备注"])
        checks[f"{mode}_two_question_editors"] = stem_count == 2
        checks[f"{mode}_per_question_metadata"] = type_count == 2
        checks[f"{mode}_topic_dropdowns"] = topic_count == 2
        checks[f"{mode}_compact_note_fields"] = note_count == 2
        checks[f"{mode}_direct_import_button"] = "录入其余未处理题" in [item.label for item in app.button]
        checks[f"{mode}_single_import_actions"] = (
            "单独录入本题" in [item.label for item in app.button]
            and "确认不录入" in [item.label for item in app.button]
        )
        checks[f"{mode}_review_workspace_hidden"] = "草稿审核与确认入库" not in [item.value for item in app.subheader]
        if mode == "同书试题录入":
            checks["same_book_per_question_pages"] = len([item for item in app.text_input if item.label == "页码"]) == 2
        mode_radio = next(item for item in app.radio if item.label == "录入方式")
    checks["formal_database_unchanged"] = sha256(FORMAL_DB) == before
    for name, ok in checks.items():
        print(f"{name}={'ok' if ok else 'failed'}")
    print(f"status={'ok' if all(checks.values()) else 'failed'}")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
