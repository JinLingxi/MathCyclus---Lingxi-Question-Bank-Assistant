from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class GeometrySolveResult:
    """Named points plus auxiliary drawable primitives (circles, ellipses, long segments)."""

    points: dict[str, tuple[float, float]] = field(default_factory=dict)
    drawables: list[dict[str, Any]] = field(default_factory=list)
