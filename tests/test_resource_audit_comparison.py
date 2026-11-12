import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.compare_resource_audits import compare_reports


def report():
    return {"mode": "read_only",
            "database_counts": {"question": 10, "question_import_draft": 20,
                                "question_import_draft_asset": 4},
            "job_counts": {"jobs": 2, "source_pdfs": 2, "payloads": 2},
            "readability_checked": True, "readability_counts": {"images_decoded": 8},
            "issue_count": 1, "issues": [
                {"category": "draft_sample_fixture_missing", "owner": "sample",
                 "field": "source_path", "value": "incoming/example.png", "detail": ""}]}


class ResourceAuditComparisonTests(unittest.TestCase):
    def test_unchanged_known_issue_stays_visible(self):
        baseline = report()
        result = compare_reports(baseline, copy.deepcopy(baseline))
        self.assertEqual(result["status"], "no_new_issues")
        self.assertEqual(result["unchanged_issue_occurrences"], 1)
        self.assertFalse(result["baseline_replaced"])
        self.assertEqual(len(baseline["issues"]), 1)

    def test_same_total_different_missing_path_is_new_regression(self):
        before = report()
        current = copy.deepcopy(before)
        current["issues"][0]["owner"] = "real-draft"
        current["issues"][0]["value"] = "data/draft_assets/lost.png"
        result = compare_reports(before, current)
        self.assertEqual(result["status"], "regression")
        self.assertEqual(result["new_issues"][0]["owner"], "real-draft")
        self.assertEqual(len(result["resolved_issues"]), 1)

    def test_weaker_scan_cannot_pass(self):
        current = report()
        current["readability_checked"] = False
        self.assertEqual(compare_reports(report(), current)["status"], "review_required")

    def test_count_decrease_requires_review_even_without_new_missing_file(self):
        current = report()
        current["database_counts"]["question_import_draft"] -= 1
        result = compare_reports(report(), current)
        self.assertEqual(result["status"], "review_required")
        self.assertEqual(result["count_changes"][0]["delta"], -1)

    def test_newly_added_content_is_reported_without_losing_issue_identity(self):
        current = report()
        current["database_counts"]["question"] += 1
        result = compare_reports(report(), current)
        self.assertEqual(result["status"], "no_new_issues")
        self.assertEqual(result["count_changes"][0]["delta"], 1)

    def test_duplicate_problem_occurrences_are_not_deduplicated_away(self):
        current = report()
        current["issues"].append(copy.deepcopy(current["issues"][0]))
        current["issue_count"] = 2
        result = compare_reports(report(), current)
        self.assertEqual(result["status"], "regression")
        self.assertEqual(result["new_issues"][0]["occurrences"], 1)

    def test_malformed_report_cannot_look_clean(self):
        for current in ({}, {**report(), "database_counts": {}},
                        {**report(), "issue_count": 0}):
            with self.subTest(current=current), self.assertRaises(ValueError):
                compare_reports(report(), current)

    def test_invalid_baseline_fails_before_scanning_or_writing(self):
        from scripts.audit_resource_integrity import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "bad.json"
            baseline.write_text("{}", encoding="utf-8")
            output = root / "out.json"
            with patch("sys.argv", ["audit", "--baseline", str(baseline), "--output", str(output)]), \
                 patch("scripts.audit_resource_integrity.audit") as scanner:
                with self.assertRaises(ValueError):
                    main()
                scanner.assert_not_called()
            self.assertFalse(output.exists())

    def test_unified_entry_writes_comparison_and_returns_failure_on_regression(self):
        from scripts.audit_resource_integrity import main
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            baseline = root / "baseline.json"
            baseline.write_text(json.dumps(report()), encoding="utf-8")
            current = report()
            current["issues"][0]["value"] = "new-missing.png"
            output = root / "out.json"
            with patch("sys.argv", ["audit", "--baseline", str(baseline), "--output", str(output)]), \
                 patch("scripts.audit_resource_integrity.audit", return_value={
                     **current, "issue_counts": {}, "modified_files": 0, "deleted_files": 0}):
                self.assertEqual(main(), 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["comparison"]["status"], "regression")
            self.assertEqual(json.loads(baseline.read_text(encoding="utf-8")), report())


if __name__ == "__main__":
    unittest.main()
