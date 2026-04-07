from __future__ import annotations

from solaire.primebrush.common.models import StyleSpec

_DEFAULT_STYLE = StyleSpec(
    stroke_width=1.0,
    font_family="sans-serif",
    font_size=12.0,
)


def merge_style(doc_style: StyleSpec | None) -> StyleSpec:
    base = _DEFAULT_STYLE.model_copy()
    if doc_style is None:
        return base
    data = base.model_dump()
    for k, v in doc_style.model_dump(exclude_none=True).items():
        data[k] = v
    return StyleSpec.model_validate(data)
