"""Qualified id: ``namespace/local_id`` — namespace 可含 ``/``（科目/题集），最后一节为题内 id。"""

from __future__ import annotations


def split_qualified_id(qualified_id: str) -> tuple[str, str]:
    if "/" not in qualified_id:
        raise ValueError("qualified_id must contain at least one '/'")
    return qualified_id.rsplit("/", 1)


def namespace_of_qualified(qualified_id: str) -> str:
    """Library namespace (e.g. 科目/题集) for graphicspath / roots lookup."""
    return split_qualified_id(qualified_id)[0]
