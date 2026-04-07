"""Optional web search (Tavily) for teaching research."""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from solaire.agent_layer.models import InvocationContext, ToolResult


def tool_web_search(ctx: InvocationContext, args: dict[str, Any]) -> ToolResult:
    q = str(args.get("query") or "").strip()
    if not q:
        return ToolResult(status="failed", error_code="invalid_arguments", error_message="query 必填")
    try:
        max_results = int(args.get("max_results") or 5)
    except (TypeError, ValueError):
        max_results = 5
    max_results = max(1, min(max_results, 10))

    api_key = (
        os.environ.get("SOLAIRE_TAVILY_API_KEY")
        or os.environ.get("TAVILY_API_KEY")
        or os.environ.get("SOLAIRE_SEARCH_API_KEY")
        or ""
    ).strip()
    if not api_key:
        return ToolResult(
            status="failed",
            error_code="not_configured",
            error_message="未配置联网检索：请在环境中设置 SOLAIRE_TAVILY_API_KEY（或 TAVILY_API_KEY）。",
        )

    body = json.dumps(
        {
            "api_key": api_key,
            "query": q,
            "max_results": max_results,
            "search_depth": "basic",
        },
        ensure_ascii=False,
    ).encode("utf-8")
    req = urllib.request.Request(
        "https://api.tavily.com/search",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return ToolResult(
            status="failed",
            error_code="http_error",
            error_message=f"检索服务返回错误：{e.code}",
        )
    except (OSError, json.JSONDecodeError) as e:
        return ToolResult(status="failed", error_code="network_error", error_message=str(e))

    results: list[dict[str, Any]] = []
    for item in raw.get("results") or []:
        if not isinstance(item, dict):
            continue
        results.append(
            {
                "title": item.get("title") or "",
                "url": item.get("url") or "",
                "snippet": item.get("content") or item.get("snippet") or "",
            }
        )
    return ToolResult(
        status="succeeded",
        data={"query": q, "results": results, "answer": raw.get("answer")},
    )
