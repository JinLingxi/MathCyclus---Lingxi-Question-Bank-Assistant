"""Export a new optional handout/training folder; existing UI/export defaults are unchanged."""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.handout_export_service import export_handout


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--db")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--sample", action="store_true")
    selection.add_argument("--question-id", action="append")
    parser.add_argument("--training", action="store_true")
    parser.add_argument("--monochrome", action="store_true")
    parser.add_argument("--title", default="数学学习讲义")
    args = parser.parse_args()
    result = export_handout(args.output, db_path=args.db, question_ids=args.question_id,
                            sample=args.sample, training=args.training,
                            monochrome=args.monochrome, title=args.title)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
