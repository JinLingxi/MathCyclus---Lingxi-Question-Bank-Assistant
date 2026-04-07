from __future__ import annotations

from pathlib import Path

import yaml

from solaire.exam_compiler.models import ExamConfig, SelectedSection


def write_exam_yaml(dest_dir: Path, exam_id: str, sections: list[tuple[str, int, float]]) -> None:
    """Write a minimal exam.yaml for integration API tests."""
    selected_items: list[SelectedSection] = []
    for sec_idx, (sec_id, qcount, score_per_item) in enumerate(sections, start=1):
        selected_items.append(
            SelectedSection(
                section_id=sec_id,
                question_ids=[f"q_{sec_idx}_{i}" for i in range(1, qcount + 1)],
                score_per_item=score_per_item,
            )
        )

    exam = ExamConfig(
        exam_id=exam_id,
        template_ref="default",
        metadata={"title": f"{exam_id} title", "subject": "数学"},
        question_libraries=[],
        template_path="templates/test.yaml",
        selected_items=selected_items,
    )
    with (dest_dir / "exam.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(exam.model_dump(mode="json"), f, allow_unicode=True, sort_keys=False)
