from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
import threading
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

from services.two_lane_sources import provider_tasks
from services.two_lane_sources.pipeline import OpenAlexQuery, PipelineConfig, S2BulkQuery
from test_two_lane_provider_task_orchestration import (
    FakeDispatcher,
    FakeFirestoreService,
    LocalArtifactStore,
    _FakeHandler,
    _ServerState,
)
from services.two_lane_sources.internal_tasks import run_two_lane_internal_task_payload


async def _process_one(dispatcher: FakeDispatcher) -> dict:
    item = dispatcher.tasks.pop(0)
    result = await run_two_lane_internal_task_payload(item["payload"])
    return {"task_name": item["task_name"], "kind": item["payload"].get("kind"), "result": result}


def _make_cfg(*, artifact_root: Path, base_url: str, openalex_pages: int, s2_pages: int) -> PipelineConfig:
    return PipelineConfig(
        runs_root=artifact_root,
        pipeline_version="two_lane_v1",
        openalex_base_url=base_url,
        openalex_rps=5.0,
        openalex_task_max_pages_per_task=int(openalex_pages),
        semanticscholar_base_url=base_url + "/graph/v1",
        semanticscholar_rps=2.0,
        semanticscholar_task_max_pages_per_task=int(s2_pages),
        provider_rate_limit_backend="local",
        provider_rate_limit_collection="unused",
        provider_rate_limit_dispatch_buffer_ms=0,
        provider_task_max_runtime_s=900.0,
        force_rebuild=False,
    )


async def _exercise(*, openalex_pages: int, s2_pages: int) -> dict:
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
    artifact_root = Path(tempfile.mkdtemp(prefix="two_lane_query_segments_"))
    artifact_store = LocalArtifactStore(artifact_root / "artifacts")
    state = _ServerState()
    handler_cls = type("RecursiveFakeHandler", (_FakeHandler,), {"state": state})
    from http.server import ThreadingHTTPServer

    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    cfg = _make_cfg(artifact_root=artifact_root, base_url=base_url, openalex_pages=openalex_pages, s2_pages=s2_pages)

    original = {
        "QuellenFinderFirestoreService": provider_tasks.QuellenFinderFirestoreService,
        "_artifact_store_from_run_doc": provider_tasks._artifact_store_from_run_doc,
        "build_two_lane_task_dispatcher": provider_tasks.build_two_lane_task_dispatcher,
        "PipelineConfig_from_env": provider_tasks.PipelineConfig.from_env,
    }

    provider_tasks.QuellenFinderFirestoreService = lambda: fake_fs
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    provider_tasks.build_two_lane_task_dispatcher = lambda: dispatcher
    provider_tasks.PipelineConfig.from_env = classmethod(lambda cls, *, runs_root, pipeline_version: cfg)

    try:
        oa_seed = provider_tasks.seed_openalex_provider_tasks(
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
        oa_initial_queue_size = len(dispatcher.tasks)
        oa_first = await _process_one(dispatcher)
        oa_after_first_queue_size = len(dispatcher.tasks)
        oa_provider_work = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123").get("providerWork", {}).get("openalex", {})

        dispatcher.tasks.clear()
        s2_seed = provider_tasks.seed_s2_provider_tasks(
            user_id="user",
            projekt_id="project",
            run_id="run-123",
            queries=[S2BulkQuery(intent="match", language="en", query_string='"balance sheet" AND automation', notes="test")],
            run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
        )
        s2_initial_queue_size = len(dispatcher.tasks)
        s2_first = await _process_one(dispatcher)
        s2_after_first_queue_size = len(dispatcher.tasks)
        s2_provider_work = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123").get("providerWork", {}).get("semanticscholar", {})
    finally:
        provider_tasks.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
        provider_tasks._artifact_store_from_run_doc = original["_artifact_store_from_run_doc"]
        provider_tasks.build_two_lane_task_dispatcher = original["build_two_lane_task_dispatcher"]
        provider_tasks.PipelineConfig.from_env = original["PipelineConfig_from_env"]
        server.shutdown()
        server.server_close()
        thread.join(timeout=5.0)
        shutil.rmtree(artifact_root, ignore_errors=True)

    return {
        "openalex": {
            "seeded_tasks_initial": int(oa_seed.get("seeded_tasks") or 0),
            "queue_size_after_seed": int(oa_initial_queue_size),
            "queue_size_after_first_task": int(oa_after_first_queue_size),
            "provider_work_after_first_task": oa_provider_work,
            "first_task": oa_first,
        },
        "semanticscholar": {
            "seeded_tasks_initial": int(s2_seed.get("seeded_tasks") or 0),
            "queue_size_after_seed": int(s2_initial_queue_size),
            "queue_size_after_first_task": int(s2_after_first_queue_size),
            "provider_work_after_first_task": s2_provider_work,
            "first_task": s2_first,
        },
    }


async def _main() -> dict:
    no_continuation = await _exercise(openalex_pages=100, s2_pages=100)
    with_continuation = await _exercise(openalex_pages=1, s2_pages=1)

    if no_continuation["openalex"]["seeded_tasks_initial"] != 1 or no_continuation["openalex"]["queue_size_after_seed"] != 1:
        raise RuntimeError(f"Unexpected OpenAlex seed behavior: {no_continuation['openalex']}")
    if int((no_continuation["openalex"]["provider_work_after_first_task"] or {}).get("enqueuedTasks") or 0) != 1:
        raise RuntimeError(f"OpenAlex should not enqueue continuation by default: {no_continuation['openalex']}")
    if no_continuation["openalex"]["queue_size_after_first_task"] != 0:
        raise RuntimeError(f"OpenAlex queue should drain after one query task by default: {no_continuation['openalex']}")
    if no_continuation["semanticscholar"]["queue_size_after_first_task"] != 0:
        raise RuntimeError(f"S2 queue should drain after one query task by default: {no_continuation['semanticscholar']}")

    if int((with_continuation["openalex"]["provider_work_after_first_task"] or {}).get("enqueuedTasks") or 0) < 2:
        raise RuntimeError(f"OpenAlex should enqueue a bounded continuation when capped: {with_continuation['openalex']}")
    if with_continuation["openalex"]["queue_size_after_first_task"] != 1:
        raise RuntimeError(f"OpenAlex continuation task missing when capped: {with_continuation['openalex']}")
    if not bool(((with_continuation["openalex"]["first_task"] or {}).get("result") or {}).get("continued")):
        raise RuntimeError(f"OpenAlex task did not report continuation when capped: {with_continuation['openalex']}")

    if int((with_continuation["semanticscholar"]["provider_work_after_first_task"] or {}).get("enqueuedTasks") or 0) < 2:
        raise RuntimeError(f"S2 should enqueue a bounded continuation when capped: {with_continuation['semanticscholar']}")
    if with_continuation["semanticscholar"]["queue_size_after_first_task"] != 1:
        raise RuntimeError(f"S2 continuation task missing when capped: {with_continuation['semanticscholar']}")
    if not bool(((with_continuation["semanticscholar"]["first_task"] or {}).get("result") or {}).get("continued")):
        raise RuntimeError(f"S2 task did not report continuation when capped: {with_continuation['semanticscholar']}")

    return {"ok": True, "no_continuation": no_continuation, "with_continuation": with_continuation}


def main() -> int:
    result = asyncio.run(_main())
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_provider_recursive_enqueue_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
