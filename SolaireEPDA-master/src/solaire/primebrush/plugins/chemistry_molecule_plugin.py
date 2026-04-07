"""化学二维结构式插件（SMILES → SVG，可选 RDKit）。"""

from __future__ import annotations

import html
from typing import TYPE_CHECKING

from solaire.primebrush.common.canvas import normalize_canvas
from solaire.primebrush.common.models import ChemistryMoleculeModel
from solaire.primebrush.plugin_base import PrimeBrushPlugin

if TYPE_CHECKING:
    from solaire.primebrush.common.models import PrimeBrushDoc


def _svg_placeholder(title: str, subtitle: str, width: float, height: float) -> str:
    safe_t = html.escape(title, quote=True)
    safe_s = html.escape(subtitle, quote=True)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}">'
        f'<rect fill="#f8fafc" width="100%" height="100%" stroke="#e2e8f0"/>'
        f'<text x="50%" y="42%" dominant-baseline="middle" text-anchor="middle" '
        f'font-size="14" fill="#475569" font-family="sans-serif">{safe_t}</text>'
        f'<text x="50%" y="58%" dominant-baseline="middle" text-anchor="middle" '
        f'font-size="12" fill="#64748b" font-family="monospace">{safe_s}</text>'
        "</svg>"
    )


def _smiles_to_svg_rdkit(smiles: str, width: int, height: int) -> str:
    from rdkit import Chem
    from rdkit.Chem.Draw import rdMolDraw2D

    mol = Chem.MolFromSmiles(smiles.strip())
    if mol is None:
        raise ValueError("invalid SMILES")
    drawer = rdMolDraw2D.MolDraw2DSVG(width, height)
    drawer.DrawMolecule(mol)
    drawer.FinishDrawing()
    return drawer.GetDrawingText()


class ChemistryMoleculePlugin(PrimeBrushPlugin):
    @property
    def type_names(self) -> frozenset[str]:
        return frozenset({"chemistry_molecule"})

    def parse_block(self, block: dict) -> PrimeBrushDoc:
        return ChemistryMoleculeModel.model_validate(block)

    def render_doc(self, doc: PrimeBrushDoc, *, seed: int | None) -> str:
        assert isinstance(doc, ChemistryMoleculeModel)
        w, h, _ = normalize_canvas(doc.canvas if hasattr(doc, "canvas") else None)
        wi, hi = int(w), int(h)
        if doc.notation != "SMILES":
            return _svg_placeholder("当前仅支持一种结构式写法（见用户手册）", doc.value or "—", w, h)
        if not (doc.value or "").strip():
            return _svg_placeholder("请填写结构式内容", "", w, h)
        try:
            return _smiles_to_svg_rdkit(doc.value, wi, hi)
        except ImportError:
            return _svg_placeholder("当前显示为示意图占位；安装化学结构式扩展后可显示完整结构", doc.value, w, h)
        except Exception:
            return _svg_placeholder("无法根据当前内容生成示意图", doc.value, w, h)
