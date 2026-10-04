"""Exercise the localhost draft API without touching the real database."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.local_api_service import create_local_api_server
from services.schema_migration_service import apply_pending_migrations


def request(base: str, path: str, *, method: str = "GET", token: str = "smoke-token", body: dict | None = None):
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(base + path, data=data, headers=headers, method=method)
    with urllib.request.urlopen(req, timeout=10) as response:
        return response.status, json.loads(response.read().decode("utf-8"))


def main() -> int:
    source_db = ROOT / "data" / "mathcyclus.sqlite3"
    with tempfile.TemporaryDirectory(prefix="mathcyclus_local_api_smoke_") as temp_dir:
        db_path = Path(temp_dir) / source_db.name
        shutil.copy2(source_db, db_path)
        apply_pending_migrations(str(db_path), apply=True, backup=False, allow_external_database=True)
        server = create_local_api_server(
            port=0, db_path=str(db_path), auth_token="smoke-token", migrate=False,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            status, health = request(base, "/health")
            assert status == 200 and health["draft_only"] is True

            status, similarity = request(
                base,
                "/api/v1/questions/similarity",
                method="POST",
                body={
                    "stem_tex": r"已知函数 $f(x)=x^2+4x+4$，求其最小值。",
                    "minimum_score": 0.4,
                    "max_results": 5,
                },
            )
            assert status == 200
            assert similarity["algorithm"] == "gaokao_web_bind_sim_v1"
            assert isinstance(similarity["items"], list)
            if similarity["items"]:
                assert {"score", "channel", "reasons"}.issubset(similarity["items"][0])

            status, paper_match = request(
                base,
                "/api/v1/papers/match",
                method="POST",
                body={
                    "year": "2024",
                    "paper_series": "G",
                    "paper_name": "全国 I 卷",
                },
            )
            assert status == 200
            assert paper_match["algorithm"] == "paper_catalog_match_v1"
            assert "match" in paper_match and "candidates" in paper_match["match"]

            status, created = request(
                base,
                "/api/v1/drafts",
                method="POST",
                body={
                    "items": [{
                        "source_item_id": "api-smoke-1",
                        "stem_tex": r"$x=1$",
                        "review_status": "approved",
                    }],
                },
            )
            assert status == 200 and created["human_review_required"] is True
            draft_id = created["results"][0]["draft_id"]
            assert created["results"][0]["draft"]["review_status"] != "approved"

            status, checked = request(base, f"/api/v1/drafts/{draft_id}/validate", method="POST")
            assert status == 200 and checked["draft_id"] == draft_id

            status, updated = request(
                base,
                f"/api/v1/drafts/{draft_id}",
                method="PATCH",
                body={"updates": {"note": "api smoke"}},
            )
            assert status == 200 and "note" in updated["changed_fields"]

            status, batch_validation = request(
                base,
                f"/api/v1/batches/{created['batch_id']}/validate",
                method="POST",
                body={},
            )
            assert status == 200
            assert batch_validation["draft_count"] == 1
            assert batch_validation["human_review_required"] is True
            assert batch_validation["results"][0]["draft_id"] == draft_id

            status, events = request(base, f"/api/v1/drafts/{draft_id}/review-events")
            assert status == 200 and events["items"]

            try:
                request(base, f"/api/v1/drafts/{draft_id}/approve", method="POST", body={})
            except urllib.error.HTTPError as exc:
                assert exc.code == 404
            else:
                raise AssertionError("draft-only API unexpectedly exposed approval")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)
    print("local_api_smoke=ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
