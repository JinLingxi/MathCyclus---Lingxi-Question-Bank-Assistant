"""Dry-run by default; relocate draft images with a SQLite backup and rollback manifest."""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.draft_asset_migration_service import (
    build_draft_asset_relocation_plan, apply_draft_asset_relocation, rollback_draft_asset_relocation,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data" / "mathcyclus.sqlite3"))
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--rollback", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    output = args.output or ROOT / "reports" / f"draft_asset_storage_{stamp}.json"
    if output.exists():
        raise FileExistsError(output)
    backup = ROOT / "data" / "backups" / "draft_asset_storage" / f"before_{stamp}.sqlite3"
    if args.rollback:
        if not args.apply:
            parser.error("回退需同时指定 --apply")
        manifest = json.loads(args.rollback.read_text(encoding="utf-8"))
        result = rollback_draft_asset_relocation(manifest, backup_path=backup)
    else:
        plan = build_draft_asset_relocation_plan(args.db)
        output.parent.mkdir(parents=True, exist_ok=True)
        # Persist preflight before any database writes.
        output.with_suffix(".dryrun.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
        result = apply_draft_asset_relocation(plan, backup_path=backup) if args.apply and plan["assets"] else plan
    with output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"applied": result.get("applied", False),
                      "rolled_back": result.get("rolled_back", False),
                      "assets": len(result.get("assets", [])), "skipped": len(result.get("skipped", [])),
                      "deleted_files": 0, "report": str(output)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
