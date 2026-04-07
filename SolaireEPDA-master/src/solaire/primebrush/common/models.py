from __future__ import annotations

from typing import Any, Literal, Union

from pydantic import BaseModel, Field


class CanvasSpec(BaseModel):
    width: float = 400.0
    height: float = 300.0
    unit: str = "px"


class StyleSpec(BaseModel):
    stroke_width: float | None = None
    font_family: str | None = None
    font_size: float | None = None


class Geometry2DModel(BaseModel):
    type: Literal["geometry_2d"] = "geometry_2d"
    canvas: CanvasSpec | None = None
    style: StyleSpec | None = None
    constructions: list[dict[str, Any]] = Field(default_factory=list)
    seed: int | None = None


class Plot2DModel(BaseModel):
    type: Literal["plot_2D", "plot_2d"] = "plot_2D"
    canvas: CanvasSpec | None = None
    style: StyleSpec | None = None
    axes: dict[str, Any] = Field(default_factory=dict)
    elements: list[dict[str, Any]] = Field(default_factory=list)
    seed: int | None = None


class ChartModel(BaseModel):
    type: Literal["chart"] = "chart"
    canvas: CanvasSpec | None = None
    style: StyleSpec | None = None
    kind: str = "bar"
    theme: str = "academic"
    data: list[dict[str, Any]] = Field(default_factory=list)
    options: dict[str, Any] = Field(default_factory=dict)
    seed: int | None = None


class ChemistryMoleculeModel(BaseModel):
    """二维结构式（优先 SMILES）；无 RDKit 时输出带说明的占位图。"""

    type: Literal["chemistry_molecule"] = "chemistry_molecule"
    canvas: CanvasSpec | None = None
    style: StyleSpec | None = None
    notation: Literal["SMILES", "IUPAC"] = "SMILES"
    value: str = ""
    seed: int | None = None


PrimeBrushDoc = Union[Geometry2DModel, Plot2DModel, ChartModel, ChemistryMoleculeModel]
