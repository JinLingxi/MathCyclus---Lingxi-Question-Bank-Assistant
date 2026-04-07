"""PrimeBrush 公共 API。

PrimeBrush 是 EducationPaperDesignAutomation 的教育绘图库，
声明式 YAML → SVG，支持 K12 全学科绘图需求。

当前已实现的图类型（type 字段）：
  - geometry_2d  平面几何（尺规构造、辅助线、标注）
  - plot_2D      二维函数图（表达式、散点、切线）
  - chart        统计图（柱状图）

规划中的图类型（尚未实现，传入时将抛出 NotImplementedError）：
  - geometry_3d  三维基础绘图
  - physics_force 物理受力分析图
  - physics_field 物理场分布图
  - chemistry_lattice  晶格绘图
  - geography_contour  地理等高线绘图

已实现扩展：
  - chemistry_molecule  化学二维结构式（SMILES，可选 RDKit）

外部模块接口（不变的契约）：
  parse_primebrush(raw) -> PrimeBrushDoc
  render(doc, *, seed) -> str  # SVG 字符串
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from solaire.primebrush.common.models import PrimeBrushDoc
from solaire.primebrush.registry import get_plugin_for_doc, get_plugin_for_type

__all__ = ["PrimeBrushDoc", "parse_primebrush", "render"]

# 规划中的扩展图类型（尚未实现）
_PLANNED_TYPES = frozenset(
    {
        "geometry_3d",
        "physics_force",
        "physics_field",
        "chemistry_lattice",
        "geography_contour",
    }
)


def _load_yaml_dict(raw: str | bytes | Path) -> dict[str, Any]:
    if isinstance(raw, Path):
        text = raw.read_text(encoding="utf-8")
    else:
        text = raw.decode("utf-8") if isinstance(raw, bytes) else raw
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    return data


def _render_python_impl(doc: PrimeBrushDoc, *, seed: int | None = None) -> str:
    plugin = get_plugin_for_doc(doc)
    if plugin is None:
        raise TypeError(f"unsupported doc type: {type(doc)}")
    return plugin.render_doc(doc, seed=seed)


def render(doc: PrimeBrushDoc, *, seed: int | None = None) -> str:
    """Render a PrimeBrushDoc to an SVG string.

    This is the stable public contract. When PrimeBrush is migrated to Rust/WASM,
    this function signature remains unchanged; only the implementation changes.

    Args:
        doc: A validated PrimeBrushDoc instance (from parse_primebrush).
        seed: Optional RNG seed for reproducible output.

    Returns:
        SVG string.
    """
    try:
        from primebrush_rs import render as _rust_render  # type: ignore[import-not-found]

        return _rust_render(doc.model_dump(mode="json"), seed=seed)  # type: ignore[no-any-return]
    except (ImportError, NotImplementedError):
        return _render_python_impl(doc, seed=seed)


def parse_primebrush(raw: str | bytes | Path) -> PrimeBrushDoc:
    """Parse a PrimeBrush YAML document.

    Args:
        raw: YAML string, bytes, or path to a .yaml file.
             Top-level key must be ``primebrush``.

    Returns:
        A validated PrimeBrushDoc model instance.

    Raises:
        ValueError: If the YAML is invalid or the diagram type is unknown.
        NotImplementedError: If the diagram type is planned but not yet implemented.
    """
    data = _load_yaml_dict(raw)
    block = data.get("primebrush")
    if block is None:
        raise ValueError("missing top-level 'primebrush' key")
    if not isinstance(block, dict):
        raise ValueError("'primebrush' must be a mapping")

    diagram_type = block.get("type")
    if diagram_type in _PLANNED_TYPES:
        raise NotImplementedError(
            f"PrimeBrush diagram type '{diagram_type}' is planned but not yet implemented. "
            f"Currently supported: geometry_2d, plot_2D, chart, chemistry_molecule."
        )

    plugin = get_plugin_for_type(diagram_type)
    if plugin is None:
        raise ValueError(f"unknown primebrush.type: {diagram_type!r}")
    return plugin.parse_block(block)
