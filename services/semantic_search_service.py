"""Optional semantic search backed by an OpenAI-compatible embeddings endpoint.

The CSV index remains the source of truth.  This module stores only a rebuildable
derived index, so keyword search continues to work when embeddings are disabled
or the embedding service is unavailable.
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


SEMANTIC_INDEX_PATH = os.path.join(BASE_DIR, "utils", "semantic_index.sqlite3")
SEMANTIC_INDEX_VERSION = 1
EMBEDDING_BATCH_SIZE = 20
SEMANTIC_QUERY_CACHE_TTL = 60.0
SEMANTIC_QUERY_CACHE_MAX_ENTRIES = 128
_QUERY_CACHE: OrderedDict[tuple, tuple[float, list[dict]]] = OrderedDict()
SIMILARITY_WEIGHTS = {
    "semantic": 0.68,
    "formula": 0.15,
    "lexical": 0.09,
    "knowledge": 0.05,
    "question_type": 0.03,
}


class SemanticSearchError(RuntimeError):
    """Raised for configuration, transport, or response errors."""


def _clear_query_cache() -> None:
    _QUERY_CACHE.clear()


def _rows_cache_token(rows: list[dict]) -> str:
    payload = sorted(
        (
            str(row.get("鐩稿鏂囦欢璺緞") or "").strip().replace("/", "\\"),
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
    payload = {
        key: str(row.get(key, "") or "").strip()
        for key in ("文件名称", "相对文件路径", "知识板块", "题型", "标签", "题干", "选项")
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


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

    valid_rows = [row for row in rows if (row.get("相对文件路径") or "").strip() and embedding_text(row).strip()]
    _clear_query_cache()
    with closing(_connect()) as conn:
        existing = {} if force else _existing_fingerprints(conn, model_name)
        existing_dimensions = {dimensions for _, dimensions in existing.values()}
        if len(existing_dimensions) > 1:
            raise SemanticSearchError("语义索引中的向量维度不一致，请强制重建索引")
        expected_dimensions = next(iter(existing_dimensions), None)
        current_paths = {row["相对文件路径"].strip() for row in valid_rows}
        if current_paths:
            placeholders = ",".join("?" for _ in current_paths)
            conn.execute(
                f"DELETE FROM semantic_embeddings WHERE relative_path NOT IN ({placeholders})",
                tuple(current_paths),
            )
        else:
            conn.execute("DELETE FROM semantic_embeddings")

        pending = [
            row for row in valid_rows
            if force
            or row["相对文件路径"].strip() not in existing
            or existing[row["相对文件路径"].strip()][0] != row_fingerprint(row)
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
                relative_path = row["相对文件路径"].strip()
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
                    (relative_path, str(row.get("题目ID", "") or ""), row_fingerprint(row), model_name, dimensions, blob, now),
                )
            if progress:
                progress(min(offset + len(batch), total), total)
        conn.execute("DELETE FROM semantic_pending")
        conn.execute(
            "INSERT INTO semantic_meta(key, value) VALUES('version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SEMANTIC_INDEX_VERSION),),
        )
        conn.commit()
        return {"total": len(valid_rows), "updated": total, "removed": max(0, len(existing) - len(current_paths))}


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
    row_by_path = {
        str(row.get("相对文件路径") or "").strip().replace("/", "\\"): row
        for row in rows
        if str(row.get("相对文件路径") or "").strip()
    }
    with closing(_connect()) as conn:
        pending_paths = [item[0] for item in conn.execute("SELECT relative_path FROM semantic_pending ORDER BY requested_at")]
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
                relative_path = str(row.get("相对文件路径") or "").strip().replace("/", "\\")
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
                    (relative_path, str(row.get("题目ID", "") or ""), row_fingerprint(row), model_name, dimensions, blob, now),
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
        stored = conn.execute("SELECT relative_path, dimensions, vector FROM semantic_embeddings").fetchall()
    vectors = request_embeddings(base_url, api_key, model_name, [query.strip()])
    query_vector = vectors[0]
    query_norm = math.sqrt(sum(value * value for value in query_vector)) or 1.0
    row_by_path = {(row.get("相对文件路径") or "").replace("/", "\\"): row for row in rows}
    for relative_path, dimensions, blob in stored:
        row = row_by_path.get(relative_path.replace("/", "\\"))
        if not row:
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


def combined_similarity_score(reference_row: dict, candidate_row: dict, semantic_score: float) -> dict:
    """Combine semantic recall with local mathematical-structure signals."""
    reference_text = _row_similarity_text(reference_row)
    candidate_text = _row_similarity_text(candidate_row)
    components = {
        "semantic": max(0.0, min(1.0, float(semantic_score))),
        "formula": _set_similarity(_formula_features(reference_text), _formula_features(candidate_text)),
        "lexical": _lexical_similarity(reference_text, candidate_text),
        "knowledge": _metadata_similarity(reference_row.get("知识板块"), candidate_row.get("知识板块")),
        "question_type": _metadata_similarity(reference_row.get("题型"), candidate_row.get("题型")),
    }
    available_weight = sum(
        SIMILARITY_WEIGHTS[name]
        for name, value in components.items()
        if value is not None
    )
    score = sum(
        SIMILARITY_WEIGHTS[name] * value
        for name, value in components.items()
        if value is not None
    ) / (available_weight or 1.0)

    reasons = []
    if components["knowledge"] is not None and components["knowledge"] >= 0.8:
        reasons.append("同知识板块")
    if components["question_type"] is not None and components["question_type"] >= 0.8:
        reasons.append("同题型")
    if components["formula"] is not None and components["formula"] >= 0.35:
        reasons.append("公式结构接近")
    if components["lexical"] is not None and components["lexical"] >= 0.28:
        reasons.append("题干表述接近")
    if not reasons:
        reasons.append("语义接近")
    return {
        "score": float(max(0.0, min(1.0, score))),
        "semantic_score": components["semantic"],
        "components": components,
        "reason": " · ".join(reasons),
    }


def search_similar_row(
    reference_row: dict,
    rows: list[dict],
    model_name: str,
    top_k: int = 200,
) -> list[dict]:
    """Rank indexed rows against an already-indexed reference row."""
    if not rows:
        return []
    if not model_name.strip():
        raise SemanticSearchError("请先配置 embedding 模型")
    reference_id = str(reference_row.get("SQLite题目ID") or reference_row.get("题目ID") or "").strip()
    reference_path = _normalized_index_path(reference_row.get("相对文件路径"))
    if not reference_id and not reference_path:
        raise SemanticSearchError("基准题缺少可关联的题目 ID 或索引路径")
    if not os.path.exists(SEMANTIC_INDEX_PATH):
        raise SemanticSearchError("语义索引尚未建立，请先更新语义索引")

    with closing(_connect()) as conn:
        indexed_models = [row[0] for row in conn.execute(
            "SELECT DISTINCT model_name FROM semantic_embeddings"
        ).fetchall()]
        if not indexed_models:
            raise SemanticSearchError("语义索引为空，请先更新语义索引")
        if len(indexed_models) != 1 or indexed_models[0] != model_name.strip():
            raise SemanticSearchError("当前 embedding 模型与索引不一致，请重建索引")
        stored = conn.execute(
            "SELECT relative_path, question_id, dimensions, vector FROM semantic_embeddings"
        ).fetchall()

    vectors_by_path = {}
    vectors_by_id = {}
    for path, question_id, dimensions, blob in stored:
        entry = (int(dimensions), blob)
        normalized_path = _normalized_index_path(path)
        if normalized_path:
            vectors_by_path[normalized_path] = entry
        normalized_id = str(question_id or "").strip()
        if normalized_id:
            vectors_by_id[normalized_id] = entry

    reference_entry = vectors_by_id.get(reference_id) or vectors_by_path.get(reference_path)
    if not reference_entry:
        raise SemanticSearchError("基准题尚未建立向量，请先更新语义索引")
    reference_dimensions, reference_blob = reference_entry
    reference_vector = _unpack_vector(reference_blob, reference_dimensions)
    reference_norm = math.sqrt(sum(value * value for value in reference_vector)) or 1.0

    scored = []
    seen_keys = set()
    for row in rows:
        row_id = str(row.get("SQLite题目ID") or row.get("题目ID") or "").strip()
        row_path = _normalized_index_path(row.get("相对文件路径"))
        if (reference_id and row_id == reference_id) or (reference_path and row_path == reference_path):
            continue
        entry = vectors_by_id.get(row_id) or vectors_by_path.get(row_path)
        if not entry:
            continue
        dimensions, blob = entry
        if dimensions != reference_dimensions:
            continue
        unique_key = row_id or row_path
        if unique_key in seen_keys:
            continue
        seen_keys.add(unique_key)
        vector = _unpack_vector(blob, dimensions)
        denominator = reference_norm * (math.sqrt(sum(value * value for value in vector)) or 1.0)
        semantic_score = sum(left * right for left, right in zip(reference_vector, vector)) / denominator
        ranking = combined_similarity_score(reference_row, row, semantic_score)
        scored.append({
            "row": row,
            "score": ranking["score"],
            "semantic_score": ranking["semantic_score"],
            "components": ranking["components"],
            "reason": ranking["reason"],
            "path": row.get("相对文件路径", ""),
        })
    scored.sort(key=lambda item: item["score"], reverse=True)
    return scored[: max(1, int(top_k))]
