"""Two-tier indexed memory: INDEX.md + topics/*.md under .solaire/agent/memory/."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from solaire.common.security import assert_within_project

DEFAULT_INDEX = """## 记忆索引
- 暂无条目。助手会在对话结束后根据你的教学目标与分析结论更新此处。
"""

SAFE_TOPIC_RE = re.compile(r"^[a-zA-Z0-9_.-]+\.md$")


def memory_dir(project_root: Path) -> Path:
    d = project_root / ".solaire" / "agent" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / "topics").mkdir(parents=True, exist_ok=True)
    return d


def index_path(project_root: Path) -> Path:
    return memory_dir(project_root) / "INDEX.md"


def ensure_memory_layout(project_root: Path) -> None:
    mp = memory_dir(project_root)
    idx = mp / "INDEX.md"
    if not idx.is_file():
        idx.write_text(DEFAULT_INDEX.strip() + "\n", encoding="utf-8")


def read_index(project_root: Path) -> str:
    ensure_memory_layout(project_root)
    return index_path(project_root).read_text(encoding="utf-8")


def write_index(project_root: Path, content: str) -> None:
    ensure_memory_layout(project_root)
    p = index_path(project_root)
    assert_within_project(project_root, p)
    p.write_text(content, encoding="utf-8")


def _topic_path(project_root: Path, topic: str) -> Path:
    if not SAFE_TOPIC_RE.match(topic):
        raise ValueError("invalid topic filename")
    p = memory_dir(project_root) / "topics" / topic
    assert_within_project(project_root, p)
    return p


def read_topic(project_root: Path, topic: str) -> str:
    p = _topic_path(project_root, topic)
    if not p.is_file():
        return ""
    return p.read_text(encoding="utf-8")


def write_topic(project_root: Path, topic: str, content: str) -> None:
    p = _topic_path(project_root, topic)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def list_topic_filenames(project_root: Path) -> list[str]:
    """Sorted topic basenames under topics/."""
    ensure_memory_layout(project_root)
    root = memory_dir(project_root) / "topics"
    if not root.is_dir():
        return []
    return sorted(p.name for p in root.glob("*.md"))


def _token_set(text: str) -> set[str]:
    return set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower()))


def _overlap_ratio(a: str, b: str) -> float:
    ta, tb = _token_set(a), _token_set(b)
    if not ta or not tb:
        return 0.0
    inter = len(ta & tb)
    union = len(ta | tb)
    return inter / union if union else 0.0


def merge_index_bullet(
    project_root: Path,
    new_bullet_text: str,
    *,
    overlap_threshold: float = 0.6,
) -> bool:
    """Self-healing: merge or replace index line when token overlap exceeds threshold; else append.

    Returns True if INDEX.md was modified.
    """
    ensure_memory_layout(project_root)
    new_bullet_text = new_bullet_text.strip()
    if not new_bullet_text:
        return False
    idx = read_index(project_root)
    lines = idx.splitlines()
    header: list[str] = []
    bullets: list[str] = []
    rest: list[str] = []
    phase = "header"
    for line in lines:
        stripped = line.strip()
        if phase == "header":
            if stripped.startswith("- "):
                phase = "bullets"
                bullets.append(line)
            else:
                header.append(line)
        elif phase == "bullets":
            if stripped.startswith("- "):
                bullets.append(line)
            else:
                phase = "rest"
                rest.append(line)
        else:
            rest.append(line)

    replaced = False
    new_bullets: list[str] = []
    for b in bullets:
        body = b.lstrip()[2:].strip() if b.lstrip().startswith("-") else b
        if _overlap_ratio(body, new_bullet_text) >= overlap_threshold:
            new_bullets.append(f"- {new_bullet_text}")
            replaced = True
        else:
            new_bullets.append(b)
    if not replaced:
        if len(bullets) == 1 and "暂无条目" in bullets[0]:
            new_bullets = [f"- {new_bullet_text}"]
        elif not bullets:
            new_bullets = [f"- {new_bullet_text}"]
        else:
            new_bullets = list(bullets)
            new_bullets.append(f"- {new_bullet_text}")

    out_lines = []
    if header:
        out_lines.extend(header)
    else:
        out_lines.append("## 记忆索引")
    out_lines.extend(new_bullets)
    if rest:
        if out_lines and out_lines[-1].strip():
            out_lines.append("")
        out_lines.extend(rest)
    new_idx = "\n".join(out_lines).strip() + "\n"
    if new_idx == idx:
        return False
    write_index(project_root, new_idx)
    return True


def append_session_digest_line(project_root: Path, line: str) -> None:
    """L3: append one structured line to session_digest topic (topic file)."""
    line = line.strip()
    if not line:
        return
    prev = read_topic(project_root, "session_digest.md")
    from datetime import datetime, timezone

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    block = (prev.strip() + "\n\n" if prev.strip() else "") + f"- {ts} UTC — {line}\n"
    write_topic(project_root, "session_digest.md", block)


def search_topics(project_root: Path, query: str, *, max_hits: int = 20) -> list[dict[str, Any]]:
    """Simple case-insensitive substring search across topic files."""
    ensure_memory_layout(project_root)
    q = query.lower().strip()
    hits: list[dict[str, Any]] = []
    topics_root = memory_dir(project_root) / "topics"
    if not topics_root.is_dir():
        return hits
    for p in sorted(topics_root.glob("*.md")):
        text = p.read_text(encoding="utf-8", errors="replace")
        if not q or q in text.lower():
            snippet = text[:400].replace("\n", " ")
            if len(text) > 400:
                snippet += "…"
            hits.append({"topic": p.name, "snippet": snippet})
            if len(hits) >= max_hits:
                break
    return hits
