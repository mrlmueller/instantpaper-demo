from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

import replay_two_lane_query_builders as replay
from services.two_lane_sources.runner import _build_run_ctx


def _load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_attempt(summary_payload: dict, key: str) -> int:
    attempt = summary_payload.get(key)
    if attempt is None:
        raise ValueError(f"Missing {key} in summary payload")
    return int(attempt)


def run_fetch_smoke(*, run_dir: Path, output_name: str) -> dict:
    cfg = replay.PipelineConfig.model_validate(_load_json(run_dir / "effective_config.json"))
    plan = replay.QueryPlan.model_validate(_load_json(run_dir / "query_plan.json"))

    openalex_summary = _load_json(run_dir / "openalex_summary.json")
    s2_summary = _load_json(run_dir / "s2_summary.json")
    openalex_attempt = _selected_attempt(openalex_summary, "selected_attempt")
    s2_attempt = _selected_attempt(s2_summary, "selected_attempt")

    openalex_payload = _load_json(run_dir / "openalex" / f"openalex_attempt_{openalex_attempt}" / "parsed_output.json")
    s2_payload = _load_json(run_dir / "s2" / f"s2_attempt_{s2_attempt}" / "parsed_output.json")

    openalex_validated = replay._validate_openalex_queries(openalex_payload, plan=plan, cfg=cfg)
    s2_validated = replay._validate_s2_queries(s2_payload, plan=plan, cfg=cfg)

    run_ctx = _build_run_ctx(run_dir=run_dir / "scratch_run_saved_smoke", run_id="saved-smoke")
    run_ctx.create_artifact_skeleton(overwrite=False)

    smoke = replay._run_fetch_and_candidates(
        cfg=cfg,
        run_ctx=run_ctx,
        openalex_queries=list(openalex_validated["queries"]),
        s2_queries=list(s2_validated["queries"]),
    )
    out_path = run_dir / output_name
    out_path.write_text(
        json.dumps(smoke, indent=2, ensure_ascii=False, default=replay._json_default),
        encoding="utf-8",
    )
    return {
        "output_path": str(out_path),
        "openalex_records": int(((smoke.get("openalex_fetch") or {}).get("records")) or 0),
        "s2_records": int(((smoke.get("s2_fetch") or {}).get("records")) or 0),
        "deduped_candidates": int(((smoke.get("candidate_meta") or {}).get("deduped_candidates")) or 0),
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Phase D/E smoke tests from saved two-lane query-builder artifacts.")
    parser.add_argument("--run-dir", required=True, help="Path to the investigation artifact directory")
    parser.add_argument(
        "--output-name",
        default="pipeline_smoke_saved.json",
        help="Filename for the smoke-test JSON payload written under the run directory",
    )
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()
    result = run_fetch_smoke(
        run_dir=Path(args.run_dir).resolve(),
        output_name=str(args.output_name or "pipeline_smoke_saved.json").strip() or "pipeline_smoke_saved.json",
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
