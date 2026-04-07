"""Tests for cleaning stale LaTeX intermediates before latexmk."""

from pathlib import Path

from solaire.exam_compiler.pipeline.compile_tex import clean_latex_intermediates


def test_clean_latex_intermediates_removes_aux_keeps_tex(tmp_path: Path) -> None:
    work = tmp_path / "work"
    work.mkdir()
    (work / "student_paper.tex").write_text("\\documentclass{article}\\begin{document}x\\end{document}\n", encoding="utf-8")
    (work / "student_paper.aux").write_text("\\pgfsyspdfmark{pgfid1}{0}{0}\n", encoding="utf-8")
    (work / "student_paper.fdb_latexmk").write_text("dummy\n", encoding="utf-8")
    sub = work / "figures"
    sub.mkdir()
    (sub / "keep.aux").write_text("nested\n", encoding="utf-8")

    clean_latex_intermediates(work)

    assert (work / "student_paper.tex").is_file()
    assert not (work / "student_paper.aux").exists()
    assert not (work / "student_paper.fdb_latexmk").exists()
    assert (sub / "keep.aux").is_file()
