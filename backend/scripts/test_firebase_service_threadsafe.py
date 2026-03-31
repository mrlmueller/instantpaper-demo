from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import services.firebase_service as firebase_module


def main() -> int:
    service_cls = firebase_module.FirebaseService
    original_get_app = firebase_module.firebase_admin.get_app
    original_initialize_app = firebase_module.firebase_admin.initialize_app
    original_client = firebase_module.firestore.client

    state = {"initialized": False, "initialize_calls": 0, "client_calls": 0}
    fake_db = object()

    def fake_get_app():
        if not state["initialized"]:
            raise ValueError("no app")
        return object()

    def fake_initialize_app(_cred=None, _options=None):
        time.sleep(0.05)
        state["initialized"] = True
        state["initialize_calls"] += 1
        return object()

    def fake_client():
        state["client_calls"] += 1
        return fake_db

    service_cls._instance = None
    service_cls._initialized = False
    service_cls._db = None
    firebase_module.firebase_admin.get_app = fake_get_app
    firebase_module.firebase_admin.initialize_app = fake_initialize_app
    firebase_module.firestore.client = fake_client

    try:
        service = service_cls()
        errors: list[str] = []
        results: list[object] = []

        def worker() -> None:
            try:
                results.append(service.db)
            except Exception as exc:  # pragma: no cover - explicit test failure path
                errors.append(repr(exc))

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

        if errors:
            raise RuntimeError(f"Concurrent db access raised errors: {errors}")
        if any(item is not fake_db for item in results):
            raise RuntimeError("Expected all worker threads to receive the same cached Firestore client.")
        if state["initialize_calls"] != 1:
            raise RuntimeError(f"Expected exactly one initialize_app call, got {state['initialize_calls']}")
        if state["client_calls"] != 1:
            raise RuntimeError(f"Expected exactly one firestore.client call, got {state['client_calls']}")
    finally:
        firebase_module.firebase_admin.get_app = original_get_app
        firebase_module.firebase_admin.initialize_app = original_initialize_app
        firebase_module.firestore.client = original_client
        service_cls._instance = None
        service_cls._initialized = False
        service_cls._db = None

    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_firebase_service_threadsafe_latest.json"
    out_path.write_text(
        json.dumps(
            {
                "ok": True,
                "threads": 8,
                "initialize_calls": state["initialize_calls"],
                "client_calls": state["client_calls"],
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
