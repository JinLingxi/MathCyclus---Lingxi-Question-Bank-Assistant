"""Verify all migrated source paths, recovery bytes, manifests and PDF rendering."""

import argparse
import hashlib
import json
import os
import stat
import sys
import zipfile
from pathlib import Path
import fitz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.source_pdf_storage_service import source_object_path, sha256_file
from services.source_pdf_migration_service import write_manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    result = json.loads(args.journal.read_text(encoding="utf-8"))
    project = Path(result["project"])
    checked = 0
    with zipfile.ZipFile(result["backup"]) as archive:
        for group in result["groups"]:
            digest = group["sha256"]
            obj = source_object_path(digest, project / "data" / "source_pdfs")
            if sha256_file(obj) != digest:
                raise AssertionError("source object mismatch")
            with archive.open(digest + ".pdf") as source:
                if hashlib.file_digest(source, "sha256").hexdigest() != digest:
                    raise AssertionError("recovery archive mismatch")
            with fitz.open(stream=archive.read(digest + ".pdf"), filetype="pdf") as baseline:
                baseline_image = baseline[0].get_pixmap(matrix=fitz.Matrix(0.25, 0.25)).samples
                if baseline.page_count != group["page_count"]:
                    raise AssertionError("baseline page count mismatch")
            for item in group["files"]:
                path = project / item["path"]
                if not os.path.samefile(path, obj) or sha256_file(path) != digest:
                    raise AssertionError("job source mismatch: " + item["path"])
                if path.stat().st_mode & stat.S_IWUSR:
                    raise AssertionError("job source is writable")
                if sha256_file(path.parent / "job_manifest.json") != item["manifest_sha256"]:
                    raise AssertionError("job manifest changed")
                with fitz.open(path) as document:
                    if document.page_count != group["page_count"]:
                        raise AssertionError("job page count changed")
                    if document[0].get_pixmap(matrix=fitz.Matrix(0.25, 0.25)).samples != baseline_image:
                        raise AssertionError("job source render changed")
                checked += 1
    if len(result["operations"]) != checked or any(item["state"] != "applied" for item in result["operations"]):
        raise AssertionError("incomplete operation journal")
    if args.finalize:
        result["state"] = "complete"
        result.pop("error", None)
        write_manifest(args.journal, result)
    redundant = sum(group["size"] * (len(group["files"]) - 1) for group in result["groups"])
    archive_bytes = Path(result["backup"]).stat().st_size
    report = {"status": "ok", "verified_sources": checked, "verified_unique_objects": len(result["groups"]),
              "job_manifest_bytes_unchanged": True, "source_render_verified": True,
              "recovery_archive_verified": True, "task_paths_removed": 0,
              "redundant_bytes_before": redundant, "recovery_archive_bytes": archive_bytes,
              "net_estimated_bytes_reclaimed": redundant - archive_bytes,
              "journal_state": result["state"]}
    with args.output.open("x", encoding="utf-8") as target:
        json.dump(report, target, ensure_ascii=False, indent=2)
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
