from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

FASTAPI_ROOT = Path(__file__).resolve().parents[1]
if str(FASTAPI_ROOT) not in sys.path:
    sys.path.insert(0, str(FASTAPI_ROOT))

from services.firebase_service import firebase_service


SUBCOLLECTION_NAMES = ["pdfScanDocs", "pdfScanSections", "pdfScanDetails"]


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(value)


def _age_seconds(value: Any) -> float | None:
    if not isinstance(value, datetime):
        return None
    dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds(), 1)


def _count_docs(col_ref: Any) -> int:
    return sum(1 for _ in col_ref.stream())


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return _to_iso(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _run_payload(snap: Any) -> dict[str, Any]:
    data = snap.to_dict() or {}
    parts = list((snap.reference.path or "").split("/"))
    payload = {
        "runId": snap.id,
        "path": snap.reference.path,
        "userId": parts[1] if len(parts) > 1 else None,
        "projectId": parts[3] if len(parts) > 3 else None,
        "kind": data.get("kind"),
        "status": data.get("status"),
        "errorMessage": data.get("errorMessage"),
        "hadPartialFailures": bool(data.get("hadPartialFailures")),
        "createdAt": _to_iso(data.get("createdAt")),
        "startedAt": _to_iso(data.get("startedAt")),
        "updatedAt": _to_iso(data.get("updatedAt")),
        "finishedAt": _to_iso(data.get("finishedAt")),
        "updatedAgeSeconds": _age_seconds(data.get("updatedAt")),
        "progress": _json_safe(data.get("progress") or {}),
        "job": _json_safe(data.get("job") or {}),
        "resultCount": data.get("resultCount"),
        "summary": _json_safe(data.get("summary") or {}),
        "kapitelIds": list(data.get("kapitelIds") or []),
        "pdfIds": list(data.get("pdfIds") or []),
        "subcollections": {},
    }
    for name in SUBCOLLECTION_NAMES:
        payload["subcollections"][name] = _count_docs(snap.reference.collection(name))
    return payload


def _find_run_by_id(run_id: str) -> Any | None:
    db = firebase_service.db
    for snap in db.collection_group("researchRuns").stream():
        if snap.id == run_id:
            return snap
    return None


def _list_latest_runs(limit: int) -> list[dict[str, Any]]:
    db = firebase_service.db
    rows: list[tuple[Any, dict[str, Any]]] = []
    for snap in db.collection_group("researchRuns").stream():
        data = snap.to_dict() or {}
        if str(data.get("kind") or "") != "pdf_scan":
            continue
        rows.append((data.get("createdAt"), _run_payload(snap)))
    rows.sort(key=lambda item: item[0] or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return [row for _, row in rows[: max(1, int(limit))]]


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return

    print(f"runId: {payload.get('runId')}")
    print(f"path: {payload.get('path')}")
    print(f"status: {payload.get('status')} | kind: {payload.get('kind')} | hadPartialFailures: {payload.get('hadPartialFailures')}")
    print(f"createdAt: {payload.get('createdAt')}")
    print(f"startedAt: {payload.get('startedAt')}")
    print(f"updatedAt: {payload.get('updatedAt')} | age_s: {payload.get('updatedAgeSeconds')}")
    print(f"finishedAt: {payload.get('finishedAt')}")
    print(f"errorMessage: {payload.get('errorMessage')}")
    print(f"progress: {json.dumps(payload.get('progress') or {}, ensure_ascii=False)}")
    print(f"job: {json.dumps(payload.get('job') or {}, ensure_ascii=False)}")
    print(f"summary: {json.dumps(payload.get('summary') or {}, ensure_ascii=False)}")
    print(f"subcollections: {json.dumps(payload.get('subcollections') or {}, ensure_ascii=False)}")
    print(f"kapitelIds: {payload.get('kapitelIds')}")
    print(f"pdfIds_count: {len(list(payload.get('pdfIds') or []))}")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect Firestore state for Quellen-Finder PDF scan runs.")
    parser.add_argument("--run-id", default="", help="Exact researchRuns document id to inspect.")
    parser.add_argument("--latest", type=int, default=5, help="List the latest N pdf_scan runs when --run-id is omitted.")
    parser.add_argument("--watch", action="store_true", help="Poll repeatedly.")
    parser.add_argument("--poll-seconds", type=float, default=10.0, help="Polling interval for --watch.")
    parser.add_argument("--json", action="store_true", help="Print JSON payloads.")
    return parser


def main() -> int:
    args = build_arg_parser().parse_args()
    poll_seconds = max(1.0, float(args.poll_seconds))

    while True:
        if args.run_id:
            snap = _find_run_by_id(str(args.run_id).strip())
            if snap is None:
                print(f"Run not found: {args.run_id}")
            else:
                _print_payload(_run_payload(snap), as_json=bool(args.json))
        else:
            rows = _list_latest_runs(int(args.latest))
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=2))
            else:
                for index, row in enumerate(rows, start=1):
                    print(f"[{index}] {row.get('runId')} | status={row.get('status')} | updatedAt={row.get('updatedAt')} | subcollections={row.get('subcollections')}")
                    print(f"    progress={json.dumps(row.get('progress') or {}, ensure_ascii=False)}")
                    print(f"    path={row.get('path')}")
        if not args.watch:
            return 0
        print(f"\n--- polling again in {poll_seconds:.1f}s ---\n")
        time.sleep(poll_seconds)


if __name__ == "__main__":
    raise SystemExit(main())
