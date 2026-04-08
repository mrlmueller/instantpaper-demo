from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources import runner


class FakeLLM:
    def __init__(self, **kwargs) -> None:
        self.user_id = kwargs.get("user_id")
        self.projekt_id = kwargs.get("projekt_id")
        self.kapitel_id = kwargs.get("kapitel_id")
        self.run_id = kwargs.get("run_id")
        self.api_key = kwargs.get("api_key")
        self.key_source = kwargs.get("key_source")
        self.max_total_cost_usd = float(kwargs.get("max_total_cost_usd") or 2.0)
        self.total_cost_usd = 0.0
        self.budget_exceeded = False
        self.stage_costs = {}

    def _stage(self, stage: str):
        record = type("StageCost", (), {})()
        record.cost_usd = 0.0
        record.input_tokens = 0
        record.cached_input_tokens = 0
        record.output_tokens = 0
        record.requests = 0
        self.stage_costs[stage] = record
        return record

    async def _request_live_cost_emit(self, stage: str):
        del stage
        return None


class FakePlan:
    def __init__(self) -> None:
        self.facets = [{"id": "f1"}, {"id": "f2"}]

    def model_dump(self, mode: str = "json") -> dict[str, Any]:
        del mode
        return {
            "topic_summary_de": "test",
            "topic_summary_en": "test",
            "primary_context_anchors": {"en": ["anchor"], "de": ["anker"]},
            "global_canonical_terms": {"en": ["term"], "de": ["begriff"]},
            "global_exclusions": {"en": [], "de": []},
            "facets": list(self.facets),
        }


class FakeQuery:
    def __init__(self, *, provider: str, intent: str, language: str, query_string: str) -> None:
        self.provider = provider
        self.intent = intent
        self.language = language
        self.query_string = query_string
        self.notes = None
        self.search_field = "default"
        self.filters = None
        self.sort = None
        self.per_page = 25


async def _resolve_api_key(_user_id: str):
    return "test-key", "user"


async def _plan_queries_llm(*args, **kwargs):
    del args, kwargs
    return FakePlan(), {"cache": False}


async def _build_openalex_queries_llm(*args, run_ctx, **kwargs):
    del args, kwargs
    payload = {"openalex_queries": [{"intent": "match", "language": "en", "query_string": "oa"}]}
    Path(run_ctx.artifacts.openalex_queries_json).write_text(json.dumps(payload), encoding="utf-8")
    return [FakeQuery(provider="openalex", intent="match", language="en", query_string="oa")], {"query_count": 1}


async def _build_s2_bulk_queries_llm(*args, run_ctx, **kwargs):
    del args, kwargs
    payload = {"s2_bulk_queries": [{"intent": "authority", "language": "de", "query_string": "s2"}]}
    Path(run_ctx.artifacts.semanticscholar_queries_json).write_text(json.dumps(payload), encoding="utf-8")
    return [FakeQuery(provider="s2", intent="authority", language="de", query_string="s2")], {"query_count": 1}


def _fetch_openalex_to_cache(*, run_ctx, **kwargs):
    del kwargs
    Path(run_ctx.artifacts.openalex_raw_jsonl).write_text('{"provider":"openalex","intent":"match"}\n', encoding="utf-8")
    return {"records": 1, "used_cache_paths": [Path(run_ctx.artifacts.openalex_raw_jsonl)]}


def _fetch_s2_to_cache(*, run_ctx, **kwargs):
    del kwargs
    Path(run_ctx.artifacts.semanticscholar_raw_jsonl).write_text('{"provider":"semanticscholar","intent":"authority"}\n', encoding="utf-8")
    return {"records": 1, "used_cache_paths": [Path(run_ctx.artifacts.semanticscholar_raw_jsonl)]}


def _build_candidates_from_raw(*, run_ctx, **kwargs):
    del kwargs
    Path(run_ctx.artifacts.candidates_normalized_jsonl).write_text('{"id":"c1"}\n', encoding="utf-8")
    Path(run_ctx.artifacts.candidates_normalized_csv).write_text("id\nc1\n", encoding="utf-8")
    return [{"id": "c1"}], {"deduped_candidates": 1}


async def _run_phase_f_embeddings_and_scoring(*, run_ctx, **kwargs):
    del kwargs
    (Path(run_ctx.run_dir) / "scores_stage1.jsonl").write_text('{"id":"c1"}\n', encoding="utf-8")
    return {"ok": True}


async def _run_phase_g_lane_fusion(*, run_ctx, **kwargs):
    del kwargs
    (Path(run_ctx.run_dir) / "rankings_stageg.json").write_text(json.dumps({"rows": []}), encoding="utf-8")
    return {"ok": True}


async def _run_phase_h_coverage_tags(*, run_ctx, **kwargs):
    del kwargs
    (Path(run_ctx.run_dir) / "coverage_tags.jsonl").write_text('{"id":"c1"}\n', encoding="utf-8")
    return {"ok": True}


async def _run_phase_i_rerank(*, run_ctx, **kwargs):
    del kwargs
    Path(run_ctx.artifacts.rerank_results_jsonl).write_text('{"id":"c1","score":90}\n', encoding="utf-8")
    return {"ok": True}


async def _run_phase_k_output(*, run_ctx, **kwargs):
    del kwargs
    Path(run_ctx.artifacts.output_json).write_text(
        json.dumps(
            {
                "schema_version": "two_lane_output_v1",
                "top": {
                    "match": {"with_abstract": [{"id": "c1", "title": "Doc 1"}], "without_abstract": []},
                    "authority": {"with_abstract": [], "without_abstract": []},
                },
            }
        ),
        encoding="utf-8",
    )
    return {"ok": True}


def _build_two_lane_telemetry(**kwargs):
    del kwargs
    return {"v2_report": {"value": "ok"}}


async def _main() -> dict[str, Any]:
    original = {
        "resolve_api_key_for_user": runner.user_key_service.resolve_api_key_for_user,
        "TwoLaneOpenAI": runner.TwoLaneOpenAI,
        "plan_queries_llm": runner.plan_queries_llm,
        "build_openalex_queries_llm": runner.build_openalex_queries_llm,
        "build_s2_bulk_queries_llm": runner.build_s2_bulk_queries_llm,
        "fetch_openalex_to_cache": runner.fetch_openalex_to_cache,
        "fetch_s2_to_cache": runner.fetch_s2_to_cache,
        "build_candidates_from_raw": runner.build_candidates_from_raw,
        "run_phase_f_embeddings_and_scoring": runner.run_phase_f_embeddings_and_scoring,
        "run_phase_g_lane_fusion": runner.run_phase_g_lane_fusion,
        "run_phase_h_coverage_tags": runner.run_phase_h_coverage_tags,
        "run_phase_i_rerank": runner.run_phase_i_rerank,
        "run_phase_k_output": runner.run_phase_k_output,
        "build_two_lane_telemetry": runner.build_two_lane_telemetry,
    }
    runner.user_key_service.resolve_api_key_for_user = _resolve_api_key
    runner.TwoLaneOpenAI = FakeLLM
    runner.plan_queries_llm = _plan_queries_llm
    runner.build_openalex_queries_llm = _build_openalex_queries_llm
    runner.build_s2_bulk_queries_llm = _build_s2_bulk_queries_llm
    runner.fetch_openalex_to_cache = _fetch_openalex_to_cache
    runner.fetch_s2_to_cache = _fetch_s2_to_cache
    runner.build_candidates_from_raw = _build_candidates_from_raw
    runner.run_phase_f_embeddings_and_scoring = _run_phase_f_embeddings_and_scoring
    runner.run_phase_g_lane_fusion = _run_phase_g_lane_fusion
    runner.run_phase_h_coverage_tags = _run_phase_h_coverage_tags
    runner.run_phase_i_rerank = _run_phase_i_rerank
    runner.run_phase_k_output = _run_phase_k_output
    runner.build_two_lane_telemetry = _build_two_lane_telemetry

    progress_events: list[dict[str, str]] = []

    async def _on_progress(stage: str, message: str) -> None:
        progress_events.append({"stage": stage, "message": message})

    try:
        with tempfile.TemporaryDirectory(prefix="two_lane_split_stage_runner_") as tmpdir:
            run_dir = Path(tmpdir).resolve() / "pipeline_runs" / "run-123"
            preprocess = await runner.run_two_lane_sources_pipeline_stage(
                stage_name="preprocess",
                user_id="user",
                projekt_id="project",
                kapitel_id="kapitel",
                run_id="run-123",
                chapter_title="Title",
                chapter_spec_text="Spec",
                settings={"force_rebuild": True},
                run_dir=run_dir,
                on_progress=_on_progress,
            )
            fetch = await runner.run_two_lane_sources_pipeline_stage(
                stage_name="openalex_fetch",
                user_id="user",
                projekt_id="project",
                kapitel_id="kapitel",
                run_id="run-123",
                chapter_title="Title",
                chapter_spec_text="Spec",
                settings={},
                run_dir=run_dir,
                on_progress=_on_progress,
            )
            s2_fetch = await runner.run_two_lane_sources_pipeline_stage(
                stage_name="s2_fetch",
                user_id="user",
                projekt_id="project",
                kapitel_id="kapitel",
                run_id="run-123",
                chapter_title="Title",
                chapter_spec_text="Spec",
                settings={},
                run_dir=run_dir,
                on_progress=_on_progress,
            )
            candidates = await runner.run_two_lane_sources_pipeline_stage(
                stage_name="candidates",
                user_id="user",
                projekt_id="project",
                kapitel_id="kapitel",
                run_id="run-123",
                chapter_title="Title",
                chapter_spec_text="Spec",
                settings={},
                run_dir=run_dir,
                on_progress=_on_progress,
            )
            finalize = await runner.run_two_lane_sources_pipeline_stage(
                stage_name="finalize",
                user_id="user",
                projekt_id="project",
                kapitel_id="kapitel",
                run_id="run-123",
                chapter_title="Title",
                chapter_spec_text="Spec",
                settings={},
                run_dir=run_dir,
                on_progress=_on_progress,
            )
            final_output = json.loads(Path(run_dir / "output.json").read_text(encoding="utf-8"))
            progress_stage_names = [event["stage"] for event in progress_events]
            expected_progress = [
                "phase_b_query_planner",
                "phase_c_query_builders",
                "phase_d_openalex_retrieval",
                "phase_d_semanticscholar_retrieval",
                "phase_e_candidates",
                "phase_f",
                "phase_g",
                "phase_h",
                "phase_i",
                "phase_k",
            ]
            if progress_stage_names != expected_progress:
                raise RuntimeError(f"Unexpected progress stages: {progress_stage_names}")
            if final_output.get("schema_version") != "two_lane_output_v1":
                raise RuntimeError(f"Unexpected output schema: {final_output.get('schema_version')}")
            return {
                "ok": True,
                "preprocess_stage": preprocess.get("stage"),
                "openalex_fetch_stage": fetch.get("stage"),
                "s2_fetch_stage": s2_fetch.get("stage"),
                "candidates_stage": candidates.get("stage"),
                "finalize_stage": finalize.get("stage"),
                "progress_stages": progress_stage_names,
                "output_schema": final_output.get("schema_version"),
                "candidates_meta": candidates.get("candidates_meta"),
            }
    finally:
        runner.user_key_service.resolve_api_key_for_user = original["resolve_api_key_for_user"]
        runner.TwoLaneOpenAI = original["TwoLaneOpenAI"]
        runner.plan_queries_llm = original["plan_queries_llm"]
        runner.build_openalex_queries_llm = original["build_openalex_queries_llm"]
        runner.build_s2_bulk_queries_llm = original["build_s2_bulk_queries_llm"]
        runner.fetch_openalex_to_cache = original["fetch_openalex_to_cache"]
        runner.fetch_s2_to_cache = original["fetch_s2_to_cache"]
        runner.build_candidates_from_raw = original["build_candidates_from_raw"]
        runner.run_phase_f_embeddings_and_scoring = original["run_phase_f_embeddings_and_scoring"]
        runner.run_phase_g_lane_fusion = original["run_phase_g_lane_fusion"]
        runner.run_phase_h_coverage_tags = original["run_phase_h_coverage_tags"]
        runner.run_phase_i_rerank = original["run_phase_i_rerank"]
        runner.run_phase_k_output = original["run_phase_k_output"]
        runner.build_two_lane_telemetry = original["build_two_lane_telemetry"]


def main() -> int:
    result = asyncio.run(_main())
    out_dir = Path(__file__).resolve().parents[1] / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_split_stage_runner_latest.json"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
