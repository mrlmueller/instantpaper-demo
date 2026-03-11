from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


ROOT = Path(__file__).resolve().parent
REPO_ROOT = ROOT.parent.parent
RUNS_DIR = REPO_ROOT / "sources-v2" / "runs"
OUTPUT_DIR = ROOT / "probe_outputs"

USER_AGENT = "instantpaper-phase-c-query-replay/1.0"
OPENALEX_URL = "https://api.openalex.org/works"
S2_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

OPENALEX_SELECT = "id,display_name,publication_year,cited_by_count,language"
S2_FIELDS = "paperId,title,year,venue"


def _now_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _load_env() -> None:
    try:
        from dotenv import load_dotenv  # type: ignore
    except Exception:
        return

    root_env = REPO_ROOT / ".env"
    if root_env.exists():
        load_dotenv(root_env, override=True)
    fastapi_env = REPO_ROOT / "fastapi" / ".env"
    if fastapi_env.exists():
        load_dotenv(fastapi_env, override=False)


def _latest_run_dir() -> Path:
    runs = [p for p in RUNS_DIR.iterdir() if p.is_dir()]
    if not runs:
        raise FileNotFoundError(f"No run directories found under {RUNS_DIR}")
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs[0]


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _request_json(
    session: requests.Session,
    *,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 60.0,
    max_attempts: int = 4,
    backoff_initial_s: float = 2.0,
    sleep_s: float = 0.0,
) -> Dict[str, Any]:
    last_error: Optional[str] = None
    for attempt in range(1, max_attempts + 1):
        started = time.perf_counter()
        try:
            response = session.request(method=method, url=url, params=params, headers=headers, timeout=timeout_s)
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
            text_preview = response.text[:500]
            try:
                payload = response.json()
            except Exception:
                payload = {"_non_json_body": text_preview}

            out = {
                "status_code": response.status_code,
                "ok": response.ok,
                "elapsed_ms": elapsed_ms,
                "final_url": response.url,
                "headers": dict(response.headers),
                "json": payload,
                "text_preview": text_preview,
            }
            if response.ok:
                if sleep_s > 0:
                    time.sleep(sleep_s)
                return out

            last_error = f"HTTP {response.status_code}"
            if response.status_code not in {429, 500, 502, 503, 504} or attempt >= max_attempts:
                if sleep_s > 0:
                    time.sleep(sleep_s)
                return out
        except Exception as exc:
            elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
            last_error = repr(exc)
            out = {
                "status_code": None,
                "ok": False,
                "elapsed_ms": elapsed_ms,
                "final_url": url,
                "headers": {},
                "json": {},
                "text_preview": "",
                "exception": repr(exc),
            }
            if attempt >= max_attempts:
                if sleep_s > 0:
                    time.sleep(sleep_s)
                return out

        time.sleep(min(backoff_initial_s * (2 ** (attempt - 1)), 30.0))

    return {
        "status_code": None,
        "ok": False,
        "elapsed_ms": 0.0,
        "final_url": url,
        "headers": {},
        "json": {},
        "text_preview": "",
        "exception": last_error or "unknown",
    }


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip().lower()


def _any_term_in_text(text: str, terms: Iterable[str]) -> bool:
    hay = _normalize_text(text)
    if not hay:
        return False
    for term in terms:
        needle = _normalize_text(str(term or ""))
        if needle and needle in hay:
            return True
    return False


def _sample_title_metrics(
    titles: List[str],
    *,
    anchors: List[str],
    core_terms: List[str],
) -> Dict[str, Any]:
    total = len(titles)
    anchor_hits = sum(1 for title in titles if _any_term_in_text(title, anchors))
    core_hits = sum(1 for title in titles if _any_term_in_text(title, core_terms))
    return {
        "sample_titles_n": total,
        "sample_title_anchor_hits": anchor_hits,
        "sample_title_anchor_rate": (float(anchor_hits) / float(max(1, total))) if total else None,
        "sample_title_core_hits": core_hits,
        "sample_title_core_rate": (float(core_hits) / float(max(1, total))) if total else None,
    }


def _extract_openalex_titles(payload: Dict[str, Any]) -> List[str]:
    rows = (payload.get("json") or {}).get("results") or []
    titles: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("display_name") or "").strip()
        if title:
            titles.append(title)
    return titles


def _extract_s2_titles(payload: Dict[str, Any]) -> List[str]:
    rows = (payload.get("json") or {}).get("data") or []
    titles: List[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if title:
            titles.append(title)
    return titles


def _count_s2_required_groups(qs: str) -> int:
    return len(re.findall(r"(?:^|\s)\+(?=(?:\(|\"|[\w]))", str(qs or ""), flags=re.UNICODE))


def _count_s2_negatives(qs: str) -> int:
    return len(re.findall(r"(?:^|\s)-\s*(?:(?:\"[^\"]+\")|[^\s()|]+)", str(qs or ""), flags=re.UNICODE))


def _has_s2_advanced_syntax(qs: str) -> bool:
    s = str(qs or "")
    return (
        "*" in s
        or "?" in s
        or bool(re.search(r"\w+~\d+", s))
        or bool(re.search(r'"[^"]+"\s*~\s*\d+', s))
    )


def _strip_s2_negatives(qs: str) -> str:
    s = re.sub(r"(?:^|\s)-\s*(?:\"[^\"]+\"|[^\s()|]+)", " ", str(qs or ""), flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()


def _openalex_params(
    query: Dict[str, Any],
    *,
    sample_size: int,
    alt_surface: Optional[str],
) -> Dict[str, Any]:
    search_field = str(alt_surface or query.get("search_field") or "title_and_abstract.search")
    query_string = str(query.get("query_string") or "")
    filters = str(query.get("filters") or "").strip().strip(",")
    params: Dict[str, Any] = {
        "per-page": int(sample_size),
        "select": OPENALEX_SELECT,
    }
    sort = query.get("sort")
    if sort:
        params["sort"] = sort

    api_key = (os.getenv("OPENALEX_API_KEY") or "").strip()
    mailto = (os.getenv("OPENALEX_EMAIL") or os.getenv("OPENALEX_MAILTO") or "").strip()
    if api_key:
        params["api_key"] = api_key
    if mailto:
        params["mailto"] = mailto

    if search_field == "search":
        params["search"] = query_string
        if filters:
            params["filter"] = filters
        return params

    search_filter = f"{search_field}:{query_string}"
    params["filter"] = f"{filters},{search_filter}" if filters else search_filter
    return params


def _probe_openalex(
    session: requests.Session,
    *,
    query: Dict[str, Any],
    sample_size: int,
    anchors: List[str],
    core_terms: List[str],
    alt_surface: Optional[str] = None,
    sleep_s: float,
) -> Dict[str, Any]:
    payload = _request_json(
        session,
        method="GET",
        url=OPENALEX_URL,
        params=_openalex_params(query, sample_size=sample_size, alt_surface=alt_surface),
        headers=None,
        timeout_s=90.0,
        max_attempts=5,
        sleep_s=sleep_s,
    )
    titles = _extract_openalex_titles(payload)
    meta = (payload.get("json") or {}).get("meta") or {}
    out = {
        "surface": alt_surface or query.get("search_field"),
        "count": meta.get("count"),
        "titles": titles,
        "db_response_time_ms": meta.get("db_response_time_ms"),
        "sample": _sample_title_metrics(titles, anchors=anchors, core_terms=core_terms),
        "http": {
            "status_code": payload.get("status_code"),
            "ok": payload.get("ok"),
            "elapsed_ms": payload.get("elapsed_ms"),
            "final_url": payload.get("final_url"),
        },
    }
    if not payload.get("ok"):
        out["error"] = payload.get("text_preview") or payload.get("exception")
    return out


def _probe_s2_endpoint(
    session: requests.Session,
    *,
    url: str,
    query_string: str,
    sample_size: int,
    anchors: List[str],
    core_terms: List[str],
    sleep_s: float,
) -> Dict[str, Any]:
    payload = _request_json(
        session,
        method="GET",
        url=url,
        params={"query": query_string, "fields": S2_FIELDS, "limit": int(sample_size)},
        headers=None,
        timeout_s=90.0,
        max_attempts=5,
        sleep_s=sleep_s,
    )
    titles = _extract_s2_titles(payload)
    body = payload.get("json") or {}
    out = {
        "total": body.get("total"),
        "returned_n": len(body.get("data") or []),
        "token": body.get("token"),
        "next": body.get("next"),
        "titles": titles,
        "sample": _sample_title_metrics(titles, anchors=anchors, core_terms=core_terms),
        "http": {
            "status_code": payload.get("status_code"),
            "ok": payload.get("ok"),
            "elapsed_ms": payload.get("elapsed_ms"),
            "final_url": payload.get("final_url"),
        },
    }
    if not payload.get("ok"):
        out["error"] = payload.get("text_preview") or payload.get("exception")
    return out


def _list_terms(obj: Dict[str, Any], key: str, language: str) -> List[str]:
    sub = obj.get(key) or {}
    vals = sub.get(language) or []
    return [str(v).strip() for v in vals if str(v or "").strip()]


def _openalex_alt_surface(search_field: str) -> str:
    return "search" if search_field != "search" else "title_and_abstract.search"


def _pct(n: int, d: int) -> str:
    if d <= 0:
        return "n/a"
    return f"{(100.0 * float(n) / float(d)):.1f}%"


def _summarize_openalex(probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = [int(p.get("current", {}).get("count") or 0) for p in probes]
    zeros = sum(1 for c in counts if c == 0)
    alt_pairs = []
    for p in probes:
        cur = p.get("current", {}).get("count")
        alt = p.get("alt_surface_probe", {}).get("count")
        if isinstance(cur, int) and isinstance(alt, int) and cur > 0:
            alt_pairs.append(float(alt) / float(cur))
    return {
        "queries": len(probes),
        "zero_queries": zeros,
        "zero_rate": (float(zeros) / float(max(1, len(probes)))) if probes else 0.0,
        "count_min": min(counts) if counts else None,
        "count_median": statistics.median(counts) if counts else None,
        "count_max": max(counts) if counts else None,
        "alt_surface_ratio_median": statistics.median(alt_pairs) if alt_pairs else None,
    }


def _summarize_s2(probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    bulk_totals = [int(p.get("bulk", {}).get("total") or 0) for p in probes]
    search_totals = [int(p.get("search", {}).get("total") or 0) for p in probes if p.get("search", {}).get("total") is not None]
    zeros = sum(1 for c in bulk_totals if c == 0)
    neg_lifts: List[float] = []
    for p in probes:
        cur = p.get("bulk", {}).get("total")
        no_neg = p.get("bulk_without_negatives", {}).get("total")
        if isinstance(cur, int) and isinstance(no_neg, int) and cur > 0:
            neg_lifts.append(float(no_neg) / float(cur))
    return {
        "queries": len(probes),
        "bulk_zero_queries": zeros,
        "bulk_zero_rate": (float(zeros) / float(max(1, len(probes)))) if probes else 0.0,
        "bulk_total_min": min(bulk_totals) if bulk_totals else None,
        "bulk_total_median": statistics.median(bulk_totals) if bulk_totals else None,
        "bulk_total_max": max(bulk_totals) if bulk_totals else None,
        "search_total_median": statistics.median(search_totals) if search_totals else None,
        "negative_lift_median": statistics.median(neg_lifts) if neg_lifts else None,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay actual Phase C query outputs against live provider APIs.")
    parser.add_argument("--run-dir", type=Path, default=None, help="Run directory containing query artifacts. Defaults to latest run.")
    parser.add_argument("--output", type=Path, default=None, help="Optional JSON output path.")
    parser.add_argument("--openalex-sample-size", type=int, default=8)
    parser.add_argument("--s2-sample-size", type=int, default=10)
    parser.add_argument("--provider", choices=["all", "openalex", "semanticscholar"], default="all")
    parser.add_argument("--sleep-openalex", type=float, default=0.35)
    parser.add_argument("--sleep-s2", type=float, default=0.75)
    args = parser.parse_args()

    _load_env()
    run_dir = (args.run_dir or _latest_run_dir()).resolve()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (OUTPUT_DIR / f"phase_c_query_replay_{run_dir.name}_{_now_slug()}.json")

    plan = _read_json(run_dir / "query_plan.json")
    openalex_queries = _read_json(run_dir / "openalex_queries.json").get("openalex_queries") or []
    s2_queries = _read_json(run_dir / "semanticscholar_queries.json").get("s2_bulk_queries") or []

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
        "inputs": {
            "openalex_queries_path": str(run_dir / "openalex_queries.json"),
            "semanticscholar_queries_path": str(run_dir / "semanticscholar_queries.json"),
        },
        "method": {
            "openalex_current_vs_alt_surface": True,
            "s2_bulk_vs_search": True,
            "s2_negative_ablation": True,
        },
        "openalex": {"queries": []},
        "semanticscholar": {"queries": []},
    }

    if args.provider in {"all", "openalex"}:
        for idx, query in enumerate(openalex_queries, start=1):
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

    if args.provider in {"all", "semanticscholar"}:
        for idx, query in enumerate(s2_queries, start=1):
            language = str(query.get("language") or "")
            anchors = _list_terms(plan, "primary_context_anchors", language)
            core_terms = _list_terms(plan, "core_object_terms", language)
            qs = str(query.get("query_string") or "")
            bulk = _probe_s2_endpoint(
                session_s2,
                url=S2_BULK_URL,
                query_string=qs,
                sample_size=args.s2_sample_size,
                anchors=anchors,
                core_terms=core_terms,
                sleep_s=args.sleep_s2,
            )
            search = _probe_s2_endpoint(
                session_s2,
                url=S2_SEARCH_URL,
                query_string=qs,
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
            }
            bulk_total = bulk.get("total")
            search_total = search.get("total")
            if isinstance(bulk_total, int) and bulk_total > 0 and isinstance(search_total, int):
                record["search_over_bulk_ratio"] = float(search_total) / float(bulk_total)

            if record["negative_count"] > 0:
                qs_no_neg = _strip_s2_negatives(qs)
                ablated_bulk = _probe_s2_endpoint(
                    session_s2,
                    url=S2_BULK_URL,
                    query_string=qs_no_neg,
                    sample_size=args.s2_sample_size,
                    anchors=anchors,
                    core_terms=core_terms,
                    sleep_s=args.sleep_s2,
                )
                record["query_string_without_negatives"] = qs_no_neg
                record["bulk_without_negatives"] = ablated_bulk
                no_neg_total = ablated_bulk.get("total")
                if isinstance(bulk_total, int) and bulk_total > 0 and isinstance(no_neg_total, int):
                    record["no_negative_over_current_ratio"] = float(no_neg_total) / float(bulk_total)

            output["semanticscholar"]["queries"].append(record)

        output["semanticscholar"]["summary"] = _summarize_s2(output["semanticscholar"]["queries"])

    output_path.write_text(json.dumps(_sanitize(output), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
