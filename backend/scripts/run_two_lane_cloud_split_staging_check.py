from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from google.cloud import firestore
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.two_lane_sources.storage import TwoLaneArtifactStore
from utils.config import config


def _json_default(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Launch concurrent two-lane split runs against deployed Cloud Run jobs and inspect their state.")
    parser.add_argument("--count", type=int, default=3)
    parser.add_argument("--user-id", default="")
    parser.add_argument("--project-prefix", default="qf-cloud-test")
    parser.add_argument("--job-name", default=str(config.TWO_LANE_CLOUD_RUN_JOB_NAME or "instantpaper-two-lane-sources"))
    parser.add_argument("--region", default=str(config.TWO_LANE_CLOUD_RUN_JOB_REGION or "europe-west3"))
    parser.add_argument("--timeout-seconds", type=float, default=21600.0)
    parser.add_argument("--poll-seconds", type=float, default=30.0)
    parser.add_argument("--chapter-title", default="Automatisierung der Dokumentenanalyse mittels NLP/LLM")
    parser.add_argument(
        "--chapter-spec",
        default=(
            "Einsatz von LLMs und NLP zur automatisierten Auswertung von Bilanzen, BWAs und Verträgen. "
            "Zeitersparnis in der Marktfolge, Reduktion manueller Fehler. Praxisbeispiele "
            "(z. B. Pilotprojekte anderer Sparkassen oder Finanzinstitute)."
        ),
    )
    parser.add_argument("--output-name", default="staging_split_concurrency_latest.json")
    parser.add_argument("--seed-topup-credits", type=float, default=10.0)
    parser.add_argument("--cleanup", action="store_true")
    return parser.parse_args(argv)


def _gcloud_run_job_execute(*, job_name: str, region: str, user_id: str, projekt_id: str, run_id: str, stage: str) -> dict[str, Any]:
    gcloud_bin = shutil.which("gcloud") or shutil.which("gcloud.cmd")
    if not gcloud_bin:
        raise RuntimeError("gcloud executable was not found on PATH")
    cmd = [
        gcloud_bin,
        "run",
        "jobs",
        "execute",
        job_name,
        f"--region={region}",
        f"--args=run_two_lane_job.py,--user-id={user_id},--project-id={projekt_id},--run-id={run_id},--stage={stage}",
        "--format=json",
    ]
    completed = subprocess.run(cmd, cwd=str(BACKEND_ROOT.parent), capture_output=True, text=True, check=False)
    if completed.returncode != 0:
        raise RuntimeError(f"gcloud run jobs execute failed: {completed.stderr.strip() or completed.stdout.strip()}")
    payload = json.loads(completed.stdout or "{}")
    return payload if isinstance(payload, dict) else {}


def _create_run(*, fs: QuellenFinderFirestoreService, title: str, spec: str, suffix: str, user_id: str = "", project_prefix: str = "qf-cloud-test") -> dict[str, str]:
    user_id_norm = str(user_id or "").strip() or f"staging-two-lane-{suffix}"
    project_prefix_norm = str(project_prefix or "").strip() or "qf-cloud-test"
    synthetic = not bool(str(user_id or "").strip())
    projekt_id = f"{project_prefix_norm}-{suffix}"
    kapitel_id = f"{project_prefix_norm}-kapitel-{suffix}"
    run_id = f"{project_prefix_norm}-run-{suffix}"
    fs.create_run(
        user_id=user_id_norm,
        projekt_id=projekt_id,
        run_id=run_id,
        kind="sources_two_lane",
        kapitel_ids=[kapitel_id],
        kapitel_snapshots=[
            {
                "id": kapitel_id,
                "title": title,
                "ueberschrift": title,
                "thema": spec,
            }
        ],
        model="gpt-5-mini",
        extra={
            "executionBackend": "cloud_run_split_jobs",
            "chapterInputSnapshot": {
                "chapterTitle": title,
                "chapterSpecText": spec,
            },
            "twoLaneSettingsRequested": {
                "openai_model_planner": "gpt-5-mini",
                "openai_model_openalex_query_builder": "gpt-5-mini",
                "openai_model_s2_query_builder": "gpt-5-mini",
                "openai_model_rerank": "gpt-5-nano",
                "embedding_model": "text-embedding-3-small",
                "openai_reasoning_effort": "high",
                "rerank_concurrency": 20,
            },
            "job": {
                "provider": "cloud_run_split_jobs",
                "jobName": str(config.TWO_LANE_CLOUD_RUN_JOB_NAME or "").strip() or None,
                "region": str(config.TWO_LANE_CLOUD_RUN_JOB_REGION or "").strip() or None,
                "operationName": None,
                "executionName": None,
                "launchedAt": None,
                "launchError": None,
            },
            "splitExecution": {
                "backend": "cloud_run_split_jobs",
                "version": 1,
                "currentStage": "preprocess",
                "preprocess": {"status": "queued"},
                "openalex_fetch": {"status": "pending"},
                "s2_fetch": {"status": "pending"},
                "candidates": {"status": "pending"},
                "finalize": {"status": "pending"},
            },
        },
    )
    return {
        "user_id": user_id_norm,
        "projekt_id": projekt_id,
        "kapitel_id": kapitel_id,
        "run_id": run_id,
        "synthetic_user": "1" if synthetic else "0",
    }


def _seed_test_billing(*, user_id: str, topup_credits: float) -> None:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required")
    firebase_service.db.collection("users").document(uid).set(
        {
            "uid": uid,
            "email": f"{uid}@example.invalid",
            "displayName": uid,
            "updatedAt": SERVER_TIMESTAMP,
        },
        merge=True,
    )
    firebase_service.db.collection("users").document(uid).collection("billing").document("balance").set(
        {
            "topupCredits": float(max(topup_credits, 0.0)),
            "reservedCredits": 0.0,
            "updatedAt": SERVER_TIMESTAMP,
        },
        merge=True,
    )


def _recursive_delete_doc(doc_ref) -> None:
    for subcol in doc_ref.collections():
        for child in subcol.stream():
            _recursive_delete_doc(child.reference)
    try:
        doc_ref.delete()
    except Exception:
        pass


def _cleanup_run_tree(*, ids: dict[str, str]) -> dict[str, Any]:
    user_id = str(ids.get("user_id") or "").strip()
    projekt_id = str(ids.get("projekt_id") or "").strip()
    run_id = str(ids.get("run_id") or "").strip()
    synthetic_user = str(ids.get("synthetic_user") or "").strip() == "1"
    result: dict[str, Any] = {"user_id": user_id, "projekt_id": projekt_id, "run_id": run_id}

    try:
        store = TwoLaneArtifactStore(
            bucket_name=str(config.TWO_LANE_ARTIFACT_BUCKET or config.FIREBASE_STORAGE_BUCKET or "").strip(),
            base_prefix=str(config.TWO_LANE_ARTIFACT_PREFIX or "").strip(),
            project_id=str(config.GOOGLE_CLOUD_PROJECT or config.FIREBASE_PROJECT_ID or "").strip(),
        )
        result["deletedArtifactObjects"] = int(store.delete_run_prefix(run_id))
    except Exception as exc:
        result["artifactError"] = str(exc)

    user_ref = firebase_service.db.collection("users").document(user_id)
    project_ref = user_ref.collection("projects").document(projekt_id)
    run_ref = project_ref.collection("researchRuns").document(run_id)
    _recursive_delete_doc(run_ref)
    _recursive_delete_doc(project_ref)
    if synthetic_user:
        _recursive_delete_doc(user_ref)
        _recursive_delete_doc(firebase_service.db.collection("customers").document(user_id))
    result["cleanupDone"] = True
    return result


def _read_run(fs: QuellenFinderFirestoreService, ids: dict[str, str]) -> dict[str, Any]:
    return fs.get_run(user_id=ids["user_id"], projekt_id=ids["projekt_id"], run_id=ids["run_id"])


def _inspect_cleanup(run_doc: dict[str, Any]) -> dict[str, Any]:
    artifacts = run_doc.get("twoLaneArtifacts") if isinstance(run_doc.get("twoLaneArtifacts"), dict) else {}
    bucket = str((artifacts or {}).get("bucket") or config.TWO_LANE_ARTIFACT_BUCKET or config.FIREBASE_STORAGE_BUCKET or "").strip()
    base_prefix = str((artifacts or {}).get("basePrefix") or config.TWO_LANE_ARTIFACT_PREFIX or "").strip()
    run_id = str((run_doc or {}).get("id") or "").strip()
    if not bucket:
        return {"bucketConfigured": False}
    store = TwoLaneArtifactStore(
        bucket_name=bucket,
        base_prefix=base_prefix,
        project_id=str(config.GOOGLE_CLOUD_PROJECT or config.FIREBASE_PROJECT_ID or "").strip(),
    )
    prefix = store.run_prefix(run_doc.get("run_id") or run_id or "")
    objects = store.list_prefix(prefix=prefix) if prefix else []
    return {
        "bucketConfigured": True,
        "bucket": bucket,
        "basePrefix": base_prefix,
        "remainingObjects": len(objects),
        "sampleObjects": [item.object_name for item in objects[:20]],
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    fs = QuellenFinderFirestoreService()
    count = max(1, min(5, int(args.count or 1)))
    suffix_root = uuid.uuid4().hex[:8]
    runs: list[dict[str, Any]] = []

    for idx in range(1, count + 1):
        suffix = f"{suffix_root}-{idx:02d}"
        ids = _create_run(
            fs=fs,
            title=str(args.chapter_title),
            spec=str(args.chapter_spec),
            suffix=suffix,
            user_id=str(args.user_id or "").strip(),
            project_prefix=str(args.project_prefix or "qf-cloud-test"),
        )
        if str(ids.get("synthetic_user") or "").strip() == "1":
            _seed_test_billing(
                user_id=ids["user_id"],
                topup_credits=float(args.seed_topup_credits or 0.0),
            )
        launch = _gcloud_run_job_execute(
            job_name=str(args.job_name),
            region=str(args.region),
            user_id=ids["user_id"],
            projekt_id=ids["projekt_id"],
            run_id=ids["run_id"],
            stage="preprocess",
        )
        runs.append({"ids": ids, "launch": launch, "history": []})

    deadline = time.time() + float(args.timeout_seconds)
    while True:
        all_terminal = True
        snapshot = []
        for item in runs:
            run_doc = _read_run(fs, item["ids"])
            status_now = str((run_doc or {}).get("status") or "").strip().lower()
            split = run_doc.get("splitExecution") if isinstance(run_doc.get("splitExecution"), dict) else {}
            provider_work = run_doc.get("providerWork") if isinstance(run_doc.get("providerWork"), dict) else {}
            record = {
                "ts_epoch_s": time.time(),
                "status": status_now,
                "progressStage": ((run_doc.get("progress") or {}).get("stage")),
                "progressMessage": ((run_doc.get("progress") or {}).get("message")),
                "currentStage": split.get("currentStage"),
                "splitExecution": split,
                "providerWork": provider_work,
                "cleanup": run_doc.get("twoLaneArtifacts"),
                "updatedAt": run_doc.get("updatedAt"),
            }
            item["history"].append(record)
            snapshot.append({"run_id": item["ids"]["run_id"], "status": status_now, "stage": split.get("currentStage"), "progress": record["progressStage"]})
            if status_now not in {"success", "error", "cancelled"}:
                all_terminal = False

        print(json.dumps({"event": "poll", "snapshot": snapshot}, ensure_ascii=False), flush=True)
        if all_terminal:
            break
        if time.time() >= deadline:
            raise TimeoutError(f"Timed out waiting for {count} staging runs to finish")
        time.sleep(max(5.0, float(args.poll_seconds)))

    summary_runs: list[dict[str, Any]] = []
    for item in runs:
        run_doc = _read_run(fs, item["ids"])
        cleanup_check = None
        try:
            cleanup_check = _inspect_cleanup({**run_doc, "run_id": item["ids"]["run_id"]})
        except Exception as exc:
            cleanup_check = {"error": str(exc)}
        summary_runs.append(
            {
                **item["ids"],
                "launch": item["launch"],
                "status": run_doc.get("status"),
                "resultCount": run_doc.get("resultCount"),
                "summary": run_doc.get("summary"),
                "splitExecution": run_doc.get("splitExecution"),
                "providerWork": run_doc.get("providerWork"),
                "cleanup": run_doc.get("twoLaneArtifacts"),
                "cleanupCheck": cleanup_check,
                "history": item["history"],
            }
        )

    result = {
        "ok": True,
        "count": count,
        "job_name": args.job_name,
        "region": args.region,
        "runs": summary_runs,
    }
    if bool(args.cleanup):
        result["cleanup"] = [_cleanup_run_tree(ids=item["ids"]) for item in runs]
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "cloud_checks"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / str(args.output_name or "staging_split_concurrency_latest.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default), encoding="utf-8")
    print(json.dumps({"event": "done", "output": str(out_path)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
