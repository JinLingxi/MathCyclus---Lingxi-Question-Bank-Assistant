from __future__ import annotations

import math
from typing import Any


class BaseChart:
    chart_type = "base"

    def __init__(self, *, title: str, data: list[dict[str, Any]]) -> None:
        if not isinstance(title, str) or not title.strip():
            raise ValueError("title must be non-empty string")
        if not isinstance(data, list):
            raise ValueError("data must be list of dict")
        self.title = title
        self.data = data

    def _series_points(self) -> list[dict[str, float | str]]:
        points: list[dict[str, float | str]] = []
        for i, row in enumerate(self.data):
            if not isinstance(row, dict):
                raise ValueError(f"data[{i}] must be object")
            if "label" not in row or "value" not in row:
                raise ValueError(f"data[{i}] needs label and value")
            points.append({"label": str(row["label"]), "value": float(row["value"])})
        return points

    def to_payload(self) -> dict[str, Any]:
        raise NotImplementedError

    def get_picture(self, width: int = 640, height: int = 320) -> str:
        raise NotImplementedError


class HistogramChart(BaseChart):
    chart_type = "bar"

    def to_payload(self) -> dict[str, Any]:
        sid = "script_histogram_series"
        return {
            "summary": {"title": self.title, "status": "succeeded"},
            "tables": [],
            "chart_specs": [
                {
                    "id": "script_histogram",
                    "type": "bar",
                    "title": self.title,
                    "series_id": sid,
                    "x": "label",
                    "y": "value",
                }
            ],
            "series": [{"id": sid, "points": self._series_points()}],
            "logs": [],
            "warnings": [],
        }

    def get_picture(self, width: int = 640, height: int = 320) -> str:
        points = self._series_points()
        if not points:
            return "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='320'></svg>"
        max_v = max(abs(float(p["value"])) for p in points) or 1.0
        bar_w = max(8, (width - 80) // max(1, len(points)))
        x = 40
        bars: list[str] = []
        labels: list[str] = []
        for p in points:
            v = float(p["value"])
            h = int((v / max_v) * (height - 100))
            y = height - 40 - h
            bars.append(f"<rect x='{x}' y='{y}' width='{bar_w-4}' height='{max(2,h)}' fill='#3b82f6'/>")
            labels.append(f"<text x='{x+2}' y='{height-20}' font-size='10' fill='#334155'>{str(p['label'])[:8]}</text>")
            x += bar_w
        return (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
            "<rect width='100%' height='100%' fill='white'/>"
            f"<text x='16' y='20' font-size='14' fill='#0f172a'>{self.title}</text>"
            f"{''.join(bars)}{''.join(labels)}</svg>"
        )


class PieChart(BaseChart):
    chart_type = "pie"

    def to_payload(self) -> dict[str, Any]:
        sid = "script_pie_series"
        return {
            "summary": {"title": self.title, "status": "succeeded"},
            "tables": [],
            "chart_specs": [
                {
                    "id": "script_pie",
                    "type": "pie",
                    "title": self.title,
                    "series_id": sid,
                    "x": "label",
                    "y": "value",
                }
            ],
            "series": [{"id": sid, "points": self._series_points()}],
            "logs": [],
            "warnings": [],
        }

    def get_picture(self, width: int = 640, height: int = 320) -> str:
        points = self._series_points()
        total = sum(max(0.0, float(p["value"])) for p in points)
        if total <= 0:
            return "<svg xmlns='http://www.w3.org/2000/svg' width='640' height='320'></svg>"
        cx = width // 2
        cy = height // 2 + 8
        r = min(width, height) // 3
        colors = ["#3b82f6", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6", "#06b6d4"]
        start = 0.0
        paths: list[str] = []
        for i, p in enumerate(points):
            val = max(0.0, float(p["value"]))
            if val == 0:
                continue
            ang = (val / total) * 2 * math.pi
            end = start + ang
            x1 = cx + r * math.cos(start)
            y1 = cy + r * math.sin(start)
            x2 = cx + r * math.cos(end)
            y2 = cy + r * math.sin(end)
            large_arc = 1 if ang > math.pi else 0
            d = f"M {cx} {cy} L {x1:.2f} {y1:.2f} A {r} {r} 0 {large_arc} 1 {x2:.2f} {y2:.2f} Z"
            paths.append(f"<path d='{d}' fill='{colors[i % len(colors)]}'/>")
            start = end
        return (
            f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}'>"
            "<rect width='100%' height='100%' fill='white'/>"
            f"<text x='16' y='20' font-size='14' fill='#0f172a'>{self.title}</text>"
            f"{''.join(paths)}</svg>"
        )
