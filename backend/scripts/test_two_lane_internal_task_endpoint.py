from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import main as mainmod
from services.two_lane_sources.internal_tasks import TwoLaneTaskBusyError, TwoLaneTaskMissingError


def _fake_handler(payload: dict):
    kind = payload.get("kind")
    if kind == "busy":
        raise TwoLaneTaskBusyError("task busy")
    if kind == "missing":
        raise TwoLaneTaskMissingError("task missing")
    return {"handled": True, "kind": payload.get("kind")}


def main() -> int:
    original_validate = mainmod.validate_two_lane_dispatch_token
    original_handler = mainmod.run_two_lane_internal_task_payload_sync
    mainmod.validate_two_lane_dispatch_token = lambda token: str(token or "") == "test-token"
    mainmod.run_two_lane_internal_task_payload_sync = _fake_handler
    try:
        client = TestClient(mainmod.app)
        unauthorized = client.post(
            "/api/internal/quellen-finder/two-lane/task",
            json={"kind": "openalex_query"},
        )
        if unauthorized.status_code != 401:
            raise RuntimeError(f"Expected 401, got {unauthorized.status_code}: {unauthorized.text}")

        authorized = client.post(
            "/api/internal/quellen-finder/two-lane/task",
            headers={"X-TwoLane-Dispatch-Token": "test-token"},
            json={"kind": "openalex_query"},
        )
        if authorized.status_code != 202:
            raise RuntimeError(f"Expected 202, got {authorized.status_code}: {authorized.text}")
        payload = authorized.json()
        if not bool(payload.get("success")) or ((payload.get("result") or {}).get("kind")) != "openalex_query":
            raise RuntimeError(f"Unexpected authorized payload: {payload}")

        busy = client.post(
            "/api/internal/quellen-finder/two-lane/task",
            headers={"X-TwoLane-Dispatch-Token": "test-token"},
            json={"kind": "busy"},
        )
        if busy.status_code != 503:
            raise RuntimeError(f"Expected 503, got {busy.status_code}: {busy.text}")

        missing = client.post(
            "/api/internal/quellen-finder/two-lane/task",
            headers={"X-TwoLane-Dispatch-Token": "test-token"},
            json={"kind": "missing"},
        )
        if missing.status_code != 500:
            raise RuntimeError(f"Expected 500, got {missing.status_code}: {missing.text}")
    finally:
        mainmod.validate_two_lane_dispatch_token = original_validate
        mainmod.run_two_lane_internal_task_payload_sync = original_handler

    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_internal_task_endpoint_latest.json"
    out_path.write_text(
        json.dumps(
            {
                "ok": True,
                "unauthorized_status": 401,
                "authorized_status": 202,
                "busy_status": 503,
                "missing_status": 500,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(out_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
