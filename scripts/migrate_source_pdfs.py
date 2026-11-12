"""Dry-run-first PDF source deduplication with archive and rollback journal."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.source_pdf_migration_service import (
    plan_source_pdf_migration, apply_source_pdf_migration, rollback_source_pdf_migration,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--journal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = args.output or ROOT / "reports" / f"source_pdf_migration_{stamp}.json"
    journal = args.journal or ROOT / "reports" / f"source_pdf_migration_journal_{stamp}.json"
    backup = ROOT / "data" / "backups" / "source_pdf_migration" / f"sources_{stamp}.zip"
    if output.exists():
        raise FileExistsError(output)
    if args.rollback:
        if not args.apply:
            parser.error("回退操作需同时指定 --apply")
        result = rollback_source_pdf_migration(args.rollback)
    else:
        plan = plan_source_pdf_migration(ROOT)
        if args.apply and plan["groups"]:
            result = apply_source_pdf_migration(plan, journal, backup)
        else:
            result = plan
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8") as target:
        json.dump(result, target, ensure_ascii=False, indent=2)
    summary = {"state": result.get("state", "dry_run"),
               "groups": len(result.get("groups", [])),
               "files": sum(len(group["files"]) for group in result.get("groups", [])),
               "operations": len(result.get("operations", [])),
               "deleted_task_paths": 0, "report": str(output)}
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
