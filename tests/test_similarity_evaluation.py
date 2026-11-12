import unittest
from scripts.evaluate_similarity import evaluate_labels, run_regressions


class SimilarityEvaluationTests(unittest.TestCase):
    def test_pending_or_uncertain_labels_never_become_calibration_truth(self):
        pair = {"left": {"SQLite题目ID": "Q1"}, "scores": {
            "recommendation": {"score": 0.8}, "verification": {"score": 0.7}},
            "review_status": "pending", "human_label": "exact", "reviewer": "reviewer",
            "provenance": "already approved source relationship"}
        self.assertEqual(evaluate_labels([pair])["human_confirmed_pairs"], 0)
        pair["review_status"] = "confirmed"
        pair["human_label"] = "uncertain"
        self.assertEqual(evaluate_labels([pair])["human_confirmed_pairs"], 0)
        pair["human_label"] = "exact"
        pair["reviewer"] = ""
        self.assertEqual(evaluate_labels([pair])["human_confirmed_pairs"], 0)

    def test_confirmed_query_group_gets_ranking_metrics_without_auto_tuning(self):
        pairs = [{"left": {"SQLite题目ID": "Q1"}, "scores": {
            "recommendation": {"score": score}, "verification": {"score": score}},
            "review_status": "confirmed", "human_label": label, "reviewer": "reviewer"}
                 for score, label in ((1.0, "exact"), (0.8, "variant"), (0.2, "unrelated"))]
        result = evaluate_labels(pairs)
        self.assertEqual(result["human_confirmed_pairs"], 3)
        self.assertEqual(result["eligible_query_groups"], 1)
        self.assertAlmostEqual(result["recommendation_ndcg_at_10"], 1)
        self.assertFalse(result["weight_changes_applied"])
        self.assertFalse(result["threshold_changes_applied"])

    def test_syntax_suite_covers_200_cases_without_human_accuracy_claim(self):
        result = run_regressions()
        self.assertEqual(result["total"], 200)
        self.assertEqual(result["passed"], 200)
        self.assertEqual(result["new_identical_expression_collisions_on_hard_cases"], 0)


if __name__ == "__main__":
    unittest.main()
