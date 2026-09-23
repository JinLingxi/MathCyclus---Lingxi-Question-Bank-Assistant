"""Small, configurable client for the MinerU cloud v4 API.

This module only owns transport and result staging.  Converting MinerU's
content list into our PDF draft format remains the document parser's job.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
import zipfile
from pathlib import Path
from typing import Any

import requests


DEFAULT_BASE_URL = "https://mineru.net/api/v4"
DEFAULT_TIMEOUT_SECONDS = 30
DEFAULT_POLL_INTERVAL_SECONDS = 3
DEFAULT_POLL_TIMEOUT_SECONDS = 900


def mineru_cloud_config() -> dict[str, Any]:
    token = str(os.getenv("MINERU_API_TOKEN") or os.getenv("MINERU_API_KEY") or "").strip()
    base_url = str(os.getenv("MINERU_API_BASE_URL") or DEFAULT_BASE_URL).strip().rstrip("/")
    try:
        timeout = max(5, int(os.getenv("MINERU_API_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT_SECONDS
    try:
        poll_interval = max(1, int(os.getenv("MINERU_API_POLL_INTERVAL_SECONDS", DEFAULT_POLL_INTERVAL_SECONDS)))
    except (TypeError, ValueError):
        poll_interval = DEFAULT_POLL_INTERVAL_SECONDS
    try:
        poll_timeout = max(30, int(os.getenv("MINERU_API_POLL_TIMEOUT_SECONDS", DEFAULT_POLL_TIMEOUT_SECONDS)))
    except (TypeError, ValueError):
        poll_timeout = DEFAULT_POLL_TIMEOUT_SECONDS
    return {
        "configured": bool(token),
        "base_url": base_url,
        "token": token,
        "timeout_seconds": timeout,
        "poll_interval_seconds": poll_interval,
        "poll_timeout_seconds": poll_timeout,
    }


def mineru_cloud_available() -> bool:
    return bool(mineru_cloud_config()["configured"])


def _headers(config: dict[str, Any]) -> dict[str, str]:
    return {"Authorization": f"Bearer {config['token']}", "Content-Type": "application/json"}


def _json_response(response: requests.Response) -> dict[str, Any]:
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("MinerU API 返回格式不是 JSON 对象")
    code = payload.get("code")
    if code not in (None, 0, 200):
        raise RuntimeError(str(payload.get("msg") or payload.get("message") or f"MinerU API code={code}"))
    return payload


def _data(payload: dict[str, Any]) -> dict[str, Any]:
    value = payload.get("data")
    if isinstance(value, dict):
        return value
    return payload


def _safe_extract_zip(zip_path: Path, output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted: list[str] = []
    root = output_dir.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (output_dir / member.filename).resolve()
            try:
                target.relative_to(root)
            except ValueError as exc:
                raise ValueError(f"MinerU 结果包包含非法路径：{member.filename}") from exc
            if member.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, target.open("wb") as destination:
                destination.write(source.read())
            extracted.append(target.relative_to(root).as_posix())
    return extracted


def submit_pdf(pdf_path: str | Path, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    """Request a signed upload URL and upload one PDF to MinerU."""
    settings = config or mineru_cloud_config()
    source = Path(pdf_path).resolve()
    if not source.is_file() or source.suffix.lower() != ".pdf":
        raise ValueError("MinerU 只接受存在的 PDF 文件")
    if not settings.get("configured"):
        raise RuntimeError("未配置 MINERU_API_TOKEN")
    response = requests.post(
        f"{settings['base_url']}/file-urls/batch",
        headers=_headers(settings),
        json={"files": [{"name": source.name}]},
        timeout=settings["timeout_seconds"],
    )
    payload = _json_response(response)
    data = _data(payload)
    batch_id = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") or data.get("urls") or []
    if isinstance(file_urls, dict):
        file_urls = list(file_urls.values())
    if not batch_id or not file_urls:
        raise RuntimeError("MinerU 未返回 batch_id 或上传地址")
    upload_url = str(file_urls[0]).strip()
    if not upload_url:
        raise RuntimeError("MinerU 返回的上传地址为空")
    with source.open("rb") as file_obj:
        upload_response = requests.put(upload_url, data=file_obj, timeout=max(settings["timeout_seconds"], 120))
    upload_response.raise_for_status()
    return {
        "batch_id": batch_id,
        "file_name": source.name,
        "sha256": _sha256(source),
    }


def poll_batch(batch_id: str, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = config or mineru_cloud_config()
    safe_batch_id = str(batch_id or "").strip()
    if not safe_batch_id:
        raise ValueError("batch_id 不能为空")
    deadline = time.monotonic() + settings["poll_timeout_seconds"]
    last_payload: dict[str, Any] = {}
    while time.monotonic() < deadline:
        response = requests.get(
            f"{settings['base_url']}/extract/task/{safe_batch_id}",
            headers={"Authorization": f"Bearer {settings['token']}"},
            timeout=settings["timeout_seconds"],
        )
        payload = _json_response(response)
        last_payload = payload
        data = _data(payload)
        results = data.get("extract_result") or data.get("results") or []
        if isinstance(results, dict):
            results = [results]
        states = [str(item.get("state") or item.get("status") or "").lower() for item in results if isinstance(item, dict)]
        if any(state in {"failed", "error", "failure"} for state in states):
            raise RuntimeError(json.dumps(payload, ensure_ascii=False))
        if results and all(state in {"done", "success", "succeeded", "completed"} for state in states):
            return {"batch_id": safe_batch_id, "payload": payload, "results": results}
        time.sleep(settings["poll_interval_seconds"])
    raise TimeoutError(f"MinerU 解析超时：batch_id={safe_batch_id}; last={json.dumps(last_payload, ensure_ascii=False)}")


def download_batch_results(
    batch_result: dict[str, Any],
    output_dir: str | Path,
    *,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    settings = config or mineru_cloud_config()
    target_dir = Path(output_dir).resolve()
    results = batch_result.get("results") or []
    downloads: list[dict[str, Any]] = []
    for index, result in enumerate(results, start=1):
        if not isinstance(result, dict):
            continue
        url = str(result.get("full_zip_url") or result.get("zip_url") or result.get("download_url") or "").strip()
        if not url:
            continue
        response = requests.get(url, timeout=max(settings["timeout_seconds"], 120))
        response.raise_for_status()
        zip_path = target_dir / f"mineru_result_{index:03d}.zip"
        zip_path.parent.mkdir(parents=True, exist_ok=True)
        zip_path.write_bytes(response.content)
        extracted = _safe_extract_zip(zip_path, target_dir / f"result_{index:03d}")
        downloads.append({"zip_path": str(zip_path), "output_dir": str(zip_path.parent / f"result_{index:03d}"), "extracted": extracted})
    if not downloads:
        raise RuntimeError("MinerU 已完成，但没有返回可下载的解析结果")
    return {"batch_id": batch_result.get("batch_id") or "", "downloads": downloads}


def parse_pdf_to_directory(pdf_path: str | Path, output_dir: str | Path, *, config: dict[str, Any] | None = None) -> dict[str, Any]:
    submitted = submit_pdf(pdf_path, config=config)
    completed = poll_batch(submitted["batch_id"], config=config)
    downloaded = download_batch_results(completed, output_dir, config=config)
    return {**submitted, **downloaded, "parser": "mineru_cloud"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
