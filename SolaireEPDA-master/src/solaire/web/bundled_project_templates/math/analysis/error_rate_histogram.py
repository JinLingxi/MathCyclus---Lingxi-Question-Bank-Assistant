raw = get_rawdata()

points = []
for q in raw.get("question_stats", [])[:20]:
    if q.get("error_rate") is not None:
        points.append({"label": q.get("header", ""), "value": q.get("error_rate")})

RESULT = HistogramChart(title="题目错误率 Top20", data=points)
