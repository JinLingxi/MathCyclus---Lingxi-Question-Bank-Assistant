"""Skill system: scan SKILL.md files (YAML frontmatter + Markdown body), progressive disclosure."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SkillDescriptor:
    """Tier 1: lightweight catalog entry loaded at startup."""

    name: str
    label: str
    description: str
    tool_patterns: tuple[str, ...]
    suggested_user_input: str
    skill_dir: Path
    prompt_fragment: str = ""


def _parse_yaml_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Split SKILL.md into (yaml_dict, markdown_body)."""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    if not m:
        return {}, text
    yaml_block = m.group(1)
    body = text[m.end():]
    try:
        import yaml
        data = yaml.safe_load(yaml_block) or {}
    except Exception:
        data = _simple_yaml_parse(yaml_block)
    return data, body.strip()


def _simple_yaml_parse(block: str) -> dict[str, Any]:
    """Fallback parser when PyYAML is unavailable."""
    result: dict[str, Any] = {}
    for line in block.split("\n"):
        line = line.strip()
        if ":" in line and not line.startswith("#"):
            k, v = line.split(":", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if v:
                result[k] = v
    return result


def _scan_skill_dir(directory: Path) -> list[SkillDescriptor]:
    """Scan a directory for */SKILL.md files and return descriptors."""
    skills: list[SkillDescriptor] = []
    if not directory.is_dir():
        return skills
    for child in sorted(directory.iterdir()):
        skill_file = child / "SKILL.md"
        if not skill_file.is_file():
            continue
        try:
            text = skill_file.read_text(encoding="utf-8")
        except Exception:
            continue
        meta, body = _parse_yaml_frontmatter(text)
        if not meta.get("name"):
            continue
        md = meta.get("metadata") or {}
        if isinstance(md, str):
            md = {}
        tp_raw = md.get("tool_patterns", "")
        if isinstance(tp_raw, str):
            tool_patterns = tuple(tp_raw.split())
        elif isinstance(tp_raw, (list, tuple)):
            tool_patterns = tuple(str(x) for x in tp_raw)
        else:
            tool_patterns = ()
        desc_raw = meta.get("description", "")
        if isinstance(desc_raw, str):
            description = desc_raw.strip()
        else:
            description = str(desc_raw).strip()

        skills.append(SkillDescriptor(
            name=str(meta["name"]).strip(),
            label=str(md.get("label", meta.get("name", ""))).strip(),
            description=description,
            tool_patterns=tool_patterns,
            suggested_user_input=str(md.get("suggested_user_input", "")).strip(),
            skill_dir=child,
            prompt_fragment=body[:5000] if body else "",
        ))
    return skills


def _builtin_skills_dir() -> Path:
    return Path(__file__).parent / "skills"


def _project_skills_dir(project_root: Path) -> Path:
    return project_root / ".solaire" / "agent" / "skills"


_cached_skills: dict[str, SkillDescriptor] = {}
_cache_stamp: float = 0


def _ensure_cache(project_root: Path | None = None) -> dict[str, SkillDescriptor]:
    global _cached_skills, _cache_stamp
    import time
    now = time.time()
    if _cached_skills and (now - _cache_stamp) < 10:
        return _cached_skills

    builtin = _scan_skill_dir(_builtin_skills_dir())
    result = {s.name: s for s in builtin}

    if project_root is not None:
        project = _scan_skill_dir(_project_skills_dir(project_root))
        for s in project:
            result[s.name] = s

    _cached_skills = result
    _cache_stamp = now
    return result


def get_skill(skill_id: str | None, project_root: Path | None = None) -> SkillDescriptor | None:
    if not skill_id:
        return None
    cache = _ensure_cache(project_root)
    return cache.get(skill_id.strip())


def list_skills_public(project_root: Path | None = None) -> list[dict[str, str]]:
    cache = _ensure_cache(project_root)
    return [
        {
            "id": s.name,
            "label": s.label,
            "description": s.description,
            "suggested_user_input": s.suggested_user_input,
        }
        for s in cache.values()
    ]


def build_skill_catalog(project_root: Path | None = None) -> str:
    """Tier 1 catalog: name + description for all discovered skills."""
    cache = _ensure_cache(project_root)
    if not cache:
        return ""
    lines: list[str] = []
    for s in cache.values():
        lines.append(f"- **{s.label or s.name}**（`{s.name}`）：{s.description}")
    return "\n".join(lines)


def load_skill_content(name: str, project_root: Path | None = None) -> str | None:
    """Tier 2: load full SKILL.md body for activated skill."""
    sk = get_skill(name, project_root)
    if sk is None:
        return None
    skill_file = sk.skill_dir / "SKILL.md"
    if not skill_file.is_file():
        return None
    try:
        text = skill_file.read_text(encoding="utf-8")
    except Exception:
        return None
    _, body = _parse_yaml_frontmatter(text)
    return body or sk.prompt_fragment
