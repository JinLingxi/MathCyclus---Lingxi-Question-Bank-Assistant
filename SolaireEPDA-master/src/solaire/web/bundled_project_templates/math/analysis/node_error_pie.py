raw = get_rawdata()

points = []
for n in raw.get("node_stats", [])[:12]:
    points.append(
        {
            "label": str(n.get("node_id", "")).split("/")[-1] or str(n.get("node_id", "")),
            "value": float(n.get("error_rate", 0.0)),
        }
    )

RESULT = PieChart(title="知识点错误率占比", data=points)
