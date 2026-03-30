from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import sys
import tempfile
import threading
import time
import uuid
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.firebase_service import firebase_service
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService
from services.quellen_finder_sources_two_lane_job import (
    _persist_two_lane_pipeline_success as _persist_two_lane_pipeline_success_orig,
)
from services.quellen_finder_sources_two_lane_job import run_quellen_finder_sources_two_lane_job_from_run_doc
from services.two_lane_sources import provider_tasks
from services.two_lane_sources.provider_rate_limit import delete_provider_rate_limit_docs
from services.two_lane_sources.storage import TwoLaneArtifactStore
from utils.config import config
import services.quellen_finder_sources_two_lane_job as jobmod
import services.two_lane_sources.pipeline as pipeline_mod
import requests


@dataclass(frozen=True)
class _LocalArtifactLocation:
    bucket: str
    object_name: str

    @property
    def uri(self) -> str:
        return f"file:///{self.object_name}"


class LocalArtifactStore:
    def __init__(self, root: Path, *, bucket_name: str = "local-two-lane", base_prefix: str = "two-lane-live") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket_name = str(bucket_name)
        self.base_prefix = str(base_prefix or "").strip().strip("/")

    def run_prefix(self, run_id: str) -> str:
        if self.base_prefix:
            return f"{self.base_prefix}/{str(run_id).strip()}"
        return str(run_id).strip()

    def _normalize_object_name(self, path_or_uri: str) -> str:
        text = str(path_or_uri or "").strip()
        if text.startswith("file:///"):
            text = text[8:]
        text = text.lstrip("/").replace("\\", "/")
        if not text:
            raise ValueError("path_or_uri is required")
        return text

    def _path(self, path_or_uri: str) -> Path:
        return (self.root / self._normalize_object_name(path_or_uri)).resolve()

    def location(self, path_or_uri: str) -> _LocalArtifactLocation:
        rel = self._normalize_object_name(path_or_uri)
        return _LocalArtifactLocation(bucket=self.bucket_name, object_name=rel)

    def upload_file(self, *, local_path: Path, path_or_uri: str, content_type: str | None = None) -> str:
        del content_type
        src = Path(local_path).resolve()
        dst = self._path(path_or_uri)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return self.location(path_or_uri).uri

    def upload_text(self, *, text: str, path_or_uri: str, content_type: str = "text/plain; charset=utf-8") -> str:
        del content_type
        dst = self._path(path_or_uri)
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(str(text or ""), encoding="utf-8")
        return self.location(path_or_uri).uri

    def upload_json(self, *, payload: Any, path_or_uri: str) -> str:
        return self.upload_text(
            text=json.dumps(payload, ensure_ascii=False, indent=2),
            path_or_uri=path_or_uri,
            content_type="application/json; charset=utf-8",
        )

    def download_file(self, *, path_or_uri: str, local_path: Path) -> Path:
        src = self._path(path_or_uri)
        dst = Path(local_path).resolve()
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        return dst

    def download_text(self, *, path_or_uri: str) -> str:
        return self._path(path_or_uri).read_text(encoding="utf-8")

    def download_json(self, *, path_or_uri: str) -> Any:
        return json.loads(self.download_text(path_or_uri=path_or_uri))

    def exists(self, *, path_or_uri: str) -> bool:
        return self._path(path_or_uri).exists()

    def list_prefix(self, *, prefix: str) -> list[_LocalArtifactLocation]:
        base = self._path(prefix)
        if not base.exists():
            return []
        out: list[_LocalArtifactLocation] = []
        for path in sorted(base.rglob("*")):
            if not path.is_file():
                continue
            rel = str(path.relative_to(self.root)).replace("\\", "/")
            out.append(_LocalArtifactLocation(bucket=self.bucket_name, object_name=rel))
        return out

    def delete_prefix(self, *, prefix: str) -> int:
        base = self._path(prefix)
        if not base.exists():
            return 0
        deleted = 0
        for path in sorted(base.rglob("*"), reverse=True):
            if path.is_file():
                path.unlink(missing_ok=True)
                deleted += 1
        shutil.rmtree(base, ignore_errors=True)
        return deleted

    def delete_run_prefix(self, run_id: str) -> int:
        return self.delete_prefix(prefix=self.run_prefix(run_id))


class ProviderRequestRecorder:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.events: list[dict[str, Any]] = []

    def _provider_for_url(self, url: str) -> str | None:
        host = (urlparse(str(url or "")).netloc or "").lower()
        path = (urlparse(str(url or "")).path or "").lower()
        if "openalex" in host:
            return "openalex"
        if "semanticscholar" in host or "/graph/v1/paper/" in path or "/recommendations/v1/" in path:
            return "semanticscholar"
        return None

    def wrap(self, original):
        def _wrapped(session, method, url, *args, **kwargs):
            provider = self._provider_for_url(str(url or ""))
            started = time.time()
            exc_text = None
            response = None
            try:
                response = original(session, method, url, *args, **kwargs)
                return response
            except Exception as exc:  # pragma: no cover - live-run only
                exc_text = repr(exc)
                raise
            finally:
                if provider:
                    entry = {
                        "provider": provider,
                        "method": str(method or "").upper(),
                        "url": str(url or ""),
                        "path": urlparse(str(url or "")).path,
                        "status_code": getattr(response, "status_code", None),
                        "started_at_epoch_s": started,
                        "finished_at_epoch_s": time.time(),
                        "duration_s": max(0.0, time.time() - started),
                        "exception": exc_text,
                    }
                    with self._lock:
                        self.events.append(entry)

        return _wrapped

    def build_summary(self, *, openalex_rps: float, s2_rps: float) -> dict[str, Any]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        with self._lock:
            for event in self.events:
                grouped[str(event.get("provider"))].append(deepcopy(event))

        out: dict[str, Any] = {}
        for provider, items in grouped.items():
            items.sort(key=lambda item: float(item.get("started_at_epoch_s") or 0.0))
            gaps_ms: list[float] = []
            for prev, cur in zip(items, items[1:]):
                gap_ms = max(0.0, (float(cur.get("started_at_epoch_s") or 0.0) - float(prev.get("started_at_epoch_s") or 0.0)) * 1000.0)
                gaps_ms.append(gap_ms)
            target_rps = float(openalex_rps if provider == "openalex" else s2_rps)
            min_gap_target_ms = (1000.0 / target_rps) if target_rps > 0 else 0.0
            tolerance_ms = 90.0
            out[provider] = {
                "calls": len(items),
                "status_codes": sorted({int(x["status_code"]) for x in items if x.get("status_code") is not None}),
                "errors": sum(1 for x in items if x.get("exception")),
                "min_gap_ms": round(min(gaps_ms), 2) if gaps_ms else None,
                "p50_gap_ms": round(_percentile(gaps_ms, 50.0), 2) if gaps_ms else None,
                "p95_gap_ms": round(_percentile(gaps_ms, 95.0), 2) if gaps_ms else None,
                "max_duration_s": round(max(float(x.get("duration_s") or 0.0) for x in items), 3) if items else 0.0,
                "min_gap_target_ms": round(min_gap_target_ms, 2),
                "gap_violations": sum(1 for gap_ms in gaps_ms if min_gap_target_ms > 0 and gap_ms + tolerance_ms < min_gap_target_ms),
                "sample": items[:20],
            }
        return out


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    values_sorted = sorted(float(v) for v in values)
    if len(values_sorted) == 1:
        return values_sorted[0]
    rank = (len(values_sorted) - 1) * (float(pct) / 100.0)
    lo = int(rank)
    hi = min(len(values_sorted) - 1, lo + 1)
    frac = rank - lo
    return values_sorted[lo] + (values_sorted[hi] - values_sorted[lo]) * frac


class InProcessStageLauncher:
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop
        self._lock = threading.Lock()
        self.tasks: set[asyncio.Task[Any]] = set()
        self.launches: list[dict[str, Any]] = []

    async def wait_idle(self, *, timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + float(timeout_s)
        while True:
            with self._lock:
                pending = [task for task in self.tasks if not task.done()]
            if not pending:
                return
            if time.monotonic() >= deadline:
                raise TimeoutError("Timed out waiting for in-process stage launches to drain")
            await asyncio.sleep(0.5)

    def launch(self, *, user_id: str, projekt_id: str, run_id: str, stage: str | None = None) -> dict[str, Any]:
        stage_norm = str(stage or "").strip().lower() or "preprocess"
        launch_meta = {
            "stage": stage_norm,
            "queued_at_epoch_s": time.time(),
        }
        with self._lock:
            self.launches.append(launch_meta)

        async def _runner() -> None:
            await run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id=user_id,
                projekt_id=projekt_id,
                run_id=run_id,
                stage=stage_norm,
            )

        def _schedule() -> None:
            task = self.loop.create_task(_runner(), name=f"two-lane-stage-{stage_norm}-{run_id}")
            with self._lock:
                self.tasks.add(task)

            def _done_callback(done_task: asyncio.Task[Any]) -> None:
                with self._lock:
                    self.tasks.discard(done_task)

            task.add_done_callback(_done_callback)

        self.loop.call_soon_threadsafe(_schedule)
        return {
            "job_name": "local-in-process",
            "region": "local",
            "project_id": str(config.GOOGLE_CLOUD_PROJECT or ""),
            "operation_name": f"local-op-{stage_norm}-{uuid.uuid4().hex[:8]}",
            "execution_name": f"local-exec-{stage_norm}-{uuid.uuid4().hex[:8]}",
        }


@dataclass(frozen=True)
class _BudgetReservation:
    result: str
    status: str
    required_credits: float
    available_credits: float


class _BypassBudgetService:
    async def reserve_operation(self, *, estimate: dict, **kwargs) -> _BudgetReservation:
        del kwargs
        required = float((estimate or {}).get("credits") or 0.0)
        return _BudgetReservation(
            result="reserved",
            status="reserved",
            required_credits=required,
            available_credits=max(required, 9999.0),
        )

    async def mark_running(self, **kwargs) -> None:
        del kwargs

    async def mark_status(self, **kwargs) -> None:
        del kwargs

    async def release_reservation(self, **kwargs) -> None:
        del kwargs


def _json_default_live(value: Any) -> Any:
    if hasattr(value, "isoformat"):
        try:
            return value.isoformat()
        except Exception:
            pass
    return str(value)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the two-lane split Quellen-Finder pipeline locally against live providers.")
    parser.add_argument("--chapter-title", default="Automatisierung der Dokumentenanalyse mittels NLP/LLM")
    parser.add_argument(
        "--chapter-spec",
        default=(
            "Einsatz von LLMs und NLP zur automatisierten Auswertung von Bilanzen, BWAs und Verträgen. "
            "Zeitersparnis in der Marktfolge, Reduktion manueller Fehler. Praxisbeispiele "
            "(z. B. Pilotprojekte anderer Sparkassen oder Finanzinstitute)."
        ),
    )
    parser.add_argument("--openalex-rps", type=float, default=5.0)
    parser.add_argument("--s2-rps", type=float, default=1.0)
    parser.add_argument("--timeout-seconds", type=float, default=14400.0)
    parser.add_argument("--poll-seconds", type=float, default=5.0)
    parser.add_argument("--reasoning-effort", default="high")
    parser.add_argument("--planner-model", default="gpt-5-mini")
    parser.add_argument("--openalex-query-builder-model", default="gpt-5-mini")
    parser.add_argument("--s2-query-builder-model", default="gpt-5-mini")
    parser.add_argument("--rerank-model", default="gpt-5-nano")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--rerank-concurrency", type=int, default=20)
    parser.add_argument("--output-name", default="local_split_live_latest.json")
    return parser.parse_args(argv)


async def _poll_terminal_run(
    *,
    fs: QuellenFinderFirestoreService,
    user_id: str,
    projekt_id: str,
    run_id: str,
    poll_seconds: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + float(timeout_seconds)
    while True:
        data = await asyncio.to_thread(fs.get_run, user_id=user_id, projekt_id=projekt_id, run_id=run_id)
        status_now = str((data or {}).get("status") or "").strip().lower()
        if status_now in {"success", "error", "cancelled"}:
            return data
        if time.monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for run {run_id} to finish; last status={status_now!r}")
        await asyncio.sleep(max(1.0, float(poll_seconds)))


async def _main_async(args: argparse.Namespace) -> dict[str, Any]:
    fs = QuellenFinderFirestoreService()
    run_uuid = uuid.uuid4().hex[:12]
    user_id = f"local-two-lane-{run_uuid}"
    projekt_id = f"local-two-lane-project-{run_uuid}"
    kapitel_id = f"local-two-lane-kapitel-{run_uuid}"
    run_id = f"qf-local-{run_uuid}"
    rate_limit_collection = f"quellenFinderProviderRateLimitsLocal_{run_uuid}"
    temp_root = Path(tempfile.mkdtemp(prefix=f"qf_local_split_live_{run_uuid}_"))
    artifact_store = LocalArtifactStore(temp_root / "artifacts", base_prefix="two-lane-live")
    recorder = ProviderRequestRecorder()
    stage_launcher = InProcessStageLauncher(asyncio.get_running_loop())
    persisted: dict[str, Any] = {}

    os.environ["TWO_LANE_OPENALEX_RPS"] = str(float(args.openalex_rps))
    os.environ["TWO_LANE_SEMANTICSCHOLAR_RPS"] = str(float(args.s2_rps))
    os.environ["TWO_LANE_PROVIDER_RATE_LIMIT_BACKEND"] = "firestore"
    os.environ["TWO_LANE_PROVIDER_RATE_LIMIT_COLLECTION"] = rate_limit_collection
    os.environ["TWO_LANE_PROVIDER_RATE_LIMIT_MAX_FUTURE_MS"] = "86400000"
    os.environ["TWO_LANE_PROVIDER_RATE_LIMIT_DISPATCH_BUFFER_MS"] = "150"

    config.TWO_LANE_SOURCES_EXECUTION_BACKEND = "local_split_jobs"
    config.TWO_LANE_TASK_DISPATCH_BACKEND = "local_background"

    settings = {
        "openai_model_planner": str(args.planner_model),
        "openai_model_openalex_query_builder": str(args.openalex_query_builder_model),
        "openai_model_s2_query_builder": str(args.s2_query_builder_model),
        "openai_model_rerank": str(args.rerank_model),
        "embedding_model": str(args.embedding_model),
        "openai_reasoning_effort": str(args.reasoning_effort),
        "rerank_concurrency": int(args.rerank_concurrency),
    }

    fs.create_run(
        user_id=user_id,
        projekt_id=projekt_id,
        run_id=run_id,
        kind="sources_two_lane",
        kapitel_ids=[kapitel_id],
        kapitel_snapshots=[
            {
                "id": kapitel_id,
                "title": str(args.chapter_title),
                "ueberschrift": str(args.chapter_title),
                "thema": str(args.chapter_spec),
            }
        ],
        model=str(args.planner_model),
        extra={
            "executionBackend": "local_split_jobs",
            "chapterInputSnapshot": {
                "chapterTitle": str(args.chapter_title),
                "chapterSpecText": str(args.chapter_spec),
            },
            "twoLaneSettingsRequested": settings,
            "job": {
                "provider": "local_split_jobs",
                "jobName": "local-in-process",
                "region": "local",
                "operationName": None,
                "executionName": None,
                "launchedAt": None,
                "launchError": None,
            },
            "splitExecution": {
                "backend": "local_split_jobs",
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

    inflight_dir = BACKEND_ROOT / ".two_lane_artifacts" / "live_runs"
    inflight_dir.mkdir(parents=True, exist_ok=True)
    inflight_path = inflight_dir / (str(args.output_name or "local_split_live_latest.json").replace(".json", ".started.json"))
    inflight_payload = {
        "user_id": user_id,
        "projekt_id": projekt_id,
        "kapitel_id": kapitel_id,
        "run_id": run_id,
        "started_at_epoch_s": time.time(),
    }
    inflight_path.write_text(json.dumps(inflight_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"event": "started", **inflight_payload}, ensure_ascii=False), flush=True)

    original_request = requests.sessions.Session.request
    original_job_artifact = jobmod._artifact_store_from_config
    original_provider_artifact = provider_tasks._artifact_store_from_run_doc
    original_launcher_job = jobmod.cloud_run_job_launcher.execute_two_lane_sources_job
    original_launcher_provider = provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job
    original_persist = jobmod._persist_two_lane_pipeline_success
    original_budget_factory = pipeline_mod.get_openai_budget_service

    def _patched_persist(*, fs, user_id, projekt_id, run_id, result, elapsed_seconds):
        persisted["result"] = {
            "output": deepcopy(result.get("output") if isinstance(result, dict) else None),
            "telemetry": deepcopy(result.get("telemetry") if isinstance(result, dict) else None),
            "metrics": deepcopy(result.get("metrics") if isinstance(result, dict) else None),
            "costs": deepcopy(result.get("costs") if isinstance(result, dict) else None),
            "effective_settings": deepcopy(result.get("effective_settings") if isinstance(result, dict) else None),
            "elapsed_seconds_finalize_only": float(elapsed_seconds),
        }
        return _persist_two_lane_pipeline_success_orig(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            result=result,
            elapsed_seconds=elapsed_seconds,
        )

    requests.sessions.Session.request = recorder.wrap(original_request)
    jobmod._artifact_store_from_config = lambda run_doc=None: artifact_store
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    jobmod.cloud_run_job_launcher.execute_two_lane_sources_job = stage_launcher.launch
    provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = stage_launcher.launch
    jobmod._persist_two_lane_pipeline_success = _patched_persist
    pipeline_mod.get_openai_budget_service = lambda firebase: _BypassBudgetService()

    started = time.time()
    try:
        await run_quellen_finder_sources_two_lane_job_from_run_doc(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            stage="preprocess",
        )
        final_doc = await _poll_terminal_run(
            fs=fs,
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            poll_seconds=float(args.poll_seconds),
            timeout_seconds=float(args.timeout_seconds),
        )
        await stage_launcher.wait_idle(timeout_s=60.0)
    finally:
        requests.sessions.Session.request = original_request
        jobmod._artifact_store_from_config = original_job_artifact
        provider_tasks._artifact_store_from_run_doc = original_provider_artifact
        jobmod.cloud_run_job_launcher.execute_two_lane_sources_job = original_launcher_job
        provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = original_launcher_provider
        jobmod._persist_two_lane_pipeline_success = original_persist
        pipeline_mod.get_openai_budget_service = original_budget_factory

    finished = time.time()
    delete_provider_rate_limit_docs(collection_name=rate_limit_collection, providers=["openalex", "semanticscholar"])
    run_prefix_path = temp_root / "artifacts" / artifact_store.run_prefix(run_id)
    cleanup_exists_after = run_prefix_path.exists()

    split_execution = final_doc.get("splitExecution") if isinstance(final_doc.get("splitExecution"), dict) else {}
    persisted_result = persisted.get("result") if isinstance(persisted.get("result"), dict) else {}
    output = persisted_result.get("output") if isinstance(persisted_result, dict) else {}
    top = output.get("top") if isinstance(output, dict) else {}

    result = {
        "ok": str((final_doc or {}).get("status") or "").strip().lower() == "success",
        "user_id": user_id,
        "projekt_id": projekt_id,
        "kapitel_id": kapitel_id,
        "run_id": run_id,
        "status": (final_doc or {}).get("status"),
        "started_at_epoch_s": started,
        "finished_at_epoch_s": finished,
        "elapsed_seconds_total": round(finished - started, 3),
        "summary": deepcopy((final_doc or {}).get("summary") or {}),
        "result_count": int((final_doc or {}).get("resultCount") or 0),
        "cleanup": deepcopy((final_doc.get("twoLaneArtifacts") if isinstance(final_doc.get("twoLaneArtifacts"), dict) else {})),
        "split_execution": deepcopy(split_execution),
        "launches": deepcopy(stage_launcher.launches),
        "provider_requests": recorder.build_summary(openalex_rps=float(args.openalex_rps), s2_rps=float(args.s2_rps)),
        "persisted_result_meta": {
            "costs": deepcopy(persisted_result.get("costs") or {}),
            "effective_settings": deepcopy(persisted_result.get("effective_settings") or {}),
            "telemetry_keys": sorted(list((persisted_result.get("telemetry") or {}).keys())) if isinstance(persisted_result.get("telemetry"), dict) else [],
            "top_counts": {
                "match_with_abstract": len(((top.get("match") or {}).get("with_abstract") or [])) if isinstance(top, dict) else 0,
                "authority_with_abstract": len(((top.get("authority") or {}).get("with_abstract") or [])) if isinstance(top, dict) else 0,
            },
        },
        "local_artifact_root": str(temp_root),
        "local_artifact_exists_after_run": bool(cleanup_exists_after),
    }
    shutil.rmtree(temp_root, ignore_errors=True)
    try:
        inflight_path.unlink(missing_ok=True)
    except Exception:
        pass
    return result


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    result = asyncio.run(_main_async(args))
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "live_runs"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / str(args.output_name or "local_split_live_latest.json")
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default_live), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=_json_default_live))
    return 0 if bool(result.get("ok")) else 1


if __name__ == "__main__":
    raise SystemExit(main())
