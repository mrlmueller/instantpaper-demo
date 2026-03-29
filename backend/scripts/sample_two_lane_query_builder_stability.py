"""
Sample the two-lane query builders multiple times from a saved replay/investigation directory.

This is useful for measuring intermittent lint failures after prompt or validator changes.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

from dotenv import load_dotenv
from openai import AsyncOpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv(REPO_ROOT / ".env", override=True)
load_dotenv(BACKEND_ROOT / ".env", override=True)

import replay_two_lane_query_builders as replay
from services.two_lane_sources.pipeline import (
    ChapterInput,
    OPENALEX_QUERY_BUILDER_JSON_SCHEMA,
    OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT,
    OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
    QueryPlan,
    S2_BULK_QUERY_BUILDER_JSON_SCHEMA,
    S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT,
    S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
    _json_for_prompt,
    _render_template,
    _sanitize_plan_for_query_builders,
    _truncate_chars,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


async def _sample_openalex(*, client: AsyncOpenAI, prompt: str, plan: QueryPlan, cfg, samples: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for idx in range(1, samples + 1):
        obj, meta, _raw = await replay._responses_json_schema_call(
            client=client,
            model=cfg.openai_model_openalex_query_builder,
            system_prompt=OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT,
            user_prompt=prompt,
            schema_name="openalex_queries",
            schema=OPENALEX_QUERY_BUILDER_JSON_SCHEMA,
            reasoning_effort=cfg.openai_reasoning_effort,
            max_output_tokens=50000,
            timeout_s=float(cfg.openai_timeout_s),
        )
        rec: dict[str, Any] = {"sample": idx, "meta": meta}
        try:
            validated = replay._validate_openalex_queries(obj, plan=plan, cfg=cfg)
            rec["status"] = "passed"
            rec["query_count"] = len(validated["queries"])
            rec["runtime_fingerprint"] = replay._legacy_openalex_fingerprint_summary(validated["queries"], plan=plan)
        except Exception as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)
        print(f"openalex sample {idx}: {rec['status']} {rec.get('error', '')}")
        results.append(rec)
    return results


async def _sample_s2(*, client: AsyncOpenAI, prompt: str, plan: QueryPlan, cfg, samples: int) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for idx in range(1, samples + 1):
        obj, meta, _raw = await replay._responses_json_schema_call(
            client=client,
            model=cfg.openai_model_s2_query_builder,
            system_prompt=S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT,
            user_prompt=prompt,
            schema_name="s2_bulk_queries",
            schema=S2_BULK_QUERY_BUILDER_JSON_SCHEMA,
            reasoning_effort=cfg.openai_reasoning_effort,
            max_output_tokens=50000,
            timeout_s=float(cfg.openai_timeout_s),
        )
        rec: dict[str, Any] = {"sample": idx, "meta": meta}
        try:
            validated = replay._validate_s2_queries(obj, plan=plan, cfg=cfg)
            rec["status"] = "passed"
            rec["query_count"] = len(validated["queries"])
        except Exception as exc:
            rec["status"] = "failed"
            rec["error"] = str(exc)
        print(f"s2 sample {idx}: {rec['status']} {rec.get('error', '')}")
        results.append(rec)
    return results


async def _async_main(args: argparse.Namespace) -> int:
    if not os.getenv("OPENAI_API_KEY", "").strip():
        raise RuntimeError("OPENAI_API_KEY is not available after loading dotenv")

    run_dir = Path(args.run_dir).resolve()
    cfg = replay._effective_config(
        run_root=run_dir / "stability_runs",
        run_settings=(_read_json(run_dir / "case.json").get("run_settings") or {}),
    )
    plan = QueryPlan.model_validate(_read_json(run_dir / "query_plan.json"))
    chapter = ChapterInput.model_validate(_read_json(run_dir / "chapter_input.json"))
    client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    openalex_prompt = _render_template(
        OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter.chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter.chapter_spec_text, 12000),
        query_plan_json=_json_for_prompt(_sanitize_plan_for_query_builders(plan)),
        max_queries=str(int(cfg.max_queries_per_provider or 50)),
    )
    s2_prompt = _render_template(
        S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter.chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter.chapter_spec_text, 12000),
        query_plan_json=_json_for_prompt(_sanitize_plan_for_query_builders(plan)),
        max_queries=str(int(cfg.max_queries_per_provider or 50)),
    )

    report: dict[str, Any] = {"run_dir": str(run_dir)}
    if args.provider in {"openalex", "both"}:
        report["openalex"] = await _sample_openalex(
            client=client,
            prompt=openalex_prompt,
            plan=plan,
            cfg=cfg,
            samples=int(args.openalex_samples),
        )
    if args.provider in {"s2", "both"}:
        report["s2"] = await _sample_s2(
            client=client,
            prompt=s2_prompt,
            plan=plan,
            cfg=cfg,
            samples=int(args.s2_samples),
        )

    output_name = str(args.output_name or "").strip() or f"stability_sampling_{args.provider}.json"
    out_path = run_dir / output_name
    _write_json(out_path, report)
    print(f"Wrote {out_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Repeatedly sample the query builders from a saved investigation directory.")
    parser.add_argument("--run-dir", required=True, help="Investigation directory created by replay_two_lane_query_builders.py")
    parser.add_argument("--provider", choices=["openalex", "s2", "both"], default="both")
    parser.add_argument("--openalex-samples", type=int, default=4)
    parser.add_argument("--s2-samples", type=int, default=4)
    parser.add_argument("--output-name", default=None)
    args = parser.parse_args()
    return asyncio.run(_async_main(args))


if __name__ == "__main__":
    raise SystemExit(main())
