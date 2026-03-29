"""
Analyze saved two-lane query-builder artifacts and report lint outcomes.

Usage:
    python backend/scripts/analyze_two_lane_query_builder_lints.py --run-dir <investigation_dir>
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple


REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources.pipeline import (
    OpenAlexQuery,
    PipelineConfig,
    QueryPlan,
    S2BulkQuery,
    _find_anchor_terms_in_text,
    _normalize_openalex_query,
    _normalize_s2_query,
    _plan_language_terms,
    _validate_intent_coverage,
    _validate_language_coverage,
    _validate_match_core_object_presence,
    _validate_openalex_anchor_presence,
    _validate_openalex_match_anchor_fingerprint_diversity,
    _validate_openalex_search_field_budget,
    _validate_s2_advanced_syntax_budget,
    _validate_s2_anchor_presence,
    _validate_s2_match_required_group_budget,
)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _shadowed_defs_report(py_path: Path) -> Dict[str, Any]:
    tree = ast.parse(py_path.read_text(encoding="utf-8"))
    defs: Dict[str, List[int]] = defaultdict(list)
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            defs[node.name].append(int(node.lineno))
    shadowed = {name: lines for name, lines in defs.items() if len(lines) > 1}
    return {
        "path": str(py_path),
        "duplicate_function_count": len(shadowed),
        "duplicates": shadowed,
    }


def _active_fingerprint_summary(queries: List[OpenAlexQuery], *, plan: QueryPlan, max_share: float = 0.60) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [str(term).strip() for term in anchors if str(term or "").strip()]
        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        fps: Counter[Tuple[str, str]] = Counter()
        eligible = 0
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, anchors)
            top2 = tuple(hit.lower() for hit in hits[:2])
            if len(top2) < 2:
                continue
            fps[top2] += 1
            eligible += 1
        result: Dict[str, Any] = {"eligible_count": eligible, "pass": True}
        if eligible >= 4 and fps:
            fp, count = fps.most_common(1)[0]
            share = count / max(eligible, 1)
            result["pass"] = bool(share <= float(max_share))
            result["most_common_fingerprint"] = list(fp)
            result["most_common_share"] = round(share, 4)
        report[lang] = result
    return report


def _legacy_fingerprint_summary(queries: List[OpenAlexQuery], *, plan: QueryPlan, max_share: float = 0.60) -> Dict[str, Any]:
    report: Dict[str, Any] = {}
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [str(term).strip() for term in anchors if str(term or "").strip()]
        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        presence_counts = {anchor: 0 for anchor in anchors}
        for q in match_qs:
            for anchor in anchors:
                if anchor.casefold() in q.query_string.casefold():
                    presence_counts[anchor] += 1
        variable_anchors = [anchor for anchor in anchors if (presence_counts.get(anchor, 0) / max(len(match_qs), 1)) < 0.90]
        fps: Counter[Tuple[str, str]] = Counter()
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, variable_anchors)
            top2 = tuple(hit.lower() for hit in hits[:2])
            if len(top2) < 2:
                continue
            fps[top2] += 1
        eligible = int(sum(fps.values()))
        result: Dict[str, Any] = {"eligible_count": eligible, "variable_anchors": variable_anchors, "pass": True}
        if eligible >= 4 and fps:
            fp, count = fps.most_common(1)[0]
            share = count / max(eligible, 1)
            result["pass"] = bool(share <= float(max_share))
            result["most_common_fingerprint"] = list(fp)
            result["most_common_share"] = round(share, 4)
        report[lang] = result
    return report


def _query_rows_openalex(queries: List[OpenAlexQuery], plan: QueryPlan) -> List[Dict[str, Any]]:
    rows = []
    for query in queries:
        rows.append(
            {
                "intent": query.intent,
                "language": query.language,
                "search_field": query.search_field,
                "anchor_hits": _find_anchor_terms_in_text(query.query_string, getattr(plan.primary_context_anchors, query.language, []) or []),
                "core_object_hits": _find_anchor_terms_in_text(query.query_string, _plan_language_terms(plan, "core_object_terms", query.language)),
                "query_string": query.query_string,
            }
        )
    return rows


def _query_rows_s2(queries: List[S2BulkQuery], plan: QueryPlan) -> List[Dict[str, Any]]:
    rows = []
    for query in queries:
        rows.append(
            {
                "intent": query.intent,
                "language": query.language,
                "anchor_hits": _find_anchor_terms_in_text(query.query_string, getattr(plan.primary_context_anchors, query.language, []) or []),
                "core_object_hits": _find_anchor_terms_in_text(query.query_string, _plan_language_terms(plan, "core_object_terms", query.language)),
                "query_string": query.query_string,
            }
        )
    return rows


def _analyze_openalex_attempt(path: Path, plan: QueryPlan, cfg: PipelineConfig) -> Dict[str, Any]:
    payload = _read_json(path)
    items = payload.get("openalex_queries")
    if not isinstance(items, list):
        return {"status": "invalid", "error": "missing openalex_queries list"}
    queries = [_normalize_openalex_query(OpenAlexQuery.model_validate(item)) for item in items]
    if len(queries) > int(cfg.max_queries_per_provider or 50):
        queries = queries[: int(cfg.max_queries_per_provider or 50)]
    _validate_language_coverage(queries, provider="OpenAlex")
    _validate_intent_coverage(queries, provider="OpenAlex")
    _validate_openalex_anchor_presence(queries, plan=plan)
    _validate_match_core_object_presence(queries, plan=plan, provider="OpenAlex")
    _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)
    _validate_openalex_search_field_budget(queries)
    return {
        "status": "passed",
        "active_fingerprint": _active_fingerprint_summary(queries, plan=plan),
        "legacy_fingerprint": _legacy_fingerprint_summary(queries, plan=plan),
        "rows": _query_rows_openalex(queries, plan),
    }


def _analyze_s2_attempt(path: Path, plan: QueryPlan, cfg: PipelineConfig) -> Dict[str, Any]:
    payload = _read_json(path)
    items = payload.get("s2_bulk_queries")
    if not isinstance(items, list):
        return {"status": "invalid", "error": "missing s2_bulk_queries list"}
    queries = [_normalize_s2_query(S2BulkQuery.model_validate(item)) for item in items]
    if len(queries) > int(cfg.max_queries_per_provider or 50):
        queries = queries[: int(cfg.max_queries_per_provider or 50)]
    _validate_language_coverage(queries, provider="S2")
    _validate_intent_coverage(queries, provider="S2")
    _validate_s2_anchor_presence(queries, plan=plan)
    _validate_match_core_object_presence(queries, plan=plan, provider="S2")
    _validate_s2_match_required_group_budget(queries)
    _validate_s2_advanced_syntax_budget(queries)
    return {"status": "passed", "rows": _query_rows_s2(queries, plan)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze saved query-builder attempts.")
    parser.add_argument("--run-dir", required=True, help="Investigation directory created by replay_two_lane_query_builders.py")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    plan = QueryPlan.model_validate(_read_json(run_dir / "query_plan.json"))
    cfg = PipelineConfig.model_validate(_read_json(run_dir / "effective_config.json"))

    report: Dict[str, Any] = {
        "run_dir": str(run_dir),
        "shadowed_definitions": _shadowed_defs_report(BACKEND_ROOT / "services" / "two_lane_sources" / "pipeline.py"),
        "openalex_attempts": {},
        "s2_attempts": {},
    }

    for path in sorted((run_dir / "openalex").glob("openalex_attempt_*/parsed_output.json")):
        name = path.parent.name
        try:
            report["openalex_attempts"][name] = _analyze_openalex_attempt(path, plan, cfg)
        except Exception as exc:
            report["openalex_attempts"][name] = {"status": "failed", "error": str(exc)}

    for path in sorted((run_dir / "s2").glob("s2_attempt_*/parsed_output.json")):
        name = path.parent.name
        try:
            report["s2_attempts"][name] = _analyze_s2_attempt(path, plan, cfg)
        except Exception as exc:
            report["s2_attempts"][name] = {"status": "failed", "error": str(exc)}

    out_path = run_dir / "lint_analysis.json"
    _write_json(out_path, report)
    print(f"Wrote {out_path}")
    print(json.dumps({"run_dir": str(run_dir), "shadowed_duplicate_functions": report['shadowed_definitions']['duplicate_function_count']}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
