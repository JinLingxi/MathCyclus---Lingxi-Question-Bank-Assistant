"""CLI entry: solaire-exam build <exam.yaml> [--out DIR]（ExamCompiler）。"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from solaire.exam_compiler import __version__
from pydantic import ValidationError

from solaire.exam_compiler.pipeline.build import build_exam_pdfs
from solaire.exam_compiler.pipeline.compile_tex import LatexmkError


def _cmd_build(args: argparse.Namespace) -> int:
    exam = Path(args.exam_yaml)
    out = Path(args.out) if args.out else None
    try:
        sp, tp = build_exam_pdfs(exam, out, clean_workdir=args.clean)
    except LatexmkError as e:
        print(f"LaTeX build failed:\n{e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"Configuration validation failed:\n{e}", file=sys.stderr)
        return 1
    except Exception as e:
        if args.verbose:
            raise
        print(f"Error: {e}", file=sys.stderr)
        return 1
    if args.verbose:
        print(f"Student PDF: {sp}")
        print(f"Teacher PDF: {tp}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="solaire-exam",
        description="Solaire Education — ExamCompiler：从 exam.yaml 生成 PDF",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_build = sub.add_parser("build", help="从 exam.yaml 生成学生版与教师版 PDF")
    p_build.add_argument("exam_yaml", help="试卷配置 exam.yaml 路径")
    p_build.add_argument(
        "--out",
        "-o",
        help="PDF 输出目录（默认与 exam.yaml 同目录）",
    )
    p_build.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="打印输出路径",
    )
    p_build.add_argument(
        "--clean",
        action="store_true",
        help="构建前清空与 yaml 同名的临时工作目录",
    )
    p_build.set_defaults(func=_cmd_build)

    ns = parser.parse_args(argv)
    if ns.command == "build":
        return ns.func(ns)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
