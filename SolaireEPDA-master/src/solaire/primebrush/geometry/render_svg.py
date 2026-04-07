from __future__ import annotations

from solaire.primebrush.common.style import merge_style
from solaire.primebrush.common.svg_util import escape_text, svg_root
from solaire.primebrush.geometry.solver import solve_geometry
from solaire.primebrush.common.models import Geometry2DModel

import numpy as np


def _seg(ax: float, ay: float, bx: float, by: float) -> str:
    return f'<line x1="{ax:.2f}" y1="{ay:.2f}" x2="{bx:.2f}" y2="{by:.2f}"'


def render_geometry_svg(
    model: Geometry2DModel,
    width: float,
    height: float,
    rng: np.random.Generator,
) -> str:
    style = merge_style(model.style)
    sw = style.stroke_width or 1.0
    fs = style.font_size or 12.0
    ff = style.font_family or "sans-serif"

    result = solve_geometry(model.constructions, width, height, rng)
    pts = result.points
    constructions = model.constructions

    parts: list[str] = []

    tri_nodes: list[str] = []
    in_line_ids: set[str] = set()
    for item in constructions:
        if item.get("op") == "triangle":
            tri_nodes = [str(x) for x in item["nodes"]]
        elif item.get("op") == "in_line":
            in_line_ids.add(str(item["id"]))

    # Draw triangle edges if we have A,B,C from first triangle
    if tri_nodes and len(tri_nodes) == 3:
        a, b, c = tri_nodes
        for u, v in ((a, b), (b, c), (c, a)):
            x1, y1 = pts[u]
            x2, y2 = pts[v]
            parts.append(
                f'{_seg(x1, y1, x2, y2)} stroke="#222" stroke-width="{sw:.2f}" fill="none"/>'
            )

    # Draw construction lines (classic line op)
    for item in constructions:
        if item.get("op") != "line":
            continue
        src = [str(x) for x in item["source"]]
        st = (item.get("style") or "solid").lower()
        dash = ' stroke-dasharray="6,4"' if st == "dashed" else ""
        x1, y1 = pts[src[0]]
        x2, y2 = pts[src[1]]
        parts.append(
            f'{_seg(x1, y1, x2, y2)} stroke="#444" stroke-width="{sw:.2f}"{dash} fill="none"/>'
        )
        lab = item.get("label")
        if isinstance(lab, dict) and "text" in lab:
            t = str(lab["text"])
            pos = float(lab.get("pos", 0.5))
            mx = x1 + pos * (x2 - x1)
            my = y1 + pos * (y2 - y1)
            parts.append(
                f'<text x="{mx:.2f}" y="{my:.2f}" font-size="{fs:.1f}" font-family="{escape_text(ff)}" '
                f'fill="#111" text-anchor="middle" dominant-baseline="middle">{escape_text(t)}</text>'
            )

    # New ops: perpendicular bisector, angle bisector, circle, ellipse
    for d in result.drawables:
        kind = d["kind"]
        if kind == "segment":
            st = (d.get("style") or "dashed").lower()
            dash = ' stroke-dasharray="6,4"' if st == "dashed" else ""
            x1, y1, x2, y2 = d["x1"], d["y1"], d["x2"], d["y2"]
            parts.append(
                f'{_seg(x1, y1, x2, y2)} stroke="#2d6a4f" stroke-width="{sw:.2f}"{dash} fill="none"/>'
            )
            lab = d.get("label")
            if isinstance(lab, dict) and "text" in lab:
                t = str(lab["text"])
                pos = float(lab.get("pos", 0.5))
                mx = x1 + pos * (x2 - x1)
                my = y1 + pos * (y2 - y1)
                parts.append(
                    f'<text x="{mx:.2f}" y="{my:.2f}" font-size="{fs * 0.95:.1f}" font-family="{escape_text(ff)}" '
                    f'fill="#1b4332" text-anchor="middle" dominant-baseline="middle">{escape_text(t)}</text>'
                )
        elif kind == "circle":
            cx, cy, r = d["cx"], d["cy"], d["r"]
            fill = d.get("fill")
            fill_attr = ' fill="none"' if fill is None else f' fill="{escape_text(str(fill))}"'
            parts.append(
                f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" stroke="#1d3557" stroke-width="{sw:.2f}"{fill_attr}/>'
            )
        elif kind == "ellipse":
            cx, cy = d["cx"], d["cy"]
            rx, ry = d["rx"], d["ry"]
            rot = float(d.get("rotation_deg", 0))
            fill = d.get("fill")
            fill_attr = ' fill="none"' if fill is None else f' fill="{escape_text(str(fill))}"'
            tf = ""
            if abs(rot) > 1e-6:
                tf = f' transform="rotate({rot:.2f} {cx:.2f} {cy:.2f})"'
            parts.append(
                f'<ellipse cx="{cx:.2f}" cy="{cy:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
                f'stroke="#6a4c93" stroke-width="{sw:.2f}"{fill_attr}{tf}/>'
            )

    # Vertices and in_line points: small circles + optional labels
    for item in constructions:
        if item.get("op") == "triangle":
            for n in item["nodes"]:
                n = str(n)
                x, y = pts[n]
                parts.append(
                    f'<circle cx="{x:.2f}" cy="{y:.2f}" r="3" fill="#111"/>'
                )
                hint = (item.get("label") or {}).get(n)
                if hint:
                    ox, oy = _label_offset(str(hint), 14)
                    parts.append(
                        f'<text x="{x + ox:.2f}" y="{y + oy:.2f}" font-size="{fs:.1f}" '
                        f'font-family="{escape_text(ff)}" fill="#111">{escape_text(n)}</text>'
                    )
                else:
                    parts.append(
                        f'<text x="{x + 8:.2f}" y="{y - 8:.2f}" font-size="{fs:.1f}" '
                        f'font-family="{escape_text(ff)}" fill="#111">{escape_text(n)}</text>'
                    )
        elif item.get("op") == "in_line":
            pid = str(item["id"])
            x, y = pts[pid]
            parts.append(
                f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.5" fill="#c00"/>'
            )
            lab = item.get("label")
            if lab:
                parts.append(
                    f'<text x="{x + 8:.2f}" y="{y - 8:.2f}" font-size="{fs:.1f}" '
                    f'font-family="{escape_text(ff)}" fill="#111">{escape_text(str(lab))}</text>'
                )

    # Other constructed points (交点、垂足等)
    tri_set = set(tri_nodes)
    for name, (x, y) in pts.items():
        if name in tri_set or name in in_line_ids:
            continue
        parts.append(
            f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2.8" fill="#0d47a1" stroke="#111" stroke-width="0.4"/>'
        )
        parts.append(
            f'<text x="{x + 7:.2f}" y="{y - 7:.2f}" font-size="{fs * 0.9:.1f}" '
            f'font-family="{escape_text(ff)}" fill="#111">{escape_text(name)}</text>'
        )

    inner = "\n".join(parts)
    return svg_root(width, height, inner)


def _label_offset(hint: str, d: float) -> tuple[float, float]:
    h = hint.lower()
    if "top" in h:
        return 0.0, -d
    if "bottom_left" in h:
        return -d, d
    if "bottom_right" in h:
        return d, d
    return 8.0, -8.0
