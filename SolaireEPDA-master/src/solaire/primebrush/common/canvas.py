from __future__ import annotations

from solaire.primebrush.common.models import CanvasSpec

# 1 cm ≈ 37.8 px at 96 DPI (CSS reference); used when unit is cm
_CM_TO_PX = 96.0 / 2.54


def normalize_canvas(canvas: CanvasSpec | None) -> tuple[float, float, str]:
    """Returns (width_px, height_px, unit_note) for SVG user space."""
    if canvas is None:
        return 400.0, 300.0, "px"
    w, h = float(canvas.width), float(canvas.height)
    u = (canvas.unit or "px").lower()
    if u == "cm":
        return w * _CM_TO_PX, h * _CM_TO_PX, "cm"
    return w, h, u
