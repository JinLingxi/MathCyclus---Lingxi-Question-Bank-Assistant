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
import sqlite3
import struct
import time
from contextlib import closing
from typing import Callable, Iterable

from utils.core_config import BASE_DIR


SEMANTIC_INDEX_PATH = os.path.join(BASE_DIR, "utils", "semantic_index.sqlite3")
SEMANTIC_INDEX_VERSION = 1


class SemanticSearchError(RuntimeError):
    """Raised for configuration, transport, or response errors."""


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
    conn.commit()
    return conn


def embedding_text(row: dict) -> str:
    """Build the searchable text while keeping answers out of the first index."""
    parts = [
        f"知识板块：{row.get('知识板块', '') or ''}",
        f"题型：{row.get('题型', '') or ''}",
        f"标签：{row.get('标签', '') or ''}",
        f"题干：{row.get('题干', '') or ''}",
    ]
    return "\n".join(part.strip() for part in parts if part.split("：", 1)[-1].strip())


def row_fingerprint(row: dict) -> str:
    payload = {
        key: str(row.get(key, "") or "").strip()
        for key in ("文件名称", "相对文件路径", "知识板块", "题型", "标签", "题干")
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


def _embeddings_url(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise SemanticSearchError("未配置 Base URL")
    if url.endswith("/chat/completions"):
        url = url[: -len("/chat/completions")]
    if not url.endswith("/v1") and "/v1/" not in url:
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

    try:
        response = requests.post(
            _embeddings_url(base_url),
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
        for offset in range(0, total, 32):
            batch = pending[offset : offset + 32]
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
        conn.execute(
            "INSERT INTO semantic_meta(key, value) VALUES('version', ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(SEMANTIC_INDEX_VERSION),),
        )
        conn.commit()
        return {"total": len(valid_rows), "updated": total, "removed": max(0, len(existing) - len(current_paths))}


def invalidate_path(relative_path: str) -> None:
    if not relative_path or not os.path.exists(SEMANTIC_INDEX_PATH):
        return
    with closing(_connect()) as conn:
        conn.execute("DELETE FROM semantic_embeddings WHERE relative_path = ?", (relative_path.replace("/", "\\"),))
        conn.commit()


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
    return scored[: max(1, int(top_k))]
