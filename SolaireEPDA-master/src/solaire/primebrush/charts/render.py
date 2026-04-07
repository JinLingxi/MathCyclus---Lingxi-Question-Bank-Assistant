from __future__ import annotations

import numpy as np

from solaire.primebrush.common.style import merge_style
from solaire.primebrush.common.svg_util import escape_text, svg_root
from solaire.primebrush.common.models import ChartModel


def render_chart_svg(
    model: ChartModel,
    width: float,
    height: float,
    _rng: np.random.Generator,
) -> str:
    style = merge_style(model.style)
    fs = style.font_size or 11.0
    ff = style.font_family or "sans-serif"
    sw = style.stroke_width or 1.0

    kind = (model.kind or "bar").lower()
    opts = model.options or {}
    data = model.data or []

    margin_l, margin_r = 52.0, 20.0
    margin_t, margin_b = 28.0, 52.0
    plot_w = width - margin_l - margin_r
    plot_h = height - margin_t - margin_b

    parts: list[str] = []

    if kind == "bar":
        labels = [str(row.get("label", "")) for row in data]
        values = [float(row.get("value", 0.0)) for row in data]
        errors = [float(row["error"]) if row.get("error") is not None else None for row in data]

        y_rng = opts.get("y_range")
        if y_rng and len(y_rng) == 2:
            y_min, y_max = float(y_rng[0]), float(y_rng[1])
        else:
            vmax = max(values) if values else 1.0
            emax = max((e for e in errors if e is not None), default=0.0)
            y_min, y_max = 0.0, max(vmax + emax, 1.0) * 1.1

        n = max(len(labels), 1)
        bar_w_frac = float(opts.get("bar_width", 0.6))
        gap = plot_w / n
        bar_w = gap * bar_w_frac

        # Academic grayscale
        fills = ["#333", "#666", "#999", "#444", "#777"]

        def y_to_px(yv: float) -> float:
            return margin_t + (y_max - yv) / (y_max - y_min) * plot_h

        # Grid
        for k in range(5):
            gy = y_min + (y_max - y_min) * k / 4
            ypx = y_to_px(gy)
            parts.append(
                f'<line x1="{margin_l:.2f}" y1="{ypx:.2f}" x2="{width - margin_r:.2f}" y2="{ypx:.2f}" stroke="#ccc" stroke-width="0.5"/>'
            )

        parts.append(
            f'<line x1="{margin_l:.2f}" y1="{y_to_px(y_min):.2f}" x2="{margin_l:.2f}" y2="{y_to_px(y_max):.2f}" stroke="#222" stroke-width="{sw:.2f}"/>'
        )
        parts.append(
            f'<line x1="{margin_l:.2f}" y1="{y_to_px(y_min):.2f}" x2="{width - margin_r:.2f}" y2="{y_to_px(y_min):.2f}" stroke="#222" stroke-width="{sw:.2f}"/>'
        )

        for i, (lab, val, err) in enumerate(zip(labels, values, errors, strict=True)):
            cx = margin_l + gap * i + (gap - bar_w) / 2
            x1, x2 = cx, cx + bar_w
            yb = y_to_px(y_min)
            yt = y_to_px(val)
            fill = fills[i % len(fills)]
            parts.append(
                f'<rect x="{x1:.2f}" y="{yt:.2f}" width="{bar_w:.2f}" height="{yb - yt:.2f}" fill="{fill}" stroke="#111" stroke-width="0.5"/>'
            )
            if opts.get("show_error") and err is not None and err > 0:
                ym = y_to_px(val + err)
                xm = (x1 + x2) / 2
                parts.append(
                    f'<line x1="{xm:.2f}" y1="{yt:.2f}" x2="{xm:.2f}" y2="{ym:.2f}" stroke="#111" stroke-width="1.2"/>'
                )
                parts.append(
                    f'<line x1="{xm - 4:.2f}" y1="{ym:.2f}" x2="{xm + 4:.2f}" y2="{ym:.2f}" stroke="#111" stroke-width="1.2"/>'
                )
            if opts.get("show_value"):
                parts.append(
                    f'<text x="{(x1 + x2) / 2:.2f}" y="{yt - 4:.2f}" font-size="{fs * 0.85:.1f}" font-family="{escape_text(ff)}" '
                    f'text-anchor="middle" fill="#111">{val:.0f}</text>'
                )
            parts.append(
                f'<text x="{(x1 + x2) / 2:.2f}" y="{height - margin_b + 16:.2f}" font-size="{fs * 0.85:.1f}" font-family="{escape_text(ff)}" '
                f'text-anchor="middle" fill="#111">{escape_text(lab)}</text>'
            )

        xl = opts.get("x_label") or ""
        yl = opts.get("y_label") or ""
        if xl:
            parts.append(
                f'<text x="{width / 2:.2f}" y="{height - 10:.2f}" font-size="{fs:.1f}" font-family="{escape_text(ff)}" text-anchor="middle" fill="#111">{escape_text(str(xl))}</text>'
            )
        if yl:
            parts.append(
                f'<text x="14" y="{(margin_t + height - margin_b) / 2:.2f}" font-size="{fs:.1f}" font-family="{escape_text(ff)}" '
                f'text-anchor="middle" fill="#111" transform="rotate(-90 14 {(margin_t + height - margin_b) / 2:.2f})">{escape_text(str(yl))}</text>'
            )

    elif kind == "line":
        labels = [str(row.get("label", "")) for row in data]
        values = [float(row.get("value", 0.0)) for row in data]
        n = max(len(labels), 1)
        margin_l2, margin_r2 = 52.0, 20.0
        margin_t2, margin_b2 = 28.0, 52.0
        pw = width - margin_l2 - margin_r2
        ph = height - margin_t2 - margin_b2
        y_rng = opts.get("y_range")
        if y_rng and len(y_rng) == 2:
            y_min, y_max = float(y_rng[0]), float(y_rng[1])
        else:
            y_min, y_max = 0.0, max(values) * 1.1 if values else 1.0

        def x_to_px(i: int) -> float:
            return margin_l2 + (i / max(n - 1, 1)) * pw

        def y_to_px2(yv: float) -> float:
            return margin_t2 + (y_max - yv) / (y_max - y_min) * ph

        pts = [f"{x_to_px(i):.2f},{y_to_px2(v):.2f}" for i, v in enumerate(values)]
        if len(pts) >= 2:
            path_d = "M " + " L ".join(pts)
            parts.append(f'<path d="{path_d}" fill="none" stroke="#333" stroke-width="2"/>')
        for i, lab in enumerate(labels):
            parts.append(
                f'<text x="{x_to_px(i):.2f}" y="{height - 18:.2f}" font-size="{fs * 0.8:.1f}" font-family="{escape_text(ff)}" text-anchor="middle" fill="#111">{escape_text(lab)}</text>'
            )
    else:
        parts.append(
            f'<text x="{width / 2:.2f}" y="{height / 2:.2f}" font-size="{fs:.1f}" text-anchor="middle" fill="#888">kind {escape_text(kind)} not implemented</text>'
        )

    inner = "\n".join(parts)
    return svg_root(width, height, inner)
