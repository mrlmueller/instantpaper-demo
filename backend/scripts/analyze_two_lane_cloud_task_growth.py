from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService


def _parse_ts(value: Any) -> datetime | None:
    if value is None:
        return None
    if hasattr(value, "to_datetime"):
        try:
            value = value.to_datetime()
        except Exception:
            return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except Exception:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _task_sequence_index(task_key: str) -> int | None:
    parts = str(task_key or "").split("-")
    for candidate in (parts[-1:] + parts[-2:-1]):
        if not candidate:
            continue
        try:
            return int(candidate[0])
        except Exception:
            continue
    return None


def _dt_to_iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _summarize_provider(run_ref, provider: str, seeded_tasks_hint: int) -> dict[str, Any]:
    docs: list[dict[str, Any]] = []
    prefix = f"{provider}--"
    for snap in run_ref.collection("twoLaneProviderTasks").stream():
        if not str(snap.id).startswith(prefix):
            continue
        data = snap.to_dict() or {}
        docs.append(
            {
                "id": snap.id,
                "taskKey": str(data.get("taskKey") or ""),
                "status": str(data.get("status") or ""),
                "createdAt": _parse_ts(data.get("createdAt")),
                "updatedAt": _parse_ts(data.get("updatedAt")),
                "completedAt": _parse_ts(data.get("completedAt")),
                "claimCount": int(data.get("claimCount") or 0),
                "failCount": int(data.get("failCount") or 0),
            }
        )

    status_counts = Counter(str(item.get("status") or "").strip().lower() for item in docs)
    created = [item["createdAt"] for item in docs if isinstance(item.get("createdAt"), datetime)]
    completed = [item["completedAt"] for item in docs if isinstance(item.get("completedAt"), datetime)]
    updated = [item["updatedAt"] for item in docs if isinstance(item.get("updatedAt"), datetime)]
    task_indices = [idx for idx in (_task_sequence_index(str(item.get("taskKey") or "")) for item in docs) if idx is not None]
    discovered_later = max(0, int(len(docs)) - int(max(seeded_tasks_hint, 0)))

    return {
        "provider": provider,
        "seeded_tasks_initial": int(max(seeded_tasks_hint, 0)),
        "task_docs_total": int(len(docs)),
        "task_docs_discovered_after_seed": int(discovered_later),
        "recursive_enqueue_detected": bool(len(docs) > int(max(seeded_tasks_hint, 0))),
        "status_counts": dict(status_counts),
        "max_task_sequence_seen": max(task_indices) if task_indices else None,
        "first_task_created_at": _dt_to_iso(min(created) if created else None),
        "last_task_created_at": _dt_to_iso(max(created) if created else None),
        "last_task_completed_at": _dt_to_iso(max(completed) if completed else None),
        "last_task_updated_at": _dt_to_iso(max(updated) if updated else None),
        "task_creation_span_seconds": (
            (max(created) - min(created)).total_seconds() if len(created) >= 2 else 0.0
        ),
        "sample_open_tasks": [
            {
                "taskKey": str(item.get("taskKey") or ""),
                "status": str(item.get("status") or ""),
                "claimCount": int(item.get("claimCount") or 0),
                "failCount": int(item.get("failCount") or 0),
            }
            for item in docs
            if str(item.get("status") or "").strip().lower() not in {"success", "cancelled", "skipped"}
        ][:20],
    }


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze how a cloud two-lane run grows its provider task set over time.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output-name", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    fs = QuellenFinderFirestoreService()
    run_doc = fs.get_run(user_id=args.user_id, projekt_id=args.project_id, run_id=args.run_id)
    run_ref = fs.run_ref(args.user_id, args.project_id, args.run_id)

    split = run_doc.get("splitExecution") if isinstance(run_doc.get("splitExecution"), dict) else {}
    artifacts = run_doc.get("twoLaneArtifacts") if isinstance(run_doc.get("twoLaneArtifacts"), dict) else {}
    provider_work = run_doc.get("providerWork") if isinstance(run_doc.get("providerWork"), dict) else {}

    result = {
        "user_id": args.user_id,
        "project_id": args.project_id,
        "run_id": args.run_id,
        "status": run_doc.get("status"),
        "progress": run_doc.get("progress"),
        "splitExecution": split,
        "providerWork": provider_work,
        "providers": {
            "openalex": _summarize_provider(
                run_ref,
                "openalex",
                int(
                    (
                        ((artifacts.get("openalex_fetch") or {}) if isinstance(artifacts.get("openalex_fetch"), dict) else {})
                        .get("seededTasks")
                        or 0
                    )
                ),
            ),
            "semanticscholar": _summarize_provider(
                run_ref,
                "semanticscholar",
                int(
                    (
                        ((artifacts.get("s2_fetch") or {}) if isinstance(artifacts.get("s2_fetch"), dict) else {})
                        .get("seededTasks")
                        or 0
                    )
                ),
            ),
        },
    }

    output_name = str(args.output_name or "").strip() or f"cloud_task_growth_{args.run_id}.json"
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "cloud_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / output_name
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps({"ok": True, "output": str(out_path), "result": result}, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
