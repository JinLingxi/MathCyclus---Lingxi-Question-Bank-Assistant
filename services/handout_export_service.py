"""Optional standalone handout/training export, leaving existing exports unchanged."""

from __future__ import annotations

import shutil
from pathlib import Path

from services.export_service import question_to_legacy_tex, copy_graphics_for_export, copy_questionassets_for_export
from services.question_db_service import get_question
from services.database_service import resolve_database_path

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "templates" / "handouts"


def _title_tex(value: str) -> str:
    replacements = {"\\": r"\textbackslash{}", "{": r"\{", "}": r"\}", "$": r"\$",
                    "&": r"\&", "#": r"\#", "%": r"\%", "_": r"\_",
                    "^": r"\textasciicircum{}", "~": r"\textasciitilde{}"}
    return "".join(replacements.get(char, char) for char in value.replace("\n", " "))


def export_handout(output_dir: str | Path, *, db_path: str | None = None,
                   question_ids: list[str] | None = None, sample: bool = False,
                   training: bool = False, monochrome: bool = False,
                   title: str = "数学学习讲义") -> dict:
    """Create a new output folder; fail rather than publish missing question figures."""
    output = Path(output_dir).resolve()
    if output.exists():
        raise FileExistsError(output)
    ids = list(question_ids or [])
    if sample == bool(ids):
        raise ValueError("选择样张或明确指定正式题目 ID，不能同时使用")
    if len(ids) != len(set(ids)):
        raise ValueError("导出题目 ID 不能重复")
    questions = []
    for question_id in ids:
        question = get_question(db_path, question_id)
        if not question:
            raise ValueError("题目不存在：" + question_id)
        questions.append(question)
    import tempfile
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".handout-", dir=output.parent) as workspace:
        staged = Path(workspace) / "document"
        staged.mkdir()
        shutil.copy2(TEMPLATE / "mathcyclus-handout.sty", staged)
        if sample:
            body = (TEMPLATE / "sample-body.tex").read_text(encoding="utf-8")
        else:
            parts = []
            for question in questions:
                tex = question_to_legacy_tex(question)
                tex, graphics = copy_graphics_for_export(question, tex, staged, ROOT)
                tex, assets = copy_questionassets_for_export(
                    question, tex, staged, ROOT, db_path=resolve_database_path(db_path))
                if any(item["status"] == "missing" for item in [*graphics, *assets]):
                    raise ValueError("题目存在未解析图片，取消导出：" + str(question["question_id"]))
                parts.append(tex)
            body = "\n".join(parts)
        (staged / "body.tex").write_text(body, encoding="utf-8")
        options = ",".join(option for option, enabled in
                           (("training", training), ("monochrome", monochrome)) if enabled)
        main = (r"\documentclass[UTF8,a4paper,12pt]{ctexart}" + "\n"
                + r"\usepackage[" + options + r"]{mathcyclus-handout}" + "\n"
                + r"\begin{document}" + "\n"
                + r"\begin{center}\LARGE\bfseries " + _title_tex(title) + r"\end{center}" + "\n"
                + r"\input{body.tex}" + "\n" + r"\end{document}" + "\n")
        (staged / "main.tex").write_text(main, encoding="utf-8")
        # rename is same-volume; never merge into an existing user directory.
        staged.rename(output)
    return {"output": str(output), "question_count": len(ids), "sample": sample,
            "training": training, "monochrome": monochrome, "backend": "tcolorbox",
            "database_modified": False, "lucide_validated": False}
