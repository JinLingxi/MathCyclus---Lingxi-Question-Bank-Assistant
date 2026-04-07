from __future__ import annotations

import math
from typing import Any

import numpy as np

from solaire.primebrush.geometry import euclid
from solaire.primebrush.geometry.result import GeometrySolveResult


def _min_angle_degrees(a: np.ndarray, b: np.ndarray, c: np.ndarray) -> float:
    """Minimum angle at the three vertices (degrees)."""

    def ang_at(p: np.ndarray, q: np.ndarray, r: np.ndarray) -> float:
        v1 = q - p
        v2 = r - p
        n1 = np.linalg.norm(v1)
        n2 = np.linalg.norm(v2)
        if n1 < 1e-9 or n2 < 1e-9:
            return 0.0
        cos_t = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
        return math.degrees(math.acos(cos_t))

    return min(
        ang_at(a, b, c),
        ang_at(b, a, c),
        ang_at(c, a, b),
    )


def _random_triangle(
    w: float,
    h: float,
    rng: np.random.Generator,
    min_angle: float,
    margin: float = 12.0,
    max_tries: int = 5000,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    lo_x, hi_x = margin, w - margin
    lo_y, hi_y = margin, h - margin
    for _ in range(max_tries):
        ax, ay = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
        bx, by = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
        cx, cy = rng.uniform(lo_x, hi_x), rng.uniform(lo_y, hi_y)
        a = np.array([ax, ay])
        b = np.array([bx, by])
        c = np.array([cx, cy])
        if _min_angle_degrees(a, b, c) >= min_angle:
            return a, b, c
    raise ValueError("could not sample triangle satisfying min_angle; try different seed or relax min_angle")


def _as_vec(points: dict[str, tuple[float, float]], name: str) -> np.ndarray:
    p = points[str(name)]
    return np.array([p[0], p[1]], dtype=np.float64)


def _segment_far(
    origin: np.ndarray,
    direction: np.ndarray,
    width: float,
    height: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Two endpoints along line origin + t * direction, long enough for the canvas."""
    d = np.asarray(direction, dtype=np.float64)
    n = float(np.linalg.norm(d))
    if n < 1e-12:
        raise ValueError("degenerate direction for line")
    u = d / n
    span = math.hypot(width, height) * 1.2
    p1 = origin - span * u
    p2 = origin + span * u
    return p1, p2


def _append_segment_drawable(
    drawables: list[dict[str, Any]],
    p1: np.ndarray,
    p2: np.ndarray,
    item: dict[str, Any],
    default_style: str = "dashed",
) -> None:
    drawables.append(
        {
            "kind": "segment",
            "x1": float(p1[0]),
            "y1": float(p1[1]),
            "x2": float(p2[0]),
            "y2": float(p2[1]),
            "style": (item.get("style") or default_style).lower(),
            "id": item.get("id"),
            "label": item.get("label"),
        }
    )


def _circle_spec_radius(spec: dict[str, Any], points: dict[str, tuple[float, float]]) -> tuple[np.ndarray, float]:
    o = _as_vec(points, str(spec["center"]))
    r = euclid.resolve_circle_radius(spec, points)
    return o, r


def solve_geometry(
    constructions: list[dict[str, Any]],
    width: float,
    height: float,
    rng: np.random.Generator,
) -> GeometrySolveResult:
    """Resolve named points and collect drawable primitives."""
    points: dict[str, tuple[float, float]] = {}
    drawables: list[dict[str, Any]] = []

    for item in constructions:
        op = item.get("op")
        if op == "triangle":
            nodes = item["nodes"]
            attr = item.get("attr") or {}
            t = (attr.get("type") or "random").lower()
            min_angle = float(attr.get("min_angle", 25))
            if t == "random":
                a, b, c = _random_triangle(width, height, rng, min_angle)
            else:
                raise ValueError(f"unknown triangle attr.type: {t!r}")
            if len(nodes) != 3:
                raise ValueError("triangle requires exactly 3 nodes")
            for name, pt in zip(nodes, (a, b, c), strict=True):
                points[str(name)] = (float(pt[0]), float(pt[1]))

        elif op == "in_line":
            pid = item["id"]
            src = item["source"]
            params = float(item.get("params", 0.5))
            a = _as_vec(points, src[0])
            b = _as_vec(points, src[1])
            p = a + params * (b - a)
            points[str(pid)] = (float(p[0]), float(p[1]))

        elif op == "line":
            src = item["source"]
            for n in src:
                if str(n) not in points:
                    raise ValueError(f"line references unknown point {n!r}")

        elif op == "foot":
            pid = str(item["id"])
            p = _as_vec(points, str(item["point"]))
            a = _as_vec(points, item["line"][0])
            b = _as_vec(points, item["line"][1])
            h = euclid.foot_on_line(p, a, b)
            points[pid] = (float(h[0]), float(h[1]))

        elif op == "reflection":
            pid = str(item["id"])
            p = _as_vec(points, str(item["point"]))
            a = _as_vec(points, item["line"][0])
            b = _as_vec(points, item["line"][1])
            h = euclid.foot_on_line(p, a, b)
            rp = 2.0 * h - p
            points[pid] = (float(rp[0]), float(rp[1]))

        elif op == "perpendicular":
            p = _as_vec(points, str(item["through"]))
            a = _as_vec(points, item["to"][0])
            b = _as_vec(points, item["to"][1])
            ab = b - a
            if float(np.linalg.norm(ab)) < 1e-9:
                raise ValueError("perpendicular: degenerate line")
            direction = np.array([-ab[1], ab[0]], dtype=np.float64)
            p1, p2 = _segment_far(p, direction, width, height)
            _append_segment_drawable(drawables, p1, p2, item)

        elif op == "parallel":
            p = _as_vec(points, str(item["through"]))
            a = _as_vec(points, item["to"][0])
            b = _as_vec(points, item["to"][1])
            direction = b - a
            if float(np.linalg.norm(direction)) < 1e-9:
                raise ValueError("parallel: degenerate direction")
            p1, p2 = _segment_far(p, direction, width, height)
            _append_segment_drawable(drawables, p1, p2, item)

        elif op == "intersection_lines":
            pid = str(item["id"])
            l1 = item["line1"]
            l2 = item["line2"]
            a, b = _as_vec(points, l1[0]), _as_vec(points, l1[1])
            c, d = _as_vec(points, l2[0]), _as_vec(points, l2[1])
            inter = euclid.intersect_lines_infinite(a, b, c, d)
            if inter is None:
                raise ValueError("intersection_lines: parallel lines")
            points[pid] = (float(inter[0]), float(inter[1]))

        elif op == "intersection_line_circle":
            pid = str(item["id"])
            la = _as_vec(points, item["line"][0])
            lb = _as_vec(points, item["line"][1])
            spec = {k: item[k] for k in ("center", "radius", "through", "radius_from") if k in item}
            if "center" not in spec:
                raise ValueError("intersection_line_circle needs circle center (and radius / through / radius_from)")
            o, r = _circle_spec_radius(spec, points)
            pts = euclid.line_circle_intersections(la, lb, o, r)
            if not pts:
                raise ValueError("intersection_line_circle: no intersection")
            which = int(item.get("which", 0))
            if which < 0 or which >= len(pts):
                raise ValueError(f"intersection_line_circle: which={which} but got {len(pts)} point(s)")
            pt = pts[which]
            points[pid] = (float(pt[0]), float(pt[1]))

        elif op == "intersection_circles":
            c1 = item["circle1"]
            c2 = item["circle2"]
            o1, r1 = _circle_spec_radius(c1, points)
            o2, r2 = _circle_spec_radius(c2, points)
            pts = euclid.circle_circle_intersections(o1, r1, o2, r2)
            if not pts:
                raise ValueError("intersection_circles: no intersection (check radii and centers)")
            ids = item.get("ids")
            if not ids:
                raise ValueError("intersection_circles requires ids: [P, Q] or [P]")
            ids = [str(x) for x in ids]
            if len(pts) == 1:
                if len(ids) != 1:
                    raise ValueError("intersection_circles: tangent case yields one point; use ids with one name")
                points[ids[0]] = (float(pts[0][0]), float(pts[0][1]))
            else:
                if len(ids) != 2:
                    raise ValueError("intersection_circles: two intersections require ids: [P, Q]")
                points[ids[0]] = (float(pts[0][0]), float(pts[0][1]))
                points[ids[1]] = (float(pts[1][0]), float(pts[1][1]))

        elif op == "perpendicular_bisector":
            src = item["source"]
            if len(src) != 2:
                raise ValueError("perpendicular_bisector requires source: [A, B]")
            a = _as_vec(points, src[0])
            b = _as_vec(points, src[1])
            mid = (a + b) / 2.0
            ab = b - a
            if float(np.linalg.norm(ab)) < 1e-9:
                raise ValueError("perpendicular_bisector: segment has zero length")
            direction = np.array([-ab[1], ab[0]], dtype=np.float64)
            p1, p2 = _segment_far(mid, direction, width, height)
            _append_segment_drawable(drawables, p1, p2, item)

        elif op == "angle_bisector":
            src = item.get("source") or {}
            vertex = str(src.get("vertex"))
            arms = src.get("arms")
            if not arms or len(arms) != 2:
                raise ValueError("angle_bisector requires source: { vertex: B, arms: [A, C] }")
            pa = _as_vec(points, arms[0])
            pb = _as_vec(points, vertex)
            pc = _as_vec(points, arms[1])
            ba = pa - pb
            bc = pc - pb
            n1 = float(np.linalg.norm(ba))
            n2 = float(np.linalg.norm(bc))
            if n1 < 1e-9 or n2 < 1e-9:
                raise ValueError("angle_bisector: degenerate arm")
            u1 = ba / n1
            u2 = bc / n2
            direction = u1 + u2
            n = float(np.linalg.norm(direction))
            if n < 1e-9:
                direction = np.array([-u1[1], u1[0]], dtype=np.float64)
            else:
                direction = direction / n
            p1, p2 = _segment_far(pb, direction, width, height)
            _append_segment_drawable(drawables, p1, p2, item)

        elif op == "circle":
            center = str(item["center"])
            if center not in points:
                raise ValueError(f"circle: unknown center {center!r}")
            c = _as_vec(points, center)
            r = euclid.resolve_circle_radius(item, points)
            drawables.append(
                {
                    "kind": "circle",
                    "cx": float(c[0]),
                    "cy": float(c[1]),
                    "r": r,
                    "style": (item.get("style") or "solid").lower(),
                    "id": item.get("id"),
                    "fill": item.get("fill"),
                }
            )

        elif op == "ellipse":
            center = str(item["center"])
            if center not in points:
                raise ValueError(f"ellipse: unknown center {center!r}")
            c = _as_vec(points, center)
            rx = float(item.get("rx", 0))
            ry = float(item.get("ry", 0))
            if rx <= 0 or ry <= 0:
                raise ValueError("ellipse: rx and ry must be positive")
            rot = float(item.get("rotation_deg", item.get("rotate_deg", 0)))
            drawables.append(
                {
                    "kind": "ellipse",
                    "cx": float(c[0]),
                    "cy": float(c[1]),
                    "rx": rx,
                    "ry": ry,
                    "rotation_deg": rot,
                    "style": (item.get("style") or "solid").lower(),
                    "id": item.get("id"),
                    "fill": item.get("fill"),
                }
            )

        else:
            raise ValueError(f"unknown construction op: {op!r}")

    return GeometrySolveResult(points=points, drawables=drawables)
