from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any


CLOUD_RUN_BILLING_SERVICE_ID = "152E-C115-5142"


@dataclass(frozen=True)
class UnitPrices:
    cpu_per_second_usd: Decimal
    memory_gib_second_usd: Decimal


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Estimate Cloud Run Job cost for instantpaper-two-lane-sources from execution history."
    )
    parser.add_argument("--project", default="instantpaper")
    parser.add_argument("--job", default="instantpaper-two-lane-sources")
    parser.add_argument("--region", default="europe-west3")
    parser.add_argument("--limit", type=int, default=20)
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def _run_json(command: list[str], *, cwd: Path) -> Any:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(command)}): {completed.stderr.strip() or completed.stdout.strip()}"
        )
    text = (completed.stdout or "").strip()
    if not text:
        return None
    return json.loads(text)


def _run_text(command: list[str], *, cwd: Path) -> str:
    completed = subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"Command failed ({' '.join(command)}): {completed.stderr.strip() or completed.stdout.strip()}"
        )
    return (completed.stdout or "").strip()


def _parse_decimal_price(unit_price: dict[str, Any]) -> Decimal:
    units = Decimal(str(unit_price.get("units") or "0"))
    nanos = Decimal(str(unit_price.get("nanos") or 0)) / Decimal("1000000000")
    return units + nanos


def _parse_cpu(cpu_value: str | None) -> Decimal:
    return Decimal(str(cpu_value or "0"))


def _parse_memory_gib(memory_value: str | None) -> Decimal:
    raw = str(memory_value or "").strip()
    if not raw:
        return Decimal("0")
    if raw.endswith("Gi"):
        return Decimal(raw[:-2])
    if raw.endswith("Mi"):
        return Decimal(raw[:-2]) / Decimal("1024")
    if raw.endswith("G"):
        return Decimal(raw[:-1]) * (Decimal("1000") / Decimal("1024"))
    if raw.endswith("M"):
        return Decimal(raw[:-1]) / Decimal("1024")
    raise ValueError(f"Unsupported memory format: {raw}")


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _gcloud_bin() -> str:
    return shutil.which("gcloud") or shutil.which("gcloud.cmd") or "gcloud"


def _bq_bin() -> str:
    return shutil.which("bq") or shutil.which("bq.cmd") or "bq"


def _fetch_cloud_run_job_prices(*, region: str, cwd: Path) -> UnitPrices:
    token = _run_text([_gcloud_bin(), "auth", "print-access-token"], cwd=cwd)
    url = (
        f"https://cloudbilling.googleapis.com/v1/services/{CLOUD_RUN_BILLING_SERVICE_ID}/skus"
        f"?currencyCode=USD&pageSize=5000"
    )
    request = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        payload = json.loads(response.read().decode("utf-8"))

    cpu_desc = f"Jobs CPU in {region}"
    memory_desc = f"Jobs Memory in {region}"
    cpu_price: Decimal | None = None
    memory_price: Decimal | None = None

    for sku in payload.get("skus") or []:
        desc = str(sku.get("description") or "")
        pricing_info = sku.get("pricingInfo") or []
        if not pricing_info:
            continue
        price = _parse_decimal_price(((pricing_info[0] or {}).get("pricingExpression") or {}).get("tieredRates", [{}])[0].get("unitPrice", {}))
        if desc == cpu_desc:
            cpu_price = price
        elif desc == memory_desc:
            memory_price = price

    if cpu_price is None or memory_price is None:
        raise RuntimeError(f"Could not resolve Cloud Run Jobs pricing for region {region}")

    return UnitPrices(cpu_per_second_usd=cpu_price, memory_gib_second_usd=memory_price)


def _detect_billing_export(*, project: str, cwd: Path) -> dict[str, Any]:
    try:
        datasets = _run_json([_bq_bin(), "ls", "--all=true", "--format=prettyjson", f"--project_id={project}"], cwd=cwd)
    except RuntimeError as exc:
        return {"visible": False, "reason": str(exc), "datasets": []}
    datasets = datasets or []
    names = [str(item.get("datasetReference", {}).get("datasetId") or "") for item in datasets if isinstance(item, dict)]
    likely = [name for name in names if "billing" in name.lower() or "gcp_billing_export" in name.lower()]
    return {"visible": bool(likely), "datasets": likely, "allDatasets": names}


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    cwd = Path(__file__).resolve().parents[2]

    billing_info = _run_json(
        [_gcloud_bin(), "beta", "billing", "projects", "describe", str(args.project), "--format=json"],
        cwd=cwd,
    )
    job = _run_json(
        [
            _gcloud_bin(),
            "run",
            "jobs",
            "describe",
            str(args.job),
            f"--region={args.region}",
            "--format=json",
        ],
        cwd=cwd,
    )
    executions = _run_json(
        [
            _gcloud_bin(),
            "run",
            "jobs",
            "executions",
            "list",
            f"--job={args.job}",
            f"--region={args.region}",
            f"--limit={int(args.limit)}",
            "--format=json",
        ],
        cwd=cwd,
    ) or []

    container_spec = ((((job or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("template", {}).get("spec", {}).get("containers", [{}])[0]
    resources = (container_spec or {}).get("resources") or {}
    limits = resources.get("limits") or {}
    cpu = _parse_cpu(limits.get("cpu"))
    memory_gib = _parse_memory_gib(limits.get("memory"))
    prices = _fetch_cloud_run_job_prices(region=str(args.region), cwd=cwd)
    billing_export = _detect_billing_export(project=str(args.project), cwd=cwd)

    rows: list[dict[str, Any]] = []
    total_estimated_cost = Decimal("0")
    total_duration_seconds = Decimal("0")

    for execution in executions:
        status = execution.get("status") or {}
        spec = execution.get("spec") or {}
        task_count = Decimal(str(spec.get("taskCount") or 1))
        start = _parse_dt(status.get("startTime"))
        end = _parse_dt(status.get("completionTime"))
        if start is None or end is None:
            continue
        duration_seconds = Decimal(str((end - start).total_seconds()))
        cpu_cost = duration_seconds * task_count * cpu * prices.cpu_per_second_usd
        memory_cost = duration_seconds * task_count * memory_gib * prices.memory_gib_second_usd
        estimated_cost = cpu_cost + memory_cost
        total_duration_seconds += duration_seconds
        total_estimated_cost += estimated_cost
        rows.append(
            {
                "executionName": execution.get("metadata", {}).get("name"),
                "creator": execution.get("metadata", {}).get("annotations", {}).get("run.googleapis.com/creator"),
                "args": (spec.get("template") or {}).get("spec", {}).get("containers", [{}])[0].get("args"),
                "startedAt": status.get("startTime"),
                "completedAt": status.get("completionTime"),
                "durationSeconds": float(duration_seconds),
                "taskCount": int(task_count),
                "estimatedCpuCostUsd": float(cpu_cost),
                "estimatedMemoryCostUsd": float(memory_cost),
                "estimatedCostUsd": float(estimated_cost),
            }
        )

    payload = {
        "project": str(args.project),
        "billingInfo": billing_info,
        "job": {
            "name": str(args.job),
            "region": str(args.region),
            "cpuLimit": str(cpu),
            "memoryGiB": float(memory_gib),
            "taskCount": ((((job or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("taskCount"),
            "parallelism": ((((job or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("parallelism"),
        },
        "pricing": {
            "source": "Cloud Billing Catalog API",
            "cloudRunServiceId": CLOUD_RUN_BILLING_SERVICE_ID,
            "cpuPerSecondUsd": float(prices.cpu_per_second_usd),
            "memoryGiBSecondUsd": float(prices.memory_gib_second_usd),
        },
        "billingExport": billing_export,
        "estimate": {
            "executionCount": len(rows),
            "totalDurationSeconds": float(total_duration_seconds),
            "totalEstimatedCostUsd": float(total_estimated_cost),
            "notes": [
                "Estimate covers only the Cloud Run Job instantpaper-two-lane-sources.",
                "Estimate excludes Cloud Tasks, Cloud Storage, Firestore, logging, network egress, Artifact Registry, and the dedicated task-worker service.",
                "Estimate does not apply free tier, committed-use discounts, or billing credits.",
                "If taskCount > 1 with non-uniform task runtimes, execution-level estimation can undercount or overcount.",
                "Exact billed cost requires Cloud Billing export to BigQuery.",
            ],
        },
        "executions": rows,
    }

    output = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        out_path = Path(str(args.output))
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(str(out_path))
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
