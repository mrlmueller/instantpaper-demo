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

from services.two_lane_sources.internal_tasks import run_two_lane_internal_task_payload
from services.two_lane_sources.pipeline import OpenAlexQuery, PipelineConfig, S2BulkQuery
from services.two_lane_sources import provider_tasks


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


class _FakeSnapshot:
    def __init__(self, data: dict[str, Any] | None) -> None:
        self._data = deepcopy(data) if isinstance(data, dict) else None
        self.exists = self._data is not None

    def to_dict(self) -> dict[str, Any]:
        return deepcopy(self._data or {})


class _FakeRunRef:
    def __init__(self, service: "FakeFirestoreService", key: tuple[str, str, str]) -> None:
        self.service = service
        self.key = key

    def get(self) -> _FakeSnapshot:
        return _FakeSnapshot(self.service.docs.get(self.key))

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        current = deepcopy(self.service.docs.get(self.key) or {})
        if not merge:
            self.service.docs[self.key] = deepcopy(payload)
            return
        self.service.docs[self.key] = _deep_merge(current, deepcopy(payload))

    def collection(self, name: str):
        return _FakeCollection(self.service, (*self.key, str(name)))


class _FakeCollection:
    def __init__(self, service: "FakeFirestoreService", key: tuple[str, ...]) -> None:
        self.service = service
        self.key = key

    def document(self, doc_id: str):
        return _FakeSubDocRef(self.service, (*self.key, str(doc_id)))


class _FakeSubDocRef:
    def __init__(self, service: "FakeFirestoreService", key: tuple[str, ...]) -> None:
        self.service = service
        self.key = key

    def set(self, payload: dict[str, Any], merge: bool = False) -> None:
        current = deepcopy(self.service.subdocs.get(self.key) or {})
        if not merge:
            self.service.subdocs[self.key] = deepcopy(payload)
            return
        self.service.subdocs[self.key] = _deep_merge(current, deepcopy(payload))


class FakeFirestoreService:
    def __init__(self, initial_doc: dict[str, Any]) -> None:
        self.docs: dict[tuple[str, str, str], dict[str, Any]] = {("user", "project", "run-123"): deepcopy(initial_doc)}
        self.subdocs: dict[tuple[str, ...], dict[str, Any]] = {}
        self.task_docs: dict[tuple[str, str, str, str], dict[str, Any]] = {}

    def run_ref(self, user_id: str, projekt_id: str, run_id: str):
        return _FakeRunRef(self, (str(user_id), str(projekt_id), str(run_id)))

    def get_run(self, *, user_id: str, projekt_id: str, run_id: str) -> dict[str, Any]:
        data = self.docs.get((str(user_id), str(projekt_id), str(run_id)))
        if data is None:
            raise ValueError("Run not found.")
        return deepcopy(data)

    def enqueue_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, stage_name: str, queue_name: str, task_key: str, results_prefix: str) -> bool:
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() in {"queued", "running", "success"}:
            return False
        self.task_docs[key] = {
            "provider": str(provider),
            "stageName": str(stage_name),
            "queueName": str(queue_name),
            "taskKey": str(task_key),
            "status": "queued",
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
        del stale_after_ms
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key)
        if task is None:
            return False
        if str(task.get("status") or "").strip().lower() == "success":
            return False
        if str(task.get("status") or "").strip().lower() == "running":
            return False
        task["status"] = "running"
        return True

    def complete_two_lane_provider_task(self, *, user_id: str, projekt_id: str, run_id: str, provider: str, task_key: str, stage_name: str, summary: dict[str, Any] | None = None) -> dict[str, Any]:
        del summary
        key = (str(user_id), str(projekt_id), str(run_id), f"{provider}--{task_key}")
        task = self.task_docs.get(key) or {}
        if str(task.get("status") or "").strip().lower() == "success":
            doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
            provider_work = (doc.get("providerWork") or {}).get(str(provider)) or {}
            return {"provider_done": int(provider_work.get("pendingTasks") or 0) <= 0, "already_done": True}
        task["status"] = "success"
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        provider_work = doc.setdefault("providerWork", {}).setdefault(str(provider), {})
        provider_work["pendingTasks"] = max(0, int(provider_work.get("pendingTasks") or 0) - 1)
        provider_work["completedTasks"] = int(provider_work.get("completedTasks") or 0) + 1
        provider_done = int(provider_work.get("pendingTasks") or 0) <= 0
        if provider_done:
            provider_work["status"] = "success"
            doc.setdefault("splitExecution", {}).setdefault(str(stage_name), {})["status"] = "success"
        return {"provider_done": provider_done, "already_done": False}

    def try_queue_two_lane_stage(self, *, user_id: str, projekt_id: str, run_id: str, target_stage: str, prerequisite_stages, allowed_current_statuses, current_stage_value: str | None = None) -> bool:
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
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
    def __init__(self, root: Path, *, base_prefix: str = "two-lane-test") -> None:
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
            cursor = str(params.get("cursor") or "*")
            if cursor == "*":
                payload = {
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
                    "meta": {"next_cursor": "CURSOR-2"},
                }
            else:
                payload = {
                    "results": [
                        {
                            "id": "https://openalex.org/W2",
                            "doi": "10.1000/oa2",
                            "display_name": "OpenAlex Page 2",
                            "publication_year": 2023,
                            "type": "article",
                            "ids": {"openalex": "W2"},
                            "cited_by_count": 2,
                            "primary_location": {"source": {"display_name": "Test Venue"}},
                            "authorships": [{"author": {"display_name": "Author 2"}}],
                            "abstract_inverted_index": {"page": [0], "two": [1]},
                        }
                    ],
                    "meta": {"next_cursor": None},
                }
            self._send_json(200, payload)
            return

        if parsed.path == "/graph/v1/paper/search/bulk":
            self.state.record(provider="semanticscholar", endpoint="bulk", method="GET", params=params)
            token = str(params.get("token") or "")
            if not token:
                payload = {"data": [{"paperId": "S2-A"}, {"paperId": "S2-B"}], "token": "TOKEN-2"}
            else:
                payload = {"data": [{"paperId": "S2-C"}], "token": None}
            self._send_json(200, payload)
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


async def _drain(dispatcher: FakeDispatcher) -> list[dict[str, Any]]:
    processed: list[dict[str, Any]] = []
    while dispatcher.tasks:
        item = dispatcher.tasks.pop(0)
        result = await run_two_lane_internal_task_payload(item["payload"])
        processed.append({"task_name": item["task_name"], "kind": item["payload"].get("kind"), "result": result})
    return processed


async def _main() -> dict[str, Any]:
    initial_doc = {
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
    fake_fs = FakeFirestoreService(initial_doc)
    dispatcher = FakeDispatcher()
    launches: list[str] = []
    artifact_root = Path(tempfile.mkdtemp(prefix="two_lane_provider_tasks_"))
    artifact_store = LocalArtifactStore(artifact_root / "artifacts")
    state = _ServerState()
    handler_cls = type("FakeHandler", (_FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"

    cfg = PipelineConfig(
        runs_root=artifact_root,
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

    original = {
        "QuellenFinderFirestoreService": provider_tasks.QuellenFinderFirestoreService,
        "_artifact_store_from_run_doc": provider_tasks._artifact_store_from_run_doc,
        "build_two_lane_task_dispatcher": provider_tasks.build_two_lane_task_dispatcher,
        "PipelineConfig_from_env": provider_tasks.PipelineConfig.from_env,
        "launch": provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job,
    }

    provider_tasks.QuellenFinderFirestoreService = lambda: fake_fs
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    provider_tasks.build_two_lane_task_dispatcher = lambda: dispatcher
    provider_tasks.PipelineConfig.from_env = classmethod(lambda cls, *, runs_root, pipeline_version: cfg)
    provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = lambda **kwargs: launches.append(str(kwargs.get("stage"))) or {"execution_name": "exec-candidates", "operation_name": "op-candidates"}

    try:
        openalex_seed = provider_tasks.seed_openalex_provider_tasks(
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
                    notes="test",
                )
            ],
            run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
        )
        s2_seed = provider_tasks.seed_s2_provider_tasks(
            user_id="user",
            projekt_id="project",
            run_id="run-123",
            queries=[S2BulkQuery(intent="match", language="en", query_string='"balance sheet" AND automation', notes="test")],
            run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
        )
        processed = await _drain(dispatcher)

        aggregate_dir = artifact_root / "aggregate"
        aggregate_dir.mkdir(parents=True, exist_ok=True)
        openalex_materialized = provider_tasks.materialize_provider_results(
            artifact_store=artifact_store,
            run_id="run-123",
            provider="openalex",
            destination=aggregate_dir / "openalex_raw.jsonl",
        )
        s2_materialized = provider_tasks.materialize_provider_results(
            artifact_store=artifact_store,
            run_id="run-123",
            provider="semanticscholar",
            destination=aggregate_dir / "semanticscholar_raw.jsonl",
        )
        final_doc = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")
    finally:
        provider_tasks.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
        provider_tasks._artifact_store_from_run_doc = original["_artifact_store_from_run_doc"]
        provider_tasks.build_two_lane_task_dispatcher = original["build_two_lane_task_dispatcher"]
        provider_tasks.PipelineConfig.from_env = original["PipelineConfig_from_env"]
        provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = original["launch"]
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        shutil.rmtree(artifact_root, ignore_errors=True)

    if launches != ["candidates"]:
        raise RuntimeError(f"Unexpected launches: {launches}")
    if int(openalex_seed.get("seeded_tasks") or 0) != 1 or int(s2_seed.get("seeded_tasks") or 0) != 1:
        raise RuntimeError(f"Unexpected seed counts: {openalex_seed} / {s2_seed}")
    if int(openalex_materialized.get("records") or 0) != 2:
        raise RuntimeError(f"Unexpected OpenAlex materialized records: {openalex_materialized}")
    if int(s2_materialized.get("records") or 0) != 3:
        raise RuntimeError(f"Unexpected S2 materialized records: {s2_materialized}")
    if (((final_doc.get("splitExecution") or {}).get("openalex_fetch") or {}).get("status")) != "success":
        raise RuntimeError(f"OpenAlex stage not marked success: {final_doc.get('splitExecution')}")
    if (((final_doc.get("splitExecution") or {}).get("s2_fetch") or {}).get("status")) != "success":
        raise RuntimeError(f"S2 stage not marked success: {final_doc.get('splitExecution')}")
    if (((final_doc.get("splitExecution") or {}).get("candidates") or {}).get("status")) != "queued":
        raise RuntimeError(f"Candidates stage not queued: {final_doc.get('splitExecution')}")

    return {
        "ok": True,
        "openalex_seed": openalex_seed,
        "s2_seed": s2_seed,
        "processed_tasks": processed,
        "launches": launches,
        "openalex_materialized": openalex_materialized,
        "s2_materialized": s2_materialized,
        "request_count": len(state.requests),
        "requests": state.requests,
    }


def main() -> int:
    result = asyncio.run(_main())
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_provider_task_orchestration_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
