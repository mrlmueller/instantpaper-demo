#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path
from typing import Any, Dict, List


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def stable_hash(*parts: str, length: int = 24) -> str:
    import hashlib

    payload = "\n".join([(part or "").strip().replace("\r\n", "\n") for part in parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: int(length)]


def find_run_dir(base_dir: Path, run_id: str | None) -> Path:
    runs_dir = base_dir / "runs"
    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir

    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "phase_a" / "phase_a_summary.json").exists()]
    if not candidates:
        raise FileNotFoundError(f"No Phase A lab run found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_review(run_dir: Path) -> Dict[str, Any]:
    config = read_json(run_dir / "config.json")
    manifest = read_json(run_dir / "pdf_manifest.json")
    metrics = read_json(run_dir / "metrics.json")
    logs = read_jsonl(run_dir / "logs.jsonl")
    api_calls = read_jsonl(run_dir / "api_calls.jsonl")
    phase_a_summary = read_json(run_dir / "phase_a" / "phase_a_summary.json")
    phase_a_assessment = read_json(run_dir / "phase_a" / "phase_a_assessment.json")
    phase_a_runtime = read_json(run_dir / "phase_a" / "phase_a_runtime.json")
    pdf_rows = list(manifest.get("pdfs") or [])

    recomputed_run_id = stable_hash(
        str(config.get("pipeline_version") or ""),
        str(config.get("chapter_title") or ""),
        str(config.get("chapter_spec_text") or ""),
        "\n".join([f"{row.get('label')}::{row.get('sha256')}" for row in pdf_rows]),
        length=24,
    )
    phase_metrics = dict(((metrics.get("stages") or {}).get("phase_a") or {}))
    log_events = [row.get("event") for row in logs if str(row.get("stage") or "") == "phase_a"]
    page_counts = [int(row.get("page_count") or 0) for row in pdf_rows if isinstance(row.get("page_count"), int)]
    size_mbs = [float(row.get("size_mb") or 0.0) for row in pdf_rows]
    outline_docs = [row["file_name"] for row in pdf_rows if bool(row.get("has_outline"))]
    empty_first_page_text_docs = [row["file_name"] for row in pdf_rows if int(row.get("text_chars_page_1") or 0) == 0]

    qc_rows = [
        {
            "check": "run_id_recomputes",
            "status": "OK" if recomputed_run_id == run_dir.name else "FAIL",
            "value": recomputed_run_id,
            "expected": run_dir.name,
        },
        {
            "check": "config_has_full_chapter_text",
            "status": "OK" if bool(config.get("chapter_spec_text")) else "FAIL",
            "value": bool(config.get("chapter_spec_text")),
            "expected": True,
        },
        {
            "check": "phase_a_status_in_metrics",
            "status": "OK" if str(phase_metrics.get("status") or "") in {"success", "success_with_warnings"} else "FAIL",
            "value": phase_metrics.get("status"),
            "expected": "success or success_with_warnings",
        },
        {
            "check": "stage_started_logged",
            "status": "OK" if "stage_started" in log_events else "FAIL",
            "value": "stage_started" in log_events,
            "expected": True,
        },
        {
            "check": "stage_finished_logged",
            "status": "OK" if "stage_finished" in log_events else "FAIL",
            "value": "stage_finished" in log_events,
            "expected": True,
        },
        {
            "check": "run_initialized_logged",
            "status": "OK" if "run_initialized" in log_events else "FAIL",
            "value": "run_initialized" in log_events,
            "expected": True,
        },
        {
            "check": "api_ledger_initialized",
            "status": "OK" if (run_dir / "api_calls.jsonl").exists() else "FAIL",
            "value": (run_dir / "api_calls.jsonl").exists(),
            "expected": True,
        },
        {
            "check": "api_calls_empty_in_phase_a",
            "status": "OK" if len(api_calls) == 0 else "WARN",
            "value": len(api_calls),
            "expected": "0 for Phase A-only run",
        },
    ]

    review = {
        "run_dir": str(run_dir),
        "run_id": run_dir.name,
        "recomputed_run_id": recomputed_run_id,
        "phase_a_status": phase_a_assessment.get("status"),
        "phase_a_quality_band": phase_a_assessment.get("quality_band"),
        "pdf_count": manifest.get("pdf_count"),
        "log_event_count": len(logs),
        "api_call_count": len(api_calls),
        "runtime_dependencies": phase_a_runtime.get("dependencies") or {},
        "manifest_analysis": {
            "page_count_min": min(page_counts) if page_counts else None,
            "page_count_median": statistics.median(page_counts) if page_counts else None,
            "page_count_max": max(page_counts) if page_counts else None,
            "total_size_mb": round(sum(size_mbs), 6),
            "outline_doc_count": len(outline_docs),
            "outline_docs": outline_docs,
            "empty_first_page_text_doc_count": len(empty_first_page_text_docs),
            "empty_first_page_text_docs": empty_first_page_text_docs,
        },
        "phase_a_summary_counts": {
            "artifact_rows": len(phase_a_summary.get("artifact_rows") or []),
            "qc_rows": len(phase_a_summary.get("qc_rows") or []),
        },
        "qc_rows": qc_rows,
        "phase_a_metrics": phase_metrics,
    }
    return review


def main() -> int:
    parser = argparse.ArgumentParser(description="Review a Phase A lab run.")
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", default=None)
    args = parser.parse_args()

    run_dir = find_run_dir(Path(args.base_dir).resolve(), args.run_id)
    review = build_review(run_dir)
    out_path = run_dir / "phase_a_review" / "phase_a_review_summary.json"
    write_json(out_path, review)

    print("Phase A review")
    print(f"run_dir: {review['run_dir']}")
    print(f"status: {review['phase_a_status']} ({review['phase_a_quality_band']})")
    for row in review["qc_rows"]:
        print(f"- {row['check']}: {row['status']} | value={row['value']} | expected={row['expected']}")
    print(f"saved: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
