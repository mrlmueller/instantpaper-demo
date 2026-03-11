from __future__ import annotations

import argparse
import json
import os
import re
import requests
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from phase_c_query_replay_probe import (
    OUTPUT_DIR,
    USER_AGENT,
    _count_s2_negatives,
    _count_s2_required_groups,
    _has_s2_advanced_syntax,
    _latest_run_dir,
    _list_terms,
    _load_env,
    _openalex_alt_surface,
    _probe_openalex,
    _probe_s2_endpoint,
    _read_json,
    _sanitize,
    _strip_s2_negatives,
    _summarize_openalex,
    _summarize_s2,
)


def _now_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _dedupe_keep_order(values: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for value in values:
        s = re.sub(r"\s+", " ", str(value or "").strip())
        if not s:
            continue
        key = s.casefold()
        if key in seen:
            continue
        seen.add(key)
        out.append(s)
    return out


def _word_count(text: str) -> int:
    return len(re.findall(r"\w+", str(text or ""), flags=re.UNICODE))


def _is_de_plausible(terms: List[str]) -> bool:
    clean = [t for t in terms if str(t or "").strip()]
    if len(clean) < 3:
        return False
    if max(_word_count(t) for t in clean) > 4:
        return False
    return True


def _pick_terms(
    primary: Iterable[str],
    *,
    secondary: Optional[Iterable[str]] = None,
    exclude: Optional[Iterable[str]] = None,
    max_terms: int,
) -> List[str]:
    excluded = {str(x or "").strip().casefold() for x in (exclude or []) if str(x or "").strip()}
    items = []
    items.extend(primary or [])
    if secondary:
        items.extend(secondary)
    out: List[str] = []
    seen = set()
    for item in items:
        s = re.sub(r"\s+", " ", str(item or "").strip())
        if not s:
            continue
        key = s.casefold()
        if key in seen or key in excluded:
            continue
        seen.add(key)
        out.append(s)
        if len(out) >= int(max_terms):
            break
    return out


def _terms_for_obj(plan: Dict[str, Any], lang: str, *, max_terms: int = 5) -> List[str]:
    return _pick_terms(
        _list_terms(plan, "core_object_terms", lang),
        secondary=_list_terms(plan, "primary_context_anchors", lang),
        max_terms=max_terms,
    )


def _facet_terms(facet: Dict[str, Any], lang: str, *, max_terms: int = 8) -> List[str]:
    group = str(facet.get("facet_group") or "")
    canon = [str(x).strip() for x in ((facet.get("canonical_terms") or {}).get(lang) or []) if str(x or "").strip()]
    neigh = [str(x).strip() for x in ((facet.get("neighbor_terms") or {}).get(lang) or []) if str(x or "").strip()]

    if group == "object":
        return _pick_terms(neigh, secondary=canon, max_terms=max_terms)
    return _pick_terms(canon, secondary=neigh, max_terms=max_terms)


def _group_openalex(terms: List[str]) -> str:
    safe = [f'"{t}"' for t in terms if str(t or "").strip()]
    return "(" + " OR ".join(safe) + ")"


def _group_s2(terms: List[str]) -> str:
    safe = [f'"{t}"' for t in terms if str(t or "").strip()]
    return "(" + " | ".join(safe) + ")"


def _facet_sort_key(facet: Dict[str, Any]) -> Tuple[int, int, str]:
    group_rank = {
        "object": 0,
        "construct": 1,
        "data_proxy": 2,
        "limitation": 3,
        "context": 4,
        "method": 5,
    }
    return (
        -int(facet.get("importance_weight") or 0),
        group_rank.get(str(facet.get("facet_group") or ""), 9),
        str(facet.get("facet_id") or ""),
    )


def _blueprint_terms(
    blueprint: Dict[str, Any],
    *,
    lang: str,
    facet_by_id: Dict[str, Dict[str, Any]],
    object_terms: List[str],
) -> List[str]:
    out: List[str] = []
    for facet_id in blueprint.get("target_facet_ids") or []:
        facet = facet_by_id.get(str(facet_id))
        if not facet:
            continue
        facet_group_terms = _facet_terms(facet, lang, max_terms=3 if str(blueprint.get("authority_kind")) == "core" else 2)
        out.extend(facet_group_terms)
    return _pick_terms(out, exclude=object_terms, max_terms=8)


def _emit_languages(strategy: str, *, de_terms: List[str], de_mode: str) -> List[str]:
    strategy = str(strategy or "")
    if de_mode == "never":
        return ["en"]
    if de_mode == "parallel-only":
        return ["en", "de"] if strategy == "en_de_parallel" else ["en"]
    if strategy == "en_de_parallel":
        return ["en", "de"]
    if strategy in {"en_plus_selective_de", "en_plus_bilingual_fallback"} and _is_de_plausible(de_terms):
        return ["en", "de"]
    return ["en"]


def _notes(prefix: str, label: str) -> str:
    s = re.sub(r"\s+", " ", f"{prefix}: {label}".strip())
    words = s.split()
    return " ".join(words[:18]).strip()


def assemble_deterministic_queries(plan: Dict[str, Any], *, de_mode: str) -> Dict[str, List[Dict[str, Any]]]:
    facets = list(plan.get("facets") or [])
    facet_by_id = {str(f.get("facet_id") or ""): f for f in facets if str(f.get("facet_id") or "").strip()}
    blueprints = list(plan.get("authority_blueprints") or [])

    openalex_queries: List[Dict[str, Any]] = []
    s2_queries: List[Dict[str, Any]] = []

    def add_openalex(query: Dict[str, Any]) -> None:
        key = (
            str(query.get("intent") or ""),
            str(query.get("language") or ""),
            str(query.get("search_field") or ""),
            str(query.get("query_string") or ""),
        )
        if key not in seen_oa:
            seen_oa.add(key)
            openalex_queries.append(query)

    def add_s2(query: Dict[str, Any]) -> None:
        key = (
            str(query.get("intent") or ""),
            str(query.get("language") or ""),
            str(query.get("query_string") or ""),
        )
        if key not in seen_s2:
            seen_s2.add(key)
            s2_queries.append(query)

    seen_oa = set()
    seen_s2 = set()

    for bp in blueprints:
        strategy = str(bp.get("language_strategy") or "")
        for lang in _emit_languages(strategy, de_terms=_list_terms(plan, "core_object_terms", "de"), de_mode=de_mode):
            object_terms = _terms_for_obj(plan, lang, max_terms=5)
            facet_terms = _blueprint_terms(bp, lang=lang, facet_by_id=facet_by_id, object_terms=object_terms)
            if len(object_terms) < 2 or len(facet_terms) < 2:
                continue
            label = str(bp.get("label_en") or bp.get("label_de") or "authority blueprint")
            add_openalex(
                {
                    "intent": "authority",
                    "language": lang,
                    "search_field": "search",
                    "query_string": f"{_group_openalex(object_terms)} AND {_group_openalex(facet_terms)}",
                    "filters": f"is_paratext:false,is_retracted:false,language:{lang}",
                    "sort": "cited_by_count:desc",
                    "per_page": 200,
                    "notes": _notes("Deterministic authority", label),
                }
            )
            add_s2(
                {
                    "intent": "authority",
                    "language": lang,
                    "query_string": f"+{_group_s2(object_terms)} +{_group_s2(facet_terms)}",
                    "notes": _notes("Deterministic authority", label),
                }
            )

    ranked_facets = sorted(
        [f for f in facets if int(f.get("importance_weight") or 0) >= 4 and str(f.get("authority_role") or "") != "none"],
        key=_facet_sort_key,
    )
    if ranked_facets:
        global_facet = ranked_facets[0]
        for lang in _emit_languages(
            str(global_facet.get("language_strategy") or ""),
            de_terms=_facet_terms(global_facet, "de", max_terms=6),
            de_mode=de_mode,
        ):
            object_terms = _terms_for_obj(plan, lang, max_terms=5)
            facet_terms = _facet_terms(global_facet, lang, max_terms=6)
            facet_terms = _pick_terms(facet_terms, exclude=object_terms, max_terms=6)
            if len(object_terms) >= 2 and len(facet_terms) >= 2:
                add_openalex(
                    {
                        "intent": "match",
                        "language": lang,
                        "search_field": "title_and_abstract.search",
                        "query_string": f"{_group_openalex(object_terms)} AND {_group_openalex(facet_terms)}",
                        "filters": f"is_paratext:false,is_retracted:false,language:{lang}",
                        "sort": "relevance_score:desc",
                        "per_page": 200,
                        "notes": _notes("Deterministic global match", str(global_facet.get("facet_label_en") or "global")),
                    }
                )
                add_s2(
                    {
                        "intent": "match",
                        "language": lang,
                        "query_string": f"+{_group_s2(object_terms)} +{_group_s2(facet_terms)}",
                        "notes": _notes("Deterministic global match", str(global_facet.get("facet_label_en") or "global")),
                    }
                )

    for facet in ranked_facets:
        strategy = str(facet.get("language_strategy") or "")
        for lang in _emit_languages(strategy, de_terms=_facet_terms(facet, "de", max_terms=7), de_mode=de_mode):
            object_terms = _terms_for_obj(plan, lang, max_terms=5)
            facet_terms = _facet_terms(facet, lang, max_terms=7)
            facet_terms = _pick_terms(facet_terms, exclude=object_terms, max_terms=7)
            if len(object_terms) < 2 or len(facet_terms) < 2:
                continue

            note = str(facet.get("facet_label_en") or facet.get("facet_id") or "facet")
            add_openalex(
                {
                    "intent": "match",
                    "language": lang,
                    "search_field": "title_and_abstract.search",
                    "query_string": f"{_group_openalex(object_terms)} AND {_group_openalex(facet_terms)}",
                    "filters": f"is_paratext:false,is_retracted:false,language:{lang}",
                    "sort": "relevance_score:desc",
                    "per_page": 200,
                    "notes": _notes("Deterministic facet match", note),
                }
            )
            add_s2(
                {
                    "intent": "match",
                    "language": lang,
                    "query_string": f"+{_group_s2(object_terms)} +{_group_s2(facet_terms)}",
                    "notes": _notes("Deterministic facet match", note),
                }
            )

    return {"openalex_queries": openalex_queries, "s2_bulk_queries": s2_queries}


def main() -> int:
    parser = argparse.ArgumentParser(description="Build deterministic Phase C queries from query_plan.json and probe live providers.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory containing query_plan.json. Defaults to latest run.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--openalex-sample-size", type=int, default=8)
    parser.add_argument("--s2-sample-size", type=int, default=10)
    parser.add_argument("--sleep-openalex", type=float, default=0.35)
    parser.add_argument("--sleep-s2", type=float, default=0.75)
    parser.add_argument("--de-mode", choices=["auto", "parallel-only", "never"], default="auto")
    args = parser.parse_args()

    _load_env()
    run_dir = (args.run_dir or _latest_run_dir()).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (OUTPUT_DIR / f"phase_c_deterministic_probe_{run_dir.name}_{_now_slug()}.json")

    plan = _read_json(run_dir / "query_plan.json")
    assembled = assemble_deterministic_queries(plan, de_mode=args.de_mode)

    session_oa = requests.Session()
    session_oa.headers.update({"User-Agent": USER_AGENT})
    session_s2 = requests.Session()
    session_s2.headers.update({"User-Agent": USER_AGENT})
    s2_key = (os.getenv("SEMANTICSCHOLAR_API_KEY") or "").strip()
    if s2_key:
        session_s2.headers.update({"x-api-key": s2_key})

    output: Dict[str, Any] = {
        "generated_at": _now_slug(),
        "run_dir": str(run_dir),
        "query_plan_path": str(run_dir / "query_plan.json"),
        "method": {
            "type": "deterministic_phase_c_assembly",
            "description": "Object-led query assembly from plan semantics without LLM query generation.",
            "de_mode": args.de_mode,
            "openalex_current_vs_alt_surface": True,
            "s2_bulk_vs_search": True,
            "s2_negative_ablation": True,
        },
        "assembled_queries": assembled,
        "openalex": {"queries": []},
        "semanticscholar": {"queries": []},
    }

    for idx, query in enumerate(assembled["openalex_queries"], start=1):
        language = str(query.get("language") or "")
        anchors = _list_terms(plan, "primary_context_anchors", language)
        core_terms = _list_terms(plan, "core_object_terms", language)
        current = _probe_openalex(
            session_oa,
            query=query,
            sample_size=args.openalex_sample_size,
            anchors=anchors,
            core_terms=core_terms,
            sleep_s=args.sleep_openalex,
        )
        alt_surface = _openalex_alt_surface(str(query.get("search_field") or ""))
        alt = _probe_openalex(
            session_oa,
            query=query,
            sample_size=args.openalex_sample_size,
            anchors=anchors,
            core_terms=core_terms,
            alt_surface=alt_surface,
            sleep_s=args.sleep_openalex,
        )
        record = {
            "index": idx,
            "intent": query.get("intent"),
            "language": language,
            "search_field": query.get("search_field"),
            "notes": query.get("notes"),
            "query_string": query.get("query_string"),
            "chars": len(str(query.get("query_string") or "")),
            "current": current,
            "alt_surface_probe": alt,
        }
        cur_count = current.get("count")
        alt_count = alt.get("count")
        if isinstance(cur_count, int) and cur_count > 0 and isinstance(alt_count, int):
            record["alt_over_current_ratio"] = float(alt_count) / float(cur_count)
        output["openalex"]["queries"].append(record)

    output["openalex"]["summary"] = _summarize_openalex(output["openalex"]["queries"])

    for idx, query in enumerate(assembled["s2_bulk_queries"], start=1):
        language = str(query.get("language") or "")
        anchors = _list_terms(plan, "primary_context_anchors", language)
        core_terms = _list_terms(plan, "core_object_terms", language)
        qs = str(query.get("query_string") or "")
        bulk = _probe_s2_endpoint(
            session_s2,
            url="https://api.semanticscholar.org/graph/v1/paper/search/bulk",
            query_string=qs,
            sample_size=args.s2_sample_size,
            anchors=anchors,
            core_terms=core_terms,
            sleep_s=args.sleep_s2,
        )
        search = _probe_s2_endpoint(
            session_s2,
            url="https://api.semanticscholar.org/graph/v1/paper/search",
            query_string=qs,
            sample_size=args.s2_sample_size,
            anchors=anchors,
            core_terms=core_terms,
            sleep_s=args.sleep_s2,
        )
        no_neg_qs = _strip_s2_negatives(qs)
        bulk_no_neg = None
        if no_neg_qs and no_neg_qs != qs:
            bulk_no_neg = _probe_s2_endpoint(
                session_s2,
                url="https://api.semanticscholar.org/graph/v1/paper/search/bulk",
                query_string=no_neg_qs,
                sample_size=args.s2_sample_size,
                anchors=anchors,
                core_terms=core_terms,
                sleep_s=args.sleep_s2,
            )
        record = {
            "index": idx,
            "intent": query.get("intent"),
            "language": language,
            "notes": query.get("notes"),
            "query_string": qs,
            "chars": len(qs),
            "required_groups": _count_s2_required_groups(qs),
            "negative_count": _count_s2_negatives(qs),
            "has_advanced_syntax": _has_s2_advanced_syntax(qs),
            "bulk": bulk,
            "search": search,
            "bulk_without_negatives": bulk_no_neg or {},
        }
        cur_total = bulk.get("total")
        search_total = search.get("total")
        if isinstance(cur_total, int) and cur_total > 0 and isinstance(search_total, int):
            record["search_over_bulk_ratio"] = float(search_total) / float(cur_total)
        if bulk_no_neg and isinstance(cur_total, int) and cur_total > 0 and isinstance(bulk_no_neg.get("total"), int):
            record["no_negative_over_current_ratio"] = float(bulk_no_neg.get("total")) / float(cur_total)
        output["semanticscholar"]["queries"].append(record)

    output["semanticscholar"]["summary"] = _summarize_s2(output["semanticscholar"]["queries"])

    output_path.write_text(json.dumps(_sanitize(output), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
