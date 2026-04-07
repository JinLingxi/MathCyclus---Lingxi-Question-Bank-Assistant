"""PrimeBrush 插件注册表。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solaire.primebrush.common.models import PrimeBrushDoc

from solaire.primebrush.plugin_base import PrimeBrushPlugin

_BY_TYPE: dict[str, PrimeBrushPlugin] = {}


def register_plugin(plugin: PrimeBrushPlugin) -> None:
    """注册插件；同 type 后注册覆盖前者。"""
    for name in plugin.type_names:
        _BY_TYPE[name] = plugin


def get_plugin_for_type(type_name: str) -> PrimeBrushPlugin | None:
    return _BY_TYPE.get(type_name)


def list_registered_types() -> frozenset[str]:
    return frozenset(_BY_TYPE.keys())


def get_plugin_for_doc(doc: PrimeBrushDoc) -> PrimeBrushPlugin | None:
    """按文档模型类型解析渲染插件。"""
    from solaire.primebrush.common.models import ChartModel, ChemistryMoleculeModel, Geometry2DModel, Plot2DModel

    if isinstance(doc, Geometry2DModel):
        return get_plugin_for_type("geometry_2d")
    if isinstance(doc, Plot2DModel):
        return get_plugin_for_type("plot_2D")
    if isinstance(doc, ChartModel):
        return get_plugin_for_type("chart")
    if isinstance(doc, ChemistryMoleculeModel):
        return get_plugin_for_type("chemistry_molecule")
    return None


def _load_builtin_plugins() -> None:
    from solaire.primebrush.plugins.builtin import register_builtin_plugins

    register_builtin_plugins()


_load_builtin_plugins()
