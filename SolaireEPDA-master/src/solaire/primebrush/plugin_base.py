"""PrimeBrush 绘图插件抽象基类（Python 侧；Rust 迁移后插件契约对齐）。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from solaire.primebrush.common.models import PrimeBrushDoc


class PrimeBrushPlugin(ABC):
    """可注册的图类型插件：解析 YAML 块并渲染为 SVG。"""

    @property
    @abstractmethod
    def type_names(self) -> frozenset[str]:
        """与 YAML ``type:`` 对应的标识（可多个别名，如 plot_2d / plot_2D）。"""

    @abstractmethod
    def parse_block(self, block: dict) -> PrimeBrushDoc:
        """将 ``primebrush`` 下的 mapping 校验为文档模型。"""

    @abstractmethod
    def render_doc(self, doc: PrimeBrushDoc, *, seed: int | None) -> str:
        """渲染为 SVG 字符串。"""
