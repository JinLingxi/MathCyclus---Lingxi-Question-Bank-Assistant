from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.local_preferences_service import (
    QUESTION_SOURCE_LEGACY,
    QUESTION_SOURCE_SQLITE,
    get_browse_default_source,
    get_exam_default_source,
    load_local_preferences,
    save_local_preferences,
    source_label,
)


def assert_equal(name: str, actual, expected) -> None:
    if actual != expected:
        raise AssertionError(f"{name}: expected {expected!r}, got {actual!r}")


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="mathcyclus_preferences_smoke_") as temp_dir:
        prefs_path = Path(temp_dir) / "local_preferences.json"

        defaults = load_local_preferences(prefs_path)
        assert_equal("default_browse", defaults["browse_default_source"], QUESTION_SOURCE_SQLITE)
        assert_equal("default_exam", defaults["exam_default_source"], QUESTION_SOURCE_SQLITE)
        assert_equal("default_exists", defaults["_exists"], False)

        saved = save_local_preferences(
            {
                "browse_default_source": QUESTION_SOURCE_LEGACY,
                "exam_default_source": "SQLite 试用题库",
            },
            prefs_path,
        )
        assert_equal("saved_browse", saved["browse_default_source"], QUESTION_SOURCE_LEGACY)
        assert_equal("saved_exam", saved["exam_default_source"], QUESTION_SOURCE_SQLITE)
        assert_equal("saved_exists", saved["_exists"], True)
        assert_equal("read_browse", get_browse_default_source(prefs_path), QUESTION_SOURCE_LEGACY)
        assert_equal("read_exam", get_exam_default_source(prefs_path), QUESTION_SOURCE_SQLITE)
        assert_equal("exam_label", source_label(QUESTION_SOURCE_SQLITE, surface="exam"), "SQLite 试用题库")

        prefs_path.write_text("{broken json", encoding="utf-8")
        recovered = load_local_preferences(prefs_path)
        assert_equal("broken_config_fallback", recovered["browse_default_source"], QUESTION_SOURCE_SQLITE)

    print(json.dumps({"status": "ok", "writes_formal_database": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
