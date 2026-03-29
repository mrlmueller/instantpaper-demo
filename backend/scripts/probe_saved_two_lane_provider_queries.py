from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
import requests


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = Path(__file__).resolve().parent
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

load_dotenv(REPO_ROOT / ".env", override=True)
load_dotenv(BACKEND_ROOT / ".env", override=True)

import replay_two_lane_query_builders as replay
from services.two_lane_sources.pipeline import (
    OPENALEX_SELECT,
    S2_BATCH_FIELDS,
    S2_BULK_FIELDS,
    QueryPlan,
    _openalex_params,
    _s2_iter_batch_items,
)
from services.two_lane_sources.runner import _build_run_ctx


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _selected_attempt(summary_payload: Dict[str, Any]) -> int:
    attempt = summary_payload.get("selected_attempt")
    if attempt is None:
        raise ValueError("selected_attempt missing in summary payload")
    return int(attempt)


def _query_has_data(provider: str, probe_payload: Dict[str, Any]) -> bool:
    if provider == "openalex":
        return bool(int(probe_payload.get("result_count_reported") or 0) > 0 and list(probe_payload.get("sample_results") or []))
    if list(probe_payload.get("sample_results") or []):
        return True
    return bool(int(probe_payload.get("ids_seen") or 0) > 0)


def _query_probe_count(provider: str, probe_payload: Dict[str, Any]) -> int:
    if provider == "openalex":
        return int(probe_payload.get("result_count_reported") or 0)
    return int(probe_payload.get("ids_seen") or 0)


def _validate_selected_queries(run_dir: Path) -> Dict[str, Any]:
    cfg = replay.PipelineConfig.model_validate(_load_json(run_dir / "effective_config.json"))
    plan = QueryPlan.model_validate(_load_json(run_dir / "query_plan.json"))

    openalex_summary = _load_json(run_dir / "openalex_summary.json")
    s2_summary = _load_json(run_dir / "s2_summary.json")

    openalex_attempt = _selected_attempt(openalex_summary)
    s2_attempt = _selected_attempt(s2_summary)

    openalex_payload = _load_json(run_dir / "openalex" / f"openalex_attempt_{openalex_attempt}" / "parsed_output.json")
    s2_payload = _load_json(run_dir / "s2" / f"s2_attempt_{s2_attempt}" / "parsed_output.json")

    openalex_validated = replay._validate_openalex_queries(openalex_payload, plan=plan, cfg=cfg)
    s2_validated = replay._validate_s2_queries(s2_payload, plan=plan, cfg=cfg)
    return {
        "cfg": cfg,
        "plan": plan,
        "openalex": openalex_validated,
        "s2": s2_validated,
        "openalex_attempt": openalex_attempt,
        "s2_attempt": s2_attempt,
    }


def _probe_openalex_with_pipeline_transport(*, cfg, run_ctx, session: requests.Session, query, top_k: int) -> Dict[str, Any]:
    url = cfg.openalex_base_url.rstrip("/") + "/works"
    params = _openalex_params(cfg, query.model_copy(update={"per_page": min(max(top_k, 1), 25)}), cursor="*")
    params["select"] = OPENALEX_SELECT
    auth_mode = "configured"
    initial_status: int | None = None
    direct_resp = session.get(url, params=params, timeout=float(cfg.openalex_timeout_s))
    initial_status = int(direct_resp.status_code)
    if direct_resp.status_code == 429 and "Insufficient budget" in (direct_resp.text or ""):
        params = dict(params)
        params.pop("api_key", None)
        auth_mode = "without_api_key_fallback"
        direct_resp = session.get(url, params=params, timeout=float(cfg.openalex_timeout_s))

    if direct_resp.status_code >= 400:
        raise RuntimeError(f"openalex HTTP {direct_resp.status_code} | URL: {direct_resp.url} | Body: {direct_resp.text[:600]}")

    payload = direct_resp.json()
    rows: List[Dict[str, Any]] = []
    for item in (payload.get("results") or [])[:top_k]:
        rows.append(
            {
                "id": item.get("id"),
                "title": item.get("display_name"),
                "year": item.get("publication_year"),
                "type": item.get("type"),
                "cited_by_count": item.get("cited_by_count"),
            }
        )
    return {
        "status_code": int(direct_resp.status_code),
        "initial_status_code": initial_status,
        "auth_mode": auth_mode,
        "result_count_reported": int(((payload.get("meta") or {}).get("count")) or 0),
        "sample_results": rows,
        "request_params": {k: ("<redacted>" if k == "api_key" else v) for k, v in params.items()},
    }


def _probe_s2_with_pipeline_transport(*, cfg, run_ctx, session: requests.Session, query, top_k: int) -> Dict[str, Any]:
    base = cfg.semanticscholar_base_url.rstrip("/")
    bulk_url = base + "/paper/search/bulk"
    batch_url = base + "/paper/batch"
    bulk_resp = session.get(
        bulk_url,
        params={"query": query.query_string, "fields": S2_BULK_FIELDS, "limit": int(min(max(top_k, 1), 25))},
        timeout=float(cfg.semanticscholar_timeout_s),
    )
    if bulk_resp.status_code >= 400:
        raise RuntimeError(f"semanticscholar bulk HTTP {bulk_resp.status_code} | URL: {bulk_resp.url} | Body: {bulk_resp.text[:600]}")
    bulk_payload = bulk_resp.json()
    ids = [str(item.get("paperId")) for item in (bulk_payload.get("data") or []) if item.get("paperId")][:top_k]
    batch_items: List[Dict[str, Any]] = []
    batch_status: int | None = None
    batch_error: str | None = None
    if ids:
        batch_resp = session.post(
            batch_url,
            params={"fields": S2_BATCH_FIELDS},
            json={"ids": ids},
            timeout=float(cfg.semanticscholar_timeout_s),
        )
        batch_status = int(batch_resp.status_code)
        if batch_resp.status_code < 400:
            batch_items = _s2_iter_batch_items(batch_resp.json())
        else:
            batch_error = batch_resp.text[:600]

    rows: List[Dict[str, Any]] = []
    for item in batch_items[:top_k]:
        rows.append(
            {
                "paperId": item.get("paperId"),
                "title": item.get("title"),
                "year": item.get("year"),
                "venue": item.get("venue"),
                "citationCount": item.get("citationCount"),
            }
        )
    return {
        "bulk_status_code": int(bulk_resp.status_code),
        "batch_status_code": batch_status,
        "batch_error": batch_error,
        "ids_seen": len(ids),
        "sample_ids": ids,
        "sample_results": rows,
        "request_query": query.query_string,
    }


def _probe_provider_queries(
    *,
    provider: str,
    cfg,
    run_ctx,
    validated: Dict[str, Any],
    top_k: int,
    target_successes: int,
    max_attempted: int,
) -> Dict[str, Any]:
    queries = list(validated.get("queries") or [])
    rows = list(validated.get("rows") or [])
    if len(queries) != len(rows):
        raise ValueError(f"{provider}: query/row length mismatch")

    ordered_pairs: List[tuple[Any, Dict[str, Any]]] = []
    seen_indices: set[int] = set()
    for intent in ("authority", "match"):
        for idx, (query, row) in enumerate(zip(queries, rows)):
            if idx in seen_indices:
                continue
            if str(row.get("intent") or "") != intent:
                continue
            ordered_pairs.append((query, row))
            seen_indices.add(idx)
            break
    for idx, (query, row) in enumerate(zip(queries, rows)):
        if idx in seen_indices:
            continue
        ordered_pairs.append((query, row))
        seen_indices.add(idx)

    attempts: List[Dict[str, Any]] = []
    successes = 0
    attempted = 0
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane-verification/1.0"})
    if provider == "s2" and cfg.semanticscholar_api_key:
        session.headers.update({"x-api-key": cfg.semanticscholar_api_key})

    for query, row in ordered_pairs:
        if attempted >= max_attempted or successes >= target_successes:
            break
        attempted += 1
        if provider == "openalex":
            probe = _probe_openalex_with_pipeline_transport(
                cfg=cfg,
                run_ctx=run_ctx,
                session=session,
                query=query,
                top_k=top_k,
            )
        else:
            probe = _probe_s2_with_pipeline_transport(
                cfg=cfg,
                run_ctx=run_ctx,
                session=session,
                query=query,
                top_k=top_k,
            )
        had_data = _query_has_data(provider, probe)
        attempts.append(
            {
                "index": int(row.get("index") or attempted),
                "intent": row.get("intent"),
                "language": row.get("language"),
                "notes": row.get("notes"),
                "query_string": row.get("query_string"),
                "anchor_hits": row.get("anchor_hits"),
                "core_object_hits": row.get("core_object_hits"),
                "had_data": had_data,
                "count_signal": _query_probe_count(provider, probe),
                "probe": probe,
            }
        )
        if had_data:
            successes += 1

    session.close()
    return {
        "attempted": attempted,
        "successful_with_data": successes,
        "target_successes": target_successes,
        "max_attempted": max_attempted,
        "results": attempts,
    }


def _build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Probe saved two-lane provider queries against OpenAlex and Semantic Scholar.")
    parser.add_argument("--run-dir", required=True, help="Investigation directory created by replay_two_lane_query_builders.py")
    parser.add_argument("--provider", choices=["openalex", "s2", "both"], default="both")
    parser.add_argument("--top-k", type=int, default=3, help="How many provider results to capture per query")
    parser.add_argument("--target-successes", type=int, default=2, help="How many data-returning queries to keep per provider")
    parser.add_argument("--max-attempted", type=int, default=6, help="Maximum queries to probe per provider")
    parser.add_argument("--output-name", default="provider_query_probe.json", help="Output JSON filename under the run directory")
    return parser


def main() -> int:
    parser = _build_arg_parser()
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    context = _validate_selected_queries(run_dir)
    probe_run_ctx = _build_run_ctx(run_dir=run_dir / "probe_run", run_id="provider-query-probe")
    probe_run_ctx.create_artifact_skeleton(overwrite=False)
    payload: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "selected_attempts": {
            "openalex": int(context["openalex_attempt"]),
            "s2": int(context["s2_attempt"]),
        },
    }

    if args.provider in {"openalex", "both"}:
        payload["openalex"] = _probe_provider_queries(
            provider="openalex",
            cfg=context["cfg"],
            run_ctx=probe_run_ctx,
            validated=context["openalex"],
            top_k=int(args.top_k),
            target_successes=int(args.target_successes),
            max_attempted=int(args.max_attempted),
        )
    if args.provider in {"s2", "both"}:
        payload["s2"] = _probe_provider_queries(
            provider="s2",
            cfg=context["cfg"],
            run_ctx=probe_run_ctx,
            validated=context["s2"],
            top_k=int(args.top_k),
            target_successes=int(args.target_successes),
            max_attempted=int(args.max_attempted),
        )

    out_path = run_dir / (str(args.output_name or "").strip() or "provider_query_probe.json")
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=replay._json_default), encoding="utf-8")
    print(json.dumps({"output_path": str(out_path), "providers": [key for key in ("openalex", "s2") if key in payload]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
