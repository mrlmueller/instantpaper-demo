from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "probe_outputs"
USER_AGENT = "instantpaper-phase-c-probe/1.0"

OPENALEX_URL = "https://api.openalex.org/works"
S2_BULK_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"
S2_SEARCH_URL = "https://api.semanticscholar.org/graph/v1/paper/search"

OPENALEX_SELECT = "id,display_name,publication_year,cited_by_count,language"
S2_FIELDS = "paperId,title,year,venue"


@dataclass
class Experiment:
    provider: str
    endpoint: str
    name: str
    description: str
    params: Dict[str, Any]


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


def _request_json(
    session: requests.Session,
    *,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout_s: float = 60.0,
) -> Dict[str, Any]:
    started = time.perf_counter()
    response = session.request(method=method, url=url, params=params, headers=headers, timeout=timeout_s)
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 1)
    payload: Dict[str, Any]
    text_preview = response.text[:400]
    try:
        payload = response.json()
    except Exception:
        payload = {"_non_json_body": text_preview}
    return {
        "status_code": response.status_code,
        "ok": response.ok,
        "elapsed_ms": elapsed_ms,
        "final_url": response.url,
        "headers": dict(response.headers),
        "json": payload,
        "text_preview": text_preview,
    }


def build_openalex_experiments(limit: int) -> List[Experiment]:
    base_filter_en = "is_paratext:false,is_retracted:false,language:en"
    base_filter_de = "is_paratext:false,is_retracted:false,language:de"
    return [
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_simple_en",
            description="Top-level search with a direct English object phrase.",
            params={"search": "online reviews", "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_titleabs_simple_en",
            description="Legacy title_and_abstract.search filter with the same direct English object phrase.",
            params={"filter": f"{base_filter_en},title_and_abstract.search:online reviews", "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_phrase_boolean_en",
            description="Top-level search using quoted phrases plus AND.",
            params={"search": '("online reviews" AND "proxy operationalization")', "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_phrase_and_bias_en",
            description="Top-level search using a more realistic conjunction for the chapter object plus bias.",
            params={"search": '("online reviews" AND "selection bias")', "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_titleabs_phrase_boolean_en",
            description="title_and_abstract.search using the same quoted-phrase AND query.",
            params={"filter": f'{base_filter_en},title_and_abstract.search:("online reviews" AND "proxy operationalization")', "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_titleabs_phrase_and_bias_en",
            description="title_and_abstract.search using a more realistic conjunction for the chapter object plus bias.",
            params={"filter": f'{base_filter_en},title_and_abstract.search:("online reviews" AND "selection bias")', "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_wildcard_en",
            description="Top-level wildcard search to test current documented wildcard behavior.",
            params={"search": "review*", "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_fuzzy_en",
            description="Top-level fuzzy search to test current documented fuzzy behavior.",
            params={"search": "operationalization~1", "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_proximity_en",
            description="Top-level proximity search to test current documented proximity behavior.",
            params={"search": '"online reviews"~2', "filter": base_filter_en, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_direct_de",
            description="Top-level search with a direct German object phrase.",
            params={"search": "Onlinebewertungen", "filter": base_filter_de, "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_titleabs_direct_de",
            description="title_and_abstract.search with a direct German object phrase.",
            params={"filter": f"{base_filter_de},title_and_abstract.search:Onlinebewertungen", "per-page": limit, "select": OPENALEX_SELECT},
        ),
        Experiment(
            provider="openalex",
            endpoint="works",
            name="oa_search_bilingual_core",
            description="Top-level bilingual OR query to test mixed-language recall.",
            params={"search": '("online reviews" OR "Onlinebewertungen")', "filter": "is_paratext:false,is_retracted:false", "per-page": limit, "select": OPENALEX_SELECT},
        ),
    ]


def build_s2_experiments(limit: int) -> List[Experiment]:
    return [
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_direct_object_en_bulk",
            description="Bulk search with direct English review anchors plus proxy/validity terms.",
            params={
                "query": '+("online reviews" | "user reviews" | "customer reviews") +("proxy operationalization" | "construct validity" | "selection bias")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_abstract_anchor_en_bulk",
            description="Bulk search with more abstract English anchors from the degraded run.",
            params={
                "query": '+("user generated content" | "consumer ratings") +("proxy variable" | "construct validity")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_bad_run_de_bulk",
            description="Bulk search using a German query pattern from the poor-yield run.",
            params={
                "query": '+("Nutzergenerierte Inhalte" | "Kundenfeedback" | "Konsumentenbewertungen") +("Onlinebewertung" | "Bewertungstext" | "Bewertungsmetadaten" | "Bewertungsscore" | "Sentimentklassifikation" | "Themenmodellierung" | "Wortvektoren" | "Proxyvariable" | "Proxy Operationalisierung" | "Selektionsbias")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_better_run_de_bulk",
            description="Bulk search using a German query pattern from the healthier run.",
            params={
                "query": '+("Onlinebewertungen" | "Nutzerbewertungen" | "Produktbewertungen") +("Textmining" | "Natural Language Processing" | "Sentimentanalyse" | "Themenmodellierung" | "Textklassifikation" | "Wortvektoren" | "Proxy Variable" | "Proxy Operationalisierung" | "Annotation" | "Intercoder Reliabilität")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_direct_de_simple_bulk",
            description="Bulk search with a simplified direct German object group and small German facet group.",
            params={
                "query": '+("Onlinebewertungen" | "Nutzerbewertungen" | "Produktbewertungen") +("Konstruktvalidität" | "Selektionsbias" | "Textmining")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_de_object_en_facet_bulk",
            description="Bulk search with German object terms and English facet terms to test mixed-language rescue.",
            params={
                "query": '+("Onlinebewertungen" | "Nutzerbewertungen" | "Produktbewertungen") +("construct validity" | "selection bias" | "text mining")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_bilingual_fallback_bulk",
            description="Bulk search with a bilingual core object group and English facet group.",
            params={
                "query": '+("online reviews" | "Onlinebewertungen") +("proxy operationalization" | "construct validity" | "selection bias")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_full_forms_bulk",
            description="Bulk search with full lexical forms for common method abbreviations.",
            params={
                "query": '+("online reviews") +("natural language processing" | "latent dirichlet allocation" | "user generated content")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_full_forms_limit_1_bulk",
            description="Same broad bulk query with limit=1 to test whether the bulk endpoint respects the limit parameter.",
            params={
                "query": '+("online reviews") +("natural language processing" | "latent dirichlet allocation" | "user generated content")',
                "fields": S2_FIELDS,
                "limit": 1,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_full_forms_limit_100_bulk",
            description="Same broad bulk query with limit=100 to compare against limit=1 and limit=10.",
            params={
                "query": '+("online reviews") +("natural language processing" | "latent dirichlet allocation" | "user generated content")',
                "fields": S2_FIELDS,
                "limit": 100,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_acronym_heavy_bulk",
            description="Bulk search with acronym-heavy method wording to test acronym sensitivity.",
            params={
                "query": '+("online reviews") +(NLP | LDA | UGC)',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_two_required_groups_bulk",
            description="Bulk search with two required groups only.",
            params={
                "query": '+("online reviews" | "user reviews") +("construct validity" | "selection bias" | "proxy operationalization")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_three_required_groups_bulk",
            description="Bulk search with a third required group to test over-constraint.",
            params={
                "query": '+("online reviews" | "user reviews") +("review platforms" | "review text") +("construct validity" | "selection bias" | "proxy operationalization")',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_atomic_negative_bulk",
            description="Bulk search with one atomic negative phrase.",
            params={
                "query": '+("online reviews" | "user reviews") +("construct validity" | "selection bias") -"peer review"',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="bulk",
            name="s2_non_atomic_negative_bulk",
            description="Bulk search with a longer negative phrase that the pipeline would currently reject.",
            params={
                "query": '+("online reviews" | "user reviews") +("construct validity" | "selection bias") -"systematic literature review"',
                "fields": S2_FIELDS,
                "limit": limit,
            },
        ),
        Experiment(
            provider="semanticscholar",
            endpoint="search",
            name="s2_direct_object_en_search",
            description="Standard search endpoint for the direct English object query, useful for total counts.",
            params={
                "query": '+("online reviews" | "user reviews" | "customer reviews") +("proxy operationalization" | "construct validity" | "selection bias")',
                "fields": S2_FIELDS,
                "limit": min(limit, 20),
            },
        ),
    ]


def run_openalex(session: requests.Session, exp: Experiment) -> Dict[str, Any]:
    params = dict(exp.params)
    email = (os.getenv("OPENALEX_EMAIL") or os.getenv("OPENALEX_MAILTO") or "").strip()
    api_key = (os.getenv("OPENALEX_API_KEY") or "").strip()
    if email:
        params["mailto"] = email
    if api_key:
        params["api_key"] = api_key

    response = _request_json(session, method="GET", url=OPENALEX_URL, params=params)
    payload = response["json"]
    results = payload.get("results") or []
    meta = payload.get("meta") or {}
    sample_titles = [
        {
            "title": item.get("display_name"),
            "year": item.get("publication_year"),
            "cited_by_count": item.get("cited_by_count"),
        }
        for item in results[:5]
        if isinstance(item, dict)
    ]
    return {
        "provider": exp.provider,
        "endpoint": exp.endpoint,
        "name": exp.name,
        "description": exp.description,
        "params": params,
        "status_code": response["status_code"],
        "ok": response["ok"],
        "elapsed_ms": response["elapsed_ms"],
        "final_url": response["final_url"],
        "meta_count": meta.get("count"),
        "returned_items": len(results),
        "sample_titles": sample_titles,
        "error": payload.get("error") if isinstance(payload, dict) else None,
        "text_preview": response["text_preview"],
    }


def run_s2(session: requests.Session, exp: Experiment) -> Dict[str, Any]:
    params = dict(exp.params)
    api_key = (os.getenv("SEMANTICSCHOLAR_API_KEY") or "").strip()
    headers = {"x-api-key": api_key} if api_key else None
    url = S2_BULK_URL if exp.endpoint == "bulk" else S2_SEARCH_URL
    response = _request_json(session, method="GET", url=url, params=params, headers=headers)
    payload = response["json"]
    data = payload.get("data") or []
    total = payload.get("total")
    token = payload.get("token") or payload.get("next")
    sample_titles = [
        {
            "title": item.get("title"),
            "year": item.get("year"),
            "venue": item.get("venue"),
        }
        for item in data[:5]
        if isinstance(item, dict)
    ]
    return {
        "provider": exp.provider,
        "endpoint": exp.endpoint,
        "name": exp.name,
        "description": exp.description,
        "params": params,
        "status_code": response["status_code"],
        "ok": response["ok"],
        "elapsed_ms": response["elapsed_ms"],
        "final_url": response["final_url"],
        "total": total,
        "returned_items": len(data),
        "has_next_page": bool(token),
        "sample_titles": sample_titles,
        "error": payload.get("error") if isinstance(payload, dict) else None,
        "text_preview": response["text_preview"],
    }


def print_summary(results: List[Dict[str, Any]]) -> None:
    print()
    print("Phase C provider probe summary")
    print("=" * 80)
    for item in results:
        count = item.get("meta_count")
        if count is None:
            count = item.get("total")
        returned = item.get("returned_items")
        extra = f"count={count}" if count is not None else f"returned={returned}"
        if item["provider"] == "semanticscholar" and item["endpoint"] == "bulk":
            extra = f"total={count}, returned={returned}, has_next={item.get('has_next_page')}"
        print(
            f"[{item['provider']}/{item['endpoint']}] {item['name']}: "
            f"status={item['status_code']} ok={item['ok']} {extra} elapsed_ms={item['elapsed_ms']}"
        )
        if item.get("sample_titles"):
            first = item["sample_titles"][0]
            print(f"  top_sample={first.get('title')!r}")
        elif item.get("error"):
            print(f"  error={item['error']!r}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe OpenAlex and Semantic Scholar API behavior for Phase C prompt tuning.")
    parser.add_argument("--provider", choices=["all", "openalex", "semanticscholar"], default="all")
    parser.add_argument("--limit", type=int, default=10, help="Per-request page size / first-page size.")
    parser.add_argument("--match", default="", help="Only run experiments whose name contains this substring.")
    parser.add_argument("--sleep", type=float, default=1.1, help="Seconds to sleep between requests.")
    parser.add_argument("--output", type=Path, default=None, help="Optional explicit JSON output path.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = args.output or (OUTPUT_DIR / f"phase_c_api_probe_{_now_slug()}.json")

    experiments: List[Experiment] = []
    if args.provider in {"all", "openalex"}:
        experiments.extend(build_openalex_experiments(limit=args.limit))
    if args.provider in {"all", "semanticscholar"}:
        experiments.extend(build_s2_experiments(limit=args.limit))
    if args.match:
        needle = args.match.lower()
        experiments = [exp for exp in experiments if needle in exp.name.lower()]
    if not experiments:
        raise SystemExit("No experiments matched the selected provider/filter.")

    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT})

    results: List[Dict[str, Any]] = []
    for index, exp in enumerate(experiments, start=1):
        print(f"{index:02d}/{len(experiments)} {exp.provider}/{exp.endpoint} {exp.name}")
        if exp.provider == "openalex":
            result = run_openalex(session, exp)
        else:
            result = run_s2(session, exp)
        results.append(result)
        time.sleep(max(args.sleep, 0.0))

    envelope = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "python": sys.executable,
        "provider_filter": args.provider,
        "request_limit": args.limit,
        "results": [_sanitize(item) for item in results],
    }
    output_path.write_text(json.dumps(envelope, indent=2, ensure_ascii=False), encoding="utf-8")
    print_summary(results)
    print()
    print(f"Wrote probe results to {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
