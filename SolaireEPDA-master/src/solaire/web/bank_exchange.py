"""Strict export / loose import for bank exchange ZIP archives (per-file YAML + image/)."""

from __future__ import annotations

import hashlib
import io
import json
import re
import shutil
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

from solaire.exam_compiler.facade import iter_question_files

from solaire.web.bank_service import (
    _ALLOWED_BANK_IMAGE_EXT,
    _MAX_BANK_IMAGE_BYTES,
    _rel_to_resource,
    import_merged_yaml,
    library_root_for_namespace,
)
from solaire.web.security import assert_within_project

EXCHANGE_KIND = "solaire-bank-exchange"
FORMAT_VERSION = 2
PROFILE_STRICT = "strict"

_EMBED_IMG_RE = re.compile(r":::EMBED_IMG:([^:]+):::")


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _collect_embed_rels_from_text(text: str) -> list[str]:
    if not text or ":::EMBED_IMG:" not in text:
        return []
    return list(dict.fromkeys(m.group(1).strip() for m in _EMBED_IMG_RE.finditer(text)))


def _collect_embed_rels_from_yaml_text(text: str) -> list[str]:
    return _collect_embed_rels_from_text(text)


def _rewrite_embeds_exact(text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        rel = m.group(1).strip()
        new_rel = mapping.get(rel)
        if new_rel is None:
            return m.group(0)
        return f":::EMBED_IMG:{new_rel}:::"

    return _EMBED_IMG_RE.sub(repl, text)


def _rewrite_embeds_when_mapped(text: str, mapping: dict[str, str]) -> str:
    def repl(m: re.Match[str]) -> str:
        rel = m.group(1).strip()
        if rel in mapping:
            return f":::EMBED_IMG:{mapping[rel]}:::"
        return m.group(0)

    return _EMBED_IMG_RE.sub(repl, text)


def _rewrite_yaml_text_for_export(text: str, mapping: dict[str, str]) -> str:
    return _rewrite_embeds_exact(text, mapping)


def _rewrite_yaml_text_for_import(text: str, mapping: dict[str, str]) -> str:
    return _rewrite_embeds_when_mapped(text, mapping)


def export_bank_exchange_zip(project_root: Path, namespace: str) -> tuple[bytes, str]:
    """
    ZIP: manifest.json + yaml/<relative-path>.yaml (per-file bank) + image/* (package-relative EMBED).

    Returns (zip_bytes, suggested_filename_stem).
    """
    resource_root = (project_root / "resource").resolve()
    lib = library_root_for_namespace(project_root, namespace)
    if not lib.is_dir():
        raise FileNotFoundError(f"Library not found: {namespace}")

    unique_rels: list[str] = []
    for ypath in iter_question_files(lib):
        assert_within_project(project_root, ypath)
        text = ypath.read_text(encoding="utf-8")
        unique_rels.extend(_collect_embed_rels_from_yaml_text(text))
    unique_rels = list(dict.fromkeys(unique_rels))

    rel_to_package: dict[str, str] = {}
    image_payload: dict[str, bytes] = {}

    for rel in unique_rels:
        if ".." in rel or rel.startswith(("/", "\\")):
            raise ValueError(f"非法的 EMBED 路径: {rel}")
        abs_path = (project_root / "resource" / rel).resolve()
        try:
            abs_path.relative_to(resource_root)
        except ValueError as e:
            raise ValueError(f"EMBED 路径不在 resource 下: {rel}") from e
        if not abs_path.is_file():
            raise FileNotFoundError(f"引用的图片不存在: {rel}")
        data = abs_path.read_bytes()
        if len(data) > _MAX_BANK_IMAGE_BYTES:
            raise ValueError(f"图片过大: {rel}")
        ext = abs_path.suffix.lower() or ".png"
        if ext not in _ALLOWED_BANK_IMAGE_EXT:
            raise ValueError(f"不支持的图片扩展名: {rel}")
        digest = hashlib.sha256(data).hexdigest()[:16]
        pkg_name = f"image/{digest}{ext}"
        rel_to_package[rel] = pkg_name
        image_payload[pkg_name] = data

    manifest: dict[str, Any] = {
        "format_version": FORMAT_VERSION,
        "kind": EXCHANGE_KIND,
        "profile": PROFILE_STRICT,
        "exported_at": _utc_now_iso(),
        "source_namespace": namespace,
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        for ypath in iter_question_files(lib):
            assert_within_project(project_root, ypath)
            rel = ypath.relative_to(lib).as_posix()
            text = _rewrite_yaml_text_for_export(ypath.read_text(encoding="utf-8"), rel_to_package)
            zf.writestr(f"yaml/{rel}", text)
        for path_in_zip, raw in sorted(image_payload.items()):
            zf.writestr(path_in_zip, raw)
        zf.writestr("audio/.keep", b"")

    stem = namespace.replace("/", "-") if namespace != "main" else "main-bank"
    return buf.getvalue(), stem


def _safe_extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest = dest.resolve()
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename
        if name.startswith("/") or ".." in Path(name).parts:
            raise ValueError(f"非法的 zip 路径: {name}")
        target = (dest / name).resolve()
        try:
            target.relative_to(dest)
        except ValueError as e:
            raise ValueError(f"zip 路径越界: {name}") from e
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, target.open("wb") as out:
            shutil.copyfileobj(src, out)


def _find_questions_yaml(root: Path) -> Path | None:
    direct = root / "questions.yaml"
    if direct.is_file():
        return direct
    candidates = sorted(root.rglob("questions.yaml"))
    files = [p for p in candidates if p.is_file()]
    if not files:
        return None
    if len(files) > 1:
        raise ValueError(f"ZIP 内存在多个 questions.yaml: {[str(p.relative_to(root)) for p in files]}")
    return files[0]


def _resolve_embed_file_in_extract(extract_root: Path, rel: str) -> Path | None:
    rel = rel.strip().replace("\\", "/")
    if not rel or ".." in rel or rel.startswith("/"):
        return None
    candidates: list[Path] = []
    p1 = (extract_root / rel).resolve()
    try:
        p1.relative_to(extract_root.resolve())
    except ValueError:
        return None
    candidates.append(p1)
    base = Path(rel).name
    candidates.append((extract_root / "image" / base).resolve())
    for img_dir in extract_root.rglob("image"):
        if img_dir.is_dir():
            candidates.append((img_dir / base).resolve())
    seen: set[Path] = set()
    for c in candidates:
        if c in seen:
            continue
        seen.add(c)
        try:
            c.relative_to(extract_root.resolve())
        except ValueError:
            continue
        if c.is_file():
            return c
    matches = [p for p in extract_root.rglob(base) if p.is_file() and p.name == base]
    if len(matches) == 1:
        return matches[0]
    return None


def import_bank_exchange_zip(
    project_root: Path,
    zip_bytes: bytes,
    target_subject: str,
    target_collection: str,
) -> dict[str, Any]:
    """
    Import: prefer ``yaml/`` tree from ZIP; else legacy ``questions.yaml`` via ``import_merged_yaml``.

    Returns keys: written, namespace, subject, collection, warnings (list[str]).
    """
    warnings: list[str] = []
    ts = target_subject.strip()
    tc = target_collection.strip()
    if not ts or not tc:
        raise ValueError("必须提供 target_subject 与 target_collection")
    ns = f"{ts}/{tc}"
    target_lib = library_root_for_namespace(project_root, ns)
    assert_within_project(project_root, target_lib)
    target_lib.mkdir(parents=True, exist_ok=True)
    image_dir = target_lib / "image"
    image_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            _safe_extract_zip(zf, tmp_path)

        yaml_pack = tmp_path / "yaml"
        if yaml_pack.is_dir():
            written = 0
            all_rels: list[str] = []
            for p in sorted(yaml_pack.rglob("*.yaml")):
                text = p.read_text(encoding="utf-8")
                all_rels.extend(_collect_embed_rels_from_yaml_text(text))
            unique_rels = list(dict.fromkeys(all_rels))
            pkg_to_resource: dict[str, str] = {}
            for rel in unique_rels:
                src = _resolve_embed_file_in_extract(tmp_path, rel)
                if src is None:
                    warnings.append(f"未找到图片文件，保留占位符: {rel}")
                    continue
                data = src.read_bytes()
                if len(data) > _MAX_BANK_IMAGE_BYTES:
                    warnings.append(f"跳过大文件: {rel}")
                    continue
                ext = src.suffix.lower() or ".png"
                if ext not in _ALLOWED_BANK_IMAGE_EXT:
                    warnings.append(f"跳过不支持的格式: {rel}")
                    continue
                digest = hashlib.sha256(data).hexdigest()[:16]
                dest = image_dir / f"{digest}{ext}"
                assert_within_project(project_root, dest)
                dest.write_bytes(data)
                resource_rel = _rel_to_resource(project_root, dest)
                pkg_to_resource[rel] = resource_rel

            for p in sorted(yaml_pack.rglob("*.yaml")):
                rel = p.relative_to(yaml_pack)
                dest = target_lib / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                text = _rewrite_yaml_text_for_import(p.read_text(encoding="utf-8"), pkg_to_resource)
                dest.write_text(text, encoding="utf-8")
                written += 1
            return {
                "written": written,
                "namespace": ns,
                "subject": ts,
                "collection": tc,
                "warnings": warnings,
            }

        qyaml = _find_questions_yaml(tmp_path)
        if qyaml is None:
            raise FileNotFoundError("ZIP 内未找到 yaml/ 目录或 questions.yaml")
        raw = yaml.safe_load(qyaml.read_text(encoding="utf-8"))
        if raw is None:
            raise ValueError("questions.yaml 为空")

        all_rels: list[str] = []
        if isinstance(raw, dict):
            for q in raw.get("questions") or []:
                if isinstance(q, dict):
                    for k in ("content", "answer", "analysis", "group_material"):
                        if q.get(k):
                            all_rels.extend(_collect_embed_rels_from_text(str(q[k])))
            for g in raw.get("groups") or []:
                if isinstance(g, dict) and g.get("material"):
                    all_rels.extend(_collect_embed_rels_from_text(str(g["material"])))
                for it in g.get("items") or []:
                    if isinstance(it, dict):
                        for k in ("content", "answer", "analysis"):
                            if it.get(k):
                                all_rels.extend(_collect_embed_rels_from_text(str(it[k])))
        unique_rels = list(dict.fromkeys(all_rels))

        pkg_to_resource: dict[str, str] = {}
        for rel in unique_rels:
            src = _resolve_embed_file_in_extract(tmp_path, rel)
            if src is None:
                warnings.append(f"未找到图片文件，保留占位符: {rel}")
                continue
            data = src.read_bytes()
            if len(data) > _MAX_BANK_IMAGE_BYTES:
                warnings.append(f"跳过大文件: {rel}")
                continue
            ext = src.suffix.lower() or ".png"
            if ext not in _ALLOWED_BANK_IMAGE_EXT:
                warnings.append(f"跳过不支持的格式: {rel}")
                continue
            digest = hashlib.sha256(data).hexdigest()[:16]
            dest = image_dir / f"{digest}{ext}"
            assert_within_project(project_root, dest)
            dest.write_bytes(data)
            resource_rel = _rel_to_resource(project_root, dest)
            pkg_to_resource[rel] = resource_rel

        def _rew_obj(o: dict[str, Any]) -> dict[str, Any]:
            out = dict(o)
            for k in ("content", "answer", "analysis", "group_material"):
                if k in out and isinstance(out[k], str):
                    out[k] = _rewrite_embeds_when_mapped(out[k], pkg_to_resource)
            if "options" in out and isinstance(out["options"], dict):
                out["options"] = {kk: _rewrite_embeds_when_mapped(vv, pkg_to_resource) for kk, vv in out["options"].items()}
            return out

        if isinstance(raw, dict):
            nq = [_rew_obj(dict(x)) for x in (raw.get("questions") or []) if isinstance(x, dict)]
            ng = []
            for g in raw.get("groups") or []:
                if not isinstance(g, dict):
                    continue
                gg = dict(g)
                if isinstance(gg.get("material"), str):
                    gg["material"] = _rewrite_embeds_when_mapped(gg["material"], pkg_to_resource)
                items = []
                for it in gg.get("items") or []:
                    if isinstance(it, dict):
                        items.append(_rew_obj(dict(it)))
                gg["items"] = items
                ng.append(gg)
            raw = {"questions": nq, "groups": ng}

        merged_yaml = yaml.safe_dump(raw, allow_unicode=True, sort_keys=False)

    r = import_merged_yaml(project_root, merged_yaml, ts, tc)
    return {**r, "warnings": warnings}
