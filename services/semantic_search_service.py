"""Optional semantic search backed by an OpenAI-compatible embeddings endpoint.

SQLite is the source of truth for formal questions. Legacy CSV callers remain
supported. This module stores only a rebuildable derived index.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
import struct
import time
from collections import OrderedDict
from contextlib import closing
from typing import Callable, Iterable

from utils.core_config import BASE_DIR
from services.question_similarity_service import SIM_MAIN_THRESHOLD, score_question_pair
from services.formula_similarity_service import compare_formula_texts


SEMANTIC_INDEX_PATH = os.path.join(BASE_DIR, "utils", "semantic_index.sqlite3")
SEMANTIC_INDEX_VERSION = 1
EMBEDDING_BATCH_SIZE = 20
SEMANTIC_QUERY_CACHE_TTL = 60.0
SEMANTIC_QUERY_CACHE_MAX_ENTRIES = 128
_QUERY_CACHE: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()
SIMILARITY_WEIGHTS = {
    "gaokao_text": 0.45,
    "semantic": 0.30,
    "formula": 0.10,
    "lexical": 0.08,
    "knowledge": 0.04,
    "question_type": 0.03,
}
VERIFICATION_WEIGHTS = {
    "gaokao_text": 0.65, "semantic": 0.10, "formula": 0.12,
    "lexical": 0.08, "knowledge": 0.03, "question_type": 0.02,
}
SIMILARITY_MODES = {"recommendation": "同类题推荐", "verification": "同题／变式核对"}


def _mode_weights(mode: str) -> dict:
    if mode not in SIMILARITY_MODES:
        raise ValueError("Unknown similarity mode")
    return VERIFICATION_WEIGHTS if mode == "verification" else SIMILARITY_WEIGHTS


def _comparison_details(left: dict, right: dict, gaokao: dict, semantic_score) -> dict:
    labels = {
        "numbers": "数字或参数不同", "variables": "变量符号不同",
        "relations": "关系符号不同", "conditions": "条件词不同",
        "intervals": "区间端点或开闭边界不同", "choices": "选项内容或顺序不同",
        "image_count": "配图数量不同", "visual_pending": "配图内容尚未比较",
    }
    notes = []
    for item in gaokao.get("differences") or []:
        label = labels.get(item.get("kind"))
        if label:
            if item.get("kind") in {"numbers", "relations", "conditions", "variables"}:
                label += f"：基准题 {', '.join(map(str, item.get('left') or [])) or '无'}；候选题 {', '.join(map(str, item.get('right') or [])) or '无'}"
            notes.append(label)
    if str(left.get("选项") or "").strip() != str(right.get("选项") or "").strip():
        notes.append("选项内容或顺序不同")
    left_type = left.get("题型ID") or left.get("question_type_id")
    right_type = right.get("题型ID") or right.get("question_type_id")
    if left_type is not None and right_type is not None and left_type != right_type:
        notes.append(f"题型不同：{left.get('题型') or left_type} / {right.get('题型') or right_type}")
    visual_pending = (bool(left.get("配图数量") or right.get("配图数量"))
                      or left.get("包含TikZ绘图") == "是" or right.get("包含TikZ绘图") == "是"
                      or any(item.get("kind") in {"visual_pending", "image_count"}
                             for item in gaokao.get("differences") or []))
    if visual_pending:
        notes.append("配图内容尚未比较")
    checked = ["题干与选项"]
    unavailable = []
    (checked if semantic_score is not None else unavailable).append(
        "语义向量" if semantic_score is not None else "语义向量未参与")
    if visual_pending:
        unavailable.append("配图未比较，需人工查看")
    if left_type is None or right_type is None:
        unavailable.append("题型 ID 不完整")
    return {"differences": list(dict.fromkeys(notes)), "checked": checked,
            "unavailable": unavailable, "visual_pending": visual_pending}


class SemanticSearchError(RuntimeError):
    """Raised for configuration, transport, or response errors."""


def _clear_query_cache() -> None:
    _QUERY_CACHE.clear()


def _rows_cache_token(rows: list[dict]) -> str:
    payload = sorted(
        (
            index_key(row),
            row_fingerprint(row),
        )
        for row in rows
    )
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode("utf-8")).hexdigest()


def _query_cache_get(key: tuple) -> list[dict] | None:
    cached = _QUERY_CACHE.get(key)
    if cached is None:
        return None
    created_at, value = cached
    if time.monotonic() - created_at >= SEMANTIC_QUERY_CACHE_TTL:
        _QUERY_CACHE.pop(key, None)
        return None
    _QUERY_CACHE.move_to_end(key)
    return value


def _query_cache_put(key: tuple, value: list[dict]) -> None:
    _QUERY_CACHE[key] = (time.monotonic(), value)
    _QUERY_CACHE.move_to_end(key)
    while len(_QUERY_CACHE) > SEMANTIC_QUERY_CACHE_MAX_ENTRIES:
        _QUERY_CACHE.popitem(last=False)


def _connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(SEMANTIC_INDEX_PATH), exist_ok=True)
    conn = sqlite3.connect(SEMANTIC_INDEX_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_embeddings (
            relative_path TEXT PRIMARY KEY,
            question_id TEXT NOT NULL DEFAULT '',
            fingerprint TEXT NOT NULL,
            model_name TEXT NOT NULL,
            dimensions INTEGER NOT NULL,
            vector BLOB NOT NULL,
            updated_at REAL NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS semantic_pending (
            relative_path TEXT PRIMARY KEY,
            reason TEXT NOT NULL DEFAULT 'source_changed',
            requested_at REAL NOT NULL
        )
        """
    )
    conn.commit()
    return conn


def embedding_text(row: dict) -> str:
    """Build the searchable text while keeping answers out of the first index."""
    parts = [
        f"知识板块：{row.get('知识板块', '') or ''}",
        f"题型：{row.get('题型', '') or ''}",
        f"标签：{row.get('标签', '') or ''}",
        f"题干：{row.get('题干', '') or ''}",
        f"选项：{row.get('选项', '') or ''}",
    ]
    return "\n".join(part.strip() for part in parts if part.split("：", 1)[-1].strip())


def row_fingerprint(row: dict) -> str:
    if str(row.get("SQLite题目ID") or "").strip():
        return hashlib.sha256(embedding_text(row).encode("utf-8")).hexdigest()
    payload = {
        key: str(row.get(key, "") or "").strip()
        for key in ("文件名称", "相对文件路径", "知识板块", "题型", "标签", "题干", "选项")
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def index_key(row: dict) -> str:
    question_id = str(row.get("SQLite题目ID") or "").strip()
    return f"sqlite://{question_id}" if question_id else _normalized_index_path(row.get("相对文件路径"))


def load_sqlite_index_rows(db_path: str | None = None) -> list[dict]:
    """Read the entire formal bank in one consistent, read-only snapshot."""
    from services.database_service import readonly_database_connection
    from services.sqlite_legacy_adapter import sqlite_summary_to_legacy_row
    with readonly_database_connection(db_path) as conn:
        conn.execute("BEGIN")
        labels = {row[0]: row[1] for row in conn.execute("SELECT question_type_id,name FROM question_type")}
        summaries = conn.execute("""
            SELECT q.question_id,q.legacy_id,q.question_type_id,q.stem_tex,q.choices_json,
                   q.tags_json,l.legacy_file_path,l.detected_chapter,l.detected_topic
            FROM question q LEFT JOIN legacy_question_map l ON l.question_id=q.question_id
            ORDER BY q.question_id
        """).fetchall()
        return [sqlite_summary_to_legacy_row(dict(row), question_type_labels=labels) for row in summaries]


def coverage_status(rows: list[dict], model_name: str, *, sync_pending: bool = False) -> dict:
    """Derive missing/changed work from current content, including bulk imports."""
    valid = {index_key(row): row for row in rows if index_key(row) and embedding_text(row).strip()}
    stored = {}
    if os.path.exists(SEMANTIC_INDEX_PATH) or sync_pending:
        with closing(_connect()) as conn:
            stored = dict(conn.execute(
                "SELECT relative_path,fingerprint FROM semantic_embeddings WHERE model_name=?",
                (model_name.strip(),)))
            pending = {key for key, row in valid.items() if stored.get(key) != row_fingerprint(row)}
            if sync_pending:
                # This is a derived queue; no cross-database writes in an import transaction.
                conn.execute("DELETE FROM semantic_pending")
                conn.executemany(
                    "INSERT INTO semantic_pending(relative_path,reason,requested_at) VALUES (?,'source_changed',?)",
                    [(key, time.time()) for key in sorted(pending)])
                conn.commit()
    else:
        pending = set(valid)
    return {"total": len(valid), "covered": len(valid)-len(pending), "pending": len(pending),
            "unindexable": len(rows)-len(valid)}


def _pack_vector(vector: Iterable[float]) -> tuple[bytes, int]:
    values = [float(value) for value in vector]
    if not values:
        raise SemanticSearchError("embedding 返回了空向量")
    if not all(math.isfinite(value) for value in values):
        raise SemanticSearchError("embedding 包含无效数字")
    return struct.pack(f"<{len(values)}f", *values), len(values)


def _unpack_vector(blob: bytes, dimensions: int) -> list[float]:
    expected_size = dimensions * 4
    if len(blob) != expected_size:
        raise SemanticSearchError("语义索引中的向量维度不一致，请重建索引")
    return list(struct.unpack(f"<{dimensions}f", blob))


_VERSION_SEGMENT_RE = re.compile(r"/v\d+(?:\.\d+)?/?$")


def _embeddings_url(base_url: str) -> str:
    override = os.getenv("AI_EMBEDDINGS_URL", "").strip()
    if override:
        return override
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise SemanticSearchError("未配置 Base URL")
    if url.endswith("/embeddings"):
        return url
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if not _VERSION_SEGMENT_RE.search(url) and "/v1" not in url:
        url += "/v1"
    return url + "/embeddings"


def request_embeddings(base_url: str, api_key: str, model_name: str, texts: list[str], timeout=90) -> list[list[float]]:
    if not api_key:
        raise SemanticSearchError("请先配置 API Key")
    if not model_name:
        raise SemanticSearchError("请先配置 embedding 模型")
    if not texts:
        return []

    import requests

    url = _embeddings_url(base_url)
    print(f"[AI] embeddings 最终请求 URL: {url}")
    try:
        response = requests.post(
            url,
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {api_key}"},
            json={"model": model_name, "input": texts},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise SemanticSearchError(f"embedding API 请求失败：{exc}") from exc
    if response.status_code != 200:
        detail = response.text[:300].replace("\n", " ")
        raise SemanticSearchError(f"embedding API 返回 HTTP {response.status_code}: {detail}")
    try:
        payload = response.json()
        data = payload.get("data") or []
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in ordered]
    except Exception as exc:
        raise SemanticSearchError(f"embedding API 响应格式无效：{exc}") from exc
    if len(vectors) != len(texts) or any(not isinstance(vector, list) for vector in vectors):
        raise SemanticSearchError("embedding API 返回数量与输入不一致")
    return vectors


def index_status() -> dict:
    if not os.path.exists(SEMANTIC_INDEX_PATH):
        return {"exists": False, "count": 0, "model_name": "", "updated_at": None}
    try:
        with closing(_connect()) as conn:
            count = conn.execute("SELECT COUNT(*) FROM semantic_embeddings").fetchone()[0]
            model = conn.execute("SELECT model_name FROM semantic_embeddings ORDER BY updated_at DESC LIMIT 1").fetchone()
            updated = conn.execute("SELECT MAX(updated_at) FROM semantic_embeddings").fetchone()[0]
        return {"exists": True, "count": count, "model_name": model[0] if model else "", "updated_at": updated}
    except sqlite3.Error as exc:
        raise SemanticSearchError(f"读取语义索引失败：{exc}") from exc


def _existing_fingerprints(conn: sqlite3.Connection, model_name: str) -> dict[str, tuple[str, int]]:
    rows = conn.execute(
        "SELECT relative_path, fingerprint, dimensions FROM semantic_embeddings WHERE model_name = ?",
        (model_name,),
    ).fetchall()
    return {row[0]: (row[1], row[2]) for row in rows}


def build_index(
    rows: list[dict],
    base_url: str,
    api_key: str,
    model_name: str,
    force: bool = False,
    progress: Callable[[int, int], None] | None = None,
) -> dict:
    """Build or incrementally refresh the derived semantic index."""
    if not model_name.strip():
        raise SemanticSearchError("请先在 API 设置中填写 embedding 模型名")

    model_name = model_name.strip()
    valid_rows = list({index_key(row): row for row in rows
                       if index_key(row) and embedding_text(row).strip()}.values())
    _clear_query_cache()
    with closing(_connect()) as conn:
        existing = {} if force else _existing_fingerprints(conn, model_name)
        existing_dimensions = {dimensions for _, dimensions in existing.values()}
        if len(existing_dimensions) > 1:
            raise SemanticSearchError("语义索引中的向量维度不一致，请强制重建索引")
        expected_dimensions = next(iter(existing_dimensions), None)
        current_paths = {index_key(row) for row in valid_rows}

        pending = [
            row for row in valid_rows
            if force
            or index_key(row) not in existing
            or existing[index_key(row)][0] != row_fingerprint(row)
        ]
        total = len(pending)
        if progress:
            progress(0, total)
        for offset in range(0, total, EMBEDDING_BATCH_SIZE):
            batch = pending[offset : offset + EMBEDDING_BATCH_SIZE]
            vectors = request_embeddings(base_url, api_key, model_name, [embedding_text(row) for row in batch])
            now = time.time()
            for row, vector in zip(batch, vectors):
                blob, dimensions = _pack_vector(vector)
                if expected_dimensions is None:
                    expected_dimensions = dimensions
                elif dimensions != expected_dimensions:
                    raise SemanticSearchError("embedding 返回的向量维度不一致，请强制重建索引")
                relative_path = index_key(row)
                conn.execute(
                    """
                    INSERT INTO semantic_embeddings
                        (relative_path, question_id, fingerprint, model_name, dimensions, vector, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(relative_path) DO UPDATE SET
                        question_id = excluded.question_id,
                        fingerprint = excluded.fingerprint,
                        model_name = excluded.model_name,
                        dimensions = excluded.dimensions,
                        vector = excluded.vector,
                        updated_at = excluded.updated_at
                    """,
                    (relative_path, str(row.get("SQLite题目ID") or row.get("题目ID") or ""), row_fingerprint(row), model_name, dimensions, blob, now),
                )
                conn.execute("DELETE FROM semantic_pending WHERE relative_path=?", (relative_path,))
            # Release the SQLite write lock before the next network request.
            conn.commit()
            _clear_query_cache()
            if progress:
                progress(min(offset + len(batch), total), total)
        # Avoid a variable-count limit for large banks. Retire old entries only
        # after a complete pass, so a failed first request preserves the old index.
        conn.execute("CREATE TEMP TABLE desired_semantic_paths(path TEXT PRIMARY KEY)")
        conn.executemany("INSERT INTO desired_semantic_paths VALUES (?)", [(path,) for path in current_paths])
        removed = conn.execute("""DELETE FROM semantic_embeddings
            WHERE NOT EXISTS (SELECT 1 FROM desired_semantic_paths d WHERE d.path=relative_path)""").rowcount
        conn.execute("DELETE FROM semantic_pending")
        conn.execute(
            "INSERT INTO semantic_meta(key, value) VALUES('version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SEMANTIC_INDEX_VERSION),),
        )
        conn.commit()
        return {"total": len(valid_rows), "updated": total, "removed": removed}


def invalidate_path(relative_path: str) -> None:
    if not relative_path:
        return
    _clear_query_cache()
    with closing(_connect()) as conn:
        normalized = relative_path.replace("/", "\\")
        conn.execute("DELETE FROM semantic_embeddings WHERE relative_path = ?", (normalized,))
        conn.execute(
            "INSERT INTO semantic_pending(relative_path, reason, requested_at) VALUES (?, 'source_changed', ?) "
            "ON CONFLICT(relative_path) DO UPDATE SET reason = excluded.reason, requested_at = excluded.requested_at",
            (normalized, time.time()),
        )
        conn.commit()


def refresh_pending(rows: list[dict], base_url: str, api_key: str, model_name: str) -> dict:
    """Refresh invalidated rows without rebuilding the complete index."""
    if not rows or not model_name.strip():
        return {"pending": 0, "updated": 0, "missing": 0}
    row_by_path = {index_key(row): row for row in rows if index_key(row)}
    with closing(_connect()) as conn:
        pending_paths = [item[0] for item in conn.execute("SELECT relative_path FROM semantic_pending ORDER BY requested_at")]
    sqlite_scope = any(row.get("SQLite题目ID") for row in rows)
    pending_paths = [path for path in pending_paths if path.startswith("sqlite://") == sqlite_scope]
    missing_paths = [path for path in pending_paths if path not in row_by_path]
    if missing_paths:
        with closing(_connect()) as conn:
            conn.executemany("DELETE FROM semantic_pending WHERE relative_path = ?", [(path,) for path in missing_paths])
            conn.commit()
    pending_rows = [row_by_path[path] for path in pending_paths if path in row_by_path]
    if not pending_rows:
        return {"pending": len(pending_paths), "updated": 0, "missing": len(missing_paths)}

    _clear_query_cache()
    updated = 0
    with closing(_connect()) as conn:
        for offset in range(0, len(pending_rows), EMBEDDING_BATCH_SIZE):
            batch = pending_rows[offset : offset + EMBEDDING_BATCH_SIZE]
            vectors = request_embeddings(base_url, api_key, model_name, [embedding_text(row) for row in batch])
            now = time.time()
            for row, vector in zip(batch, vectors):
                blob, dimensions = _pack_vector(vector)
                relative_path = index_key(row)
                conn.execute(
                    """
                    INSERT INTO semantic_embeddings
                        (relative_path, question_id, fingerprint, model_name, dimensions, vector, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(relative_path) DO UPDATE SET
                        question_id = excluded.question_id,
                        fingerprint = excluded.fingerprint,
                        model_name = excluded.model_name,
                        dimensions = excluded.dimensions,
                        vector = excluded.vector,
                        updated_at = excluded.updated_at
                    """,
                    (relative_path, str(row.get("SQLite题目ID") or row.get("题目ID") or ""), row_fingerprint(row), model_name, dimensions, blob, now),
                )
                conn.execute("DELETE FROM semantic_pending WHERE relative_path = ?", (relative_path,))
                updated += 1
        conn.commit()
    _clear_query_cache()
    return {"pending": len(pending_paths), "updated": updated, "missing": len(missing_paths)}


def search(
    query: str,
    rows: list[dict],
    base_url: str,
    api_key: str,
    model_name: str,
    top_k: int = 30,
) -> list[dict]:
    if not query.strip():
        return []
    if not rows:
        return []
    if not os.path.exists(SEMANTIC_INDEX_PATH):
        raise SemanticSearchError("语义索引尚未建立，请先重建索引")

    cache_key = (
        query.strip(),
        model_name.strip(),
        max(1, int(top_k)),
        _rows_cache_token(rows),
    )
    cached = _query_cache_get(cache_key)
    if cached is not None:
        return cached

    scored = []
    with closing(_connect()) as conn:
        indexed_models = [row[0] for row in conn.execute(
            "SELECT DISTINCT model_name FROM semantic_embeddings"
        ).fetchall()]
        if not indexed_models:
            raise SemanticSearchError("语义索引为空，请先重建索引")
        if len(indexed_models) != 1:
            raise SemanticSearchError("语义索引包含多个 embedding 模型，请重建索引")
        if model_name.strip() != indexed_models[0]:
            raise SemanticSearchError("当前 embedding 模型与索引不一致，请重建索引")
        stored = conn.execute("SELECT relative_path, dimensions, vector, fingerprint FROM semantic_embeddings").fetchall()
    vectors = request_embeddings(base_url, api_key, model_name, [query.strip()])
    query_vector = vectors[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
    row_by_path = {key: row for row in rows
                   for key in (index_key(row), _normalized_index_path(row.get("相对文件路径"))) if key}
    for relative_path, dimensions, blob, fingerprint in stored:
        row = row_by_path.get(relative_path) or row_by_path.get(_normalized_index_path(relative_path))
        if not row:
            continue
        if row_fingerprint(row) != fingerprint:
            continue
        if len(query_vector) != dimensions:
            raise SemanticSearchError("查询向量与语义索引维度不一致，请重建索引")
        vector = _unpack_vector(blob, dimensions)
        denominator = query_norm * (math.sqrt(sum(value * value for value in vector)) or 1.0)
        score = sum(left * right for left, right in zip(query_vector, vector)) / denominator
        scored.append({"row": row, "score": float(score), "path": row.get("相对文件路径", "")})
    scored.sort(key=lambda item: item["score"], reverse=True)
    result = scored[: max(1, int(top_k))]
    _query_cache_put(cache_key, result)
    return result


def _normalized_index_path(value: object) -> str:
    path = str(value or "").strip().replace("/", "\\")
    if path.casefold().startswith("chapters\\"):
        path = path[len("chapters\\"):]
    return path


def _row_similarity_text(row: dict) -> str:
    return "\n".join(filter(None, [
        str(row.get("题干") or "").strip(),
        str(row.get("选项") or "").strip(),
    ]))


def _normalized_lexical_text(value: object) -> str:
    text = str(value or "").casefold()
    text = re.sub(r"\$[^$]*\$", " ", text)
    text = re.sub(r"\\\([^)]*\\\)|\\\[[^]]*\\\]", " ", text)
    text = re.sub(r"\\(?:begin|end)\{[^{}]+\}", " ", text)
    text = re.sub(r"\\[a-z]+", " ", text)
    text = re.sub(r"\d+(?:\.\d+)?", "0", text)
    text = re.sub(r"(?<![a-z])[a-z](?![a-z])", " ", text)
    return re.sub(r"[^0-9a-z\u3400-\u9fff]+", "", text)


def _character_ngrams(value: str, size: int = 3) -> set[str]:
    if not value:
        return set()
    if len(value) <= size:
        return {value}
    return {value[index:index + size] for index in range(len(value) - size + 1)}


def _set_similarity(left: set, right: set) -> float | None:
    if not left or not right:
        return None
    return len(left & right) / len(left | right)


def _lexical_similarity(left: object, right: object) -> float | None:
    left_ngrams = _character_ngrams(_normalized_lexical_text(left))
    right_ngrams = _character_ngrams(_normalized_lexical_text(right))
    return _set_similarity(left_ngrams, right_ngrams)


def _formula_features(value: object) -> set[tuple[str, str]]:
    text = str(value or "").casefold()
    raw_tokens = re.findall(
        r"\\[a-z]+|\d+(?:\.\d+)?|[a-z]|<=|>=|!=|=|\+|-|\*|/|\^|_|<|>|\(|\)|\[|\]|\{|\}|\|",
        text,
    )
    normalized_tokens = []
    for token in raw_tokens:
        if token.startswith("\\"):
            normalized_tokens.append(token)
        elif re.fullmatch(r"\d+(?:\.\d+)?", token):
            normalized_tokens.append("NUM")
        elif re.fullmatch(r"[a-z]", token):
            normalized_tokens.append("VAR")
        else:
            normalized_tokens.append(token)
    return set(zip(normalized_tokens, normalized_tokens[1:]))


def _metadata_similarity(left: object, right: object) -> float | None:
    left_text = re.sub(r"\s+", "", str(left or "")).casefold()
    right_text = re.sub(r"\s+", "", str(right or "")).casefold()
    if not left_text or not right_text:
        return None
    if left_text == right_text:
        return 1.0
    separators = r"[,，、;/；·|]+"
    left_parts = {part for part in re.split(separators, left_text) if part}
    right_parts = {part for part in re.split(separators, right_text) if part}
    return _set_similarity(left_parts, right_parts) or 0.0


def combined_similarity_score(
    reference_row: dict,
    candidate_row: dict,
    semantic_score: float | None,
    *,
    mode: str = "recommendation",
) -> dict:
    """Combine GaokaoWeb text scoring with embedding and local signals."""
    weights = _mode_weights(mode)
    reference_text = _row_similarity_text(reference_row)
    candidate_text = _row_similarity_text(candidate_row)
    gaokao = score_question_pair(
        reference_row.get("题干") or "",
        candidate_row.get("题干") or "",
        left_choices=reference_row.get("选项"),
        right_choices=candidate_row.get("选项"),
        left_question_type_id=reference_row.get("题型ID") or reference_row.get("question_type_id"),
        right_question_type_id=candidate_row.get("题型ID") or candidate_row.get("question_type_id"),
        allow_sub=True,
    )
    formula = compare_formula_texts(reference_text, candidate_text)
    formula_score = (formula[mode + "_score"] if formula["complete"] else
                     _set_similarity(_formula_features(reference_text), _formula_features(candidate_text)))
    components = {
        "gaokao_text": gaokao.get("score"),
        "semantic": None if semantic_score is None else max(0.0, min(1.0, float(semantic_score))),
        "formula": formula_score,
        "lexical": _lexical_similarity(reference_text, candidate_text),
        "knowledge": (_set_similarity(set(reference_row["关联知识板块"]), set(candidate_row["关联知识板块"]))
                      if reference_row.get("关联知识板块") and candidate_row.get("关联知识板块")
                      else _metadata_similarity(reference_row.get("知识板块"), candidate_row.get("知识板块"))),
        "question_type": _metadata_similarity(reference_row.get("题型"), candidate_row.get("题型")),
    }
    available_weight = sum(
        weights[name]
        for name, value in components.items()
        if value is not None
    )
    score = sum(
        weights[name] * value
        for name, value in components.items()
        if value is not None
    ) / (available_weight or 1.0)

    reasons = []
    if gaokao.get("score") is not None and gaokao.get("score", 0) >= 0.6:
        reasons.append(f"文本结构接近（{gaokao['score']:.0%}）")
    if components["knowledge"] is not None and components["knowledge"] >= 0.8:
        reasons.append("同知识板块")
    if components["question_type"] is not None and components["question_type"] >= 0.8:
        reasons.append("同题型")
    if components["formula"] is not None and components["formula"] >= 0.35:
        reasons.append("公式结构接近")
    if components["lexical"] is not None and components["lexical"] >= 0.28:
        reasons.append("题干表述接近")
    if not reasons:
        reasons.append("语义向量参与排序" if semantic_score is not None else "按本地可用特征排序")
    comparison = _comparison_details(reference_row, candidate_row, gaokao, semantic_score)
    comparison["formula"] = formula
    comparison["differences"].extend(formula["differences"])
    if formula["complete"]:
        comparison["checked"].append("公式结构")
    if formula["complete"] and formula["exact"]:
        reasons.append("公式表达式一致（不含等价变形推导）")
    if not formula["complete"] and (formula["left_count"] or formula["right_count"]):
        comparison["unavailable"].append("部分公式未完成结构解析，使用基础符号比较")
    if gaokao.get("kind") == "exact" and comparison["visual_pending"]:
        gaokao = {**gaokao, "kind": "similar", "channel": "题文一致，配图待核对",
                  "warnings": [*(gaokao.get("warnings") or []), "配图内容尚未比较"]}
    gaokao_score = gaokao.get("score")
    relationship_kind = None
    if gaokao.get("kind") == "exact" and not comparison["visual_pending"]:
        relationship_kind = "same_question"
    elif gaokao_score is not None and float(gaokao_score) >= SIM_MAIN_THRESHOLD:
        relationship_kind = "similar_question"
    return {
        "score": float(max(0.0, min(1.0, score))),
        "semantic_score": components["semantic"],
        "gaokao_score": gaokao_score,
        "gaokao_detail": gaokao,
        "relationship_kind": relationship_kind,
        "relationship_eligible": relationship_kind is not None,
        "relationship_score": 1.0 if relationship_kind == "same_question" else gaokao_score,
        "components": components,
        "reason": " · ".join(reasons),
        "comparison": comparison,
        "mode": mode,
        "effective_weights": {name: weights[name] / (available_weight or 1.0)
                              for name, value in components.items() if value is not None},
    }


def search_similar_row(
    reference_row: dict,
    rows: list[dict],
    model_name: str,
    top_k: int = 200,
    *,
    mode: str = "recommendation",
) -> list[dict]:
    """Rank rows with embeddings when available and always keep a local fallback."""
    _mode_weights(mode)
    if not rows:
        return []
    reference_id = str(reference_row.get("SQLite题目ID") or reference_row.get("题目ID") or "").strip()
    reference_path = index_key(reference_row)
    if not model_name.strip() or not os.path.exists(SEMANTIC_INDEX_PATH):
        return _rank_local_similarity(reference_row, rows, reference_id, reference_path, top_k, mode=mode)

    with closing(_connect()) as conn:
        indexed_models = [row[0] for row in conn.execute(
            "SELECT DISTINCT model_name FROM semantic_embeddings"
        ).fetchall()]
        if not indexed_models or len(indexed_models) != 1 or indexed_models[0] != model_name.strip():
            return _rank_local_similarity(reference_row, rows, reference_id, reference_path, top_k, mode=mode)
        stored = conn.execute(
            "SELECT relative_path, question_id, dimensions, vector, fingerprint FROM semantic_embeddings"
        ).fetchall()

    vectors_by_path = {}
    vectors_by_id = {}
    for path, question_id, dimensions, blob, fingerprint in stored:
        entry = (int(dimensions), blob, fingerprint)
        normalized_path = _normalized_index_path(path)
        if normalized_path:
            vectors_by_path[normalized_path] = entry
        normalized_id = str(question_id or "").strip()
        if normalized_id:
            vectors_by_id[normalized_id] = entry

    reference_entry = vectors_by_id.get(reference_id) or vectors_by_path.get(reference_path)
    reference_dimensions = None
    reference_vector = None
    reference_norm = 1.0
    if reference_entry and reference_entry[2] == row_fingerprint(reference_row):
        reference_dimensions, reference_blob, _ = reference_entry
        reference_vector = _unpack_vector(reference_blob, reference_dimensions)
        reference_norm = math.sqrt(sum(value * value for value in reference_vector)) or 1.0

    scored = []
    seen_keys = set()
    for row in rows:
        row_id = str(row.get("SQLite题目ID") or row.get("题目ID") or "").strip()
        row_path = index_key(row)
        if (reference_id and row_id == reference_id) or (reference_path and row_path == reference_path):
            continue
        entry = vectors_by_id.get(row_id) or vectors_by_path.get(row_path)
        unique_key = row_id or row_path
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        semantic_score = None
        if entry and reference_vector and entry[2] == row_fingerprint(row):
            dimensions, blob, _ = entry
            if dimensions == reference_dimensions:
                vector = _unpack_vector(blob, dimensions)
                denominator = reference_norm * (math.sqrt(sum(value * value for value in vector)) or 1.0)
                semantic_score = sum(left * right for left, right in zip(reference_vector, vector)) / denominator
        ranking = combined_similarity_score(reference_row, row, semantic_score, mode=mode)
        scored.append({
            "row": row,
            "score": ranking["score"],
            "semantic_score": ranking["semantic_score"],
            "gaokao_score": ranking.get("gaokao_score"),
            "gaokao_detail": ranking.get("gaokao_detail"),
            "relationship_kind": ranking.get("relationship_kind"),
            "relationship_eligible": ranking.get("relationship_eligible", False),
            "relationship_score": ranking.get("relationship_score"),
            "components": ranking["components"],
            "reason": ranking["reason"],
            "comparison": ranking["comparison"],
            "mode": mode,
            "effective_weights": ranking["effective_weights"],
            "path": row.get("相对文件路径", ""),
        })
    _sort_similarity_results(scored, mode)
    return scored[: max(1, int(top_k))]


def _rank_local_similarity(
    reference_row: dict,
    rows: list[dict],
    reference_id: str,
    reference_path: str,
    top_k: int,
    *,
    mode: str = "recommendation",
) -> list[dict]:
    """Use the shared text rule when embedding configuration is unavailable."""
    scored = []
    for index, row in enumerate(rows):
        row_id = str(row.get("SQLite题目ID") or row.get("题目ID") or "").strip()
        row_path = index_key(row)
        if (reference_id and row_id == reference_id) or (reference_path and row_path == reference_path):
            continue
        ranking = combined_similarity_score(reference_row, row, None, mode=mode)
        scored.append({
            "row": row,
            "score": ranking["score"],
            "semantic_score": None,
            "gaokao_score": ranking.get("gaokao_score"),
            "gaokao_detail": ranking.get("gaokao_detail"),
            "relationship_kind": ranking.get("relationship_kind"),
            "relationship_eligible": ranking.get("relationship_eligible", False),
            "relationship_score": ranking.get("relationship_score"),
            "components": ranking["components"],
            "reason": ranking["reason"],
            "comparison": ranking["comparison"],
            "mode": mode,
            "effective_weights": ranking["effective_weights"],
            "path": row.get("相对文件路径", ""),
            "_index": index,
        })
    _sort_similarity_results(scored, mode)
    return scored[: max(1, int(top_k))]


def _sort_similarity_results(scored: list[dict], mode: str) -> None:
    def key(item):
        if mode == "verification":
            group = {"same_question": 2, "similar_question": 1}.get(item.get("relationship_kind"), 0)
            return (group, float(item.get("gaokao_score") or 0), item["score"])
        return (item["score"],)
    scored.sort(key=key, reverse=True)
