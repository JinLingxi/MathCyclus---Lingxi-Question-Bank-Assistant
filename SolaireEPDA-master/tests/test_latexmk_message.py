"""latexmk 失败信息格式化（Web/API 可读摘要）。"""

from solaire.exam_compiler.pipeline.compile_tex import LatexmkError, format_latexmk_failure_message


def test_format_truncates_long_log() -> None:
    body = "x" * 20_000
    exc = LatexmkError(body)
    out = format_latexmk_failure_message(exc, max_chars=500)
    assert "PDF 编译失败" in out
    assert "省略" in out
    assert len(out) < len(body)


def test_format_short_unchanged() -> None:
    exc = LatexmkError("! LaTeX Error: foo")
    out = format_latexmk_failure_message(exc, max_chars=10_000)
    assert "! LaTeX Error" in out
