"""Compare resource audits without changing the workspace or accepting a new baseline."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

COUNT_FIELDS = ("question", "question_import_draft", "question_import_draft_asset")
JOB_FIELDS = ("jobs", "source_pdfs", "payloads", "resolved_job_references", "candidates")
READABILITY_FIELDS = ("registered_assets_checked", "draft_review_references", "draft_source_page_numbers",
                      "job_page_images", "unique_files_probed", "images_decoded", "pdfs_opened")


def _validate(report: dict) -> None:
    if not isinstance(report, dict) or report.get("mode") != "read_only":
        raise ValueError("不是受支持的只读资源审计报告")
    if not isinstance(report.get("issues"), list) or not isinstance(report.get("database_counts"), dict):
        raise ValueError("审计报告缺少问题明细或数据库计数")
    if type(report.get("readability_checked")) is not bool:
        raise ValueError("审计报告缺少明确的检查范围")
    for issue in report["issues"]:
        if not isinstance(issue, dict) or any(not isinstance(issue.get(key), str)
                                              for key in ("category", "owner", "field", "value")):
            raise ValueError("问题记录格式不完整")
    for field in COUNT_FIELDS:
        count = report["database_counts"].get(field)
        if type(count) is not int or count < 0:
            raise ValueError("数据库计数缺失或格式无效：" + field)
    if report.get("issue_count") != len(report["issues"]):
        raise ValueError("问题计数与明细不一致")
    for group, fields in (("job_counts", JOB_FIELDS),
                          ("readability_counts", READABILITY_FIELDS if report["readability_checked"] else ())):
        counters = report.get(group)
        if not isinstance(counters, dict):
            raise ValueError("审计报告缺少计数：" + group)
        for field in fields:
            count = counters.get(field, 0)
            if type(count) is not int or count < 0:
                raise ValueError("计数格式无效：" + group + "." + field)


def _issue_key(row: dict) -> str:
    # A different missing question/path must not hide behind equal totals.
    return json.dumps({key: row[key] for key in ("category", "owner", "field", "value")},
                      ensure_ascii=False, sort_keys=True)


def compare_reports(baseline: dict, current: dict) -> dict:
    _validate(baseline)
    _validate(current)
    old = Counter(_issue_key(row) for row in baseline["issues"])
    new = Counter(_issue_key(row) for row in current["issues"])
    added = [{**json.loads(key), "occurrences": count} for key, count in (new - old).items()]
    resolved = [{**json.loads(key), "occurrences": count} for key, count in (old - new).items()]
    unchanged = sum((old & new).values())
    scope_issues, count_changes = [], []
    if baseline["readability_checked"] and not current["readability_checked"]:
        scope_issues.append("基线含图片解码检查，本次未执行，不能宣称完整通过")
    fields = [("database_counts", COUNT_FIELDS), ("job_counts", JOB_FIELDS)]
    if baseline["readability_checked"] and current["readability_checked"]:
        fields.append(("readability_counts", READABILITY_FIELDS))
    for group, names in fields:
        for name in names:
            before = baseline[group].get(name, 0)
            after = current[group].get(name, 0)
            if before != after:
                count_changes.append({"group": group, "field": name, "before": before,
                                      "after": after, "delta": after - before})
                if after < before:
                    scope_issues.append(f"{group}.{name} 减少，需核对是否为授权业务变化")
    status = "regression" if added else "review_required" if scope_issues else "no_new_issues"
    return {"status": status, "new_issues": added, "resolved_issues": resolved,
            "unchanged_issue_occurrences": unchanged, "count_changes": count_changes,
            "scope_or_count_warnings": scope_issues,
            "baseline_replaced": False, "modified_files": 0, "deleted_files": 0,
            "limitations": [
                "No-new-issues is limited to the checks recorded by both reports.",
                "An existing baseline issue remains an issue; it is not automatically approved.",
                "Count increases are reported, but do not prove that specific original records were preserved.",
                "Legitimate record moves, approvals and cleanup may require review; never auto-update the baseline."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--current", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    result = compare_reports(json.loads(args.baseline.read_text(encoding="utf-8")),
                             json.loads(args.current.read_text(encoding="utf-8")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps({key: result[key] for key in
                      ("status", "new_issues", "resolved_issues", "scope_or_count_warnings")}, ensure_ascii=False))
    return 0 if result["status"] == "no_new_issues" else 1


if __name__ == "__main__":
    raise SystemExit(main())
