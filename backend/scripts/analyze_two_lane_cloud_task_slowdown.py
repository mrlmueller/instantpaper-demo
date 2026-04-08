from __future__ import annotations

import argparse
import base64
import json
import statistics
import subprocess
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


BACKEND_ROOT = Path(__file__).resolve().parents[1]
GCLOUD_BIN = shutil.which("gcloud") or shutil.which("gcloud.cmd")


def _run_gcloud(args: list[str]) -> str:
    if not GCLOUD_BIN:
        raise RuntimeError("gcloud executable was not found on PATH")
    completed = subprocess.run(
        [GCLOUD_BIN, *args],
        cwd=str(BACKEND_ROOT.parent),
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        msg = completed.stderr.strip() or completed.stdout.strip() or f"gcloud failed: {' '.join(args)}"
        raise RuntimeError(msg)
    return completed.stdout


def _run_gcloud_json(args: list[str]) -> Any:
    raw = _run_gcloud([*args, "--format=json"])
    return json.loads(raw or "null")


def _read_request_latencies(
    *,
    service_name: str,
    revision_name: str,
    handler_url: str,
    freshness: str,
    status_code: int,
    limit: int,
) -> list[float]:
    filt = (
        f'resource.type=cloud_run_revision AND '
        f'resource.labels.service_name="{service_name}" AND '
        f'resource.labels.revision_name="{revision_name}" AND '
        f'httpRequest.requestUrl="{handler_url}" AND '
        f"httpRequest.status={int(status_code)}"
    )
    raw = _run_gcloud(
        [
            "logging",
            "read",
            filt,
            f"--limit={int(limit)}",
            f"--freshness={freshness}",
            "--format=value(httpRequest.latency)",
        ]
    )
    vals: list[float] = []
    for line in (raw or "").splitlines():
        t = line.strip()
        if not t.endswith("s"):
            continue
        try:
            vals.append(float(t[:-1]))
        except Exception:
            continue
    vals.sort()
    return vals


def _latency_stats(values: list[float]) -> dict[str, Any]:
    if not values:
        return {"count": 0}

    def pct(q: float) -> float:
        idx = min(len(values) - 1, max(0, int(round((len(values) - 1) * q))))
        return float(values[idx])

    return {
        "count": int(len(values)),
        "min_s": float(values[0]),
        "p50_s": pct(0.50),
        "p90_s": pct(0.90),
        "p95_s": pct(0.95),
        "p99_s": pct(0.99),
        "max_s": float(values[-1]),
        "mean_s": float(statistics.mean(values)),
    }


def _decode_task_bodies(tasks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    decoded: list[dict[str, Any]] = []
    for task in tasks:
        body_b64 = (((task or {}).get("httpRequest") or {}).get("body") or "").strip()
        body_json: Any = None
        if body_b64:
            try:
                body_json = json.loads(base64.b64decode(body_b64).decode("utf-8"))
            except Exception as exc:
                body_json = {"decode_error": str(exc)}
        decoded.append(
            {
                "name": task.get("name"),
                "dispatchCount": task.get("dispatchCount"),
                "scheduleTime": task.get("scheduleTime"),
                "lastAttempt": task.get("lastAttempt"),
                "body": body_json,
            }
        )
    return decoded


def _env_map(service_json: dict[str, Any]) -> dict[str, str]:
    env_items = (
        ((((service_json or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or [{}]
    )[0].get("env") or []
    out: dict[str, str] = {}
    for item in env_items:
        name = str((item or {}).get("name") or "").strip()
        if not name:
            continue
        if "value" in item:
            out[name] = str(item.get("value") or "")
        elif "valueFrom" in item:
            out[name] = "<secret>"
    return out


def _first_container(service_json: dict[str, Any]) -> dict[str, Any]:
    containers = (((service_json or {}).get("spec") or {}).get("template") or {}).get("spec", {}).get("containers") or []
    if isinstance(containers, list) and containers:
        first = containers[0]
        return first if isinstance(first, dict) else {}
    return {}


def _estimate_lower_bound_seconds(*, calls_per_task: int, concurrent_dispatches: int, rps: float) -> float | None:
    if calls_per_task <= 0 or concurrent_dispatches <= 0 or rps <= 0:
        return None
    return float(calls_per_task * concurrent_dispatches) / float(rps)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze deployed two-lane Cloud Tasks slowdown characteristics.")
    parser.add_argument("--service-name", default="instantpaper-api")
    parser.add_argument("--region", default="europe-west3")
    parser.add_argument("--openalex-queue", default="quellen-finder-openalex")
    parser.add_argument("--s2-queue", default="quellen-finder-semanticscholar")
    parser.add_argument("--freshness", default="8h")
    parser.add_argument("--log-limit", type=int, default=500)
    parser.add_argument("--output-name", default="cloud_task_slowdown_analysis_latest.json")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))

    service = _run_gcloud_json(["run", "services", "describe", args.service_name, f"--region={args.region}"])
    env = _env_map(service)
    latest_revision = str((((service or {}).get("status") or {}).get("latestReadyRevisionName") or "")).strip()
    handler_url = str(env.get("TWO_LANE_TASK_HANDLER_URL") or "").strip()
    timeout_s = int(((((service or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("timeoutSeconds") or 0)
    concurrency = int(((((service or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("containerConcurrency") or 0)
    first_container = _first_container(service)
    resources = first_container.get("resources") if isinstance(first_container.get("resources"), dict) else {}
    limits = resources.get("limits") if isinstance(resources.get("limits"), dict) else {}
    cpu_limit = str(limits.get("cpu") or "")
    metadata = (((service or {}).get("spec") or {}).get("template") or {}).get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    annotations = metadata.get("annotations") if isinstance(metadata.get("annotations"), dict) else {}
    max_scale = str(annotations.get("autoscaling.knative.dev/maxScale") or "")

    openalex_queue = _run_gcloud_json(["tasks", "queues", "describe", args.openalex_queue, f"--location={args.region}"])
    s2_queue = _run_gcloud_json(["tasks", "queues", "describe", args.s2_queue, f"--location={args.region}"])
    openalex_tasks_basic = _run_gcloud_json(["tasks", "list", f"--queue={args.openalex_queue}", f"--location={args.region}"])
    s2_tasks_basic = _run_gcloud_json(["tasks", "list", f"--queue={args.s2_queue}", f"--location={args.region}"])

    openalex_tasks_full: list[dict[str, Any]] = []
    for task in openalex_tasks_basic or []:
        name = str(task.get("name") or "").strip().split("/")[-1]
        if not name:
            continue
        openalex_tasks_full.append(
            _run_gcloud_json(
                [
                    "tasks",
                    "describe",
                    name,
                    f"--queue={args.openalex_queue}",
                    f"--location={args.region}",
                    "--response-view=FULL",
                ]
            )
        )

    s2_tasks_full: list[dict[str, Any]] = []
    for task in s2_tasks_basic or []:
        name = str(task.get("name") or "").strip().split("/")[-1]
        if not name:
            continue
        s2_tasks_full.append(
            _run_gcloud_json(
                [
                    "tasks",
                    "describe",
                    name,
                    f"--queue={args.s2_queue}",
                    f"--location={args.region}",
                    "--response-view=FULL",
                ]
            )
        )

    lat_202 = _read_request_latencies(
        service_name=args.service_name,
        revision_name=latest_revision,
        handler_url=handler_url,
        freshness=args.freshness,
        status_code=202,
        limit=args.log_limit,
    )
    lat_504 = _read_request_latencies(
        service_name=args.service_name,
        revision_name=latest_revision,
        handler_url=handler_url,
        freshness=args.freshness,
        status_code=504,
        limit=args.log_limit,
    )

    openalex_rps = float(env.get("TWO_LANE_OPENALEX_RPS") or 0.0)
    s2_rps = float(env.get("TWO_LANE_SEMANTICSCHOLAR_RPS") or 0.0)
    openalex_pages_cap = int(env.get("TWO_LANE_OPENALEX_TASK_MAX_PAGES_PER_TASK") or 0)
    s2_pages_cap = int(env.get("TWO_LANE_SEMANTICSCHOLAR_TASK_MAX_PAGES_PER_TASK") or 0)
    openalex_conc = int(((openalex_queue or {}).get("rateLimits") or {}).get("maxConcurrentDispatches") or 0)
    s2_conc = int(((s2_queue or {}).get("rateLimits") or {}).get("maxConcurrentDispatches") or 0)

    result = {
        "capturedAt": datetime.now(timezone.utc).isoformat(),
        "service": {
            "name": args.service_name,
            "region": args.region,
            "latestRevision": latest_revision,
            "handlerUrl": handler_url,
            "timeoutSeconds": timeout_s,
            "containerConcurrency": concurrency,
            "cpuLimit": cpu_limit,
            "maxScale": max_scale,
        },
        "queues": {
            "openalex": openalex_queue,
            "semanticscholar": s2_queue,
        },
        "currentTasks": {
            "openalex": _decode_task_bodies(openalex_tasks_full),
            "semanticscholar": _decode_task_bodies(s2_tasks_full),
        },
        "requestLogs": {
            "status202": _latency_stats(lat_202),
            "status504": _latency_stats(lat_504),
        },
        "config": {
            "openalexRps": openalex_rps,
            "s2Rps": s2_rps,
            "openalexTaskMaxPagesPerTask": openalex_pages_cap,
            "s2TaskMaxPagesPerTask": s2_pages_cap,
            "providerTaskMaxRuntimeS": float(env.get("TWO_LANE_PROVIDER_TASK_MAX_RUNTIME_S") or 0.0),
        },
        "saturationModel": {
            "openalex": {
                "assumedCallsPerPage": 1,
                "queueMaxConcurrentDispatches": openalex_conc,
                "taskCallsAtConfiguredCap": openalex_pages_cap,
                "lowerBoundSecondsAtFullSaturation": _estimate_lower_bound_seconds(
                    calls_per_task=openalex_pages_cap,
                    concurrent_dispatches=openalex_conc,
                    rps=openalex_rps,
                ),
            },
            "semanticscholar": {
                "assumedCallsPerPage": 2,
                "queueMaxConcurrentDispatches": s2_conc,
                "taskCallsAtConfiguredCap": s2_pages_cap * 2,
                "lowerBoundSecondsAtFullSaturation": _estimate_lower_bound_seconds(
                    calls_per_task=s2_pages_cap * 2,
                    concurrent_dispatches=s2_conc,
                    rps=s2_rps,
                ),
            },
        },
        "notes": [
            "The saturation lower bound is a simple queueing approximation: calls_per_task * concurrent_dispatches / provider_rps.",
            "It excludes provider response latency, GCS writes, Firestore bookkeeping, and retry backoff, so real wall time will be higher.",
            "If requestLogs.status202.p95_s is close to service.timeoutSeconds, the current task granularity is unsafe.",
        ],
    }

    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "cloud_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / str(args.output_name or "cloud_task_slowdown_analysis_latest.json")
    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"output": str(out_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
