from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from copy import deepcopy
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import test_two_lane_provider_task_retry_cancel as retry_base
from services.two_lane_sources import provider_tasks
from services.two_lane_sources.pipeline import OpenAlexQuery, S2BulkQuery
from utils.config import config


def _make_openalex_payload() -> dict:
    return {
        "results": [
            {
                "id": "https://openalex.org/W1",
                "doi": "10.1000/oa1",
                "display_name": "OpenAlex Auto Retry",
                "publication_year": 2024,
                "type": "article",
                "ids": {"openalex": "W1"},
                "cited_by_count": 5,
                "primary_location": {"source": {"display_name": "Test Venue"}},
                "authorships": [{"author": {"display_name": "Author 1"}}],
                "abstract_inverted_index": {"auto": [0], "retry": [1]},
            }
        ],
        "meta": {"next_cursor": None},
    }


def _make_s2_bulk_payload() -> dict:
    return {"data": [{"paperId": "S2-A"}], "token": None}


def _make_s2_batch_payload() -> dict:
    return {
        "data": [
            {
                "paperId": "S2-A",
                "title": "Semantic Scholar Auto Retry",
                "year": 2024,
                "authors": [{"name": "Test Author"}],
                "venue": "Test Venue",
                "url": "https://example.org/S2-A",
                "externalIds": {"DOI": "10.1000/s2-a"},
                "citationCount": 1,
                "influentialCitationCount": 0,
                "abstract": "Auto retry abstract",
            }
        ]
    }


async def _wait_for_success(*, fake_fs: retry_base.FakeFirestoreService, provider: str, timeout_s: float = 40.0) -> dict:
    deadline = time.monotonic() + float(timeout_s)
    key_prefix = f"{provider}--"
    while time.monotonic() < deadline:
        matches = [
            deepcopy(doc)
            for (user_id, projekt_id, run_id, task_id), doc in fake_fs.task_docs.items()
            if (user_id, projekt_id, run_id) == ("user", "project", "run-123") and str(task_id).startswith(key_prefix)
        ]
        if matches and all(str(doc.get("status") or "").strip().lower() == "success" for doc in matches):
            return matches[0]
        await asyncio.sleep(0.25)
    raise TimeoutError(f"Timed out waiting for {provider} local background retry to succeed")


async def _exercise_provider(provider: str) -> dict:
    initial_doc = retry_base._base_doc()
    if provider == "openalex":
        initial_doc["splitExecution"]["s2_fetch"]["status"] = "success"
    else:
        initial_doc["splitExecution"]["openalex_fetch"]["status"] = "success"
    fake_fs = retry_base.FakeFirestoreService(initial_doc)
    launches: list[str] = []
    artifact_root = Path(tempfile.mkdtemp(prefix=f"two_lane_local_retry_{provider}_"))
    artifact_store = retry_base.LocalArtifactStore(artifact_root / "artifacts")
    cfg = retry_base._build_cfg("http://unused.local")
    request_log: list[dict] = []
    fail_once = {"remaining": 1}

    original = {
        "QuellenFinderFirestoreService": provider_tasks.QuellenFinderFirestoreService,
        "_artifact_store_from_run_doc": provider_tasks._artifact_store_from_run_doc,
        "PipelineConfig_from_env": provider_tasks.PipelineConfig.from_env,
        "launch": provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job,
        "request_json": provider_tasks.request_json,
        "dispatch_backend": config.TWO_LANE_TASK_DISPATCH_BACKEND,
    }

    def _fake_request_json(*args, **kwargs):
        provider_name = str(kwargs.get("provider") or "").strip().lower()
        url = str(kwargs.get("url") or "")
        request_log.append({"provider": provider_name, "url": url})
        if provider_name == provider and int(fail_once["remaining"]) > 0:
            fail_once["remaining"] -= 1
            raise RuntimeError(f"Injected {provider} failure")
        if provider_name == "openalex":
            return _make_openalex_payload()
        if provider_name == "semanticscholar" and url.endswith("/paper/search/bulk"):
            return _make_s2_bulk_payload()
        if provider_name == "semanticscholar" and url.endswith("/paper/batch"):
            return _make_s2_batch_payload()
        raise RuntimeError(f"Unexpected provider/url combination: {provider_name} {url}")

    provider_tasks.QuellenFinderFirestoreService = lambda: fake_fs
    provider_tasks._artifact_store_from_run_doc = lambda run_doc=None: artifact_store
    provider_tasks.PipelineConfig.from_env = classmethod(lambda cls, *, runs_root, pipeline_version: cfg)
    provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = (
        lambda **kwargs: launches.append(str(kwargs.get("stage"))) or {"execution_name": f"exec-{provider}", "operation_name": f"op-{provider}"}
    )
    provider_tasks.request_json = _fake_request_json
    config.TWO_LANE_TASK_DISPATCH_BACKEND = "local_background"

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
                        notes="auto retry",
                    )
                ],
                run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
            )
        else:
            provider_tasks.seed_s2_provider_tasks(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                queries=[S2BulkQuery(intent="match", language="en", query_string='"balance sheet" AND automation', notes="auto retry")],
                run_doc=fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123"),
            )

        task_doc = await _wait_for_success(fake_fs=fake_fs, provider=provider)
        run_doc = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")
    finally:
        provider_tasks.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
        provider_tasks._artifact_store_from_run_doc = original["_artifact_store_from_run_doc"]
        provider_tasks.PipelineConfig.from_env = original["PipelineConfig_from_env"]
        provider_tasks.cloud_run_job_launcher.execute_two_lane_sources_job = original["launch"]
        provider_tasks.request_json = original["request_json"]
        config.TWO_LANE_TASK_DISPATCH_BACKEND = original["dispatch_backend"]
        if artifact_root.exists():
            import shutil

            shutil.rmtree(artifact_root, ignore_errors=True)

    provider_work = ((run_doc.get("providerWork") or {}).get(provider) or {})
    if int(provider_work.get("pendingTasks") or 0) != 0:
        raise RuntimeError(f"{provider} pendingTasks did not drain: {provider_work}")
    if int(provider_work.get("retryCount") or 0) < 1:
        raise RuntimeError(f"{provider} retryCount was not incremented: {provider_work}")
    if str(task_doc.get("status") or "").strip().lower() != "success":
        raise RuntimeError(f"{provider} task did not succeed after local auto retry: {task_doc}")
    if int(task_doc.get("failCount") or 0) < 1:
        raise RuntimeError(f"{provider} failCount was not recorded: {task_doc}")
    if launches != ["candidates"]:
        raise RuntimeError(f"{provider} local auto retry did not queue candidates exactly once: {launches}")

    return {
        "provider": provider,
        "request_count": len(request_log),
        "task_doc": task_doc,
        "provider_work": provider_work,
        "launches": launches,
    }


async def _main_async() -> dict:
    openalex = await _exercise_provider("openalex")
    s2 = await _exercise_provider("semanticscholar")
    return {"ok": True, "openalex": openalex, "semanticscholar": s2}


def main() -> int:
    result = asyncio.run(_main_async())
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_local_background_retry_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
