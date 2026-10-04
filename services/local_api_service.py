"""Small localhost API for AI-assisted draft entry.

The API deliberately exposes draft operations only.  Human approval and
formal question-bank commits stay inside the Streamlit review workflow.
"""

from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

from services.database_service import DEFAULT_DATABASE_PATH, resolve_database_path
from services.import_service import (
    create_manual_entry_drafts,
    find_paper_position_conflict,
    find_question_content_matches,
    find_question_similarity_candidates,
    get_draft_question,
    list_draft_questions,
    list_draft_review_events,
    list_import_batches,
    summarize_batch,
    update_draft_question_fields,
    validate_existing_draft,
)
from services.question_db_service import (
    QuestionListFilters,
    get_question_bundle,
    list_questions,
)
from services.schema_migration_service import apply_pending_migrations, migration_status


API_PREFIX = "/api/v1"
MAX_REQUEST_BYTES = 8 * 1024 * 1024


def _json_value(value: Any) -> Any:
    """Convert SQLite rows and nested values into JSON-safe values."""
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _safe_int(value: Any, default: int = 0, *, minimum: int | None = None, maximum: int | None = None) -> int:
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        result = default
    if minimum is not None:
        result = max(minimum, result)
    if maximum is not None:
        result = min(maximum, result)
    return result


def _query_value(query: dict[str, list[str]], key: str, default: str = "") -> str:
    values = query.get(key) or []
    return str(values[0] if values else default).strip()


def _sanitize_draft_items(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list) or not items:
        raise ValueError("items 必须是非空数组")
    sanitized: list[dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"items[{index - 1}] 必须是对象")
        draft = dict(item)
        # A remote AI client may never pre-approve a draft.  The service layer
        # remains the final gate, but downgrading here makes the contract clear.
        if str(draft.get("review_status") or "") in {"approved", "committed"}:
            draft["review_status"] = "needs_review"
        for field in ("approved_content_hash", "approved_by", "approved_at"):
            draft.pop(field, None)
        sanitized.append(draft)
    return sanitized


class LocalApiHandler(BaseHTTPRequestHandler):
    server_version = "MathCyclusLocalAPI/1.0"
    protocol_version = "HTTP/1.1"

    @property
    def api_server(self) -> "LocalApiServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, format: str, *args: object) -> None:
        print(f"[local-api] {self.address_string()} - {format % args}")

    def _write(self, status: int, payload: Any, *, headers: dict[str, str] | None = None) -> None:
        body = json.dumps(_json_value(payload), ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-MathCyclus-Token")
        self.send_header("Access-Control-Allow-Methods", "GET, PATCH, POST, OPTIONS")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)

    def _error(self, status: int, message: str, *, detail: Any = None) -> None:
        payload: dict[str, Any] = {"error": message}
        if detail is not None:
            payload["detail"] = detail
        self._write(status, payload)

    def _authorize(self, path: str) -> bool:
        if path == "/health" or not self.api_server.auth_token:
            return True
        token = self.headers.get("X-MathCyclus-Token", "")
        if not token:
            authorization = self.headers.get("Authorization", "")
            if authorization.lower().startswith("bearer "):
                token = authorization[7:].strip()
        if token != self.api_server.auth_token:
            self._error(401, "需要本地 API token")
            return False
        return True

    def _read_json(self) -> dict[str, Any]:
        raw_length = self.headers.get("Content-Length", "0")
        length = _safe_int(raw_length, minimum=0)
        if length > MAX_REQUEST_BYTES:
            raise ValueError(f"请求体过大，不能超过 {MAX_REQUEST_BYTES} bytes")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("请求体必须是 UTF-8 JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError("请求体必须是 JSON 对象")
        return payload

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._write(204, {})

    def do_GET(self) -> None:  # noqa: N802
        self._dispatch("GET")

    def do_POST(self) -> None:  # noqa: N802
        self._dispatch("POST")

    def do_PATCH(self) -> None:  # noqa: N802
        self._dispatch("PATCH")

    def _dispatch(self, method: str) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not self._authorize(path):
            return
        query = parse_qs(parsed.query, keep_blank_values=True)
        try:
            payload = self._route(method, path, query)
            self._write(200, payload)
        except KeyError as exc:
            self._error(404, str(exc).strip("'"))
        except ValueError as exc:
            self._error(400, str(exc))
        except FileNotFoundError as exc:
            self._error(404, str(exc))
        except Exception as exc:  # Keep internal paths and SQL details out of the API response.
            self.log_error("request failed: %s", exc)
            self._error(500, "本地 API 处理失败")

    def _route(self, method: str, path: str, query: dict[str, list[str]]) -> dict[str, Any]:
        server = self.api_server
        if method == "GET" and path == "/health":
            return {
                "status": "ok",
                "service": "mathcyclus-local-api",
                "draft_only": True,
                "database": str(server.db_path),
                "migration": migration_status(str(server.db_path)),
            }

        if path == f"{API_PREFIX}/drafts" and method == "POST":
            body = self._read_json()
            items = body.get("items")
            if items is None and isinstance(body.get("draft"), dict):
                items = [body["draft"]]
            result = create_manual_entry_drafts(
                str(server.db_path),
                _sanitize_draft_items(items),
                source_path=str(body.get("source_path") or "local-api")[:500],
                mode=str(body.get("mode") or "local_api_drafts")[:100],
                stamp=str(body.get("stamp") or "")[:100],
                summary=str(body.get("summary") or "")[:500],
            )
            result["human_review_required"] = True
            return result

        if path == f"{API_PREFIX}/drafts" and method == "GET":
            batch_id = _query_value(query, "batch_id")
            review_status = _query_value(query, "review_status")
            limit = _safe_int(_query_value(query, "limit", "50"), 50, minimum=1, maximum=200)
            offset = _safe_int(_query_value(query, "offset", "0"), 0, minimum=0)
            return {
                "items": list_draft_questions(
                    str(server.db_path), batch_id=batch_id, review_status=review_status,
                    limit=limit, offset=offset,
                ),
            }

        if path == f"{API_PREFIX}/batches" and method == "GET":
            limit = _safe_int(_query_value(query, "limit", "20"), 20, minimum=1, maximum=100)
            return {"items": list_import_batches(str(server.db_path), limit=limit)}

        if path == f"{API_PREFIX}/questions/search" and method == "GET":
            filters = QuestionListFilters(
                keyword=_query_value(query, "keyword"),
                year=_safe_int(_query_value(query, "year"), 0, minimum=0) or None,
                chapter=_query_value(query, "chapter"),
                source_kind=_query_value(query, "source_kind"),
                paper_series=_query_value(query, "paper_series"),
                source=_query_value(query, "source"),
                question_number=_query_value(query, "question_number"),
                question_type_id=_safe_int(_query_value(query, "question_type_id"), 0, minimum=0) or None,
                difficulty=_safe_int(_query_value(query, "difficulty"), 0, minimum=0) or None,
                limit=_safe_int(_query_value(query, "limit", "20"), 20, minimum=1, maximum=100),
                offset=_safe_int(_query_value(query, "offset", "0"), 0, minimum=0),
            )
            items = list_questions(str(server.db_path), filters)
            return {"items": items, "limit": filters.limit, "offset": filters.offset}

        if path == f"{API_PREFIX}/questions/similarity" and method == "POST":
            body = self._read_json()
            stem_tex = str(body.get("stem_tex") or body.get("stem") or "").strip()
            if not stem_tex:
                raise ValueError("stem_tex 不能为空")
            try:
                minimum_score = float(body.get("minimum_score", 0.40))
            except (TypeError, ValueError) as exc:
                raise ValueError("minimum_score 必须是 0 到 1 之间的数字") from exc
            max_results = _safe_int(body.get("max_results", 20), 20, minimum=1, maximum=100)
            items = find_question_similarity_candidates(
                str(server.db_path),
                stem_tex,
                choices=body.get("choices"),
                question_type_id=body.get("question_type_id"),
                minimum_score=minimum_score,
                max_results=max_results,
            )
            return {
                "items": items,
                "minimum_score": max(0.0, min(1.0, minimum_score)),
                "algorithm": "gaokao_web_bind_sim_v1",
            }

        if path == f"{API_PREFIX}/papers/match" and method == "POST":
            body = self._read_json()
            from services.paper_catalog_service import match_paper

            try:
                threshold = float(body.get("similarity_threshold", 0.55))
            except (TypeError, ValueError) as exc:
                raise ValueError("similarity_threshold 必须是 0 到 1 之间的数字") from exc
            result = match_paper(
                str(server.db_path),
                year=body.get("year"),
                paper_series=str(body.get("paper_series") or "G"),
                track=str(body.get("track") or ""),
                paper_name=str(body.get("paper_name") or body.get("source_name") or ""),
                limit=_safe_int(body.get("limit", 5), 5, minimum=1, maximum=20),
                similarity_threshold=max(0.0, min(1.0, threshold)),
            )
            return {
                "match": result,
                "human_review_required": result.get("status") != "exact",
                "algorithm": "paper_catalog_match_v1",
            }

        parts = [unquote(part) for part in path.split("/") if part]
        if len(parts) >= 4 and parts[:3] == ["api", "v1", "drafts"]:
            draft_id = parts[3]
            if len(parts) == 4 and method == "GET":
                draft = get_draft_question(str(server.db_path), draft_id)
                if not draft:
                    raise KeyError(f"草稿不存在：{draft_id}")
                return {"draft": draft}
            if len(parts) == 4 and method == "PATCH":
                body = self._read_json()
                updates = body.get("updates") if isinstance(body.get("updates"), dict) else body
                if not isinstance(updates, dict):
                    raise ValueError("updates 必须是对象")
                forbidden = {"review_status", "approved_content_hash", "approved_by", "approved_at"}
                if forbidden.intersection(updates):
                    raise ValueError("审核状态只能在题库人工审核界面修改")
                operator = str(body.get("operator") or "local_api")[:120]
                return update_draft_question_fields(str(server.db_path), draft_id, updates, operator=operator)
            if len(parts) == 5 and parts[4] == "validate" and method == "POST":
                result = validate_existing_draft(str(server.db_path), draft_id)
                draft = get_draft_question(str(server.db_path), draft_id)
                extra = _parse_json_object(draft.get("extra_json"))
                result["content_matches"] = find_question_content_matches(
                    str(server.db_path),
                    str(draft.get("stem_tex") or ""),
                    choices=draft.get("choices_json"),
                    question_type_id=draft.get("question_type_id"),
                    max_results=5,
                )
                result["paper_position_conflicts"] = find_paper_position_conflict(str(server.db_path), extra)
                return result
            if len(parts) == 5 and parts[4] == "review-events" and method == "GET":
                limit = _safe_int(_query_value(query, "limit", "100"), 100, minimum=1, maximum=500)
                return {"items": list_draft_review_events(str(server.db_path), draft_id=draft_id, limit=limit)}

        if len(parts) == 4 and parts[:3] == ["api", "v1", "batches"] and method == "GET":
            batch_id = parts[3]
            summary = summarize_batch(str(server.db_path), batch_id)
            if not summary.get("batch"):
                raise KeyError(f"批次不存在：{batch_id}")
            summary["drafts"] = list_draft_questions(str(server.db_path), batch_id=batch_id, limit=200)
            return summary

        if len(parts) == 5 and parts[:3] == ["api", "v1", "batches"] and parts[4] == "validate" and method == "POST":
            batch_id = parts[3]
            summary = summarize_batch(str(server.db_path), batch_id)
            if not summary.get("batch"):
                raise KeyError(f"批次不存在：{batch_id}")
            drafts = list_draft_questions(str(server.db_path), batch_id=batch_id, limit=200)
            results = []
            for item in drafts:
                draft_id = str(item.get("draft_id") or "")
                draft = get_draft_question(str(server.db_path), draft_id)
                validation = validate_existing_draft(str(server.db_path), draft_id)
                extra = _parse_json_object(draft.get("extra_json"))
                validation["content_matches"] = find_question_content_matches(
                    str(server.db_path),
                    str(draft.get("stem_tex") or ""),
                    choices=draft.get("choices_json"),
                    question_type_id=draft.get("question_type_id"),
                    max_results=5,
                )
                validation["paper_position_conflicts"] = find_paper_position_conflict(
                    str(server.db_path), extra,
                )
                results.append(validation)
            return {
                "batch_id": batch_id,
                "draft_count": len(results),
                "results": results,
                "human_review_required": True,
            }

        if len(parts) == 4 and parts[:3] == ["api", "v1", "questions"] and method == "GET":
            question_id = parts[3]
            question = get_question_bundle(str(server.db_path), question_id)
            if not question:
                raise KeyError(f"题目不存在：{question_id}")
            return {"question": question}

        raise KeyError("API 路径不存在")


def _parse_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(str(value or "{}"))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class LocalApiServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address: tuple[str, int], *, db_path: str | os.PathLike[str] | None = None, auth_token: str = ""):
        self.db_path = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
        self.auth_token = str(auth_token or "").strip()
        super().__init__(address, LocalApiHandler)


def prepare_local_api_database(db_path: str | os.PathLike[str] | None = None) -> dict[str, Any]:
    """Apply pending migrations before the standalone API starts."""
    target = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
    if not target.exists():
        raise FileNotFoundError(f"SQLite 数据库不存在：{target}")
    return apply_pending_migrations(str(target), apply=True, backup=True)


def create_local_api_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    *,
    db_path: str | os.PathLike[str] | None = None,
    auth_token: str = "",
    migrate: bool = True,
) -> LocalApiServer:
    target = Path(resolve_database_path(db_path or DEFAULT_DATABASE_PATH))
    if migrate:
        prepare_local_api_database(str(target))
    return LocalApiServer((host, int(port)), db_path=str(target), auth_token=auth_token)
