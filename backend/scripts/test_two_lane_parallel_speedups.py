"""
Assertion-based smoke for the runner-level two-lane parallel speedups.

This monkeypatches the expensive stages and verifies that:
- OpenAlex and S2 query builders run concurrently
- OpenAlex and S2 retrieval run concurrently
- the runner still produces a valid result payload
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources import runner
from services.two_lane_sources.pipeline import (
    BilingualTerms,
    Facet,
    OpenAlexQuery,
    QueryPlan,
    S2BulkQuery,
    write_json,
)


def _make_plan() -> QueryPlan:
    return QueryPlan(
        topic_summary_en="Automation of document analysis",
        topic_summary_de="Automatisierung der Dokumentenanalyse",
        primary_context_anchors=BilingualTerms(en=["balance sheet", "LLM"], de=["Bilanz", "LLM"]),
        core_object_terms=BilingualTerms(en=["balance sheet", "contract"], de=["Bilanz", "Vertrag"]),
        must_keep_constraints=[],
        drift_risks=[],
        authority_blueprints=[],
        facets=[
            Facet(
                facet_id="time_savings",
                facet_label_en="Time savings",
                facet_label_de="Zeitersparnis",
                facet_type="evidence",
                facet_group="context",
                query_family_preference="object_plus_construct",
                language_strategy="bilingual",
                authority_role="supporting",
                importance_weight=5,
                text_en="Evidence for time savings in document analysis workflows",
                text_de="Evidenz für Zeitersparnis in Dokumentenanalyse-Workflows",
                canonical_terms=BilingualTerms(en=["time savings"], de=["Zeitersparnis"]),
                neighbor_terms=BilingualTerms(en=["processing time"], de=["Bearbeitungszeit"]),
                exclusion_terms=BilingualTerms(en=[], de=[]),
            )
        ],
        global_canonical_terms=BilingualTerms(en=[], de=[]),
        global_exclusions=BilingualTerms(en=[], de=[]),
    )


class _FakeLLM:
    def __init__(self, *args, **kwargs):  # noqa: ARG002
        self.max_total_cost_usd = 2.0
        self.total_cost_usd = 0.0
        self.stage_costs = {}


class _AsyncUserKeyService:
    @staticmethod
    async def resolve_api_key_for_user(user_id: str):  # noqa: ARG004
        return "fake-key", "test"


async def _run_test() -> dict:
    timeline: list[dict] = []

    def record(kind: str, name: str, event: str) -> None:
        timeline.append({"kind": kind, "name": name, "event": event, "ts": time.perf_counter()})

    async def fake_plan_queries_llm(*args, **kwargs):  # noqa: ARG001
        record("phase", "planner", "start")
        await asyncio.sleep(0.05)
        record("phase", "planner", "end")
        return _make_plan(), {"cache_hit": False}

    async def fake_build_openalex_queries_llm(*args, **kwargs):  # noqa: ARG001
        record("builder", "openalex", "start")
        await asyncio.sleep(0.35)
        record("builder", "openalex", "end")
        return [
            OpenAlexQuery(
                intent="match",
                language="en",
                search_field="title_and_abstract.search",
                query_string='("balance sheet" OR "contract") AND ("automation" OR "LLM")',
                filters="is_paratext:false,is_retracted:false,language:en",
                sort="relevance_score:desc",
                per_page=200,
                notes="fake openalex",
            )
        ], {"cache_hit": False, "query_count": 1}

    async def fake_build_s2_bulk_queries_llm(*args, **kwargs):  # noqa: ARG001
        record("builder", "s2", "start")
        await asyncio.sleep(0.35)
        record("builder", "s2", "end")
        return [
            S2BulkQuery(
                intent="match",
                language="en",
                query_string='"balance sheet" AND automation',
                notes="fake s2",
            )
        ], {"cache_hit": False, "query_count": 1}

    def fake_fetch_openalex_to_cache(*, run_ctx, **kwargs):  # noqa: ARG001
        record("fetch", "openalex", "start")
        time.sleep(0.35)
        cache_path = run_ctx.run_dir / "cache" / "openalex" / "fake_openalex.jsonl"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text('{"provider":"openalex","intent":"match"}\n', encoding="utf-8")
        record("fetch", "openalex", "end")
        return {"used_cache_paths": [cache_path], "records": 1, "records_fetched": 1}

    def fake_fetch_s2_to_cache(*, run_ctx, **kwargs):  # noqa: ARG001
        record("fetch", "s2", "start")
        time.sleep(0.35)
        cache_path = run_ctx.run_dir / "cache" / "semanticscholar" / "fake_s2.jsonl"
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text('{"provider":"semanticscholar","intent":"match"}\n', encoding="utf-8")
        record("fetch", "s2", "end")
        return {"used_cache_paths": [cache_path], "records": 1, "records_fetched": 1}

    def fake_build_candidates_from_raw(*args, **kwargs):  # noqa: ARG001
        return [], {"deduped_candidates": 1}

    async def fake_phase_noop(*args, **kwargs):  # noqa: ARG001
        return {"ok": True}

    async def fake_run_phase_k_output(*, run_ctx, **kwargs):  # noqa: ARG001
        write_json(
            Path(run_ctx.artifacts.output_json),
            {
                "schema_version": "two_lane_output_v1",
                "top": {
                    "match": {"with_abstract": [], "without_abstract": []},
                    "authority": {"with_abstract": [], "without_abstract": []},
                },
            },
        )
        return {"ok": True}

    original = {
        "IS_CLOUD_RUN": runner.app_config.IS_CLOUD_RUN,
        "user_key_service": runner.user_key_service,
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

    runner.app_config.IS_CLOUD_RUN = True
    runner.user_key_service = _AsyncUserKeyService()
    runner.TwoLaneOpenAI = _FakeLLM
    runner.plan_queries_llm = fake_plan_queries_llm
    runner.build_openalex_queries_llm = fake_build_openalex_queries_llm
    runner.build_s2_bulk_queries_llm = fake_build_s2_bulk_queries_llm
    runner.fetch_openalex_to_cache = fake_fetch_openalex_to_cache
    runner.fetch_s2_to_cache = fake_fetch_s2_to_cache
    runner.build_candidates_from_raw = fake_build_candidates_from_raw
    runner.run_phase_f_embeddings_and_scoring = fake_phase_noop
    runner.run_phase_g_lane_fusion = fake_phase_noop
    runner.run_phase_h_coverage_tags = fake_phase_noop
    runner.run_phase_i_rerank = fake_phase_noop
    runner.run_phase_k_output = fake_run_phase_k_output
    runner.build_two_lane_telemetry = lambda **kwargs: {}  # noqa: ARG005

    progress_events: list[tuple[str, str]] = []

    try:
        result = await runner.run_two_lane_sources_pipeline(
            user_id="u-test",
            projekt_id="p-test",
            kapitel_id="k-test",
            run_id="parallel-speedup-test",
            chapter_title="Automatisierung der Dokumentenanalyse mittels NLP/LLM",
            chapter_spec_text="Einsatz von LLMs und NLP zur automatisierten Auswertung von Bilanzen.",
            settings={"force_rebuild": True},
            on_progress=lambda stage, message: progress_events.append((str(stage), str(message))),
        )
    finally:
        for name, value in original.items():
            if name == "IS_CLOUD_RUN":
                runner.app_config.IS_CLOUD_RUN = value
            else:
                setattr(runner, name, value)

    if not isinstance(result, dict) or not isinstance(result.get("output"), dict):
        raise AssertionError("Runner did not produce a result payload")

    builder_starts = {row["name"]: row["ts"] for row in timeline if row["kind"] == "builder" and row["event"] == "start"}
    builder_ends = {row["name"]: row["ts"] for row in timeline if row["kind"] == "builder" and row["event"] == "end"}
    fetch_starts = {row["name"]: row["ts"] for row in timeline if row["kind"] == "fetch" and row["event"] == "start"}
    fetch_ends = {row["name"]: row["ts"] for row in timeline if row["kind"] == "fetch" and row["event"] == "end"}

    builder_span = max(builder_ends.values()) - min(builder_starts.values())
    fetch_span = max(fetch_ends.values()) - min(fetch_starts.values())
    if builder_span >= 0.62:
        raise AssertionError(f"Builder span looks sequential: {builder_span:.3f}s")
    if fetch_span >= 0.62:
        raise AssertionError(f"Fetch span looks sequential: {fetch_span:.3f}s")

    stages = [stage for stage, _ in progress_events]
    if "phase_c_query_builders" not in stages:
        raise AssertionError("Combined phase_c progress stage was not emitted")
    if "phase_d_retrieval" not in stages:
        raise AssertionError("Combined phase_d progress stage was not emitted")

    return {
        "builder_span_s": round(builder_span, 3),
        "fetch_span_s": round(fetch_span, 3),
        "progress_stages": stages,
        "timeline": timeline,
    }


def main() -> int:
    payload = asyncio.run(_run_test())
    out_dir = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "test_two_lane_parallel_speedups_latest.json"
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
