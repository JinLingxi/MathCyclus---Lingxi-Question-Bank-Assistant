from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solaire.common.security import assert_within_project


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def edu_analysis_root(project_root: Path) -> Path:
    root = (project_root / "result" / "edu_analysis").resolve()
    assert_within_project(project_root, root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def scripts_dir(project_root: Path) -> Path:
    d = edu_analysis_root(project_root) / "scripts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def jobs_dir(project_root: Path) -> Path:
    d = edu_analysis_root(project_root) / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def outputs_dir(project_root: Path) -> Path:
    d = edu_analysis_root(project_root) / "outputs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _requests_index_path(project_root: Path) -> Path:
    return edu_analysis_root(project_root) / "request_index.json"


def _audit_log_path(project_root: Path) -> Path:
    return edu_analysis_root(project_root) / "audit.log.jsonl"


def _read_json(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def get_job_for_request(project_root: Path, request_id: str) -> str | None:
    path = _requests_index_path(project_root)
    if not path.is_file():
        return None
    try:
        data = _read_json(path)
    except Exception:
        return None
    value = data.get(request_id)
    return str(value) if isinstance(value, str) else None


def bind_request_to_job(project_root: Path, request_id: str, job_id: str) -> None:
    path = _requests_index_path(project_root)
    data: dict[str, Any] = {}
    if path.is_file():
        try:
            data = _read_json(path)
        except Exception:
            data = {}
    data[request_id] = job_id
    _write_json(path, data)


def append_audit_record(project_root: Path, record: dict[str, Any]) -> None:
    path = _audit_log_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {**record, "created_at": _now()}
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def save_script(project_root: Path, script: dict[str, Any]) -> dict[str, Any]:
    script["updated_at"] = _now()
    if "created_at" not in script:
        script["created_at"] = script["updated_at"]
    path = scripts_dir(project_root) / f"{script['script_id']}.json"
    _write_json(path, script)
    return script


def load_script(project_root: Path, script_id: str) -> dict[str, Any]:
    path = scripts_dir(project_root) / f"{script_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Script not found: {script_id}")
    return _read_json(path)


def list_scripts(project_root: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(scripts_dir(project_root).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
        try:
            out.append(_read_json(p))
        except Exception:
            continue
    return out


def delete_script(project_root: Path, script_id: str) -> None:
    path = scripts_dir(project_root) / f"{script_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Script not found: {script_id}")
    path.unlink()


def save_output(project_root: Path, job_id: str, output: dict[str, Any]) -> str:
    path = outputs_dir(project_root) / f"{job_id}.json"
    _write_json(path, output)
    return f"outputs/{job_id}.json"


def load_output(project_root: Path, output_ref: str) -> dict[str, Any]:
    path = edu_analysis_root(project_root) / output_ref
    path = path.resolve()
    assert_within_project(project_root, path)
    if not path.is_file():
        raise FileNotFoundError(f"Output not found: {output_ref}")
    return _read_json(path)


def save_job(project_root: Path, job: dict[str, Any]) -> dict[str, Any]:
    job["updated_at"] = _now()
    if "created_at" not in job:
        job["created_at"] = job["updated_at"]
    path = jobs_dir(project_root) / f"{job['job_id']}.json"
    _write_json(path, job)
    return job


def load_job(project_root: Path, job_id: str) -> dict[str, Any]:
    path = jobs_dir(project_root) / f"{job_id}.json"
    if not path.is_file():
        raise FileNotFoundError(f"Job not found: {job_id}")
    return _read_json(path)


def list_jobs(project_root: Path, limit: int = 50) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in sorted(jobs_dir(project_root).glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:limit]:
        try:
            out.append(_read_json(p))
        except Exception:
            continue
    return out
