raw = get_rawdata()

bands = {"90+": 0, "80-89": 0, "70-79": 0, "60-69": 0, "<60": 0}
for s in raw.get("student_stats", []):
    ratio = float(s.get("score_ratio", 0.0)) * 100.0
    if ratio >= 90:
        bands["90+"] += 1
    elif ratio >= 80:
        bands["80-89"] += 1
    elif ratio >= 70:
        bands["70-79"] += 1
    elif ratio >= 60:
        bands["60-69"] += 1
    else:
        bands["<60"] += 1

RESULT = HistogramChart(
    title="学生分层人数",
    data=[{"label": k, "value": v} for k, v in bands.items()],
)
