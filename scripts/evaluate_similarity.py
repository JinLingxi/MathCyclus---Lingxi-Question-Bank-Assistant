"""Offline regression checks and a human-label workflow for local similarity.

Never writes formal questions, relationships, embeddings, weights or thresholds.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
import csv
from datetime import datetime
import json
import math
from pathlib import Path
import random
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dotenv import dotenv_values
from services.formula_similarity_service import compare_formula_texts, formula_structure_key
from services.semantic_search_service import (
    SEMANTIC_INDEX_PATH, SIMILARITY_WEIGHTS, VERIFICATION_WEIGHTS,
    _formula_features, _set_similarity, combined_similarity_score,
    load_sqlite_index_rows, row_fingerprint,
)
from services.sqlite_legacy_adapter import enrich_similarity_metadata

LABELS = {"exact", "variant", "related", "unrelated", "uncertain"}


def regression_cases():
    for number in range(1, 21):
        x = str(number)
        yield ("format", rf"\dfrac{{x+{x}}}{{x-1}}", rf"\frac{{x+{x}}}{{x-1}}", "exact")
        yield ("rename", rf"x+x+{x}", rf"y+y+{x}", "structure")
        yield ("parameter", rf"{number+1}*x+{x}", rf"{number+2}*x+{x}", "structure")
        yield ("exponent", rf"x^{{{number+1}}}+1", rf"x^{{{number+2}}}+1", "指数表达式不同")
        yield ("denominator", rf"\frac{{x}}{{x+{x}}}", rf"\frac{{x}}{{x}}+{x}", "分母表达式不同")
        yield ("relation", rf"x<{x}", rf"x\leq {x}", "公式关系符号不同")
        yield ("set", rf"A\cup B_{{{x}}}", rf"A\cap B_{{{x}}}", "集合运算符不同")
        yield ("unsupported", rf"\sum_{{i=1}}^{{{x}}} i", rf"\sum_{{i=1}}^{{{x}}} i", "fallback")
        yield ("repetition", rf"x+x+{x}", rf"y+z+{x}", "different_structure")
        yield ("function_group", rf"f(x)+{x}", rf"f*x+{x}", "different_expression")


def run_regressions():
    results = []
    for category, left, right, expected in regression_cases():
        left, right = "$" + left + "$", "$" + right + "$"
        result = compare_formula_texts(left, right)
        passed = (
            result["exact"] if expected == "exact" else
            result["complete"] and result["structure_score"] == 1 if expected == "structure" else
            result["complete"] and result["structure_score"] < 1 if expected == "different_structure" else
            result["complete"] and not result["exact"] if expected == "different_expression" else
            not result["complete"] if expected == "fallback" else expected in result["differences"])
        baseline = _set_similarity(_formula_features(left), _formula_features(right))
        results.append({"category": category, "left": left, "right": right, "expected": expected,
                        "passed": bool(passed), "baseline_formula_score": baseline, "new": result})
    hard = [row for row in results if row["category"] in
            {"exponent", "denominator", "relation", "set", "repetition", "function_group"}]
    return {"suite": "200 developer-authored syntax regression cases; not human-labelled bank pairs",
            "total": len(results), "passed": sum(row["passed"] for row in results),
            "baseline_identical_feature_collisions_on_hard_cases": sum(
                row["baseline_formula_score"] == 1 for row in hard),
            "new_identical_expression_collisions_on_hard_cases": sum(row["new"]["exact"] for row in hard),
            "cases": results}


def _semantic_scores(pairs):
    """Only read stored vectors; no embedding API requests."""
    from services.semantic_search_service import _unpack_vector
    wanted = {row["SQLite题目ID"] for pair in pairs for row in pair}
    entries = {}
    if Path(SEMANTIC_INDEX_PATH).exists():
        with closing(sqlite3.connect(Path(SEMANTIC_INDEX_PATH).as_uri() + "?mode=ro", uri=True)) as db:
            model = str(dotenv_values(ROOT / ".env").get("AI_EMBEDDING_MODEL_NAME") or "")
            for qid, fingerprint, dimensions, blob in db.execute(
                    "SELECT question_id,fingerprint,dimensions,vector FROM semantic_embeddings WHERE model_name=?", (model,)):
                if qid in wanted:
                    values = _unpack_vector(blob, dimensions)
                    entries[qid] = (fingerprint, values, math.sqrt(sum(value * value for value in values)) or 1)
    scores = {}
    for left, right in pairs:
        a, b = entries.get(left["SQLite题目ID"]), entries.get(right["SQLite题目ID"])
        score = None
        if a and b and a[0] == row_fingerprint(left) and b[0] == row_fingerprint(right) and len(a[1]) == len(b[1]):
            score = sum(x*y for x, y in zip(a[1], b[1])) / (a[2]*b[2])
        scores[(left["SQLite题目ID"], right["SQLite题目ID"])] = score
    return scores


def prepare_review(rows):
    rng = random.Random(20261110)
    by_id = {row["SQLite题目ID"]: row for row in rows}
    selected, seen = [], set()
    def add(left_id, right_id, category, provenance=""):
        key = tuple(sorted((left_id, right_id)))
        if left_id == right_id or key in seen or left_id not in by_id or right_id not in by_id:
            return False
        seen.add(key)
        selected.append((by_id[left_id], by_id[right_id], category, provenance))
        return True
    with closing(sqlite3.connect((ROOT / "data/mathcyclus.sqlite3").as_uri() + "?mode=ro", uri=True)) as db:
        relations = db.execute("""SELECT question_id_a,question_id_b,relation_type FROM question_equivalence
            WHERE review_status='approved' AND relation_source='manual'
            ORDER BY question_id_a,question_id_b""").fetchall()
    for left, right, kind in relations:
        add(left, right, "existing_relation", "已有人工确认关系：" + kind + "；数学类别仍需确认")
        if len(selected) >= 30:
            break
    buckets = defaultdict(list)
    for row in rows:
        key = formula_structure_key(row.get("题干"))
        if key and len(buckets[key]) < 8:
            buckets[key].append(row["SQLite题目ID"])
    target = len(selected) + 40
    for key in sorted(buckets):
        ids = buckets[key]
        for right in ids[1:4]:
            add(ids[0], right, "formula_structure", "结构键相同；不代表同题或数学等价")
        if len(selected) >= target:
            break
    chapters = defaultdict(list)
    for row in rows:
        chapters[row.get("知识板块") or "未标记"].append(row["SQLite题目ID"])
    target = min(100, len(selected) + 30)
    for chapter in sorted(chapters):
        ids = chapters[chapter]
        if len(ids) > 1:
            anchor = ids[len(ids)//2]
            for candidate in rng.sample(ids, min(3, len(ids))):
                add(anchor, candidate, "same_chapter", "同板块抽样；数学关联尚未判定")
        if len(selected) >= target:
            break
    ids = sorted(by_id)
    attempts = 0
    while len(selected) < 120 and attempts < 1000:
        left, right = rng.sample(ids, 2)
        add(left, right, "cross_bank_control", "全库抽样对照；未预设无关标签")
        attempts += 1
    selected = selected[:120]
    enrich_similarity_metadata(list({row["SQLite题目ID"]: row for pair in selected for row in pair[:2]}.values()))
    semantic = _semantic_scores([pair[:2] for pair in selected])
    output = []
    for index, (left, right, category, provenance) in enumerate(selected, 1):
        score = semantic[(left["SQLite题目ID"], right["SQLite题目ID"])]
        scores = {mode: combined_similarity_score(left, right, score, mode=mode)
                  for mode in ("recommendation", "verification")}
        output.append({"pair_id": f"P{index:03}", "category": category, "provenance": provenance,
                       "left": left, "right": right, "scores": scores,
                       "human_label": "", "reviewer": "", "review_note": "", "review_status": "pending"})
    return output


def evaluate_labels(pairs):
    confirmed = [pair for pair in pairs if pair.get("review_status") == "confirmed"
                 and pair.get("human_label") in LABELS - {"uncertain"}
                 and str(pair.get("reviewer") or "").strip()]
    distributions = defaultdict(list)
    groups = defaultdict(list)
    for pair in confirmed:
        for mode in ("recommendation", "verification"):
            distributions[mode + ":" + pair["human_label"]].append(pair["scores"][mode]["score"])
        groups[pair["left"]["SQLite题目ID"]].append(pair)
    ndcg = []
    grades = {"exact": 3, "variant": 2, "related": 1, "unrelated": 0}
    for group in groups.values():
        if len(group) < 3 or len({pair["human_label"] for pair in group}) < 2:
            continue
        ranking = sorted(group, key=lambda pair: pair["scores"]["recommendation"]["score"], reverse=True)[:10]
        ideal = sorted(group, key=lambda pair: grades[pair["human_label"]], reverse=True)[:10]
        def dcg(items):
            return sum((2**grades[pair["human_label"]]-1)/math.log2(index+2) for index, pair in enumerate(items))
        if dcg(ideal):
            ndcg.append(dcg(ranking)/dcg(ideal))
    return {"human_confirmed_pairs": len(confirmed), "pending_or_uncertain": len(pairs)-len(confirmed),
            "score_distributions": {key: {"count": len(values), "mean": sum(values)/len(values)}
                                    for key, values in distributions.items()},
            "recommendation_ndcg_at_10": sum(ndcg)/len(ndcg) if ndcg else None,
            "eligible_query_groups": len(ndcg),
            "calibration_status": "awaiting_human_labels" if not confirmed else "descriptive_only_no_auto_tuning",
            "weight_changes_applied": False, "threshold_changes_applied": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-review", action="store_true")
    parser.add_argument("--review-file", type=Path)
    args = parser.parse_args()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out = ROOT / "reports" / ("similarity_phase2_" + stamp)
    regressions = run_regressions()
    result = {"created_at": stamp, "regressions": regressions,
              "recommendation_weights": SIMILARITY_WEIGHTS, "verification_weights": VERIFICATION_WEIGHTS,
              "formal_database_writes": 0, "embedding_api_requests": 0,
              "weight_changes_applied": False, "threshold_changes_applied": False}
    if args.prepare_review:
        pairs = prepare_review(load_sqlite_index_rows())
        review_path = Path(str(out) + ".review.json")
        review_path.write_text(json.dumps(pairs, ensure_ascii=False, indent=2), encoding="utf-8")
        result["review_file"] = review_path.relative_to(ROOT).as_posix()
        result["review_summary"] = evaluate_labels(pairs)
        with Path(str(out) + ".review.csv").open("w", encoding="utf-8-sig", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["pair_id", "category", "left_id", "right_id", "left_stem", "right_stem",
                             "left_choices", "right_choices", "human_label", "reviewer", "review_note", "review_status"])
            for pair in pairs:
                writer.writerow([pair["pair_id"], pair["category"],
                                 pair["left"]["SQLite题目ID"], pair["right"]["SQLite题目ID"],
                                 pair["left"].get("题干"), pair["right"].get("题干"),
                                 pair["left"].get("选项"), pair["right"].get("选项"), "", "", "", "pending"])
        lines = ["# 真实题对待标注清单", "",
                 "这里的分类是抽样来源，不是真实数学类别。现有来源关系也没有自动转成同题标签。",
                 "标签可选 exact（同题）、variant（变式）、related（相关练习）、unrelated（无关）、uncertain（待定）。",
                 "在同名 review.json 中填写 human_label、reviewer、review_note，并将 review_status 改为 confirmed 后，可运行 --review-file 评估。",
                 "所有题干和选项均来自只读快照，未修改正式题目。评测记录不会登记正式关系。", ""]
        lines += ["含配图的题目需要在题库按 ID 打开图片核对；本清单的文字快照不替代完整题目预览。", ""]
        for pair in pairs:
            lines += [f"## {pair['pair_id']} · {pair['category']}", "",
                      pair["provenance"], "",
                      f"基准题：{pair['left']['SQLite题目ID']}", "", pair["left"].get("题干") or "",
                      "", pair["left"].get("选项") or "", "",
                      f"候选题：{pair['right']['SQLite题目ID']}", "", pair["right"].get("题干") or "",
                      "", pair["right"].get("选项") or "", "",
                      "人工标签：待确认", ""]
        Path(str(out) + ".review.md").write_text("\n".join(lines), encoding="utf-8")
    if args.review_file:
        pairs = json.loads(args.review_file.read_text(encoding="utf-8"))
        # Re-score snapshots using current rules rather than stale saved scores.
        semantic = _semantic_scores([(pair["left"], pair["right"]) for pair in pairs])
        for pair in pairs:
            pair["scores"] = {mode: combined_similarity_score(
                pair["left"], pair["right"], semantic[(pair["left"]["SQLite题目ID"], pair["right"]["SQLite题目ID"])],
                mode=mode) for mode in ("recommendation", "verification")}
        result["review_summary"] = evaluate_labels(pairs)
    Path(str(out) + ".result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"report": str(out.relative_to(ROOT)) + ".result.json",
                      "regression_total": regressions["total"], "regression_passed": regressions["passed"],
                      "baseline_hard_collisions": regressions["baseline_identical_feature_collisions_on_hard_cases"],
                      "new_hard_collisions": regressions["new_identical_expression_collisions_on_hard_cases"],
                      "review_file": result.get("review_file"), "review_summary": result.get("review_summary")}))
    if regressions["passed"] != regressions["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
