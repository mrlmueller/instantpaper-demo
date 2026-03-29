from __future__ import annotations

import heapq
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .pipeline import RunContext, _iter_jsonl_dicts, load_metrics, read_json

TELEMETRY_SCHEMA_VERSION = 2


def _safe_int(x: Any) -> Optional[int]:
    try:
        if x is None:
            return None
        return int(x)
    except Exception:
        return None


def _safe_float(x: Any) -> Optional[float]:
    try:
        if x is None:
            return None
        v = float(x)
        if not math.isfinite(v):
            return None
        return float(v)
    except Exception:
        return None


def _norm_str(x: Any) -> str:
    return str(x or "").strip()


def _truncate_chars(value: Any, max_chars: int) -> str:
    s = _norm_str(value)
    if not s:
        return ""
    if len(s) <= int(max_chars):
        return s
    if int(max_chars) <= 1:
        return "…"
    return s[: max(0, int(max_chars) - 1)].rstrip() + "…"


def _author_preview(authors: Any, *, max_chars: int = 200) -> str:
    xs: List[str] = []
    if isinstance(authors, list):
        for a in authors:
            s = _norm_str(a)
            if s:
                xs.append(s)
    joined = ", ".join(xs).strip()
    if not joined:
        return "—"
    if len(joined) <= int(max_chars):
        return joined
    return _truncate_chars(joined, int(max_chars))


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


def _econ_hits_in_text(text: str, terms: Iterable[str]) -> int:
    s = str(text or "").casefold()
    if not s:
        return 0
    hits = 0
    for t in terms:
        tt = str(t or "").strip()
        if not tt:
            continue
        if tt.casefold() in s:
            hits += 1
    return int(hits)


def _percentile(xs: List[int], p: float) -> Optional[float]:
    vals = [float(x) for x in xs if x is not None]
    if not vals:
        return None
    vals.sort()
    if len(vals) == 1:
        return float(vals[0])
    k = (len(vals) - 1) * (float(p) / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(vals[f])
    d0 = vals[f] * (c - k)
    d1 = vals[c] * (k - f)
    return float(d0 + d1)


def _hist_uniform_two_pools(
    *,
    values_with: List[float],
    values_without: List[float],
    bins: int,
    lo: float,
    hi: float,
    round_edges: int = 3,
) -> List[Dict[str, Any]]:
    bins_n = max(1, int(bins))
    lo_f = float(lo)
    hi_f = float(hi)
    if hi_f <= lo_f:
        hi_f = lo_f + 1.0
    step = (hi_f - lo_f) / float(bins_n)

    with_counts = [0] * bins_n
    without_counts = [0] * bins_n

    def _add(v: float, arr: List[int]) -> None:
        if not math.isfinite(float(v)):
            return
        x = float(v)
        if x <= lo_f:
            i = 0
        elif x >= hi_f:
            i = bins_n - 1
        else:
            i = int((x - lo_f) / step)
            i = max(0, min(bins_n - 1, i))
        arr[i] += 1

    for v in values_with:
        _add(float(v), with_counts)
    for v in values_without:
        _add(float(v), without_counts)

    out: List[Dict[str, Any]] = []
    for i in range(bins_n):
        bin_lo = lo_f + float(i) * step
        bin_hi = lo_f + float(i + 1) * step
        out.append(
            {
                "bin_lo": round(bin_lo, int(round_edges)),
                "bin_hi": round(bin_hi, int(round_edges)),
                "with_abstract": int(with_counts[i]),
                "without_abstract": int(without_counts[i]),
            }
        )
    return out


def _hist_binwidth_two_series(
    *,
    xs_a: List[int],
    xs_b: List[int],
    bin_width: int,
    key_a: str,
    key_b: str,
) -> List[Dict[str, Any]]:
    w = max(1, int(bin_width))
    vals_a = [int(x) for x in xs_a if x is not None and int(x) >= 0]
    vals_b = [int(x) for x in xs_b if x is not None and int(x) >= 0]
    if not vals_a and not vals_b:
        return []

    max_len = max(vals_a + vals_b)
    max_edge = int((max_len // w) * w + w)
    counts: Dict[int, Dict[str, int]] = {}

    for x in vals_a:
        lo = int((int(x) // w) * w)
        counts.setdefault(lo, {key_a: 0, key_b: 0})[key_a] += 1
    for x in vals_b:
        lo = int((int(x) // w) * w)
        counts.setdefault(lo, {key_a: 0, key_b: 0})[key_b] += 1

    out: List[Dict[str, Any]] = []
    for lo in range(0, max_edge, w):
        row = counts.get(lo) or {key_a: 0, key_b: 0}
        out.append({"bin_lo": int(lo), "bin_hi": int(lo + w), key_a: int(row[key_a]), key_b: int(row[key_b])})
    return out


def _scan_provider_raw_jsonl(
    *,
    path: Path,
    provider: str,
    year_field: str,
) -> Dict[str, Any]:
    records_total = 0
    by_intent_lang: Dict[Tuple[str, str], int] = defaultdict(int)
    by_query_id: Dict[str, int] = defaultdict(int)
    by_year: Dict[int, int] = defaultdict(int)
    with_abstract = 0
    without_abstract = 0

    for rec in _iter_jsonl_dicts(path):
        intent = _norm_str(rec.get("intent")) or "unknown"
        lang = _norm_str(rec.get("language")) or "unknown"
        qi = _safe_int(rec.get("query_i")) or 0
        qid = f"{provider}:{qi}:{intent}:{lang}"

        records_total += 1
        by_intent_lang[(intent, lang)] += 1
        by_query_id[qid] += 1

        obj = rec.get(year_field) or {}
        y = None
        has_abs = False
        if isinstance(obj, dict):
            if year_field == "work":
                inv = obj.get("abstract_inverted_index")
                has_abs = bool(inv) if isinstance(inv, dict) else bool(str(obj.get("abstract") or "").strip())
                y = _safe_int(obj.get("publication_year"))
            else:
                has_abs = bool(str(obj.get("abstract") or "").strip())
                y = _safe_int(obj.get("year"))
        if has_abs:
            with_abstract += 1
        else:
            without_abstract += 1
        if y is not None and 0 < int(y) < 3000:
            by_year[int(y)] += 1

    return {
        "records_total": int(records_total),
        "with_abstract": int(with_abstract),
        "without_abstract": int(without_abstract),
        "records_by_intent_lang": {
            f"{intent}/{lang}": int(n)
            for (intent, lang), n in sorted(by_intent_lang.items(), key=lambda kv: (-kv[1], kv[0][0], kv[0][1]))
        },
        "records_by_query_id": dict(sorted(by_query_id.items(), key=lambda kv: (-kv[1], kv[0]))),
        "records_by_year": {str(int(y)): int(n) for y, n in sorted(by_year.items(), key=lambda kv: (kv[0], kv[0]))},
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
    Build Firestore-ready telemetry docs (Telemetry v2).

    - Store only what the UI displays.
    - Use chart-ready arrays of objects (no nested arrays).
    - Keep payloads compact (top-k + histograms + samples).
    """

    metrics = load_metrics(run_ctx)

    # -------------------------
    # Load artifacts (best-effort)
    # -------------------------
    plan_path = Path(run_ctx.artifacts.query_plan_json)
    oa_queries_path = Path(run_ctx.artifacts.openalex_queries_json)
    s2_queries_path = Path(run_ctx.artifacts.semanticscholar_queries_json)

    plan_obj = read_json(plan_path) if plan_path.exists() else {}
    oa_q_obj = read_json(oa_queries_path) if oa_queries_path.exists() else {}
    s2_q_obj = read_json(s2_queries_path) if s2_queries_path.exists() else {}

    openalex_queries_raw = [q for q in list((oa_q_obj or {}).get("openalex_queries") or []) if isinstance(q, dict)]
    s2_queries_raw = [q for q in list((s2_q_obj or {}).get("s2_bulk_queries") or []) if isinstance(q, dict)]

    facets_raw = [f for f in list((plan_obj or {}).get("facets") or []) if isinstance(f, dict)]
    facets_count = int(len(facets_raw))

    # -------------------------
    # Phase D — Retrieval scan (aggregate JSONL)
    # -------------------------
    oa_raw_path = Path(run_ctx.artifacts.openalex_raw_jsonl)
    s2_raw_path = Path(run_ctx.artifacts.semanticscholar_raw_jsonl)
    scan_oa = _scan_provider_raw_jsonl(path=oa_raw_path, provider="openalex", year_field="work") if oa_raw_path.exists() else {}
    scan_s2 = _scan_provider_raw_jsonl(path=s2_raw_path, provider="semanticscholar", year_field="paper") if s2_raw_path.exists() else {}

    def _query_id(provider: str, i: int, intent: str, language: str) -> str:
        return f"{provider}:{int(i)}:{_norm_str(intent) or 'unknown'}:{_norm_str(language) or 'unknown'}"

    oa_query_rows: List[Dict[str, Any]] = []
    oa_id_to_qs: Dict[str, str] = {}
    for i, q in enumerate(openalex_queries_raw, start=1):
        intent = _norm_str(q.get("intent")) or "unknown"
        lang = _norm_str(q.get("language")) or "unknown"
        qid = _query_id("openalex", i, intent, lang)
        qs = _norm_str(q.get("query_string"))
        oa_id_to_qs[qid] = qs
        oa_query_rows.append(
            {
                "query_id": qid,
                "i": int(i),
                "intent": intent,
                "language": lang,
                "query_string": qs,
                "notes": (_norm_str(q.get("notes")) or None),
                "search_field": (_norm_str(q.get("search_field")) or None),
                "filters": (_norm_str(q.get("filters")) or None),
                "sort": (_norm_str(q.get("sort")) or None),
                "per_page": _safe_int(q.get("per_page")),
            }
        )

    s2_query_rows: List[Dict[str, Any]] = []
    s2_id_to_qs: Dict[str, str] = {}
    for i, q in enumerate(s2_queries_raw, start=1):
        intent = _norm_str(q.get("intent")) or "unknown"
        lang = _norm_str(q.get("language")) or "unknown"
        qid = _query_id("semanticscholar", i, intent, lang)
        qs = _norm_str(q.get("query_string"))
        s2_id_to_qs[qid] = qs
        s2_query_rows.append(
            {
                "query_id": qid,
                "i": int(i),
                "intent": intent,
                "language": lang,
                "query_string": qs,
                "notes": (_norm_str(q.get("notes")) or None),
            }
        )

    exp_oa_ids = [r["query_id"] for r in oa_query_rows if isinstance(r.get("query_id"), str)]
    exp_s2_ids = [r["query_id"] for r in s2_query_rows if isinstance(r.get("query_id"), str)]

    got_oa_by_qid: Dict[str, int] = {
        str(k): int(v or 0)
        for k, v in ((scan_oa.get("records_by_query_id") or {}) if isinstance(scan_oa, dict) else {}).items()
    }
    got_s2_by_qid: Dict[str, int] = {
        str(k): int(v or 0)
        for k, v in ((scan_s2.get("records_by_query_id") or {}) if isinstance(scan_s2, dict) else {}).items()
    }

    oa_counts_per_q = [int(got_oa_by_qid.get(qid, 0) or 0) for qid in exp_oa_ids]
    s2_counts_per_q = [int(got_s2_by_qid.get(qid, 0) or 0) for qid in exp_s2_ids]

    def _records_by_intent_lang(scan: Dict[str, Any]) -> List[Dict[str, Any]]:
        obj = scan.get("records_by_intent_lang") if isinstance(scan, dict) else None
        if not isinstance(obj, dict):
            return []
        out: List[Dict[str, Any]] = []
        for k, v in obj.items():
            try:
                intent, lang = str(k).split("/", 1)
            except Exception:
                intent, lang = str(k), "unknown"
            out.append({"intent": str(intent or "unknown"), "lang": str(lang or "unknown"), "records": int(v or 0)})
        out.sort(key=lambda r: (-int(r.get("records") or 0), str(r.get("intent") or ""), str(r.get("lang") or "")))
        return out

    ril_oa = _records_by_intent_lang(scan_oa if isinstance(scan_oa, dict) else {})
    ril_s2 = _records_by_intent_lang(scan_s2 if isinstance(scan_s2, dict) else {})

    def _sum_intent(rows: List[Dict[str, Any]], intent: str) -> int:
        return int(sum(int(r.get("records") or 0) for r in rows if str(r.get("intent") or "") == str(intent)))

    provider_totals = {
        "openalex": {
            "records_total": int((scan_oa or {}).get("records_total") or 0),
            "authority": _sum_intent(ril_oa, "authority"),
            "match": _sum_intent(ril_oa, "match"),
            "with_abstract": int((scan_oa or {}).get("with_abstract") or 0),
            "without_abstract": int((scan_oa or {}).get("without_abstract") or 0),
        },
        "semanticscholar": {
            "records_total": int((scan_s2 or {}).get("records_total") or 0),
            "authority": _sum_intent(ril_s2, "authority"),
            "match": _sum_intent(ril_s2, "match"),
            "with_abstract": int((scan_s2 or {}).get("with_abstract") or 0),
            "without_abstract": int((scan_s2 or {}).get("without_abstract") or 0),
        },
    }

    years_oa = {
        int(k): int(v or 0)
        for k, v in ((scan_oa.get("records_by_year") or {}) if isinstance(scan_oa, dict) else {}).items()
        if str(k).isdigit()
    }
    years_s2 = {
        int(k): int(v or 0)
        for k, v in ((scan_s2.get("records_by_year") or {}) if isinstance(scan_s2, dict) else {}).items()
        if str(k).isdigit()
    }
    all_years = sorted(set(list(years_oa.keys()) + list(years_s2.keys())))
    year_distribution = [
        {"year": int(y), "openalex": int(years_oa.get(y, 0)), "semanticscholar": int(years_s2.get(y, 0))}
        for y in all_years
    ]

    def _provider_summary(provider: str, exp_ids: List[str], counts_per_q: List[int], fetch_meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        qn = int(len(exp_ids))
        failed = int((fetch_meta or {}).get("query_failed") or 0)
        zero_q = int(sum(1 for x in counts_per_q if int(x or 0) <= 0))
        total_records = int(sum(int(x or 0) for x in counts_per_q))
        mean = (0.0 if qn <= 0 else float(total_records) / float(qn))
        med = (None if not counts_per_q else float(statistics.median([int(x or 0) for x in counts_per_q])))
        p90 = _percentile([int(x or 0) for x in counts_per_q], 90.0)
        mx = (None if not counts_per_q else float(max(int(x or 0) for x in counts_per_q)))
        dominance = (None if total_records <= 0 else float((max(int(x or 0) for x in counts_per_q) if counts_per_q else 0)) / float(total_records))
        return {
            "provider": str(provider),
            "queries": int(qn),
            "failed": int(failed),
            "failed_rate": (0.0 if qn <= 0 else float(failed) / float(qn)),
            "records": int(total_records),
            "zero_q": int(zero_q),
            "zero_rate": (0.0 if qn <= 0 else float(zero_q) / float(qn)),
            "mean": float(mean),
            "median": (None if med is None else float(med)),
            "p90": (None if p90 is None else float(p90)),
            "max": (None if mx is None else float(mx)),
            "dominance": (None if dominance is None else float(dominance)),
        }

    summary_oa = _provider_summary("OpenAlex", exp_oa_ids, oa_counts_per_q, openalex_fetch if isinstance(openalex_fetch, dict) else None)
    summary_s2 = _provider_summary("Semantic Scholar", exp_s2_ids, s2_counts_per_q, s2_fetch if isinstance(s2_fetch, dict) else None)

    top_queries: List[Dict[str, Any]] = []
    bottom_queries_nonzero: List[Dict[str, Any]] = []
    zero_result_queries: List[Dict[str, Any]] = []

    def _query_lists_for_provider(provider: str, exp_ids: List[str], counts_per_q: List[int], id_to_qs: Dict[str, str]) -> None:
        nonlocal top_queries, bottom_queries_nonzero, zero_result_queries
        rows = []
        for qid, n in zip(exp_ids, counts_per_q):
            parts = str(qid).split(":")
            intent = parts[2] if len(parts) >= 4 else "unknown"
            lang = parts[3] if len(parts) >= 4 else "unknown"
            rows.append(
                {
                    "provider": str(provider),
                    "query_id": str(qid),
                    "intent": str(intent),
                    "lang": str(lang),
                    "records": int(n or 0),
                    "query_string": str(id_to_qs.get(str(qid), "")),
                }
            )
        rows_sorted_desc = sorted(rows, key=lambda r: (-int(r.get("records") or 0), str(r.get("query_id") or "")))
        rows_sorted_asc = sorted(
            [r for r in rows if int(r.get("records") or 0) > 0],
            key=lambda r: (int(r.get("records") or 0), str(r.get("query_id") or "")),
        )
        top_queries.extend(rows_sorted_desc[:10])
        bottom_queries_nonzero.extend(rows_sorted_asc[:10])
        zero_result_queries.extend([r for r in rows if int(r.get("records") or 0) == 0])

    _query_lists_for_provider("openalex", exp_oa_ids, oa_counts_per_q, oa_id_to_qs)
    _query_lists_for_provider("semanticscholar", exp_s2_ids, s2_counts_per_q, s2_id_to_qs)

    zero_total = int(len(zero_result_queries))
    zero_truncated = False
    if zero_total > 200:
        zero_truncated = True
        zero_result_queries = zero_result_queries[:200]

    v2_d_retrieval = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "provider_totals": provider_totals,
        "provider_summary": [summary_oa, summary_s2],
        "records_by_intent_lang": {"openalex": ril_oa, "semanticscholar": ril_s2},
        "year_distribution": {"data": year_distribution},
        "top_queries": {"data": top_queries},
        "bottom_queries_nonzero": {"data": bottom_queries_nonzero},
        "zero_result_queries": {"data": zero_result_queries, "truncated": bool(zero_truncated), "total": int(zero_total)},
    }

    # -------------------------
    # Phase C — Queries (counts + length distribution + query lists)
    # -------------------------
    oa_lens = [len(_norm_str(q.get("query_string"))) for q in openalex_queries_raw]
    s2_lens = [len(_norm_str(q.get("query_string"))) for q in s2_queries_raw]
    all_lens = [int(x) for x in (oa_lens + s2_lens) if x is not None]
    median_len = (None if not all_lens else float(statistics.median(sorted(all_lens))))
    max_len = (None if not all_lens else int(max(all_lens)))

    lengths_dist = _hist_binwidth_two_series(xs_a=oa_lens, xs_b=s2_lens, bin_width=10, key_a="openalex", key_b="semanticscholar")

    match_total = int(sum(1 for q in (openalex_queries_raw + s2_queries_raw) if _norm_str(q.get("intent")) == "match"))
    authority_total = int(sum(1 for q in (openalex_queries_raw + s2_queries_raw) if _norm_str(q.get("intent")) == "authority"))

    openalex_zero = int(sum(1 for x in oa_counts_per_q if int(x or 0) == 0))
    s2_zero = int(sum(1 for x in s2_counts_per_q if int(x or 0) == 0))
    openalex_avg = (0.0 if len(oa_counts_per_q) <= 0 else float(sum(oa_counts_per_q)) / float(len(oa_counts_per_q)))
    s2_avg = (0.0 if len(s2_counts_per_q) <= 0 else float(sum(s2_counts_per_q)) / float(len(s2_counts_per_q)))

    v2_c_queries = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "counts": {
            "openalex_total": int(len(openalex_queries_raw)),
            "s2_total": int(len(s2_queries_raw)),
            "match_total": int(match_total),
            "authority_total": int(authority_total),
            "median_length": (None if median_len is None else float(median_len)),
            "max_length": (None if max_len is None else int(max_len)),
            "openalex_zero_result_queries": int(openalex_zero),
            "s2_zero_result_queries": int(s2_zero),
            "openalex_avg_results_per_query": float(openalex_avg),
            "s2_avg_results_per_query": float(s2_avg),
        },
        "length_distribution": {"bin_width_chars": 10, "data": lengths_dist},
        "openalex_queries": oa_query_rows,
        "s2_queries": s2_query_rows,
    }

    # -------------------------
    # Phase B — Plan (facets + term previews)
    # -------------------------
    primary_anchors = plan_obj.get("primary_context_anchors") if isinstance(plan_obj, dict) else {}
    global_terms = plan_obj.get("global_canonical_terms") if isinstance(plan_obj, dict) else {}
    global_excl = plan_obj.get("global_exclusions") if isinstance(plan_obj, dict) else {}

    v2_b_plan = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "topic_summary_de": _norm_str(plan_obj.get("topic_summary_de") if isinstance(plan_obj, dict) else "") or "",
        "topic_summary_en": _norm_str(plan_obj.get("topic_summary_en") if isinstance(plan_obj, dict) else "") or "",
        "primary_context_anchors": {
            "en": [str(x) for x in (primary_anchors.get("en") or []) if str(x or "").strip()] if isinstance(primary_anchors, dict) else [],
            "de": [str(x) for x in (primary_anchors.get("de") or []) if str(x or "").strip()] if isinstance(primary_anchors, dict) else [],
        },
        "global_canonical_terms": {
            "en": [str(x) for x in (global_terms.get("en") or []) if str(x or "").strip()] if isinstance(global_terms, dict) else [],
            "de": [str(x) for x in (global_terms.get("de") or []) if str(x or "").strip()] if isinstance(global_terms, dict) else [],
        },
        "global_exclusions": {
            "en": [str(x) for x in (global_excl.get("en") or []) if str(x or "").strip()] if isinstance(global_excl, dict) else [],
            "de": [str(x) for x in (global_excl.get("de") or []) if str(x or "").strip()] if isinstance(global_excl, dict) else [],
        },
        "facets": facets_raw,
    }

    anchors_all = [str(x) for x in (v2_b_plan["primary_context_anchors"]["en"] + v2_b_plan["primary_context_anchors"]["de"]) if str(x or "").strip()]
    econ_terms_all = [str(x) for x in (v2_b_plan["global_canonical_terms"]["en"] + v2_b_plan["global_canonical_terms"]["de"]) if str(x or "").strip()]

    # -------------------------
    # Phase E — Candidates (top lists + counts)
    # -------------------------
    stage_e_counts = (((metrics.get("stages") or {}).get("phase_e_candidates") or {}).get("counts") or {}) if isinstance(metrics, dict) else {}
    normalized_total = _safe_int(stage_e_counts.get("normalized_total")) or 0
    candidates_total = _safe_int(stage_e_counts.get("deduped_candidates")) or 0
    merges = _safe_int(stage_e_counts.get("merges")) or 0

    candidates_path = Path(run_ctx.artifacts.candidates_normalized_jsonl)
    doi_present = 0
    candidates_seen = 0
    pool_counts: Counter = Counter()

    top_cited_heap: List[Tuple[Tuple[int, str], Dict[str, Any]]] = []
    top_no_anchor_heap: List[Tuple[Tuple[int, str], Dict[str, Any]]] = []
    top_econ_heap: List[Tuple[Tuple[int, int, str], Dict[str, Any]]] = []

    def _push_top(heap: list, key, payload: Dict[str, Any], limit_n: int) -> None:
        item = (key, payload)
        if len(heap) < int(limit_n):
            heapq.heappush(heap, item)
            return
        if item > heap[0]:
            heapq.heapreplace(heap, item)

    def _base_payload(c: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": _norm_str(c.get("id")),
            "pool": _norm_str(c.get("pool")) or "unknown",
            "title": _truncate_chars(c.get("title"), 160),
            "authors_preview": _author_preview(c.get("authors"), max_chars=200),
            "venue": _truncate_chars(c.get("venue"), 120),
            "doi": _truncate_chars(c.get("doi"), 120),
            "year": _safe_int(c.get("year")),
            "citations": int(c.get("citations") or 0),
        }

    if candidates_path.exists():
        for c in _iter_jsonl_dicts(candidates_path):
            candidates_seen += 1
            pool_counts[_norm_str(c.get("pool")) or "unknown"] += 1
            if _norm_str(c.get("doi")):
                doi_present += 1

            title = _norm_str(c.get("title"))
            abstract = _norm_str(c.get("abstract"))
            text_for_hits = f"{title} {abstract}"

            anchor_hit = (_any_term_in_text(text_for_hits, anchors_all) if anchors_all else False)
            econ_hits = (_econ_hits_in_text(text_for_hits, econ_terms_all) if econ_terms_all else 0)

            citations = int(c.get("citations") or 0)
            cid = _norm_str(c.get("id"))

            base = _base_payload(c)
            _push_top(top_cited_heap, (citations, cid), base, 40)

            if not anchor_hit:
                _push_top(top_no_anchor_heap, (citations, cid), base, 40)

            if econ_hits > 0:
                _push_top(top_econ_heap, (econ_hits, citations, cid), base, 40)

    def _heap_to_desc(heap: list) -> List[Dict[str, Any]]:
        return [payload for _key, payload in sorted(heap, reverse=True)]

    top_cited = _heap_to_desc(top_cited_heap)
    top_no_anchor = _heap_to_desc(top_no_anchor_heap)
    top_econ = _heap_to_desc(top_econ_heap)

    pool_distribution = {
        "data": [
            {"pool": "with_abstract", "n": int(pool_counts.get("with_abstract", 0))},
            {"pool": "without_abstract", "n": int(pool_counts.get("without_abstract", 0))},
        ]
    }

    v2_e_candidates = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "counts": {
            "candidates_total": int(candidates_total or candidates_seen),
            "normalized_total": int(normalized_total),
            "duplicates_removed": int(max(0, int(normalized_total) - int(candidates_total or candidates_seen))),
            "merges": int(merges),
            "doi_present": int(doi_present),
        },
        "pool_distribution": pool_distribution,
        "top_cited": top_cited,
        "top_cited_no_anchors": top_no_anchor,
        "top_econ_hit": top_econ,
    }

    # -------------------------
    # Phase I — Rerank (LLM)
    # -------------------------
    phase_i_counts = (((metrics.get("stages") or {}).get("phase_i_rerank") or {}).get("counts") or {}) if isinstance(metrics, dict) else {}
    rerank_path = Path(run_ctx.artifacts.rerank_results_jsonl)

    llm_with: List[float] = []
    llm_without: List[float] = []
    insufficient_total = 0
    rerank_rows_for_scatter: List[Dict[str, Any]] = []

    if rerank_path.exists():
        for r in _iter_jsonl_dicts(rerank_path):
            pool = _norm_str(r.get("pool")) or "unknown"
            lane = _norm_str(r.get("lane")) or "unknown"
            rr = r.get("rerank") if isinstance(r.get("rerank"), dict) else {}
            llm = _safe_float(rr.get("llm_score_0_100"))
            if llm is None:
                continue
            if pool == "with_abstract":
                llm_with.append(float(llm))
            elif pool == "without_abstract":
                llm_without.append(float(llm))
            if bool(rr.get("insufficient_info")):
                insufficient_total += 1
            rerank_rows_for_scatter.append({"id": _norm_str(r.get("id")), "lane": lane, "pool": pool, "llm_score": float(llm)})

    llm_score_distribution = _hist_uniform_two_pools(values_with=llm_with, values_without=llm_without, bins=20, lo=0.0, hi=100.0, round_edges=0)

    v2_i_rerank = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "kpis": {
            "model": (_norm_str(phase_i_counts.get("model_used") or phase_i_counts.get("model")) or None),
            "tasks_total": int(phase_i_counts.get("tasks_total") or 0),
            "api_calls": int(phase_i_counts.get("api_calls") or 0),
            "failures": int(phase_i_counts.get("failures") or 0),
            "cost_usd_total": float(phase_i_counts.get("cost_usd_total") or 0.0),
            "insufficient_total": int(insufficient_total),
            "latency_s_p50": _safe_float(phase_i_counts.get("latency_s_p50")),
        },
        "llm_score_distribution": {"data": llm_score_distribution},
        "token_usage": {
            "input_tokens_total": int(phase_i_counts.get("tokens_in_total") or 0),
            "output_tokens_total": int(phase_i_counts.get("tokens_out_total") or 0),
        },
    }

    # -------------------------
    # Phase F — Scoring (embeddings + lane distributions)
    # -------------------------
    phase_f_counts = (((metrics.get("stages") or {}).get("phase_f") or {}).get("counts") or {}) if isinstance(metrics, dict) else {}
    emb_total = (((metrics.get("stages") or {}).get("phase_f") or {}).get("embeddings_total") or {}) if isinstance(metrics, dict) else {}

    kept = (((phase_f_counts.get("prune") or {}).get("kept")) or {}) if isinstance(phase_f_counts, dict) else {}
    pruning_kept_total = 0
    if isinstance(kept, dict):
        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                pruning_kept_total += int(((kept.get(lane) or {}).get(pool) or 0))

    scores_stage1_path = run_ctx.run_dir / "scores_stage1.jsonl"
    match_lane_with: List[float] = []
    match_lane_without: List[float] = []
    auth_lane_with: List[float] = []
    auth_lane_without: List[float] = []
    top500_heap: List[Tuple[float, str, Dict[str, Any]]] = []

    if scores_stage1_path.exists():
        for r in _iter_jsonl_dicts(scores_stage1_path):
            pool = _norm_str(r.get("pool")) or "unknown"
            match_lane = float(r.get("match_lane") or 0.0)
            auth_lane = float(r.get("authority_lane") or 0.0)
            if pool == "with_abstract":
                match_lane_with.append(match_lane)
                auth_lane_with.append(auth_lane)
            elif pool == "without_abstract":
                match_lane_without.append(match_lane)
                auth_lane_without.append(auth_lane)

            ml = float(r.get("match_lane") or 0.0)
            cid = _norm_str(r.get("id"))
            point = {
                "match": float(r.get("match_stage1") or 0.0),
                "authority": float(r.get("authority") or 0.0),
                "pool": pool,
            }
            if cid:
                if len(top500_heap) < 500:
                    heapq.heappush(top500_heap, (ml, cid, point))
                else:
                    if (ml, cid) > (top500_heap[0][0], top500_heap[0][1]):
                        heapq.heapreplace(top500_heap, (ml, cid, point))

    match_lane_distribution = _hist_uniform_two_pools(values_with=match_lane_with, values_without=match_lane_without, bins=30, lo=0.0, hi=1.0)
    auth_lane_distribution = _hist_uniform_two_pools(values_with=auth_lane_with, values_without=auth_lane_without, bins=30, lo=0.0, hi=1.0)
    match_vs_authority_top500 = [p for _ml, _cid, p in sorted(top500_heap, reverse=True)]

    shortlists_path = run_ctx.run_dir / "shortlists_stage1.json"
    shortlists_obj = read_json(shortlists_path) if shortlists_path.exists() else {}
    shortlist_ids: Dict[Tuple[str, str], List[str]] = {}
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = list(((shortlists_obj.get(lane) or {}).get(pool) or [])) if isinstance(shortlists_obj, dict) else []
            shortlist_ids[(lane, pool)] = [str(x) for x in ids if str(x or "").strip()][:20]

    want_ids = set([cid for ids in shortlist_ids.values() for cid in ids])
    cand_meta_by_id: Dict[str, Dict[str, Any]] = {}
    if want_ids and candidates_path.exists():
        for c in _iter_jsonl_dicts(candidates_path):
            cid = _norm_str(c.get("id"))
            if cid in want_ids:
                cand_meta_by_id[cid] = c
                if len(cand_meta_by_id) >= len(want_ids):
                    break

    def _anchor_hit_meta(c: Dict[str, Any]) -> bool:
        if not anchors_all:
            return False
        title = _norm_str(c.get("title"))
        venue = _norm_str(c.get("venue"))
        year = _norm_str(c.get("year"))
        return _any_term_in_text(f"{title} {venue} {year}", anchors_all)

    anchor_rows: List[Dict[str, Any]] = []
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = shortlist_ids.get((lane, pool), []) or []
            tot = int(len(ids))
            hits = 0
            for cid in ids:
                c = cand_meta_by_id.get(cid) or {}
                if _anchor_hit_meta(c):
                    hits += 1
            pct = (0.0 if tot <= 0 else (100.0 * float(hits) / float(tot)))
            anchor_rows.append({"lane": lane, "pool": pool, "hit": int(hits), "total": int(tot), "pct": float(pct)})

    v2_f_scoring = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "kpis": {
            "stage2_candidates": int(phase_f_counts.get("stage2_candidates") or 0),
            "facets_used": int(phase_f_counts.get("facets") or facets_count),
            "cost_usd": float(emb_total.get("cost_usd_est") or 0.0),
            "stage2_scored": int(phase_f_counts.get("stage2_scored") or 0),
            "pruning_kept_total": int(pruning_kept_total),
        },
        "anchor_hit_rate_top20": anchor_rows,
        "authority_lane_distribution": {"data": auth_lane_distribution},
        "match_lane_distribution": {"data": match_lane_distribution},
    }

    # -------------------------
    # Final score map + rankings (for report plots)
    # -------------------------
    scores_final_path = run_ctx.run_dir / "scores_final.jsonl"
    scores_by_id: Dict[str, Dict[str, Any]] = {}
    if scores_final_path.exists():
        for r in _iter_jsonl_dicts(scores_final_path):
            cid = _norm_str(r.get("id"))
            if not cid:
                continue
            sc = r.get("scores") if isinstance(r.get("scores"), dict) else {}
            scores_by_id[cid] = {
                "match_lane": _safe_float(sc.get("match_lane")),
                "authority_lane": _safe_float(sc.get("authority_lane")),
            }

    rankings_i_path = run_ctx.run_dir / "rankings_stagei.json"
    rankings_g_path = run_ctx.run_dir / "rankings_stageg.json"
    rankings_path = rankings_i_path if rankings_i_path.exists() else rankings_g_path
    rankings_obj = read_json(rankings_path) if rankings_path.exists() else {}
    rankings = rankings_obj.get("rankings") if isinstance(rankings_obj, dict) else {}

    def _lane_score(cid: str, lane: str) -> Optional[float]:
        r = scores_by_id.get(str(cid)) or {}
        if lane == "authority":
            return _safe_float(r.get("authority_lane"))
        return _safe_float(r.get("match_lane"))

    def _rank_series(lane: str, pool: str) -> List[Dict[str, Any]]:
        ids = list((((rankings.get(lane) or {}).get(pool)) or [])) if isinstance(rankings, dict) else []
        out: List[Dict[str, Any]] = []
        for rank, cid in enumerate(ids[:200], start=1):
            sc = _lane_score(str(cid), lane)
            if sc is None:
                continue
            out.append({"rank": int(rank), "lane_score": float(sc)})
        return out

    lane_score_by_rank_top200 = {
        "match_with": _rank_series("match", "with_abstract"),
        "match_without": _rank_series("match", "without_abstract"),
        "authority_with": _rank_series("authority", "with_abstract"),
        "authority_without": _rank_series("authority", "without_abstract"),
    }

    # -------------------------
    # Output-derived report plots (ranked IDs)
    # -------------------------
    output_path = Path(run_ctx.artifacts.output_json)
    output_obj = read_json(output_path) if output_path.exists() else {}
    top = output_obj.get("top") if isinstance(output_obj, dict) else {}
    if not isinstance(top, dict):
        top = {}

    year_counts: Dict[int, Dict[str, int]] = defaultdict(lambda: {"with_abstract": 0, "without_abstract": 0})
    citations_log_vals: Dict[str, List[float]] = {"with_abstract": [], "without_abstract": []}
    tag_count_freq: Dict[str, Counter] = {"with_abstract": Counter(), "without_abstract": Counter()}
    facet_freq: Counter = Counter()
    facet_label_by_id: Dict[str, str] = {}

    for lane in ["match", "authority"]:
        lane_obj = top.get(lane) if isinstance(top, dict) else None
        if not isinstance(lane_obj, dict):
            continue
        for pool in ["with_abstract", "without_abstract"]:
            cards = list((lane_obj.get(pool) or []))
            for c in cards:
                if not isinstance(c, dict):
                    continue

                y = _safe_int(c.get("year"))
                if y is not None and 0 < int(y) < 3000:
                    year_counts[int(y)][pool] += 1

                cites = _safe_int(c.get("citations"))
                if cites is not None and int(cites) >= 0:
                    citations_log_vals[pool].append(float(math.log10(1.0 + float(int(cites)))))

                tags = list(c.get("coverage_tags") or []) if isinstance(c.get("coverage_tags"), list) else []
                n_tags = int(len(tags))
                bucket = "30+" if n_tags >= 30 else str(int(n_tags))
                tag_count_freq[pool][bucket] += 1
                for t in tags:
                    if not isinstance(t, dict):
                        continue
                    fid = _norm_str(t.get("facet_id"))
                    if not fid:
                        continue
                    facet_freq[fid] += 1
                    lbl = _norm_str(t.get("facet_label_en")) or _norm_str(t.get("facet_label_de")) or fid
                    if fid not in facet_label_by_id:
                        facet_label_by_id[fid] = lbl

    publication_year_data = [
        {
            "year": int(y),
            "with_abstract": int(year_counts[y]["with_abstract"]),
            "without_abstract": int(year_counts[y]["without_abstract"]),
        }
        for y in sorted(year_counts.keys())
    ]

    cite_with = citations_log_vals.get("with_abstract") or []
    cite_without = citations_log_vals.get("without_abstract") or []
    cite_hi = max(cite_with + cite_without) if (cite_with or cite_without) else 1.0
    citations_log10_data = _hist_uniform_two_pools(
        values_with=cite_with,
        values_without=cite_without,
        bins=25,
        lo=0.0,
        hi=float(max(1.0, cite_hi)),
        round_edges=3,
    )

    buckets = [str(i) for i in range(0, 31)] + ["30+"]
    coverage_tags_count_data = [
        {
            "tag_count": b,
            "with_abstract": int(tag_count_freq["with_abstract"].get(b, 0)),
            "without_abstract": int(tag_count_freq["without_abstract"].get(b, 0)),
        }
        for b in buckets
    ]

    coverage_tags_top_data = [
        {"facet_id": str(fid), "label": str(facet_label_by_id.get(str(fid), str(fid))), "count": int(n)}
        for fid, n in facet_freq.most_common(15)
    ]

    llm_score_vs_lane_score_data: List[Dict[str, Any]] = []
    for row in rerank_rows_for_scatter[:160]:
        cid = str(row.get("id") or "").strip()
        lane = str(row.get("lane") or "").strip()
        pool = str(row.get("pool") or "").strip()
        llm_score = _safe_float(row.get("llm_score"))
        if llm_score is None:
            continue
        lane_score = _lane_score(cid, lane)
        if lane_score is None:
            continue
        llm_score_vs_lane_score_data.append(
            {
                "lane": lane,
                "pool": pool,
                "lane_score": float(lane_score),
                "llm_score": float(llm_score),
            }
        )

    # -------------------------
    # Report stage tables (durations + costs)
    # -------------------------
    stages_obj = metrics.get("stages") if isinstance(metrics, dict) else {}
    if not isinstance(stages_obj, dict):
        stages_obj = {}

    def _dur(stage_key: str) -> Optional[float]:
        st = stages_obj.get(stage_key)
        if not isinstance(st, dict):
            return None
        d = st.get("last_duration_s")
        if isinstance(d, (int, float)) and math.isfinite(float(d)):
            return float(d)
        return None

    phase_f_stage_keys = [
        "phase_f_facet_embeddings",
        "phase_f_metadata_embeddings",
        "phase_f_s2_recommendations",
        "phase_f_stage1_scoring",
        "phase_f_chunk_embeddings",
        "phase_f_stage2_scoring",
    ]
    scoring_dur = sum([_dur(k) or 0.0 for k in phase_f_stage_keys]) if any(_dur(k) is not None for k in phase_f_stage_keys) else None

    durations_rows: List[Dict[str, Any]] = [
        {"key": "init", "label": "Init", "duration_s": _dur("init")},
        {"key": "phase_b_query_planner", "label": "Query Planner (LLM)", "duration_s": _dur("phase_b_query_planner")},
        {"key": "phase_c_openalex_query_builder", "label": "OpenAlex Query Builder", "duration_s": _dur("phase_c_openalex_query_builder")},
        {"key": "phase_c_s2_query_builder", "label": "S2 Query Builder", "duration_s": _dur("phase_c_s2_query_builder")},
        {"key": "phase_d_openalex_retrieval", "label": "OpenAlex Retrieval", "duration_s": _dur("phase_d_openalex_retrieval")},
        {"key": "phase_d_semanticscholar_retrieval", "label": "S2 Retrieval", "duration_s": _dur("phase_d_semanticscholar_retrieval")},
        {"key": "phase_e_candidates", "label": "Candidates", "duration_s": _dur("phase_e_candidates")},
        {"key": "phase_f", "label": "Scoring + Embeddings", "duration_s": (None if scoring_dur is None else float(scoring_dur))},
        {"key": "phase_g", "label": "Final Scores", "duration_s": _dur("phase_g")},
        {"key": "phase_h_coverage_tags", "label": "Coverage Tags", "duration_s": _dur("phase_h_coverage_tags")},
        {"key": "phase_i_rerank", "label": "Rerank (LLM)", "duration_s": _dur("phase_i_rerank")},
        {"key": "phase_k_output", "label": "Output", "duration_s": _dur("phase_k_output")},
    ]

    dur_total = sum([float(r["duration_s"]) for r in durations_rows if isinstance(r.get("duration_s"), (int, float)) and math.isfinite(float(r["duration_s"]))])
    durations_rows.append({"key": "total", "label": "Gesamt", "duration_s": float(dur_total) if dur_total > 0 else None})

    stage_costs = costs.get("stage_costs") if isinstance(costs, dict) else {}
    if not isinstance(stage_costs, dict):
        stage_costs = {}

    def _cost_for_stage(stage_key: str) -> Dict[str, Any]:
        rec = stage_costs.get(stage_key)
        if not isinstance(rec, dict):
            return {"cost_usd": 0.0, "requests": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        return {
            "cost_usd": float(rec.get("cost_usd") or 0.0),
            "requests": int(rec.get("requests") or 0),
            "input_tokens": int(rec.get("input_tokens") or 0),
            "cached_input_tokens": int(rec.get("cached_input_tokens") or 0),
            "output_tokens": int(rec.get("output_tokens") or 0),
        }

    def _sum_costs(keys: List[str]) -> Dict[str, Any]:
        out = {"cost_usd": 0.0, "requests": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
        for k in keys:
            r = _cost_for_stage(k)
            out["cost_usd"] += float(r["cost_usd"])
            out["requests"] += int(r["requests"])
            out["input_tokens"] += int(r["input_tokens"])
            out["cached_input_tokens"] += int(r["cached_input_tokens"])
            out["output_tokens"] += int(r["output_tokens"])
        return out

    scoring_keys = [k for k in ["phase_f_facet_embeddings", "phase_f_metadata_embeddings", "phase_f_chunk_embeddings"] if k in stage_costs]
    scoring_cost = _sum_costs(scoring_keys)

    costs_rows: List[Dict[str, Any]] = [
        {"key": "phase_b_query_planner", "label": "Query Planner (LLM)", **_cost_for_stage("phase_b_query_planner")},
        {"key": "phase_c_openalex_query_builder", "label": "OpenAlex Query Builder", **_cost_for_stage("phase_c_openalex_query_builder")},
        {"key": "phase_c_s2_query_builder", "label": "S2 Query Builder", **_cost_for_stage("phase_c_s2_query_builder")},
        {"key": "phase_f", "label": "Scoring + Embeddings", **scoring_cost},
        {"key": "phase_g", "label": "Final Scores", **_cost_for_stage("phase_g")},
        {"key": "phase_h_coverage_tags", "label": "Coverage Tags", **_cost_for_stage("phase_h_coverage_tags")},
        {"key": "phase_i_rerank", "label": "Rerank (LLM)", **_cost_for_stage("phase_i_rerank")},
        {"key": "phase_k_output", "label": "Output", **_cost_for_stage("phase_k_output")},
    ]

    included_stage_keys = set(
        [
            "phase_b_query_planner",
            "phase_c_openalex_query_builder",
            "phase_c_s2_query_builder",
            "phase_g",
            "phase_h_coverage_tags",
            "phase_i_rerank",
            "phase_k_output",
            *scoring_keys,
        ]
    )
    other_keys = [k for k in stage_costs.keys() if str(k) not in included_stage_keys]
    other_keys.sort()
    if other_keys:
        costs_rows.append({"key": "other", "label": "Sonstiges", **_sum_costs(other_keys)})

    total_row = {"cost_usd": 0.0, "requests": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    for row in costs_rows:
        total_row["cost_usd"] += float(row.get("cost_usd") or 0.0)
        total_row["requests"] += int(row.get("requests") or 0)
        total_row["input_tokens"] += int(row.get("input_tokens") or 0)
        total_row["cached_input_tokens"] += int(row.get("cached_input_tokens") or 0)
        total_row["output_tokens"] += int(row.get("output_tokens") or 0)

    costs_rows.append({"key": "total", "label": "Gesamt", **total_row})

    # -------------------------
    # v2_report (Bericht) — self-contained report tab data
    # -------------------------
    records_openalex = int(provider_totals["openalex"]["records_total"])
    records_s2 = int(provider_totals["semanticscholar"]["records_total"])

    v2_models = {
        "planner": (_norm_str(effective_settings.get("openai_model_planner")) or None),
        "openalex_queries": (_norm_str(effective_settings.get("openai_model_openalex_query_builder")) or None),
        "s2_queries": (_norm_str(effective_settings.get("openai_model_s2_query_builder")) or None),
        "rerank": (_norm_str(effective_settings.get("openai_model_rerank")) or None),
        "embedding": (_norm_str(effective_settings.get("embedding_model")) or None),
    }

    v2_report = {
        "telemetry_schema_version": TELEMETRY_SCHEMA_VERSION,
        "kpis": {
            "seconds_total": (float(dur_total) if dur_total > 0 else None),
            "total_cost_usd": float(costs.get("total_cost_usd") or 0.0),
            "records_total": int(records_openalex + records_s2),
            "records_openalex": int(records_openalex),
            "records_semanticscholar": int(records_s2),
            "candidates_total": int(candidates_total or candidates_seen),
            "facets_count": int(facets_count),
            "queries_total": int(len(openalex_queries_raw) + len(s2_queries_raw)),
            "queries_openalex": int(len(openalex_queries_raw)),
            "queries_semanticscholar": int(len(s2_queries_raw)),
        },
        "stage_tables": {"durations": durations_rows, "costs": costs_rows},
        "models": v2_models,
        "plots": {
            "publication_year": {"data": publication_year_data},
            "citations_log10": {"data": citations_log10_data},
            "coverage_tags_count": {"data": coverage_tags_count_data},
            "llm_score_distribution": {"data": llm_score_distribution},
            "llm_score_vs_lane_score": {"data": llm_score_vs_lane_score_data},
            "match_lane_distribution": {"data": match_lane_distribution},
            "match_vs_authority_top500": {"data": match_vs_authority_top500},
            "lane_score_by_rank_top200": lane_score_by_rank_top200,
            "coverage_tags_top": {"data": coverage_tags_top_data},
        },
    }

    return {
        "v2_report": v2_report,
        "v2_b_plan": v2_b_plan,
        "v2_c_queries": v2_c_queries,
        "v2_d_retrieval": v2_d_retrieval,
        "v2_e_candidates": v2_e_candidates,
        "v2_f_scoring": v2_f_scoring,
        "v2_i_rerank": v2_i_rerank,
    }
