"""Read-only audit of question assets, draft resources and ingestion job files."""

from __future__ import annotations

import argparse
import json
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from scripts.local_data_bundle import file_sha256

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".tif", ".tiff"}


class ReadabilityChecks:
    """Memoize decoding per file without changing Pillow limits or source bytes."""
    def __init__(self):
        self.results = {}

    def check(self, path: Path) -> dict:
        key = str(path.resolve())
        if key in self.results:
            return self.results[key]
        result = {"status": "not_checked"}
        try:
            if path.suffix.lower() in IMAGE_SUFFIXES:
                from PIL import Image
                with Image.open(path) as image:
                    image.verify()
                with Image.open(path) as image:
                    image.load()
                    result = {"status": "ok", "kind": "image", "width": image.width, "height": image.height}
            elif path.suffix.lower() == ".pdf":
                import fitz
                with fitz.open(path) as document:
                    result = {"status": "ok" if not document.needs_pass and document.page_count > 0 else "review_required",
                              "kind": "pdf", "page_count": document.page_count}
        except Exception as exc:
            # Decode errors are evidence to inspect, never authorization to replace.
            result = {"status": "review_required", "error_type": type(exc).__name__}
        self.results[key] = result
        return result


def audit_review_materials(root: Path, database: Path) -> tuple[list[dict], dict]:
    from services.asset_service import resolve_asset_record_path
    checks = ReadabilityChecks()
    issues, counts = [], Counter()
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        for table in ("question_asset", "question_import_draft_asset"):
            owner_field = "question_id" if table == "question_asset" else "draft_id"
            for row in conn.execute(f'SELECT * FROM "{table}"'):
                asset = dict(row)
                path = resolve_asset_record_path(asset, project_root=root)
                if path:
                    result = checks.check(path)
                    counts["registered_assets_checked"] += 1
                    if result["status"] == "review_required":
                        issues.append(issue("registered_asset_decode_review", asset[owner_field], "image",
                                            safe_label(root, path), result))
        for row in conn.execute("SELECT draft_id,extra_json FROM question_import_draft"):
            extra = _json_object(row["extra_json"])
            job_id = str(extra.get("document_job_id") or "")
            job_dir = root / "data/imports/pdf_jobs" / job_id if job_id else None
            source_pdf = None
            for field, value in _path_fields(extra):
                raw = Path(value)
                # Stored page paths are relative to the explicitly recorded job.
                options = [raw] if raw.is_absolute() else (
                    [job_dir / raw, root / raw] if job_dir else [root / raw])
                path = next((p for p in options if p.is_file()), None)
                counts["draft_review_references"] += 1
                if path is None:
                    issues.append(issue("draft_review_material_missing", row["draft_id"], field,
                                        safe_label(root, options[0])))
                    continue
                result = checks.check(path)
                if result["status"] == "review_required":
                    issues.append(issue("draft_review_material_decode_review", row["draft_id"], field,
                                        safe_label(root, path), result))
                if field == "source_path" and path.suffix.lower() == ".pdf":
                    source_pdf = result
            if source_pdf and source_pdf.get("status") == "ok":
                for number in extra.get("source_pages") or []:
                    counts["draft_source_page_numbers"] += 1
                    if type(number) is not int or not 1 <= number <= source_pdf["page_count"]:
                        issues.append(issue("draft_source_page_out_of_range", row["draft_id"], "source_pages",
                                            str(number)))
    finally:
        conn.close()
    # Check job pages directly, including pages that have no question candidates.
    for manifest_path in (root / "data/imports").rglob("job_manifest.json"):
        payload_path = manifest_path.parent / "draft_payload.json"
        if not payload_path.is_file():
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue  # Existing base audit reports invalid payloads.
        for page in payload.get("pages") or []:
            ref = str(page.get("image_path") or "")
            if not ref:
                continue
            path = project_path(manifest_path.parent, ref)
            counts["job_page_images"] += 1
            if not path.is_file():
                issues.append(issue("job_page_image_missing", safe_label(root, manifest_path.parent),
                                    "pages.image_path", safe_label(root, path)))
            else:
                result = checks.check(path)
                if result["status"] == "review_required":
                    issues.append(issue("job_page_image_decode_review", safe_label(root, manifest_path.parent),
                                        "pages.image_path", safe_label(root, path), result))
    counts["unique_files_probed"] = len(checks.results)
    counts["images_decoded"] = sum(r.get("kind") == "image" and r["status"] == "ok" for r in checks.results.values())
    counts["pdfs_opened"] = sum(r.get("kind") == "pdf" and r["status"] == "ok" for r in checks.results.values())
    return issues, dict(counts)


def project_path(root: Path, value: Any) -> Path | None:
    text = str(value or "").strip()
    if not text:
        return None
    path = Path(text)
    return path if path.is_absolute() else root / path


def safe_label(root: Path, path: Path | None) -> str:
    if path is None:
        return "(empty)"
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except (OSError, ValueError):
        return "(external path)"


def issue(category, owner, field, value="", detail=""):
    return {"category": category, "owner": owner, "field": field,
            "value": value, "detail": detail}


def _json_object(value):
    if isinstance(value, dict):
        return value
    try:
        result = json.loads(str(value or "{}"))
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


def audit_database(root: Path, database: Path) -> tuple[list[dict], dict]:
    from services.asset_service import collect_asset_reference_issues

    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    issues = []
    counts = {}
    try:
        for table in ("question", "question_import_draft", "question_import_draft_asset"):
            counts[table] = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        formal_assets = {}
        for row in conn.execute("SELECT * FROM question_asset ORDER BY question_id,sort_order,asset_id"):
            asset = dict(row)
            formal_assets.setdefault(asset["question_id"], []).append(asset)
            path = project_path(root, asset.get("file_path"))
            if not path or not path.is_file():
                issues.append(issue("formal_asset_missing", asset["question_id"], "file_path",
                                    safe_label(root, path), asset.get("role", "")))
                continue
        for question in conn.execute("SELECT * FROM question ORDER BY question_id"):
            record = dict(question)
            legacy = conn.execute("SELECT legacy_file_path FROM legacy_question_map WHERE question_id=?",
                                  (record["question_id"],)).fetchone()
            source_file = legacy["legacy_file_path"] if legacy else record.get("legacy_file_path") or ""
            result = collect_asset_reference_issues(record, formal_assets.get(record["question_id"], []),
                                                    project_root=root, source_file=source_file)
            for category in ("missing_includegraphics", "unresolved_questionasset", "missing_asset_files"):
                for item in result.get(category, []):
                    issues.append(issue("formal_" + category, record["question_id"], category,
                                        str(item.get("ref") or item.get("alias") or item.get("path") or "")))
            for item in result.get("integrity_issues", []):
                issues.append(issue("formal_integrity", record["question_id"], "integrity",
                                    safe_label(root, Path(item["path"]) if item.get("path") else None),
                                    str(item.get("reason") or "")))

        draft_assets = {}
        for row in conn.execute("SELECT * FROM question_import_draft_asset ORDER BY draft_id,sort_order,draft_asset_id"):
            asset = dict(row)
            asset["extra"] = _json_object(asset.get("extra_json"))
            draft_assets.setdefault(asset["draft_id"], []).append(asset)
        for draft in conn.execute("SELECT * FROM question_import_draft ORDER BY draft_id"):
            record = dict(draft)
            record["choices"] = record.pop("choices_json", "[]")
            draft_status = str(record.get("review_status") or "")
            result = collect_asset_reference_issues(record, draft_assets.get(record["draft_id"], []),
                                                    project_root=root)
            for category in ("missing_includegraphics", "unresolved_questionasset", "missing_asset_files"):
                for item in result.get(category, []):
                    label = ("draft_sample_fixture_missing" if draft_status == "sample"
                             and category == "missing_asset_files" else "draft_" + category)
                    issues.append(issue(label, record["draft_id"], category,
                                        str(item.get("ref") or item.get("alias") or item.get("path") or "")))
            for item in result.get("integrity_issues", []):
                issues.append(issue("draft_integrity", record["draft_id"], "integrity",
                                    safe_label(root, Path(item["path"]) if item.get("path") else None),
                                    str(item.get("reason") or "")))
    finally:
        conn.close()
    return issues, counts


def _path_fields(value, *, prefix=""):
    """Yield path-like string values without interpreting arbitrary TeX."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"source_page_images", "question_crop_paths"} and isinstance(child, list):
                for index, item in enumerate(child):
                    if isinstance(item, str):
                        yield f"{prefix}{key}[{index}]", item
            elif key in {"source_path", "planned_file_path", "file_path"} and isinstance(child, str):
                yield f"{prefix}{key}", child
            elif isinstance(child, (dict, list)):
                yield from _path_fields(child, prefix=f"{prefix}{key}.")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            if isinstance(child, (dict, list)):
                yield from _path_fields(child, prefix=f"{prefix}[{index}].")


def audit_ingestion_jobs(root: Path) -> tuple[list[dict], dict]:
    imports = root / "data" / "imports"
    issues = []
    counts = Counter()
    if not imports.exists():
        return issues, {"jobs": 0, "payloads": 0}
    for manifest_path in imports.rglob("job_manifest.json"):
        if manifest_path.is_symlink() or manifest_path.is_junction():
            issues.append(issue("job_manifest_link", safe_label(root, manifest_path), "manifest"))
            continue
        job_dir = manifest_path.parent
        counts["jobs"] += 1
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(issue("job_manifest_invalid", safe_label(root, manifest_path), "manifest",
                                detail=type(exc).__name__))
            continue
        source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
        digest = str(source.get("sha256") or manifest.get("provenance", {}).get("input_sha256") or "")
        source_pdf = job_dir / str(source.get("copied_path") or "source.pdf")
        if not source_pdf.is_file():
            issues.append(issue("job_source_missing", safe_label(root, job_dir), "source.pdf"))
        else:
            if digest and file_sha256(source_pdf).lower() != digest.lower():
                issues.append(issue("job_source_hash_mismatch", safe_label(root, job_dir), "source.sha256"))
            counts["source_pdfs"] += 1
        payload_path = job_dir / "draft_payload.json"
        if not payload_path.is_file():
            status = str(manifest.get("status") or "")
            category = "job_payload_pending" if status == "created" else "job_payload_missing"
            issues.append(issue(category, safe_label(root, job_dir), "draft_payload.json", detail=status))
            continue
        try:
            payload = json.loads(payload_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            issues.append(issue("job_payload_invalid", safe_label(root, payload_path), "json",
                                detail=type(exc).__name__))
            continue
        counts["payloads"] += 1
        for field, value in _path_fields(payload):
            raw = Path(value)
            candidate = raw if raw.is_absolute() else job_dir / raw
            if not candidate.is_file():
                # Legacy references can be relative to the project or an import root.
                alternatives = [root / raw, imports / raw]
                candidate = next((item for item in alternatives if item.is_file()), candidate)
            if not candidate.is_file():
                category = "job_page_reference_missing" if "page_images" in field else (
                    "job_crop_reference_missing" if "question_crop_paths" in field else "job_asset_reference_missing")
                issues.append(issue(category, safe_label(root, job_dir), field, safe_label(root, candidate)))
            else:
                counts["resolved_job_references"] += 1
        counts["candidates"] += len(payload.get("questions") or [])
    return issues, dict(counts)


def audit(root: Path, *, check_readability: bool = False) -> dict:
    root = root.resolve()
    database = root / "data" / "mathcyclus.sqlite3"
    issues, database_counts = audit_database(root, database) if database.is_file() else ([], {})
    if not database.is_file():
        issues.append(issue("database_missing", "workspace", "data/mathcyclus.sqlite3"))
    job_issues, job_counts = audit_ingestion_jobs(root)
    issues.extend(job_issues)
    readability_counts = {}
    if check_readability and database.is_file():
        extra_issues, readability_counts = audit_review_materials(root, database)
        issues.extend(extra_issues)
    categories = Counter(row["category"] for row in issues)
    return {"mode": "read_only", "created_at": __import__("datetime").datetime.now().astimezone().isoformat(),
            "database_counts": database_counts, "job_counts": job_counts,
            "readability_checked": check_readability, "readability_counts": readability_counts,
            "issue_counts": dict(categories), "issue_count": len(issues), "issues": issues,
            "modified_files": 0, "deleted_files": 0,
            "notes": [
                "This audit reports missing references and hash mismatches; it never repairs them.",
                "Legacy TeX includegraphics checks use project and legacy source paths.",
                "External absolute paths are redacted from the report.",
                "The audit does not infer that an unreferenced file is safe to delete."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--check-readability", action="store_true", help="额外核对草稿回看材料、图片解码和来源页码")
    parser.add_argument("--baseline", type=Path, help="与已有报告逐项比较；范围缩小或计数减少需复核")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    baseline = None
    if args.baseline:
        from scripts.compare_resource_audits import compare_reports
        baseline = json.loads(args.baseline.read_text(encoding="utf-8"))
        # Reject malformed baselines before a potentially long image scan.
        compare_reports(baseline, baseline)
    report = audit(Path(__file__).resolve().parents[1], check_readability=args.check_readability)
    if baseline is not None:
        report["comparison"] = compare_reports(baseline, report)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(report, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: report[key] for key in ("database_counts", "job_counts", "issue_counts",
                                                    "issue_count", "modified_files", "deleted_files")},
                     ensure_ascii=False))
    if "comparison" in report:
        print("comparison_status=" + report["comparison"]["status"])
        return 0 if report["comparison"]["status"] == "no_new_issues" else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
