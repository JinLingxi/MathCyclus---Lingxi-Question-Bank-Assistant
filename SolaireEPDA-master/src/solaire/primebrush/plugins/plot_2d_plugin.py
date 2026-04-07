from __future__ import annotations

from typing import TYPE_CHECKING

import numpy as np

from solaire.primebrush.common.canvas import normalize_canvas
from solaire.primebrush.common.models import Plot2DModel
from solaire.primebrush.plots.plot2d import render_plot2d_svg
from solaire.primebrush.plugin_base import PrimeBrushPlugin

if TYPE_CHECKING:
    from solaire.primebrush.common.models import PrimeBrushDoc


class Plot2dPlugin(PrimeBrushPlugin):
    @property
    def type_names(self) -> frozenset[str]:
        return frozenset({"plot_2D", "plot_2d"})

    def parse_block(self, block: dict) -> PrimeBrushDoc:
        b = {**block, "type": "plot_2D"}
        return Plot2DModel.model_validate(b)

    def render_doc(self, doc: PrimeBrushDoc, *, seed: int | None) -> str:
        assert isinstance(doc, Plot2DModel)
        w, h, _ = normalize_canvas(doc.canvas if hasattr(doc, "canvas") else None)
        effective = seed
        if effective is None:
            doc_seed = getattr(doc, "seed", None)
            if doc_seed is not None:
                effective = int(doc_seed)
        if effective is None:
            effective = 42
        rng = np.random.default_rng(effective)
        return render_plot2d_svg(doc, w, h, rng)
