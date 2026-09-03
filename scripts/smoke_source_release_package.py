from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from scripts.build_source_release_package import build_manifest, is_denied, tracked_cleanup_candidates


def check(name: str, ok: bool, detail: Any = "") -> dict[str, Any]:
    return {"name": name, "ok": ok, "detail": detail}


def main() -> None:
    manifest = build_manifest()
    included = set(manifest["included_files"])
    cleanup_candidates = tracked_cleanup_candidates()
    denied_included = [path for path in included if is_denied(path)]
    checks = [
        check("manifest_not_blocked", not manifest["blocked_included"], manifest["blocked_included"]),
        check("required_present", not manifest["missing_required"], manifest["missing_required"]),
        check("denied_files_excluded", not denied_included, denied_included[:20]),
        check("main_app_included", "question_bank_app.py" in included, sorted(included)[:20]),
        check("schema_included", "db/schema.sql" in included, "db/schema.sql"),
        check("services_included", any(path.startswith("services/") for path in included), "services/"),
        check("scripts_included", any(path.startswith("scripts/") for path in included), "scripts/"),
        check("docs_included", any(path.startswith("docs/") for path in included), "docs/"),
        check("templates_included", any(path.startswith("templates/") for path in included), "templates/"),
        check("env_example_allowed", "env.example" in included and not is_denied("env.example"), "env.example"),
        check("env_denied", is_denied(".env"), ".env"),
        check("formal_db_denied", is_denied("data/mathcyclus.sqlite3"), "data/mathcyclus.sqlite3"),
        check("seed_csv_denied", is_denied("db/seed/private_review.csv"), "db/seed/"),
        check("seed_gitkeep_allowed", "db/seed/.gitkeep" in included and not is_denied("db/seed/.gitkeep"), "db/seed/.gitkeep"),
        check("question_assets_denied", is_denied("assets/questions/Q000001/figure.png"), "assets/questions/"),
        check("reports_denied", is_denied("reports/generated.json"), "reports/"),
        check("exports_denied", is_denied("exports/generated.tex"), "exports/"),
        check("local_stats_db_excluded", "utils/local_stats.sqlite3" not in included, "utils/local_stats.sqlite3"),
        check("python_cache_excluded", not any("__pycache__/" in path for path in included), "__pycache__/"),
        check("legacy_chapters_denied", is_denied("chapters/函数/content_函数.tex"), "chapters/"),
        check("exported_papers_denied", is_denied("Test Paper Group/导出文件/example.tex"), "Test Paper Group/导出文件/"),
        check("cleanup_candidates_reported", isinstance(cleanup_candidates, list), cleanup_candidates[:12]),
    ]
    failed = [item for item in checks if not item["ok"]]
    report = {
        "status": "failed" if failed else "ok",
        "checks": checks,
        "included_count": len(included),
        "excluded_count": len(manifest["excluded_candidates"]),
        "tracked_cleanup_count": len(cleanup_candidates),
        "writes_database": False,
        "creates_package": False,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
