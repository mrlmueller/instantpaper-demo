from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import threading
import time
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources import provider_tasks
from services.two_lane_sources.internal_tasks import run_two_lane_internal_task_payload
from services.two_lane_sources.pipeline import OpenAlexQuery, PipelineConfig, S2BulkQuery


def _deep_merge(base: Any, patch: Any) -> Any:
    if not isinstance(base, dict) or not isinstance(patch, dict):
        return deepcopy(patch)
    out = deepcopy(base)
    for key, value in patch.items():
        if key in out and isinstance(out[key], dict) and isinstance(value, dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out


class FakeFirestoreService:
    def __init__(self, initial_doc: dict[str, Any]) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {("user", "project", "run-123"): deepcopy(initial_doc)}
        self.task_docs: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def run_ref(self, user_id: str, projekt_id: str, run_id: str):
        service = self
        key = (str(user_id), str(projekt_id), str(run_id))

        class _RunRef:
            def get(self):
                data = deepcopy(service.docs.get(key))

                class _Snap:
                    exists = data is not None

                    def to_dict(self_inner):
                        return deepcopy(data or {})

                return _Snap()

            def set(self, payload: dict[str, Any], merge: bool = False) -> None:
                current = deepcopy(service.docs.get(key) or {})
                service.docs[key] = deepcopy(payload) if not merge else _deep_merge(current, deepcopy(payload))

        return _RunRef()

    def get_run(self, *, user_id: str, projekt_id: str, run_id: str) -> dict[str, Any]:
        data = self.docs.get((str(user_id), str(projekt_id), str(run_id)))
        if data is None:
            raise ValueError("Run not found.")
        return deepcopy(data)

    def enqueue_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, stage_name: str, queue_name: str, task_key: str, results_prefix: str) -> bool:
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() in {"queued", "running", "success", "cancelled", "skipped"}:
            return False
        self.task_docs[key] = {
            "provider": str(provider),
            "stageName": str(stage_name),
            "queueName": str(queue_name),
            "taskKey": str(task_key),
            "status": "queued",
            "failCount": 0,
        }
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        provider_work = doc.setdefault("providerWork", {}).setdefault(str(provider), {})
        provider_work["pendingTasks"] = int(provider_work.get("pendingTasks") or 0) + 1
        provider_work["enqueuedTasks"] = int(provider_work.get("enqueuedTasks") or 0) + 1
        provider_work["resultsPrefix"] = str(results_prefix)
        provider_work["status"] = "running"
        split_state = doc.setdefault("splitExecution", {}).setdefault(str(stage_name), {})
        split_state["status"] = "running"
        return True

    def claim_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stale_after_ms: int = 1_800_000) -> bool:
        result = self.claim_two_lane_provider_task_result(
            user_id=user_id,
            projekt_id=projekt_id,
            run_id=run_id,
            provider=provider,
            task_key=task_key,
            stale_after_ms=stale_after_ms,
        )
        return str((result or {}).get("status") or "").strip().lower() == "claimed"

    def claim_two_lane_provider_task_result(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stale_after_ms: int = 1_800_000) -> dict[str, Any]:
        del stale_after_ms
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key)
        if task is None:
            return {"status": "missing"}
        status_now = str(task.get("status") or "").strip().lower()
        if status_now == "success":
            return {"status": "already_success"}
        if status_now in {"running", "cancelled", "skipped"}:
            return {"status": "running"}
        task["status"] = "running"
        return {"status": "claimed"}

    def complete_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stage_name: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() == "success":
            doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
            provider_work = (doc.get("providerWork") or {}).get(str(provider)) or {}
            return {"provider_done": int(provider_work.get("pendingTasks") or 0) <= 0, "already_done": True}
        task["status"] = "success"
        task["summary"] = deepcopy(summary or {})
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        provider_work = doc.setdefault("providerWork", {}).setdefault(str(provider), {})
        provider_work["pendingTasks"] = max(0, int(provider_work.get("pendingTasks") or 0) - 1)
        provider_work["completedTasks"] = int(provider_work.get("completedTasks") or 0) + 1
        provider_done = int(provider_work.get("pendingTasks") or 0) <= 0
        if provider_done:
            provider_work["status"] = "success"
            doc.setdefault("splitExecution", {}).setdefault(str(stage_name), {})["status"] = "success"
        return {"provider_done": provider_done, "already_done": False}

    def retry_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stage_name: str, error_message: str | None = None) -> dict[str, Any]:
        del stage_name
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() == "success":
            return {"retry_queued": False, "already_done": True}
        task["status"] = "queued"
        task["failCount"] = int(task.get("failCount") or 0) + 1
        task["lastError"] = str(error_message or "")
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        provider_work = doc.setdefault("providerWork", {}).setdefault(str(provider), {})
        provider_work["retryCount"] = int(provider_work.get("retryCount") or 0) + 1
        provider_work["status"] = "running"
        provider_work["lastError"] = str(error_message or "")
        return {"retry_queued": True, "already_done": False}

    def skip_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stage_name: str, reason: str, summary: dict[str, Any] | None = None, error_message: str | None = None) -> dict[str, Any]:
        del reason, error_message
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() in {"success", "cancelled", "skipped"}:
            doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
            provider_work = (doc.get("providerWork") or {}).get(str(provider)) or {}
            return {"provider_done": int(provider_work.get("pendingTasks") or 0) <= 0, "already_done": True}
        task["status"] = "cancelled"
        task["summary"] = deepcopy(summary or {})
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        provider_work = doc.setdefault("providerWork", {}).setdefault(str(provider), {})
        provider_work["pendingTasks"] = max(0, int(provider_work.get("pendingTasks") or 0) - 1)
        provider_work["skippedTasks"] = int(provider_work.get("skippedTasks") or 0) + 1
        provider_work["status"] = "cancelled"
        doc.setdefault("splitExecution", {}).setdefault(str(stage_name), {})["status"] = "cancelled"
        return {"provider_done": int(provider_work.get("pendingTasks") or 0) <= 0, "already_done": False}

    def try_queue_two_lane_stage(self, *, user_id: str, projekt_id: str, run_id: str, target_stage: str, prerequisite_stages, allowed_current_statuses, current_stage_value: str | None = None) -> bool:
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        if bool(doc.get("cancelRequestedAt")) or str(doc.get("status") or "").strip().lower() in {"success", "error", "cancelled"}:
            return False
        split_execution = doc.get("splitExecution") if isinstance(doc.get("splitExecution"), dict) else {}
        for stage_name in list(prerequisite_stages or []):
            stage_state = split_execution.get(stage_name) if isinstance(split_execution.get(stage_name), dict) else {}
            if str((stage_state or {}).get("status") or "").strip().lower() != "success":
                return False
        target_state = split_execution.get(target_stage) if isinstance(split_execution.get(target_stage), dict) else {}
        allowed = {str(x).strip().lower() for x in list(allowed_current_statuses or [])}
        if str((target_state or {}).get("status") or "").strip().lower() not in allowed:
            return False
        doc.setdefault("splitExecution", {})["currentStage"] = str(current_stage_value or target_stage)
        doc["splitExecution"].setdefault(str(target_stage), {})["status"] = "queued"
        return True


class _LocalLocation:
    def __init__(self, root: Path, rel: str) -> None:
        self.bucket = "local-test"
        self.object_name = rel
        self.uri = f"file:///{(root / rel).resolve().as_posix()}"


class LocalArtifactStore:
    def __init__(self, root: Path, *, base_prefix: str = "two-lane-retry") -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.bucket_name = "local-test"
        self.base_prefix = str(base_prefix or "").strip().strip("/")

    def run_prefix(self, run_id: str) -> str:
        if self.base_prefix:
            return f"{self.base_prefix}/{str(run_id).strip()}"
        return str(run_id).strip()

    def _target(self, rel: str) -> Path:
        return (self.root / str(rel or "").strip().lstrip("/")).resolve()

    def upload_text(self, *, text: str, path_or_uri: str, content_type: str = "text/plain; charset=utf-8") -> str:
        del content_type
        target = self._target(path_or_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(str(text or ""), encoding="utf-8")
        return target.as_uri()

    def upload_json(self, *, payload: Any, path_or_uri: str) -> str:
        return self.upload_text(text=json.dumps(payload, ensure_ascii=False, indent=2), path_or_uri=path_or_uri, content_type="application/json")

    def download_json(self, *, path_or_uri: str):
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        return json.loads(source.read_text(encoding="utf-8"))

    def download_text(self, *, path_or_uri: str) -> str:
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        return source.read_text(encoding="utf-8")

    def exists(self, *, path_or_uri: str) -> bool:
        if str(path_or_uri or "").startswith("file:///"):
            source = Path(str(path_or_uri).replace("file:///", "")).resolve()
        else:
            source = self._target(path_or_uri)
        return source.exists()

    def list_prefix(self, *, prefix: str):
        base = self._target(prefix)
        if not base.exists():
            return []
        files = [p for p in base.rglob("*") if p.is_file()]
        return [_LocalLocation(self.root, str(path.relative_to(self.root)).replace("\\", "/")) for path in files]


class FakeDispatcher:
    def __init__(self) -> None:
        self.openalex_queue = "openalex-local"
        self.semanticscholar_queue = "s2-local"
        self.tasks: list[dict[str, Any]] = []

    def enqueue(self, *, queue_key: str, task_name: str, payload: dict[str, Any], **kwargs):
        del kwargs
        self.tasks.append({"queue_key": str(queue_key), "task_name": str(task_name), "payload": deepcopy(payload)})
        return {"created": True}


class _ServerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []

    def record(self, *, provider: str, endpoint: str, method: str, params: dict[str, Any]) -> None:
        with self.lock:
            self.requests.append(
                {
                    "provider": provider,
                    "endpoint": endpoint,
                    "method": method,
                    "params": params,
                    "ts": time.monotonic(),
                }
            )


class _FakeHandler(BaseHTTPRequestHandler):
    state: _ServerState

    def log_message(self, format, *args):  # noqa: A003
        return

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        if parsed.path == "/works":
            self.state.record(provider="openalex", endpoint="works", method="GET", params=params)
            self._send_json(
                200,
                {
                    "results": [
                        {
                            "id": "https://openalex.org/W1",
                            "doi": "10.1000/oa1",
                            "display_name": "OpenAlex Page 1",
                            "publication_year": 2024,
                            "type": "article",
                            "ids": {"openalex": "W1"},
                            "cited_by_count": 5,
                            "primary_location": {"source": {"display_name": "Test Venue"}},
                            "authorships": [{"author": {"display_name": "Author 1"}}],
                            "abstract_inverted_index": {"page": [0], "one": [1]},
                        }
                    ],
                    "meta": {"next_cursor": None},
                },
            )
            return
        if parsed.path == "/graph/v1/paper/search/bulk":
            self.state.record(provider="semanticscholar", endpoint="bulk", method="GET", params=params)
            self._send_json(200, {"data": [{"paperId": "S2-A"}], "token": None})
            return
        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body_raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        try:
            body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
        except Exception:
            body = {}
        params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        if parsed.path == "/graph/v1/paper/batch":
            self.state.record(provider="semanticscholar", endpoint="batch", method="POST", params=params)
            ids = [str(x) for x in ((body or {}).get("ids") or [])]
            self._send_json(
                200,
                {
                    "data": [
                        {
                            "paperId": pid,
                            "title": f"Hydrated {pid}",
                            "year": 2024,
                            "authors": [{"name": "Test Author"}],
                            "venue": "Test Venue",
                            "url": f"https://example.org/{pid}",
                            "externalIds": {"DOI": f"10.1000/{pid.lower()}"},
                            "citationCount": 1,
                            "influentialCitationCount": 0,
                            "abstract": f"Abstract for {pid}",
                        }
                        for pid in ids
                    ]
                },
            )
            return
        self._send_json(404, {"error": "not found"})


def _base_doc() -> dict[str, Any]:
    return {
        "kind": "sources_two_lane",
        "status": "running",
        "kapitelIds": ["kapitel"],
        "executionBackend": "local_split_jobs",
        "splitExecution": {
            "currentStage": "provider_fetch",
            "openalex_fetch": {"status": "running"},
            "s2_fetch": {"status": "running"},
            "candidates": {"status": "pending"},
            "finalize": {"status": "pending"},
        },
    }


def _build_cfg(base_url: str) -> PipelineConfig:
    return PipelineConfig(
        runs_root=Path(tempfile.gettempdir()),
        pipeline_version="two_lane_v1",
        openalex_base_url=base_url,
        openalex_rps=5.0,
        semanticscholar_base_url=base_url + "/graph/v1",
        semanticscholar_rps=2.0,
        provider_rate_limit_backend="local",
        provider_rate_limit_collection="unused",
        provider_rate_limit_dispatch_buffer_ms=0,
        force_rebuild=False,
    )


async def _exercise_retry(provider: str) -> dict[str, Any]:
    initial_doc = _base_doc()
    if provider == "openalex":
        initial_doc["splitExecution"]["s2_fetch"]["status"] = "success"
    else:
        initial_doc["splitExecution"]["openalex_fetch"]["status"] = "success"
    fake_fs = FakeFirestoreService(initial_doc)
    dispatcher = FakeDispatcher()
    launches: list[str] = []
    artifact_root = Path(tempfile.mkdtemp(prefix=f"two_lane_retry_{provider}_"))
    artifact_store = LocalArtifactStore(artifact_root / "artifacts")
    state = _ServerState()
    handler_cls = type("FakeRetryHandler", (_FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    cfg = _build_cfg(base_url)

    fail_once = {"remaining": 1}
    original = {
        "QuellenFinderFirestoreService": provider_tasks.QuellenFinderFirestoreService,
        "_artifact_store_from_run_doc": provider_tasks._artifact_store_from_run_doc,
        "build_two_lane_task_dispatcher": provider_tasks.build_two_lane_task_dispatcher,
        "PipelineConfig_from_env": provider_tasks.PipelineConfig.from_env,
        "launch": provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job,
        "request_json": provider_tasks.request_json,
    }

    def _failing_request_json(*args, **kwargs):
        if str(kwargs.get("provider") or "").strip().lower() == provider and int(fail_once["remaining"]) > 0:
            fail_once["remaining"] -= 1
            raise RuntimeError(f"Injected {provider} failure")
        return original["request_json"](*args, **kwargs)

    provider_tasks.QuellenFinderFirestoreService = lambda: fake_fs
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    provider_tasks.build_two_lane_task_dispatcher = lambda: dispatcher
    provider_tasks.PipelineConfig.from_env = classmethod(lambda cls, *, runs_root, pipeline_version: cfg)
    provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = lambda **kwargs: launches.append(str(kwargs.get("stage"))) or {"execution_name": f"exec-{provider}", "operation_name": f"op-{provider}"}
    provider_tasks.request_json = _failing_request_json

    try:
        if provider == "openalex":
            provider_tasks.seed_openalex_provider_tasks(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                queries=[
                    OpenAlexQuery(
                        intent="match",
                        language="en",
                        search_field="title_and_abstract.search",
                        query_string='"balance sheet" AND automation',
                        filters="language:en",
                        sort="relevance_score:desc",
                        per_page=200,
                        notes="retry test",
                    )
                ],
                run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
            )
        else:
            provider_tasks.seed_s2_provider_tasks(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                queries=[S2BulkQuery(intent="match", language="en", query_string='"balance sheet" AND automation', notes="retry test")],
                run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
            )

        item = dispatcher.tasks.pop(0)
        first_error = None
        try:
            await run_two_lane_internal_task_payload(item["payload"])
        except Exception as exc:  # expected
            first_error = str(exc)

        task_doc_key = ("user", "project", "run-123", f"{provider}--{item['task_name']}")
        after_first = deepcopy(fake_fs.task_docs.get(task_doc_key) or {})
        first_run = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")

        second_result = await run_two_lane_internal_task_payload(item["payload"])
        after_second = deepcopy(fake_fs.task_docs.get(task_doc_key) or {})
        second_run = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")
    finally:
        provider_tasks.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
        provider_tasks._artifact_store_from_run_doc = original["_artifact_store_from_run_doc"]
        provider_tasks.build_two_lane_task_dispatcher = original["build_two_lane_task_dispatcher"]
        provider_tasks.PipelineConfig.from_env = original["PipelineConfig_from_env"]
        provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = original["launch"]
        provider_tasks.request_json = original["request_json"]
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        shutil.rmtree(artifact_root, ignore_errors=True)

    if first_error is None:
        raise RuntimeError(f"Expected injected {provider} failure on first attempt")
    if str(after_first.get("status") or "").strip().lower() != "queued":
        raise RuntimeError(f"{provider} task was not re-queued after failure: {after_first}")
    if int((((first_run.get('providerWork') or {}).get(provider) or {}).get("pendingTasks") or 0)) != 1:
        raise RuntimeError(f"{provider} pendingTasks changed unexpectedly after failure: {first_run.get('providerWork')}")
    if str(after_second.get("status") or "").strip().lower() != "success":
        raise RuntimeError(f"{provider} task did not complete on retry: {after_second}")
    if int((((second_run.get('providerWork') or {}).get(provider) or {}).get("pendingTasks") or 0)) != 0:
        raise RuntimeError(f"{provider} pendingTasks did not drain after retry success: {second_run.get('providerWork')}")
    if launches != ["candidates"]:
        raise RuntimeError(f"{provider} retry path did not queue candidates exactly once: {launches}")

    return {
        "provider": provider,
        "first_error": first_error,
        "after_first": after_first,
        "second_result": second_result,
        "after_second": after_second,
        "launches": launches,
        "request_count": len(state.requests),
    }


async def _exercise_cancel_midflight() -> dict[str, Any]:
    initial_doc = _base_doc()
    initial_doc["splitExecution"]["s2_fetch"]["status"] = "success"
    fake_fs = FakeFirestoreService(initial_doc)
    dispatcher = FakeDispatcher()
    launches: list[str] = []
    artifact_root = Path(tempfile.mkdtemp(prefix="two_lane_cancel_midflight_"))
    artifact_store = LocalArtifactStore(artifact_root / "artifacts")
    state = _ServerState()
    handler_cls = type("FakeCancelHandler", (_FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    cfg = _build_cfg(base_url)

    original = {
        "QuellenFinderFirestoreService": provider_tasks.QuellenFinderFirestoreService,
        "_artifact_store_from_run_doc": provider_tasks._artifact_store_from_run_doc,
        "build_two_lane_task_dispatcher": provider_tasks.build_two_lane_task_dispatcher,
        "PipelineConfig_from_env": provider_tasks.PipelineConfig.from_env,
        "launch": provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job,
        "request_json": provider_tasks.request_json,
    }

    def _cancelling_request_json(*args, **kwargs):
        doc = fake_fs.docs[("user", "project", "run-123")]
        doc["cancelRequestedAt"] = "now"
        return original["request_json"](*args, **kwargs)

    provider_tasks.QuellenFinderFirestoreService = lambda: fake_fs
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    provider_tasks.build_two_lane_task_dispatcher = lambda: dispatcher
    provider_tasks.PipelineConfig.from_env = classmethod(lambda cls, *, runs_root, pipeline_version: cfg)
    provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = lambda **kwargs: launches.append(str(kwargs.get("stage"))) or {"execution_name": "exec-cancel", "operation_name": "op-cancel"}
    provider_tasks.request_json = _cancelling_request_json

    try:
        provider_tasks.seed_openalex_provider_tasks(
            user_id="user",
            projekt_id="project",
            run_id="run-123",
            queries=[
                OpenAlexQuery(
                    intent="match",
                    language="en",
                    search_field="title_and_abstract.search",
                    query_string='"balance sheet" AND automation',
                    filters="language:en",
                    sort="relevance_score:desc",
                    per_page=200,
                    notes="cancel test",
                )
            ],
            run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
        )
        item = dispatcher.tasks.pop(0)
        result = await run_two_lane_internal_task_payload(item["payload"])
        task_doc_key = ("user", "project", "run-123", f"openalex--{item['task_name']}")
        task_doc = deepcopy(fake_fs.task_docs.get(task_doc_key) or {})
        run_doc = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")
    finally:
        provider_tasks.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
        provider_tasks._artifact_store_from_run_doc = original["_artifact_store_from_run_doc"]
        provider_tasks.build_two_lane_task_dispatcher = original["build_two_lane_task_dispatcher"]
        provider_tasks.PipelineConfig.from_env = original["PipelineConfig_from_env"]
        provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = original["launch"]
        provider_tasks.request_json = original["request_json"]
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        shutil.rmtree(artifact_root, ignore_errors=True)

    provider_work = ((run_doc.get("providerWork") or {}).get("openalex") or {})
    if not result.get("skipped"):
        raise RuntimeError(f"Expected skipped cancel result, got: {result}")
    if str(task_doc.get("status") or "").strip().lower() != "cancelled":
        raise RuntimeError(f"Cancel test task did not end as cancelled: {task_doc}")
    if int(provider_work.get("pendingTasks") or 0) != 0:
        raise RuntimeError(f"Cancel test pendingTasks not drained: {provider_work}")
    if launches:
        raise RuntimeError(f"Cancel test unexpectedly launched follow-up stages: {launches}")

    return {
        "result": result,
        "task_doc": task_doc,
        "provider_work": provider_work,
        "requests": deepcopy(state.requests),
        "launches": launches,
    }


async def _main() -> dict[str, Any]:
    openalex_retry = await _exercise_retry("openalex")
    s2_retry = await _exercise_retry("semanticscholar")
    cancel_midflight = await _exercise_cancel_midflight()
    return {
        "ok": True,
        "openalex_retry": openalex_retry,
        "s2_retry": s2_retry,
        "cancel_midflight": cancel_midflight,
    }


def main() -> int:
    result = asyncio.run(_main())
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_provider_task_retry_cancel_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
