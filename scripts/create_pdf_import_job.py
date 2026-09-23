"""Create a private PDF import job and reviewable question candidates."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.pdf_import_service import DEFAULT_JOBS_ROOT, SOURCE_TYPES, create_pdf_import_job


def parse_metadata(value: str) -> dict[str, object]:
    if not value.strip():
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"--metadata-json 不是有效 JSON：{exc.msg}") from exc
    if not isinstance(parsed, dict):
        raise argparse.ArgumentTypeError("--metadata-json 必须是 JSON 对象。")
    return parsed


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="从 PDF 创建本地私有导入任务和可审核题目切分草稿。")
    parser.add_argument("pdf", help="源 PDF 路径。")
    parser.add_argument("--source-type", choices=sorted(SOURCE_TYPES), default="pdf_misc", help="来源类型。")
    parser.add_argument("--metadata-json", type=parse_metadata, default={}, help="来源元数据 JSON 对象。")
    parser.add_argument("--job-id", default=None, help="可选任务 ID；默认自动生成。")
    parser.add_argument("--jobs-root", default=str(DEFAULT_JOBS_ROOT), help="任务根目录。")
    parser.add_argument("--render-dpi", type=int, default=144, help="页面 PNG 渲染 DPI，范围 72-300。")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = create_pdf_import_job(
        args.pdf,
        jobs_root=args.jobs_root,
        job_id=args.job_id,
        source_type=args.source_type,
        source_metadata=args.metadata_json,
        render_dpi=args.render_dpi,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
