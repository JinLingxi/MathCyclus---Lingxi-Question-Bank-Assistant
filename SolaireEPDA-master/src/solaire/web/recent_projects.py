"""Recent project list persisted under the application data directory (Windows: %APPDATA%/SolEdu)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass
class RecentProjectEntry:
    name: str
    path: str
    last_opened: str  # ISO 8601

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> RecentProjectEntry | None:
        try:
            name = str(raw["name"]).strip()
            path = str(raw["path"]).strip()
            last_opened = str(raw["last_opened"]).strip()
        except (KeyError, TypeError):
            return None
        if not path:
            return None
        return cls(name=name or Path(path).name, path=path, last_opened=last_opened)


def app_data_dir() -> Path:
    if sys.platform == "win32":
        base = os.environ.get("APPDATA")
        if base:
            return Path(base) / "SolEdu"
        return Path.home() / "AppData" / "Roaming" / "SolEdu"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "SolEdu"
    base = os.environ.get("XDG_DATA_HOME")
    if base:
        return Path(base) / "SolEdu"
    return Path.home() / ".local" / "share" / "SolEdu"


def recent_projects_path() -> Path:
    return app_data_dir() / "recent_projects.json"


def _path_key(p: str) -> str:
    """Normalize path for comparison (matches dedupe in load_recent_projects)."""
    try:
        return Path(p).expanduser().resolve().as_posix().lower()
    except (OSError, ValueError):
        return Path(p).expanduser().as_posix().lower()


def load_recent_projects(*, limit: int = 12) -> list[RecentProjectEntry]:
    path = recent_projects_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    out: list[RecentProjectEntry] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        e = RecentProjectEntry.from_dict(item)
        if e is not None:
            out.append(e)
    # de-dupe by path, keep most recent
    seen: set[str] = set()
    unique: list[RecentProjectEntry] = []
    for e in sorted(out, key=lambda x: x.last_opened, reverse=True):
        key = _path_key(e.path)
        if key in seen:
            continue
        seen.add(key)
        unique.append(e)
    return unique[:limit]


def _write_recent(entries: list[RecentProjectEntry]) -> None:
    path = recent_projects_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(e) for e in entries]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def record_project_opened(root: Path) -> None:
    root = root.expanduser().resolve()
    if not root.is_dir():
        return
    name = root.name
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    new = RecentProjectEntry(name=name, path=str(root), last_opened=now)
    existing = load_recent_projects(limit=100)
    rest = [e for e in existing if _path_key(e.path) != _path_key(str(root))]
    merged = [new] + rest
    _write_recent(merged[:24])


def remove_recent_project(path: str) -> bool:
    """Remove one recent entry by path (normalized). Returns True if an entry was removed."""
    raw = path.strip()
    if not raw:
        return False
    target = _path_key(raw)
    existing = load_recent_projects(limit=100)
    rest = [e for e in existing if _path_key(e.path) != target]
    if len(rest) == len(existing):
        return False
    _write_recent(rest)
    return True
