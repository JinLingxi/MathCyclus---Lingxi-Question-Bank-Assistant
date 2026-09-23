from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

from services.semantic_search_service import combined_similarity_score


def _row(stem: str, knowledge: str, question_type: str, choices: str = "") -> dict:
    return {
        "题干": stem,
        "知识板块": knowledge,
        "题型": question_type,
        "选项": choices,
    }


def main() -> None:
    reference = _row(
        r"在锐角三角形 $ABC$ 中，角 $A,B,C$ 的对边分别为 $a,b,c$，"
        r"若 $\frac{a}{b}+\frac{b}{a}=6\cos C$，求 "
        r"$\frac{\tan C}{\tan A}+\frac{\tan C}{\tan B}$。",
        "解三角形",
        "填空题",
    )
    structurally_close = _row(
        r"在三角形 $ABC$ 中，$a,b,c$ 分别为角 $A,B,C$ 的对边，"
        r"已知 $\frac{a}{b}+\frac{b}{a}=4\cos C$，求 "
        r"$\frac{\tan C}{\tan A}+\frac{\tan C}{\tan B}$。",
        "解三角形",
        "填空题",
    )
    same_chapter_only = _row(
        r"在三角形 $ABC$ 中，已知 $a=2,b=3,C=60^\circ$，求三角形的面积。",
        "解三角形",
        "填空题",
    )
    unrelated = _row(
        r"已知函数 $f(x)=x^2-2x+1$，求函数的最小值。",
        "函数",
        "填空题",
    )

    close_result = combined_similarity_score(reference, structurally_close, 0.8)
    chapter_result = combined_similarity_score(reference, same_chapter_only, 0.8)
    unrelated_result = combined_similarity_score(reference, unrelated, 0.8)

    assert close_result["score"] > chapter_result["score"] > unrelated_result["score"]
    assert "公式结构接近" in close_result["reason"]
    assert "题干表述接近" not in unrelated_result["reason"]
    assert all(0.0 <= result["score"] <= 1.0 for result in [close_result, chapter_result, unrelated_result])
    print("semantic similarity ranking smoke test passed")


if __name__ == "__main__":
    main()
