"""Local, uncommitted UI preferences for the Streamlit app."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from services.database_service import BASE_DIR
from services.file_service import atomic_write_text


DEFAULT_PREFERENCES_PATH = Path(BASE_DIR) / "data" / "local_preferences.json"

QUESTION_SOURCE_SQLITE = "sqlite"
QUESTION_SOURCE_LEGACY = "legacy"
QUESTION_SOURCE_OPTIONS = (QUESTION_SOURCE_SQLITE, QUESTION_SOURCE_LEGACY)

BROWSE_SOURCE_LABELS = {
    QUESTION_SOURCE_SQLITE: "SQLite 数据库",
    QUESTION_SOURCE_LEGACY: "旧 TeX 题库",
}

EXAM_SOURCE_LABELS = {
    QUESTION_SOURCE_SQLITE: "SQLite 试用题库",
    QUESTION_SOURCE_LEGACY: "旧 TeX 题库",
}

DEFAULT_PREFERENCES: dict[str, Any] = {
    "browse_default_source": QUESTION_SOURCE_SQLITE,
    "exam_default_source": QUESTION_SOURCE_SQLITE,
}


def _resolve_path(path: str | Path | None = None) -> Path:
    target = Path(path) if path else DEFAULT_PREFERENCES_PATH
    if not target.is_absolute():
        target = Path(BASE_DIR) / target
    return target.resolve()


def _normalize_source(value: Any, fallback: str = QUESTION_SOURCE_SQLITE) -> str:
    text = str(value or "").strip().lower()
    aliases = {
        "sqlite": QUESTION_SOURCE_SQLITE,
        "sqlite 数据库": QUESTION_SOURCE_SQLITE,
        "sqlite 试用题库": QUESTION_SOURCE_SQLITE,
        "旧 tex 题库": QUESTION_SOURCE_LEGACY,
        "旧题库": QUESTION_SOURCE_LEGACY,
        "legacy": QUESTION_SOURCE_LEGACY,
        "tex": QUESTION_SOURCE_LEGACY,
    }
    normalized = aliases.get(text, text)
    return normalized if normalized in QUESTION_SOURCE_OPTIONS else fallback


def load_local_preferences(path: str | Path | None = None) -> dict[str, Any]:
    """Load local preferences, returning safe defaults for missing or broken files."""
    target = _resolve_path(path)
    data: dict[str, Any] = {}
    if target.exists():
        try:
            parsed = json.loads(target.read_text(encoding="utf-8"))
            if isinstance(parsed, dict):
                data = parsed
        except (OSError, json.JSONDecodeError):
            data = {}

    preferences = dict(DEFAULT_PREFERENCES)
    preferences.update(data)
    preferences["browse_default_source"] = _normalize_source(preferences.get("browse_default_source"))
    preferences["exam_default_source"] = _normalize_source(preferences.get("exam_default_source"))
    preferences["_path"] = str(target)
    preferences["_exists"] = target.exists()
    return preferences


def save_local_preferences(
    updates: dict[str, Any],
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Persist local preferences under data/, without touching repository defaults."""
    target = _resolve_path(path)
    current = load_local_preferences(target)
    current.pop("_path", None)
    current.pop("_exists", None)
    current.update(updates or {})
    current["browse_default_source"] = _normalize_source(current.get("browse_default_source"))
    current["exam_default_source"] = _normalize_source(current.get("exam_default_source"))
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_text(str(target), json.dumps(current, ensure_ascii=False, indent=2) + "\n")
    saved = load_local_preferences(target)
    saved["_saved"] = True
    return saved


def get_browse_default_source(path: str | Path | None = None) -> str:
    return str(load_local_preferences(path).get("browse_default_source") or QUESTION_SOURCE_SQLITE)


def get_exam_default_source(path: str | Path | None = None) -> str:
    return str(load_local_preferences(path).get("exam_default_source") or QUESTION_SOURCE_SQLITE)


def source_label(source: str, *, surface: str) -> str:
    labels = EXAM_SOURCE_LABELS if surface == "exam" else BROWSE_SOURCE_LABELS
    return labels.get(_normalize_source(source), labels[QUESTION_SOURCE_SQLITE])


def source_from_label(label: str) -> str:
    text = str(label or "").strip()
    for labels in (BROWSE_SOURCE_LABELS, EXAM_SOURCE_LABELS):
        for source, source_label_text in labels.items():
            if text == source_label_text:
                return source
    return _normalize_source(text)
