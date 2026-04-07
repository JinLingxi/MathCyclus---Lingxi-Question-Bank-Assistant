"""Discover question_libraries entries for exam.yaml / probe from resource/ layout."""

from __future__ import annotations

from pathlib import Path


def discover_question_library_refs(project_root: Path) -> list[dict[str, str]]:
    """
    标准目录：``resource/<科目名称>/<题集名称>/`` 下放 YAML。

    每个含 ``*.yaml`` 的 ``resource/<科目>/<题集>/`` 对应 namespace ``科目/题集``。

    若尚无题集或尚无题目文件，返回空列表（空项目合法）。
    """
    resource = project_root / "resource"
    refs: list[dict[str, str]] = []
    if not resource.is_dir():
        return []

    for subject_dir in sorted(resource.iterdir()):
        if not subject_dir.is_dir():
            continue
        subject = subject_dir.name
        for coll_dir in sorted(subject_dir.iterdir()):
            if not coll_dir.is_dir():
                continue
            if any(coll_dir.rglob("*.yaml")):
                ns = f"{subject}/{coll_dir.name}"
                if not any(r["namespace"] == ns for r in refs):
                    refs.append({"namespace": ns, "path": f"../resource/{subject}/{coll_dir.name}"})

    return refs


def library_root_for_namespace(project_root: Path, namespace: str) -> Path:
    """Absolute directory for one library（namespace = 科目/题集；``main`` 表示 ``resource/`` 根）。"""
    resource = project_root / "resource"
    if namespace == "main":
        return resource.resolve()
    parts = namespace.split("/")
    if len(parts) == 2:
        return (resource / parts[0] / parts[1]).resolve()
    if len(parts) == 1:
        # 单层目录名（旧数据或误放）：当作 resource/<name>
        return (resource / parts[0]).resolve()
    raise ValueError(f"Invalid namespace (expect 科目/题集): {namespace!r}")


def split_qualified_id(qualified_id: str) -> tuple[str, str]:
    """namespace 可含 ``/``（科目/题集），最后一节为题内 id。"""
    if "/" not in qualified_id:
        raise ValueError("qualified_id must contain at least one '/'")
    return qualified_id.rsplit("/", 1)
