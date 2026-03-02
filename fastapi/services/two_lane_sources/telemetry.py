from __future__ import annotations

import json
import math
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .pipeline import RunContext, _iter_jsonl_dicts, load_metrics, read_json


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        n = int(x)
        return n
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if not math.isfinite(v):
            return None
        return v
    except Exception:
        return None


def _norm_str(x: Any) -> str:
    return str(x or "").strip()


def _any_term_in_text(text: str, terms: Iterable[str]) -> bool:
    s = str(text or "").casefold()
    if not s:
        return False
    for t in terms:
        tt = str(t or "").strip()
        if not tt:
            continue
        if tt.casefold() in s:
            return True
    return False


def _hist(values: List[float], *, bins: int = 20, lo: float = 0.0, hi: float = 1.0) -> Dict[str, Any]:
    vals = [float(v) for v in values if v is not None and math.isfinite(float(v))]
    if not vals:
        return {"bins": bins, "lo": lo, "hi": hi, "counts": [0] * int(bins)}
    lo_f = float(lo)
    hi_f = float(hi)
    if hi_f <= lo_f:
        hi_f = lo_f + 1.0
    step = (hi_f - lo_f) / float(max(1, int(bins)))
    counts = [0] * int(bins)
    for v in vals:
        if v <= lo_f:
            i = 0
        elif v >= hi_f:
            i = int(bins) - 1
        else:
            i = int((v - lo_f) / step)
            i = max(0, min(int(bins) - 1, i))
        counts[i] += 1
    return {"bins": int(bins), "lo": lo_f, "hi": hi_f, "counts": counts}


def _scan_provider_raw_jsonl(
    *,
    path: Path,
    provider: str,
    year_field: str,
) -> Dict[str, Any]:
    records_total = 0
    by_intent_lang: Dict[str, int] = defaultdict(int)
    by_query_id: Dict[str, int] = defaultdict(int)
    by_year: Dict[str, int] = defaultdict(int)

    for rec in _iter_jsonl_dicts(path):
        intent = _norm_str(rec.get("intent")) or "unknown"
        lang = _norm_str(rec.get("language")) or "unknown"
        qi = _safe_int(rec.get("query_i")) or 0
        qid = f"{provider}:{qi}:{intent}:{lang}"

        records_total += 1
        by_intent_lang[f"{intent}/{lang}"] += 1
        by_query_id[qid] += 1

        obj = rec.get(year_field) or {}
        if isinstance(obj, dict):
            y = _safe_int(obj.get("publication_year") if year_field == "work" else obj.get("year"))
        else:
            y = None
        if y is not None and 0 < int(y) < 3000:
            by_year[str(int(y))] += 1

    return {
        "records_total": int(records_total),
        "records_by_intent_lang": dict(sorted(by_intent_lang.items(), key=lambda kv: (-kv[1], kv[0]))),
        "records_by_query_id": dict(sorted(by_query_id.items(), key=lambda kv: (-kv[1], kv[0]))),
        "records_by_year": dict(sorted(by_year.items(), key=lambda kv: (int(kv[0]), kv[0]))),
    }


def build_two_lane_telemetry(
    *,
    run_ctx: RunContext,
    effective_settings: Dict[str, Any],
    costs: Dict[str, Any],
    openalex_fetch: Optional[Dict[str, Any]] = None,
    s2_fetch: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    """
    Build Firestore-ready telemetry docs.

    Keep payloads compact: aggregate counts, histograms, and small top-K lists only.
    """

    metrics = load_metrics(run_ctx)

    plan_obj = read_json(Path(run_ctx.artifacts.query_plan_json))
    oa_q_obj = read_json(Path(run_ctx.artifacts.openalex_queries_json))
    s2_q_obj = read_json(Path(run_ctx.artifacts.semanticscholar_queries_json))

    openalex_queries = list((oa_q_obj or {}).get("openalex_queries") or [])
    s2_bulk_queries = list((s2_q_obj or {}).get("s2_bulk_queries") or [])

    # Query string length distribution
    oa_lens = [len(_norm_str(q.get("query_string"))) for q in openalex_queries if isinstance(q, dict)]
    s2_lens = [len(_norm_str(q.get("query_string"))) for q in s2_bulk_queries if isinstance(q, dict)]

    query_lengths = {
        "openalex": {"count": int(len(oa_lens)), "lengths": oa_lens, "hist_20bins": _hist([float(x) for x in oa_lens], bins=20, lo=0, hi=max(1.0, float(max(oa_lens) if oa_lens else 1)))},
        "semanticscholar": {"count": int(len(s2_lens)), "lengths": s2_lens, "hist_20bins": _hist([float(x) for x in s2_lens], bins=20, lo=0, hi=max(1.0, float(max(s2_lens) if s2_lens else 1)))},
    }

    # Phase D summaries (scan aggregated JSONL, not per-query caches)
    oa_raw_path = Path(run_ctx.artifacts.openalex_raw_jsonl)
    s2_raw_path = Path(run_ctx.artifacts.semanticscholar_raw_jsonl)
    phase_d_openalex = _scan_provider_raw_jsonl(path=oa_raw_path, provider="openalex", year_field="work") if oa_raw_path.exists() else {}
    phase_d_s2 = _scan_provider_raw_jsonl(path=s2_raw_path, provider="semanticscholar", year_field="paper") if s2_raw_path.exists() else {}

    def _expected_query_ids(provider: str, qs: List[dict]) -> List[str]:
        out: List[str] = []
        for i, q in enumerate(qs, start=1):
            intent = _norm_str(q.get("intent")) or "unknown"
            lang = _norm_str(q.get("language")) or "unknown"
            out.append(f"{provider}:{i}:{intent}:{lang}")
        return out

    exp_oa = _expected_query_ids("openalex", [q for q in openalex_queries if isinstance(q, dict)])
    exp_s2 = _expected_query_ids("semanticscholar", [q for q in s2_bulk_queries if isinstance(q, dict)])
    got_oa = phase_d_openalex.get("records_by_query_id") or {}
    got_s2 = phase_d_s2.get("records_by_query_id") or {}
    zero_oa = [qid for qid in exp_oa if int(got_oa.get(qid, 0) or 0) == 0]
    zero_s2 = [qid for qid in exp_s2 if int(got_s2.get(qid, 0) or 0) == 0]

    phase_d = {
        "openalex": {
            "query_count": int(len(openalex_queries)),
            "zero_result_query_ids": zero_oa,
            "fetch_meta": {
                "query_failed": int((openalex_fetch or {}).get("query_failed") or 0),
                "records": int((openalex_fetch or {}).get("records") or 0),
                "records_fetched": int((openalex_fetch or {}).get("records_fetched") or 0),
            }
            if isinstance(openalex_fetch, dict)
            else None,
            **phase_d_openalex,
        },
        "semanticscholar": {
            "query_count": int(len(s2_bulk_queries)),
            "zero_result_query_ids": zero_s2,
            "fetch_meta": {
                "query_failed": int((s2_fetch or {}).get("query_failed") or 0),
                "records": int((s2_fetch or {}).get("records") or 0),
                "records_fetched": int((s2_fetch or {}).get("records_fetched") or 0),
            }
            if isinstance(s2_fetch, dict)
            else None,
            **phase_d_s2,
        },
    }

    # Phase E candidates summary + top-K heuristics
    anchors_all = []
    econ_terms_all = []
    try:
        anchors_all = list(((plan_obj.get("primary_context_anchors") or {}).get("en") or [])) + list(
            ((plan_obj.get("primary_context_anchors") or {}).get("de") or [])
        )
    except Exception:
        anchors_all = []
    try:
        econ_terms_all = list(((plan_obj.get("global_canonical_terms") or {}).get("en") or [])) + list(
            ((plan_obj.get("global_canonical_terms") or {}).get("de") or [])
        )
    except Exception:
        econ_terms_all = []

    candidates_path = Path(run_ctx.artifacts.candidates_normalized_jsonl)
    candidates: List[Dict[str, Any]] = list(_iter_jsonl_dicts(candidates_path)) if candidates_path.exists() else []

    def _lane_label(intents: Any) -> str:
        xs = [str(x or "").strip() for x in (intents or []) if str(x or "").strip()]
        s = set(xs)
        if "match" in s and "authority" in s:
            return "both"
        if "authority" in s:
            return "authority"
        if "match" in s:
            return "match"
        return "unknown"

    counts_by_lane_pool: Dict[str, int] = defaultdict(int)
    for c in candidates:
        lane = _lane_label(c.get("intents") or [])
        pool = _norm_str(c.get("pool")) or "unknown"
        counts_by_lane_pool[f"{lane}/{pool}"] += 1

    def _anchor_hit(c: Dict[str, Any]) -> bool:
        if not anchors_all:
            return False
        text = f"{_norm_str(c.get('title'))} {_norm_str(c.get('abstract'))}"
        return _any_term_in_text(text, anchors_all)

    def _econ_hits(c: Dict[str, Any]) -> int:
        if not econ_terms_all:
            return 0
        text = f"{_norm_str(c.get('title'))} {_norm_str(c.get('abstract'))}".casefold()
        hits = 0
        for t in econ_terms_all:
            tt = _norm_str(t)
            if not tt:
                continue
            if tt.casefold() in text:
                hits += 1
        return hits

    by_cites = sorted(candidates, key=lambda c: (-int(c.get("citations") or 0), _norm_str(c.get("title")).casefold(), _norm_str(c.get("id"))))
    top_no_anchor = []
    if anchors_all:
        for c in by_cites[:200]:
            if not _anchor_hit(c):
                top_no_anchor.append(
                    {
                        "id": _norm_str(c.get("id")),
                        "citations": int(c.get("citations") or 0),
                        "year": _safe_int(c.get("year")),
                        "pool": _norm_str(c.get("pool")),
                        "title": _norm_str(c.get("title"))[:160] or None,
                        "doi": _norm_str(c.get("doi"))[:120] or None,
                    }
                )
            if len(top_no_anchor) >= 40:
                break

    top_econ = []
    if econ_terms_all:
        econ_rank = []
        for c in candidates:
            h = _econ_hits(c)
            if h > 0:
                econ_rank.append((h, int(c.get("citations") or 0), c))
        econ_rank.sort(key=lambda t: (-t[0], -t[1], _norm_str((t[2] or {}).get("title")).casefold(), _norm_str((t[2] or {}).get("id"))))
        for h, cites, c in econ_rank[:40]:
            top_econ.append(
                {
                    "id": _norm_str(c.get("id")),
                    "econ_hits": int(h),
                    "citations": int(cites),
                    "year": _safe_int(c.get("year")),
                    "pool": _norm_str(c.get("pool")),
                    "anchor_hit": bool(_anchor_hit(c)),
                    "title": _norm_str(c.get("title"))[:160] or None,
                    "doi": _norm_str(c.get("doi"))[:120] or None,
                }
            )

    phase_e = {
        "counts": {
            "candidates_total": int(len(candidates)),
            "pool": dict(Counter([_norm_str(c.get("pool")) or "unknown" for c in candidates])),
            "doi_present": int(sum(1 for c in candidates if _norm_str(c.get("doi")))),
            "year_missing": int(sum(1 for c in candidates if not (_safe_int(c.get("year")) or 0))),
            "by_lane_pool": dict(sorted(counts_by_lane_pool.items(), key=lambda kv: (-kv[1], kv[0]))),
        },
        "top_cited_no_anchors": top_no_anchor,
        "top_econ_hit": top_econ,
    }

    # Phase F scoring plots proxy data (based on scores_stage1.jsonl)
    scores_stage1_path = run_ctx.run_dir / "scores_stage1.jsonl"
    stage1 = list(_iter_jsonl_dicts(scores_stage1_path)) if scores_stage1_path.exists() else []

    match_lane_with = [float(r.get("match_lane") or 0.0) for r in stage1 if _norm_str(r.get("pool")) == "with_abstract"]
    match_lane_noabs = [float(r.get("match_lane") or 0.0) for r in stage1 if _norm_str(r.get("pool")) == "without_abstract"]
    auth_lane_with = [float(r.get("authority_lane") or 0.0) for r in stage1 if _norm_str(r.get("pool")) == "with_abstract"]
    auth_lane_noabs = [float(r.get("authority_lane") or 0.0) for r in stage1 if _norm_str(r.get("pool")) == "without_abstract"]

    scatter = []
    for r in stage1[:2000]:
        # Firestore does not allow nested arrays, so we store an array of objects instead of [x,y,label] tuples.
        scatter.append(
            {
                "match_lane": float(r.get("match_lane") or 0.0),
                "authority_lane": float(r.get("authority_lane") or 0.0),
                "pool": _norm_str(r.get("pool")) or "unknown",
            }
        )

    # Anchor hit rate on Phase F shortlists (top20)
    shortlists_path = run_ctx.run_dir / "shortlists_stage1.json"
    shortlists = read_json(shortlists_path) if shortlists_path.exists() else {}
    cand_by_id = {str(c.get("id") or ""): c for c in candidates}

    anchor_rate: Dict[str, Any] = {}
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = [str(x) for x in (shortlists.get(lane, {}).get(pool, []) or [])][:20]
            hits = 0
            for cid in ids:
                c = cand_by_id.get(cid) or {}
                if _anchor_hit(c):
                    hits += 1
            anchor_rate[f"{lane}/{pool}"] = {"top_n": int(len(ids)), "anchor_hits": int(hits)}

    phase_f = {
        "counts": ((metrics.get("stages") or {}).get("phase_f") or {}).get("counts") or {},
        "anchor_hit_rate_top20": anchor_rate,
        "distributions": {
            "match_lane": {
                "with_abstract": _hist(match_lane_with, bins=30, lo=0.0, hi=1.0),
                "without_abstract": _hist(match_lane_noabs, bins=30, lo=0.0, hi=1.0),
            },
            "authority_lane": {
                "with_abstract": _hist(auth_lane_with, bins=30, lo=0.0, hi=1.0),
                "without_abstract": _hist(auth_lane_noabs, bins=30, lo=0.0, hi=1.0),
            },
        },
        "scatter_match_vs_authority_sample": scatter,
    }

    # Phase I summary (LLM rerank)
    rerank_path = Path(run_ctx.artifacts.rerank_results_jsonl)
    rerank_rows = list(_iter_jsonl_dicts(rerank_path)) if rerank_path.exists() else []
    llm_scores = []
    insufficient = 0
    for r in rerank_rows:
        rr = r.get("rerank") or {}
        if isinstance(rr, dict):
            llm_scores.append(float(rr.get("llm_score_0_100") or 0))
            if bool(rr.get("insufficient_info")):
                insufficient += 1

    phase_i_counts = ((metrics.get("stages") or {}).get("phase_i_rerank") or {}).get("counts") or {}
    phase_i = {
        "counts": phase_i_counts,
        "llm_score_hist": _hist([float(x) for x in llm_scores], bins=20, lo=0.0, hi=100.0),
        "insufficient_total": int(insufficient),
    }

    # Final report plot proxy data from output.json (top cards only)
    output_obj = read_json(Path(run_ctx.artifacts.output_json))
    top = output_obj.get("top") or {}
    lane_points = []
    tags_freq: Dict[str, int] = defaultdict(int)
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            cards = list(((top.get(lane) or {}).get(pool) or []))
            for idx, c in enumerate(cards, start=1):
                sc = c.get("scores") or {}
                rr = c.get("rerank") or {}
                cov_tags = list(c.get("coverage_tags") or [])
                for t in cov_tags:
                    if isinstance(t, dict):
                        fid = _norm_str(t.get("facet_id"))
                        if fid:
                            tags_freq[fid] += 1
                lane_points.append(
                    {
                        "lane": lane,
                        "pool": pool,
                        "rank": int(idx),
                        "id": _norm_str(c.get("id")),
                        "match_lane": _safe_float(sc.get("match_lane")),
                        "authority_lane": _safe_float(sc.get("authority_lane")),
                        "match": _safe_float(sc.get("match")),
                        "authority": _safe_float(sc.get("authority")),
                        "llm_score_0_100": _safe_int(rr.get("llm_score_0_100") if isinstance(rr, dict) else None),
                        "insufficient_info": bool(rr.get("insufficient_info")) if isinstance(rr, dict) else None,
                        "year": _safe_int(c.get("year")),
                        "citations": int(c.get("citations") or 0),
                        "tag_count": int(len(cov_tags)),
                    }
                )

    final_report = {
        "models": {
            "planner": effective_settings.get("openai_model_planner"),
            "openalex_query_builder": effective_settings.get("openai_model_openalex_query_builder"),
            "s2_query_builder": effective_settings.get("openai_model_s2_query_builder"),
            "rerank": effective_settings.get("openai_model_rerank"),
            "embedding": effective_settings.get("embedding_model"),
        },
        "costs": costs,
        "durations_s": {k: (v or {}).get("last_duration_s") for k, v in (metrics.get("stages") or {}).items() if isinstance(v, dict)},
        "plot_data": {
            "lane_points": lane_points,
            "tags_frequency": dict(sorted(tags_freq.items(), key=lambda kv: (-kv[1], kv[0]))),
            "llm_score_hist": phase_i.get("llm_score_hist"),
        },
        "counts": {
            "queries_openalex": int(len(openalex_queries)),
            "queries_semanticscholar": int(len(s2_bulk_queries)),
            "records_openalex": int((phase_d_openalex or {}).get("records_total") or 0),
            "records_semanticscholar": int((phase_d_s2 or {}).get("records_total") or 0),
            "candidates_total": int(len(candidates)),
        },
    }

    return {
        "metrics": metrics,
        "phase_b_plan": plan_obj,
        "phase_c_queries": {"openalex_queries": openalex_queries, "s2_bulk_queries": s2_bulk_queries, "query_lengths": query_lengths},
        "phase_d_retrieval": phase_d,
        "phase_e_candidates": phase_e,
        "phase_f_scoring": phase_f,
        "phase_i_rerank": phase_i,
        "final_report": final_report,
    }
