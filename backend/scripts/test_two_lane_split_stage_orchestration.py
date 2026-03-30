from __future__ import annotations

import asyncio
import json
import shutil
import sys
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services import quellen_finder_sources_two_lane_job as jobmod


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

    def stream(self):
        return []

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
        self.results_docs: list[tuple[str, dict[str, Any]]] = []
        self.telemetry_docs: list[tuple[str, dict[str, Any]]] = []

    def run_ref(self, user_id: str, projekt_id: str, run_id: str):
        return _FakeRunRef(self, (str(user_id), str(projekt_id), str(run_id)))

    def get_run(self, *, user_id: str, projekt_id: str, run_id: str) -> dict[str, Any]:
        data = self.docs.get((str(user_id), str(projekt_id), str(run_id)))
        if data is None:
            raise ValueError("Run not found.")
        return deepcopy(data)

    def mark_running(self, *, user_id: str, projekt_id: str, run_id: str) -> None:
        self.run_ref(user_id, projekt_id, run_id).set({"status": "running"}, merge=True)

    def set_progress(self, *, user_id: str, projekt_id: str, run_id: str, stage: str, message: str | None = None, **kwargs) -> None:
        del kwargs
        self.run_ref(user_id, projekt_id, run_id).set({"progress": {"stage": stage, "message": message}}, merge=True)

    def clear_subcollection(self, *, user_id: str, projekt_id: str, run_id: str, name: str) -> None:
        del user_id, projekt_id, run_id, name
        return None

    def write_two_lane_results(self, *, docs, **kwargs) -> None:
        del kwargs
        self.results_docs = list(docs)

    def write_two_lane_telemetry(self, *, docs, **kwargs) -> None:
        del kwargs
        self.telemetry_docs = list(docs)

    def try_queue_two_lane_stage(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
        target_stage: str,
        prerequisite_stages,
        allowed_current_statuses,
        current_stage_value: str | None = None,
    ) -> bool:
        doc = self.docs[(str(user_id), str(projekt_id), str(run_id))]
        split_execution = doc.get("splitExecution") if isinstance(doc.get("splitExecution"), dict) else {}
        for stage_name in list(prerequisite_stages or []):
            stage_state = split_execution.get(stage_name) if isinstance(split_execution.get(stage_name), dict) else {}
            if str((stage_state or {}).get("status") or "").strip().lower() != "success":
                return False
        target_state = split_execution.get(target_stage) if isinstance(split_execution.get(target_stage), dict) else {}
        if str((target_state or {}).get("status") or "").strip().lower() not in {str(x).strip().lower() for x in list(allowed_current_statuses or [])}:
            return False
        self.run_ref(user_id, projekt_id, run_id).set(
            {
                "splitExecution": {
                    "currentStage": str(current_stage_value or target_stage),
                    str(target_stage): {"status": "queued"},
                }
            },
            merge=True,
        )
        return True

    def mark_success(self, *, user_id: str, projekt_id: str, run_id: str, had_partial_failures: bool = False, extra: dict | None = None) -> None:
        payload = {"status": "success", "hadPartialFailures": bool(had_partial_failures)}
        if isinstance(extra, dict):
            payload.update(deepcopy(extra))
        self.run_ref(user_id, projekt_id, run_id).set(payload, merge=True)

    def mark_error(self, *, user_id: str, projekt_id: str, run_id: str, error_message: str, had_partial_failures: bool = False) -> None:
        self.run_ref(user_id, projekt_id, run_id).set(
            {"status": "error", "errorMessage": str(error_message), "hadPartialFailures": bool(had_partial_failures)},
            merge=True,
        )

    def mark_cancelled(self, *, user_id: str, projekt_id: str, run_id: str) -> None:
        self.run_ref(user_id, projekt_id, run_id).set({"status": "cancelled"}, merge=True)


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

    def upload_file(self, *, local_path: Path, path_or_uri: str, content_type: str | None = None) -> str:
        del content_type
        target = self._target(path_or_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path(local_path).resolve(), target)
        return target.as_uri()

    def upload_json(self, *, payload, path_or_uri: str) -> str:
        target = self._target(path_or_uri)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target.as_uri()

    def download_file(self, *, path_or_uri: str, local_path: Path) -> Path:
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        target = Path(local_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        return target

    def download_json(self, *, path_or_uri: str):
        source = Path(str(path_or_uri or "").replace("file:///", "")).resolve()
        return json.loads(source.read_text(encoding="utf-8"))

    def location(self, path_or_uri: str):
        return _LocalLocation(self.root, str(path_or_uri or "").strip().lstrip("/"))

    def delete_run_prefix(self, run_id: str) -> int:
        prefix = self._target(self.run_prefix(run_id))
        if not prefix.exists():
            return 0
        files = [p for p in prefix.rglob("*") if p.is_file()]
        shutil.rmtree(prefix, ignore_errors=True)
        return len(files)


async def _fake_stage_runner(*, stage_name: str, run_dir: Path, **kwargs):
    del kwargs
    run_dir = Path(run_dir).resolve()
    run_dir.mkdir(parents=True, exist_ok=True)
    if stage_name == "preprocess":
        (run_dir / "query_plan.json").write_text(json.dumps({"plan": True}), encoding="utf-8")
        (run_dir / "openalex_queries.json").write_text(
            json.dumps(
                {
                    "openalex_queries": [
                        {
                            "intent": "match",
                            "language": "en",
                            "search_field": "title_and_abstract.search",
                            "query_string": "oa",
                            "filters": "language:en",
                            "sort": "relevance_score:desc",
                            "per_page": 200,
                            "notes": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "s2_bulk_queries.json").write_text(
            json.dumps(
                {
                    "s2_bulk_queries": [
                        {
                            "intent": "match",
                            "language": "en",
                            "query_string": "s2",
                            "notes": "test",
                        }
                    ]
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "metrics.json").write_text(json.dumps({"stages": {"phase_b_query_planner": {"seconds": 1}}}), encoding="utf-8")
        return {"stage": stage_name, "artifacts_dir": str(run_dir), "metrics": {"stages": {}}}
    if stage_name == "openalex_fetch":
        (run_dir / "openalex_raw.jsonl").write_text('{"id":"oa1"}\n', encoding="utf-8")
        (run_dir / "metrics.json").write_text(json.dumps({"stages": {"phase_d_openalex_retrieval": {"seconds": 1}}}), encoding="utf-8")
        return {"stage": stage_name, "artifacts_dir": str(run_dir), "metrics": {"stages": {}}, "openalex_fetch": {"records": 1}}
    if stage_name == "s2_fetch":
        (run_dir / "semanticscholar_raw.jsonl").write_text('{"id":"s21"}\n', encoding="utf-8")
        (run_dir / "metrics.json").write_text(json.dumps({"stages": {"phase_d_semanticscholar_retrieval": {"seconds": 1}}}), encoding="utf-8")
        return {"stage": stage_name, "artifacts_dir": str(run_dir), "metrics": {"stages": {}}, "s2_fetch": {"records": 1}}
    if stage_name == "candidates":
        (run_dir / "openalex_raw.jsonl").write_text('{"id":"oa1"}\n', encoding="utf-8")
        (run_dir / "semanticscholar_raw.jsonl").write_text('{"id":"s21"}\n', encoding="utf-8")
        (run_dir / "candidates_normalized.jsonl").write_text('{"id":"c1"}\n', encoding="utf-8")
        (run_dir / "metrics.json").write_text(json.dumps({"stages": {"phase_e_candidates": {"seconds": 1}}}), encoding="utf-8")
        return {"stage": stage_name, "artifacts_dir": str(run_dir), "metrics": {"stages": {}}, "candidates_meta": {"deduped_candidates": 1}}
    (run_dir / "output.json").write_text(
        json.dumps(
            {
                "schema_version": "two_lane_output_v1",
                "top": {
                    "match": {"with_abstract": [{"id": "c1", "title": "Title 1"}], "without_abstract": []},
                    "authority": {"with_abstract": [], "without_abstract": []},
                },
            }
        ),
        encoding="utf-8",
    )
    return {
        "stage": stage_name,
        "artifacts_dir": str(run_dir),
        "output": json.loads((run_dir / "output.json").read_text(encoding="utf-8")),
        "telemetry": {"v2_report": {"kpis": {"seconds_total": 1}}},
        "costs": {"total_cost_usd": 0.12, "budget_cap_usd": 2.0},
        "effective_settings": {"openai_model_planner": "gpt-test"},
    }


async def _main() -> dict[str, Any]:
    initial_doc = {
        "kind": "sources_two_lane",
        "status": "queued",
        "kapitelIds": ["kapitel"],
        "chapterInputSnapshot": {"chapterTitle": "Title", "chapterSpecText": "Spec"},
        "twoLaneSettingsRequested": {},
        "executionBackend": "local_split_jobs",
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
    }
    fake_fs = FakeFirestoreService(initial_doc)
    launches: list[str] = []

    def _fake_seed_openalex_provider_tasks(*, user_id: str, projekt_id: str, run_id: str, **kwargs):
        del kwargs
        fake_fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "providerWork": {"openalex": {"pendingTasks": 0, "status": "success"}},
                "twoLaneArtifacts": {"openalex_fetch": {"resultsPrefix": "provider/openalex/pages", "seededTasks": 1}},
            },
            merge=True,
        )
        return {"seeded_tasks": 1}

    def _fake_seed_s2_provider_tasks(*, user_id: str, projekt_id: str, run_id: str, **kwargs):
        del kwargs
        fake_fs.run_ref(user_id, projekt_id, run_id).set(
            {
                "providerWork": {"semanticscholar": {"pendingTasks": 0, "status": "success"}},
                "twoLaneArtifacts": {"s2_fetch": {"resultsPrefix": "provider/semanticscholar/pages", "seededTasks": 1}},
            },
            merge=True,
        )
        return {"seeded_tasks": 1}

    def _fake_materialize_provider_results(*, provider: str, destination: Path, **kwargs):
        del kwargs
        target = Path(destination).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if str(provider) == "openalex":
            target.write_text('{"id":"oa1"}\n', encoding="utf-8")
        else:
            target.write_text('{"id":"s21"}\n', encoding="utf-8")
        return {"objects": 1, "records": 1}

    async def _fake_launch(*, stage_name: str, **kwargs):
        del kwargs
        launches.append(stage_name)
        return {"job_name": "local:run_two_lane_job.py", "region": "local", "execution_name": f"exec-{stage_name}", "operation_name": f"op-{stage_name}"}

    original = {
        "QuellenFinderFirestoreService": jobmod.QuellenFinderFirestoreService,
        "_artifact_store_from_config": jobmod._artifact_store_from_config,
        "run_two_lane_sources_pipeline_stage": jobmod.run_two_lane_sources_pipeline_stage,
        "_launch_split_stage": jobmod._launch_split_stage,
        "seed_openalex_provider_tasks": jobmod.seed_openalex_provider_tasks,
        "seed_s2_provider_tasks": jobmod.seed_s2_provider_tasks,
        "materialize_provider_results": jobmod.materialize_provider_results,
    }

    with tempfile.TemporaryDirectory(prefix="two_lane_split_orchestration_") as tmpdir:
        artifact_store = LocalArtifactStore(Path(tmpdir) / "artifacts")
        jobmod.QuellenFinderFirestoreService = lambda: fake_fs
        jobmod._artifact_store_from_config = lambda run_doc=None: artifact_store
        jobmod.run_two_lane_sources_pipeline_stage = _fake_stage_runner
        jobmod._launch_split_stage = _fake_launch
        jobmod.seed_openalex_provider_tasks = _fake_seed_openalex_provider_tasks
        jobmod.seed_s2_provider_tasks = _fake_seed_s2_provider_tasks
        jobmod.materialize_provider_results = _fake_materialize_provider_results
        try:
            await jobmod.run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                stage="preprocess",
            )
            after_preprocess = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")

            await jobmod.run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                stage="openalex_fetch",
            )
            after_openalex = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")

            await jobmod.run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                stage="s2_fetch",
            )
            after_s2 = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")

            await jobmod.run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                stage="candidates",
            )
            after_candidates = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")

            await jobmod.run_quellen_finder_sources_two_lane_job_from_run_doc(
                user_id="user",
                projekt_id="project",
                run_id="run-123",
                stage="finalize",
            )
            final_doc = fake_fs.get_run(user_id="user", projekt_id="project", run_id="run-123")
        finally:
            jobmod.QuellenFinderFirestoreService = original["QuellenFinderFirestoreService"]
            jobmod._artifact_store_from_config = original["_artifact_store_from_config"]
            jobmod.run_two_lane_sources_pipeline_stage = original["run_two_lane_sources_pipeline_stage"]
            jobmod._launch_split_stage = original["_launch_split_stage"]
            jobmod.seed_openalex_provider_tasks = original["seed_openalex_provider_tasks"]
            jobmod.seed_s2_provider_tasks = original["seed_s2_provider_tasks"]
            jobmod.materialize_provider_results = original["materialize_provider_results"]

    expected_launches = ["openalex_fetch", "s2_fetch", "candidates", "finalize"]
    if launches != expected_launches:
        raise RuntimeError(f"Unexpected launches: {launches}")
    if ((after_preprocess.get("splitExecution") or {}).get("currentStage")) != "provider_fetch":
        raise RuntimeError(f"Unexpected stage after preprocess: {after_preprocess.get('splitExecution')}")
    if ((after_openalex.get("splitExecution") or {}).get("currentStage")) != "provider_fetch":
        raise RuntimeError(f"Unexpected stage after OpenAlex fetch: {after_openalex.get('splitExecution')}")
    if ((after_s2.get("splitExecution") or {}).get("currentStage")) != "candidates":
        raise RuntimeError(f"Unexpected stage after S2 fetch: {after_s2.get('splitExecution')}")
    if ((after_candidates.get("splitExecution") or {}).get("currentStage")) != "finalize":
        raise RuntimeError(f"Unexpected stage after candidates: {after_candidates.get('splitExecution')}")
    if final_doc.get("status") != "success":
        raise RuntimeError(f"Unexpected final status: {final_doc.get('status')}")
    if ((final_doc.get("twoLaneArtifacts") or {}).get("cleanupStatus")) != "done":
        raise RuntimeError(f"Unexpected cleanup status: {(final_doc.get('twoLaneArtifacts') or {}).get('cleanupStatus')}")

    return {
        "ok": True,
        "launches": launches,
        "after_preprocess_stage": ((after_preprocess.get("splitExecution") or {}).get("currentStage")),
        "after_openalex_stage": ((after_openalex.get("splitExecution") or {}).get("currentStage")),
        "after_s2_stage": ((after_s2.get("splitExecution") or {}).get("currentStage")),
        "after_candidates_stage": ((after_candidates.get("splitExecution") or {}).get("currentStage")),
        "final_status": final_doc.get("status"),
        "cleanup_status": ((final_doc.get("twoLaneArtifacts") or {}).get("cleanupStatus")),
        "result_docs": len(fake_fs.results_docs),
        "telemetry_docs": len(fake_fs.telemetry_docs),
    }


def main() -> int:
    result = asyncio.run(_main())
    out_dir = Path(__file__).resolve().parents[1] / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_split_stage_orchestration_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
