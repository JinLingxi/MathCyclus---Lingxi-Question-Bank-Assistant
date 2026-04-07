from __future__ import annotations

import argparse
import sys
from pathlib import Path

from solaire.primebrush.api import parse_primebrush, render


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="primebrush", description="Compile PrimeBrush YAML to SVG.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("build", help="Render a PrimeBrush YAML file to SVG")
    b.add_argument("yaml_path", type=Path, help="Input .yaml path")
    b.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output .svg path (default: same directory as YAML, same stem)",
    )
    b.add_argument("--seed", type=int, default=None, help="RNG seed for reproducible output")

    args = parser.parse_args(argv)
    if args.cmd != "build":
        parser.error("unknown command")

    src: Path = args.yaml_path
    if not src.is_file():
        print(f"error: not a file: {src}", file=sys.stderr)
        return 2

    out: Path
    if args.output is not None:
        out = args.output
    else:
        out = src.with_suffix(".svg")

    doc = parse_primebrush(src)
    svg = render(doc, seed=args.seed)
    out.write_text(svg, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
