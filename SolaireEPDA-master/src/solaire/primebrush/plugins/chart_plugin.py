from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from solaire.primebrush.charts.render import render_chart_svg
from solaire.primebrush.common.canvas import normalize_canvas
from solaire.primebrush.common.models import ChartModel
from solaire.primebrush.plugin_base import PrimeBrushPlugin

if TYPE_CHECKING:
    from solaire.primebrush.common.models import PrimeBrushDoc


class ChartPlugin(PrimeBrushPlugin):
    @property
    def type_names(self) -> frozenset[str]:
        return frozenset({"chart"})

    def parse_block(self, block: dict) -> PrimeBrushDoc:
        return ChartModel.model_validate(block)

    def render_doc(self, doc: PrimeBrushDoc, *, seed: int | None) -> str:
        assert isinstance(doc, ChartModel)
        w, h, _ = normalize_canvas(doc.canvas if hasattr(doc, "canvas") else None)
        effective = seed
        if effective is None:
            doc_seed = getattr(doc, "seed", None)
            if doc_seed is not None:
                effective = int(doc_seed)
        if effective is None:
            effective = 42
        rng = np.random.default_rng(effective)
        return render_chart_svg(doc, w, h, rng)
