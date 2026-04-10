from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.firebase_service import firebase_service


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "to_datetime"):
        try:
            value = value.to_datetime()
        except Exception:
            pass
    if isinstance(value, datetime):
        dt = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc).isoformat()
    return str(value)


def _dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return datetime.min.replace(tzinfo=timezone.utc)


def _num(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except Exception:
        return 0


def _json_safe(value: Any) -> Any:
    if hasattr(value, "to_datetime"):
        try:
            value = value.to_datetime()
        except Exception:
            return str(value)
    if isinstance(value, datetime):
        return _to_iso(value)
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    return value


def _find_projects_by_name(project_name: str) -> list[dict[str, Any]]:
    matches: list[dict[str, Any]] = []
    db = firebase_service.db
    for snap in db.collection_group("projects").stream():
        data = snap.to_dict() or {}
        name = str(data.get("name") or "").strip()
        if name != project_name:
            continue
        parts = snap.reference.path.split("/")
        user_id = parts[1] if len(parts) > 1 else None
        matches.append(
            {
                "userId": user_id,
                "projectId": snap.id,
                "path": snap.reference.path,
                "name": name,
                "createdAt": _to_iso(data.get("createdAt")),
                "updatedAt": _to_iso(data.get("updatedAt")),
                "data": data,
            }
        )
    return matches


def _find_kapitels_for_project(user_id: str, project_id: str) -> list[dict[str, Any]]:
    db = firebase_service.db
    rows: list[dict[str, Any]] = []
    ref = db.collection("users").document(user_id).collection("kapitels")
    for snap in ref.where("projektId", "==", project_id).stream():
        data = snap.to_dict() or {}
        rows.append(
            {
                "kapitelId": snap.id,
                "path": snap.reference.path,
                "nummer": str(data.get("nummer") or "").strip(),
                "title": str(data.get("title") or "").strip(),
                "thema": str(data.get("thema") or "").strip(),
                "quelleIds": list(data.get("quelleIds") or []),
                "activeRunId": str(data.get("activeRunId") or "").strip() or None,
                "latestRun": data.get("latestRun") if isinstance(data.get("latestRun"), dict) else {},
                "createdAt": _to_iso(data.get("createdAt")),
                "updatedAt": _to_iso(data.get("updatedAt")),
                "data": data,
            }
        )
    rows.sort(key=lambda row: row["nummer"])
    return rows


def _match_kapitel(rows: list[dict[str, Any]], nummer: str | None, title_substring: str | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    num_norm = str(nummer or "").strip()
    title_norm = str(title_substring or "").strip().lower()
    for row in rows:
        if num_norm and str(row.get("nummer") or "").strip() != num_norm:
            continue
        if title_norm and title_norm not in str(row.get("title") or "").strip().lower():
            continue
        out.append(row)
    return out


def _load_run_ops(user_id: str, run_id: str) -> list[dict[str, Any]]:
    db = firebase_service.db
    ops_ref = (
        db.collection("users")
        .document(user_id)
        .collection("costMetrics")
        .document("v1")
        .collection("operations")
    )
    rows: list[dict[str, Any]] = []
    for snap in ops_ref.where("runId", "==", run_id).stream():
        data = snap.to_dict() or {}
        costs = data.get("costs") if isinstance(data.get("costs"), dict) else {}
        tokens = data.get("tokens") if isinstance(data.get("tokens"), dict) else {}
        rows.append(
            {
                "operationId": snap.id,
                "timestamp": _to_iso(data.get("timestamp")),
                "operationType": str(data.get("operationType") or "").strip() or "unknown",
                "model": str(data.get("model") or "").strip() or None,
                "modelNormalized": str(data.get("modelNormalized") or "").strip() or None,
                "status": str(data.get("status") or "").strip() or None,
                "costUsd": _num(costs.get("totalCostUsd")),
                "creditsDebited": _num(data.get("creditsDebited")),
                "inputTokens": _int(tokens.get("inputTokens")),
                "cachedInputTokens": _int(tokens.get("cachedInputTokens")),
                "outputTokens": _int(tokens.get("outputTokens")),
                "totalTokens": _int(tokens.get("totalTokens")),
                "operationDetails": data.get("operationDetails") if isinstance(data.get("operationDetails"), dict) else {},
                "path": snap.reference.path,
            }
        )
    rows.sort(key=lambda row: row["timestamp"] or "")
    return rows


def _sum_ops_by_type(ops: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[str, dict[str, Any]] = {}
    for op in ops:
        op_type = str(op.get("operationType") or "unknown")
        bucket = buckets.setdefault(
            op_type,
            {
                "operationType": op_type,
                "count": 0,
                "costUsd": 0.0,
                "inputTokens": 0,
                "cachedInputTokens": 0,
                "outputTokens": 0,
                "totalTokens": 0,
                "models": defaultdict(int),
            },
        )
        bucket["count"] += 1
        bucket["costUsd"] += _num(op.get("costUsd"))
        bucket["inputTokens"] += _int(op.get("inputTokens"))
        bucket["cachedInputTokens"] += _int(op.get("cachedInputTokens"))
        bucket["outputTokens"] += _int(op.get("outputTokens"))
        bucket["totalTokens"] += _int(op.get("totalTokens"))
        model_norm = str(op.get("modelNormalized") or op.get("model") or "unknown")
        bucket["models"][model_norm] += 1
    rows = list(buckets.values())
    for row in rows:
        row["models"] = dict(sorted(row["models"].items()))
    rows.sort(key=lambda row: (-float(row["costUsd"]), row["operationType"]))
    return rows


def _load_results_and_artifacts(user_id: str, kapitel_id: str, run_id: str) -> dict[str, Any]:
    db = firebase_service.db
    run_ref = db.collection("users").document(user_id).collection("kapitels").document(kapitel_id).collection("runs").document(run_id)
    run_snap = run_ref.get()
    run_data = run_snap.to_dict() or {}

    results: list[dict[str, Any]] = []
    for snap in run_ref.collection("results").stream():
        data = snap.to_dict() or {}
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        results.append(
            {
                "resultId": snap.id,
                "quelleId": str(data.get("quelleId") or "").strip() or None,
                "status": str(data.get("status") or "").strip() or None,
                "hasContent": bool(data.get("hasContent")),
                "model": str(data.get("model") or "").strip() or None,
                "costUsd": _num(data.get("costUsd")),
                "inputTokens": _int(usage.get("inputTokens")),
                "cachedInputTokens": _int(usage.get("cachedInputTokens")),
                "outputTokens": _int(usage.get("outputTokens")),
                "totalTokens": _int(usage.get("totalTokens")),
            }
        )
    results.sort(key=lambda row: (str(row.get("status") or ""), str(row.get("quelleId") or ""), row["resultId"]))

    artifacts: dict[str, Any] = {}
    for snap in run_ref.collection("artifacts").stream():
        data = snap.to_dict() or {}
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else {}
        artifacts[snap.id] = {
            "artifactId": snap.id,
            "status": str(data.get("status") or "").strip() or None,
            "model": str(data.get("model") or "").strip() or None,
            "costUsd": _num(data.get("costUsd")),
            "inputTokens": _int(usage.get("inputTokens")),
            "cachedInputTokens": _int(usage.get("cachedInputTokens")),
            "outputTokens": _int(usage.get("outputTokens")),
            "totalTokens": _int(usage.get("totalTokens")),
            "sourceQuelleIds": list(data.get("sourceQuelleIds") or []),
            "usedKapitelIds": list(data.get("usedKapitelIds") or []),
        }

    return {
        "run": {
            "runId": run_id,
            "index": _int(run_data.get("index")),
            "model": str(run_data.get("model") or "").strip() or None,
            "instruction": str(run_data.get("instruction") or "").strip() or None,
            "status": str(run_data.get("status") or "").strip() or None,
            "createdAt": _to_iso(run_data.get("createdAt")),
            "updatedAt": _to_iso(run_data.get("updatedAt")),
            "artifactsStatus": run_data.get("artifactsStatus") if isinstance(run_data.get("artifactsStatus"), dict) else {},
            "resultsExpectedCount": _int(run_data.get("resultsExpectedCount")),
            "resultsCompletedCount": _int(run_data.get("resultsCompletedCount")),
            "resultsWithContentCount": _int(run_data.get("resultsWithContentCount")),
            "promptTemplateId": run_data.get("promptTemplateId"),
        },
        "results": results,
        "artifacts": artifacts,
    }


def _load_runs_for_kapitel(user_id: str, kapitel_id: str) -> list[dict[str, Any]]:
    db = firebase_service.db
    ref = db.collection("users").document(user_id).collection("kapitels").document(kapitel_id).collection("runs")
    rows: list[dict[str, Any]] = []
    for snap in ref.stream():
        data = snap.to_dict() or {}
        rows.append(
            {
                "runId": snap.id,
                "index": _int(data.get("index")),
                "model": str(data.get("model") or "").strip() or None,
                "createdAt": data.get("createdAt"),
                "updatedAt": data.get("updatedAt"),
                "instruction": str(data.get("instruction") or "").strip() or None,
                "artifactsStatus": data.get("artifactsStatus") if isinstance(data.get("artifactsStatus"), dict) else {},
                "resultsExpectedCount": _int(data.get("resultsExpectedCount")),
                "resultsCompletedCount": _int(data.get("resultsCompletedCount")),
                "resultsWithContentCount": _int(data.get("resultsWithContentCount")),
            }
        )
    rows.sort(key=lambda row: (_dt(row["createdAt"]), row["index"], row["runId"]), reverse=True)
    for row in rows:
        row["createdAt"] = _to_iso(row["createdAt"])
        row["updatedAt"] = _to_iso(row["updatedAt"])
    return rows


def _build_report(project: dict[str, Any], kapitel: dict[str, Any], run_limit: int) -> dict[str, Any]:
    user_id = str(project["userId"])
    project_id = str(project["projectId"])
    kapitel_id = str(kapitel["kapitelId"])

    runs = _load_runs_for_kapitel(user_id, kapitel_id)[: max(1, int(run_limit))]
    detailed_runs: list[dict[str, Any]] = []
    for run in runs:
        run_id = str(run["runId"])
        ops = _load_run_ops(user_id, run_id)
        run_docs = _load_results_and_artifacts(user_id, kapitel_id, run_id)
        op_total = round(sum(_num(op.get("costUsd")) for op in ops), 6)
        detailed_runs.append(
            {
                **run,
                "uiUsageInsightsTotalCostUsd": op_total,
                "operationCount": len(ops),
                "operationBreakdown": _sum_ops_by_type(ops),
                "operations": ops,
                "runDocs": run_docs["run"],
                "results": run_docs["results"],
                "artifacts": run_docs["artifacts"],
            }
        )

    return {
        "project": {
            "userId": user_id,
            "projectId": project_id,
            "name": project["name"],
            "path": project["path"],
            "createdAt": project["createdAt"],
            "updatedAt": project["updatedAt"],
        },
        "kapitel": {
            "kapitelId": kapitel_id,
            "path": kapitel["path"],
            "nummer": kapitel["nummer"],
            "title": kapitel["title"],
            "thema": kapitel["thema"],
            "quelleCount": len(kapitel["quelleIds"]),
            "quelleIds": kapitel["quelleIds"],
            "activeRunId": kapitel["activeRunId"],
            "latestRun": _json_safe(kapitel["latestRun"]),
            "createdAt": kapitel["createdAt"],
            "updatedAt": kapitel["updatedAt"],
        },
        "runs": detailed_runs,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Investigate Kapitel run costs from Firestore.")
    parser.add_argument("--project-name", required=True, help="Exact project name")
    parser.add_argument("--kapitel-nummer", default="", help="Exact Kapitel nummer, e.g. 2.3")
    parser.add_argument("--kapitel-title-contains", default="", help="Case-insensitive substring for the chapter title")
    parser.add_argument("--run-limit", type=int, default=10, help="How many runs to inspect")
    parser.add_argument("--json", action="store_true", help="Emit machine-readable JSON")
    args = parser.parse_args()

    projects = _find_projects_by_name(str(args.project_name or "").strip())
    if not projects:
        raise SystemExit(f"No project found with name: {args.project_name}")
    if len(projects) > 1:
        print(json.dumps({"projectMatches": projects}, ensure_ascii=False, indent=2))
        raise SystemExit("Multiple projects matched. Narrow the lookup before rerunning.")

    project = projects[0]
    kapitels = _find_kapitels_for_project(str(project["userId"]), str(project["projectId"]))
    matches = _match_kapitel(kapitels, args.kapitel_nummer, args.kapitel_title_contains)
    if not matches:
        print(json.dumps({"availableKapitels": kapitels}, ensure_ascii=False, indent=2))
        raise SystemExit("No matching chapter found.")
    if len(matches) > 1:
        print(json.dumps({"kapitelMatches": matches}, ensure_ascii=False, indent=2))
        raise SystemExit("Multiple chapters matched. Narrow the lookup before rerunning.")

    report = _build_report(project, matches[0], args.run_limit)
    print(json.dumps(_json_safe(report), ensure_ascii=False, indent=2 if args.json else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
