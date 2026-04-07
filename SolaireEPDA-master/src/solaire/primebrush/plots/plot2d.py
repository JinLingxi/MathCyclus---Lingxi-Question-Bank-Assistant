from __future__ import annotations

import math
from typing import Any

import numpy as np

from solaire.primebrush.common.style import merge_style
from solaire.primebrush.common.svg_util import escape_text, svg_root
from solaire.primebrush.plots.expr import eval_expr, eval_expr_scalar
from solaire.primebrush.common.models import Plot2DModel


def _nice_step(span: float, target_ticks: int = 6) -> float:
    """Pick a human-readable tick step for ~target_ticks divisions."""
    if span <= 0:
        return 1.0
    raw = span / max(target_ticks, 1)
    exp = math.floor(math.log10(raw))
    f = raw / (10**exp)
    if f < 1.5:
        nf = 1.0
    elif f < 3.5:
        nf = 2.0
    elif f < 7.5:
        nf = 5.0
    else:
        nf = 10.0
    return nf * (10**exp)


def _tick_values(vmin: float, vmax: float, step: float | None) -> list[float]:
    if vmax < vmin:
        vmin, vmax = vmax, vmin
    if step is None or step <= 0:
        step = _nice_step(vmax - vmin)
    vals: list[float] = []
    x = math.ceil(vmin / step - 1e-12) * step
    guard = 0
    while x <= vmax + 1e-9 * max(abs(vmax), 1.0) and guard < 10000:
        if x + 1e-12 >= vmin and x - 1e-12 <= vmax:
            vals.append(round(x, 12))
        x += step
        guard += 1
    if not vals:
        vals = [vmin, vmax]
    return vals


def _format_tick(v: float) -> str:
    if abs(v - round(v)) < 1e-6 * max(abs(v), 1.0, 1.0):
        return str(int(round(v)))
    s = f"{v:.6g}"
    return s


def render_plot2d_svg(
    model: Plot2DModel,
    width: float,
    height: float,
    rng: np.random.Generator,
) -> str:
    style = merge_style(model.style)
    sw = style.stroke_width or 1.0
    fs = style.font_size or 12.0
    ff = style.font_family or "sans-serif"

    axes = model.axes or {}
    gx = axes.get("x") or {}
    gy = axes.get("y") or {}
    xr = gx.get("range") or [-5.0, 5.0]
    yr = gy.get("range") or [-2.0, 2.0]
    x_min, x_max = float(xr[0]), float(xr[1])
    y_min, y_max = float(yr[0]), float(yr[1])

    # Extra left margin for y-axis tick number labels
    margin_l, margin_r = 56.0, 24.0
    margin_t, margin_b = 24.0, 52.0
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    def x_to_px(xv: float) -> float:
        return margin_l + (xv - x_min) / (x_max - x_min) * plot_w

    def y_to_px(yv: float) -> float:
        return margin_t + (y_max - yv) / (y_max - y_min) * plot_h

    parts: list[str] = []

    if axes.get("grid"):
        nx = max(2, int(width / 40))
        for i in range(nx + 1):
            gx_v = x_min + (x_max - x_min) * i / nx
            xpx = x_to_px(gx_v)
            parts.append(
                f'<line x1="{xpx:.2f}" y1="{margin_t:.2f}" x2="{xpx:.2f}" y2="{height - margin_b:.2f}" '
                f'stroke="#ddd" stroke-width="0.5"/>'
            )
        ny = max(2, int(height / 40))
        for j in range(ny + 1):
            gy_v = y_min + (y_max - y_min) * j / ny
            ypx = y_to_px(gy_v)
            parts.append(
                f'<line x1="{margin_l:.2f}" y1="{ypx:.2f}" x2="{width - margin_r:.2f}" y2="{ypx:.2f}" '
                f'stroke="#ddd" stroke-width="0.5"/>'
            )

    # Plot area border / axes
    parts.append(
        f'<line x1="{margin_l:.2f}" y1="{height - margin_b:.2f}" x2="{width - margin_r:.2f}" y2="{height - margin_b:.2f}" '
        f'stroke="#222" stroke-width="{sw:.2f}"/>'
    )
    parts.append(
        f'<line x1="{margin_l:.2f}" y1="{margin_t:.2f}" x2="{margin_l:.2f}" y2="{height - margin_b:.2f}" '
        f'stroke="#222" stroke-width="{sw:.2f}"/>'
    )

    # Axis tick marks + numeric labels
    tick_len = 5.0
    tick_fs = max(fs * 0.72, 8.0)
    x_axis_y = height - margin_b
    y_axis_x = margin_l

    x_step = gx.get("ticks")
    if x_step is not None:
        x_step = float(x_step)
    else:
        x_step = None
    y_step = gy.get("ticks")
    if y_step is not None:
        y_step = float(y_step)
    else:
        y_step = None

    for xv in _tick_values(x_min, x_max, x_step):
        xpx = x_to_px(xv)
        parts.append(
            f'<line x1="{xpx:.2f}" y1="{x_axis_y:.2f}" x2="{xpx:.2f}" y2="{x_axis_y + tick_len:.2f}" '
            f'stroke="#222" stroke-width="{max(sw * 0.8, 0.8):.2f}"/>'
        )
        parts.append(
            f'<text x="{xpx:.2f}" y="{x_axis_y + tick_len + 12:.2f}" font-size="{tick_fs:.1f}" font-family="{escape_text(ff)}" '
            f'text-anchor="middle" fill="#333">{escape_text(_format_tick(xv))}</text>'
        )

    for yv in _tick_values(y_min, y_max, y_step):
        ypx = y_to_px(yv)
        parts.append(
            f'<line x1="{y_axis_x:.2f}" y1="{ypx:.2f}" x2="{y_axis_x - tick_len:.2f}" y2="{ypx:.2f}" '
            f'stroke="#222" stroke-width="{max(sw * 0.8, 0.8):.2f}"/>'
        )
        parts.append(
            f'<text x="{y_axis_x - tick_len - 4:.2f}" y="{ypx + 4:.2f}" font-size="{tick_fs:.1f}" font-family="{escape_text(ff)}" '
            f'text-anchor="end" fill="#333">{escape_text(_format_tick(yv))}</text>'
        )

    xl = gx.get("label") or "x"
    yl = gy.get("label") or "y"
    parts.append(
        f'<text x="{width / 2:.2f}" y="{height - 6:.2f}" font-size="{fs:.1f}" font-family="{escape_text(ff)}" '
        f'text-anchor="middle" fill="#111">{escape_text(str(xl))}</text>'
    )
    mid_y = (margin_t + height - margin_b) / 2
    parts.append(
        f'<text x="12" y="{mid_y:.2f}" font-size="{fs:.1f}" font-family="{escape_text(ff)}" '
        f'text-anchor="middle" fill="#111" transform="rotate(-90 12 {mid_y:.2f})">{escape_text(str(yl))}</text>'
    )

    curves: list[dict[str, Any]] = []
    for el in model.elements:
        if el.get("op") == "point_on_f":
            continue
        if "f" in el:
            curves.append(el)

    colors = ["#1a5fb4", "#c01c28", "#26a269", "#e5a50a"]
    for idx, el in enumerate(curves):
        fstr = str(el["f"])
        dom = el.get("domain") or [x_min, x_max]
        d0, d1 = float(dom[0]), float(dom[1])
        n = 200
        xs = np.linspace(d0, d1, n)
        ys = eval_expr(fstr, xs)
        pts = []
        for i in range(n):
            xv, yv = float(xs[i]), float(ys[i])
            pts.append(f"{x_to_px(xv):.2f},{y_to_px(yv):.2f}")
        if len(pts) < 2:
            continue
        color = el.get("color") or colors[idx % len(colors)]
        wline = float(el.get("width") or 2)
        st = (el.get("style") or "solid").lower()
        dash = ' stroke-dasharray="4,3"' if st == "dotted" else ""
        path_d = "M " + " L ".join(pts)
        parts.append(
            f'<path d="{path_d}" fill="none" stroke="{escape_text(str(color))}" stroke-width="{wline:.2f}"{dash}/>'
        )

    for el in model.elements:
        if el.get("op") != "point_on_f":
            continue
        fid = int(el.get("f_id", 0))
        x0 = float(el["x"])
        if fid < 0 or fid >= len(curves):
            raise ValueError(f"point_on_f f_id {fid} out of range (have {len(curves)} curves)")
        fstr = str(curves[fid]["f"])
        y0 = eval_expr_scalar(fstr, x0)
        px, py = x_to_px(x0), y_to_px(y0)
        parts.append(f'<circle cx="{px:.2f}" cy="{py:.2f}" r="4" fill="#c00"/>')
        if el.get("show_projection"):
            parts.append(
                f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{px:.2f}" y2="{height - margin_b:.2f}" stroke="#888" stroke-dasharray="4,3" stroke-width="1"/>'
            )
            parts.append(
                f'<line x1="{px:.2f}" y1="{py:.2f}" x2="{margin_l:.2f}" y2="{py:.2f}" stroke="#888" stroke-dasharray="4,3" stroke-width="1"/>'
            )
        lab = el.get("label")
        if lab:
            parts.append(
                f'<text x="{px + 8:.2f}" y="{py - 8:.2f}" font-size="{fs * 0.9:.1f}" font-family="{escape_text(ff)}" fill="#111">{escape_text(str(lab))}</text>'
            )

    inner = "\n".join(parts)
    return svg_root(width, height, inner)
