"""注册内置几何 / 函数图 / 统计图插件。"""

from __future__ import annotations

from solaire.primebrush.plugins.chart_plugin import ChartPlugin
from solaire.primebrush.plugins.chemistry_molecule_plugin import ChemistryMoleculePlugin
from solaire.primebrush.plugins.geometry_2d_plugin import Geometry2dPlugin
from solaire.primebrush.plugins.plot_2d_plugin import Plot2dPlugin
from solaire.primebrush.registry import register_plugin


def register_builtin_plugins() -> None:
    register_plugin(Geometry2dPlugin())
    register_plugin(Plot2dPlugin())
    register_plugin(ChartPlugin())
    register_plugin(ChemistryMoleculePlugin())
