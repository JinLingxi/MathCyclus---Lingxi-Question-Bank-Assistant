raw = get_rawdata()
kg = get_graph()

points = []
for q in raw.get("question_stats", [])[:20]:
    if q.get("error_rate") is not None:
        points.append({"label": q.get("header", ""), "value": q.get("error_rate")})

chart = HistogramChart(title="内置统计重写：题目错误率前20", data=points)
payload = chart.to_payload()
payload["summary"]["student_count"] = raw.get("student_count", 0)
payload["summary"]["question_count"] = raw.get("question_count", 0)
payload["summary"]["graph_node_count"] = len(kg.get("nodes", []))
RESULT = payload
