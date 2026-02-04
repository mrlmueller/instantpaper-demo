from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import random
import re
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Literal, Optional, Tuple

import numpy as np
import pandas as pd
import requests
from pydantic import BaseModel, Field
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)


# -----------------------------
# Cache dirs (backend-safe)
# -----------------------------

_FASTAPI_DIR = Path(__file__).resolve().parents[1]
QF_CACHE_DIR = _FASTAPI_DIR / ".quellen_finder_cache"
QF_CACHE_DIR.mkdir(parents=True, exist_ok=True)


# -----------------------------
# Stage B: Chapter blueprint (schema)
# -----------------------------


class ChapterBlueprint(BaseModel):
    chapter_id: str
    language: str = Field("en")

    scope_statement: str
    must_cover: List[str]
    should_cover: List[str]
    must_avoid: List[str]

    main_query: str
    facet_queries: List[str]
    keywords: List[str]
    key_concepts: List[str]

    preferred_source_types: Optional[List[str]] = None
    negative_query_terms: Optional[List[str]] = None

    scoring_guidance: str
    notes: Optional[str] = None


CHAPTER_BLUEPRINT_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "chapter_id": {"type": "string"},
        "language": {"type": "string"},
        "scope_statement": {"type": "string"},
        "must_cover": {"type": "array", "items": {"type": "string"}},
        "should_cover": {"type": "array", "items": {"type": "string"}},
        "must_avoid": {"type": "array", "items": {"type": "string"}},
        "main_query": {"type": "string"},
        "facet_queries": {"type": "array", "items": {"type": "string"}},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "key_concepts": {"type": "array", "items": {"type": "string"}},
        "preferred_source_types": {"type": "array", "items": {"type": "string"}},
        "negative_query_terms": {"type": "array", "items": {"type": "string"}},
        "scoring_guidance": {"type": "string"},
        "notes": {"type": "string"},
    },
    "required": [
        "chapter_id",
        "language",
        "scope_statement",
        "must_cover",
        "should_cover",
        "must_avoid",
        "main_query",
        "facet_queries",
        "keywords",
        "key_concepts",
        "preferred_source_types",
        "negative_query_terms",
        "scoring_guidance",
        "notes",
    ],
    "additionalProperties": False,
}


BASE_BLUEPRINT_INSTRUCTIONS = (
    "You create a chapter blueprint (rubric) and search queries for academic literature retrieval.\n"
    "Return ONLY the structured output fields (no extra text).\n\n"
    "Constraints:\n"
    "- language must be 'en'\n"
    "- scope_statement: 1 sentence, <= 30 words\n"
    "- must_cover: 4–8 bullets, each <= 16 words\n"
    "- should_cover: 3–8 bullets, each <= 16 words\n"
    "- must_avoid: 3–8 bullets, each <= 16 words\n"
    "- main_query: <= 18 words\n"
    "- facet_queries: 8–14 items, each <= 14 words\n"
    "- keywords: 20–45 items\n"
    "- key_concepts: 10–22 items\n"
    "- preferred_source_types: 2–6 items\n"
    "- negative_query_terms: 0–12 items derived from must_avoid (soft negatives)\n"
    "- scoring_guidance: <= 80 words\n"
    "- Do NOT contradict yourself: if something is in must_avoid, do not emphasize it in keywords/facets.\n"
    "- Do NOT hardcode any domain. Follow the given chapter spec.\n"
)

COVERAGE_V1_INSTRUCTIONS = BASE_BLUEPRINT_INSTRUCTIONS + (
    "\nAdditional requirements (coverage_v1):\n"
    "- facet_queries must be semantically diverse (avoid near-duplicates).\n"
    "- Ensure each must_cover bullet is explicitly targeted by at least one facet_query.\n"
)

BLUEPRINT_INSTRUCTIONS = COVERAGE_V1_INSTRUCTIONS


# -----------------------------
# Stage A: API retrieval (OpenAlex + Semantic Scholar)
# -----------------------------

FETCH_MAX_QUERIES_PER_CHAPTER = 15

# OpenAlex
OA_BASE_URL = "https://api.openalex.org/works"
OA_PER_PAGE = 100
OA_MAX_WORKS_PER_QUERY = 300
OA_TIMEOUT_SEC = 30

# Semantic Scholar
S2_BASE = "https://api.semanticscholar.org/graph/v1"
S2_SEARCH_URL = f"{S2_BASE}/paper/search"
S2_BATCH_URL = f"{S2_BASE}/paper/batch"

S2_LIMIT = 100
S2_MAX_PAGES_PER_QUERY = 1
S2_FETCH_ABSTRACTS_VIA_BATCH = True
S2_BATCH_SIZE = 200

S2_CACHE_ENABLED = True
S2_CACHE_TTL_DAYS = 30

S2_VERBOSE = False

S2_TIMEOUT_SEC = 30
S2_REQUEST_MAX_RETRIES = 200
S2_REQUEST_MAX_SECONDS = 3600
S2_BACKOFF_INITIAL_SEC = 2.0
S2_BACKOFF_MAX_SEC = 300.0
S2_BACKOFF_JITTER = 0.25
S2_SUCCESS_SLEEP_SEC = 0.2
S2_MIN_INTERVAL = 1.0

S2_CACHE_DIR = QF_CACHE_DIR / "s2_cache"
S2_CACHE_DIR.mkdir(parents=True, exist_ok=True)

_S2_LAST_TS = 0.0


def dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        x = str(x).strip()
        if not x:
            continue
        k = x.lower()
        if k in seen:
            continue
        seen.add(k)
        out.append(x)
    return out


def query_list_for_chapter(bp: ChapterBlueprint | dict) -> List[str]:
    if hasattr(bp, "main_query"):
        main = bp.main_query
        facets = list(bp.facet_queries or [])
    else:
        main = (bp.get("main_query", "") if isinstance(bp, dict) else "")
        facets = list((bp.get("facet_queries") or []) if isinstance(bp, dict) else [])
    qs = [main] + facets
    qs = dedupe_preserve_order(qs)
    return qs[:FETCH_MAX_QUERIES_PER_CHAPTER]


def abstract_from_inverted_index(inv: Optional[Dict[str, List[int]]]) -> Optional[str]:
    if not inv:
        return None

    pairs: List[tuple[int, str]] = []
    for word, positions in inv.items():
        if not positions:
            continue
        for p in positions:
            if isinstance(p, int):
                pairs.append((p, word))

    if not pairs:
        return None

    pairs.sort(key=lambda x: x[0])
    max_pos = pairs[-1][0]
    words = [""] * (max_pos + 1)
    for pos, w in pairs:
        if 0 <= pos <= max_pos:
            words[pos] = w

    text = " ".join(w for w in words if w).strip()
    return text or None


def venue_from_primary_location(work: Dict[str, Any]) -> Optional[str]:
    pl = work.get("primary_location") or {}
    src = pl.get("source") or {}
    return src.get("display_name")


def first_n_authors(work: Dict[str, Any], n: int = 6) -> str:
    authors = []
    for a in (work.get("authorships") or [])[:n]:
        name = ((a.get("author") or {}).get("display_name"))
        if name:
            authors.append(name)
    return "; ".join(authors)


def oa_get(params: Dict[str, Any], *, max_retries: int = 6) -> dict:
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        r = requests.get(OA_BASE_URL, params=params, timeout=OA_TIMEOUT_SEC)
        if r.status_code in (429, 500, 502, 503, 504):
            if attempt == max_retries:
                raise RuntimeError(f"OpenAlex error {r.status_code} | URL: {r.url} | Body: {r.text[:400]}")
            time.sleep(backoff)
            backoff *= 2
            continue
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAlex error {r.status_code} | URL: {r.url} | Body: {r.text[:400]}")
        return r.json()
    raise RuntimeError("OpenAlex retry loop exhausted")


def fetch_openalex_query(*, q: str, openalex_api_key: str, max_works: Optional[int]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    cursor = "*"
    select = (
        "id,display_name,publication_year,type,doi,cited_by_count,"
        "authorships,primary_location,abstract_inverted_index"
    )

    while cursor:
        params: Dict[str, Any] = {
            "search": q,
            "per-page": OA_PER_PAGE,
            "cursor": cursor,
            "select": select,
        }
        if openalex_api_key:
            params["api_key"] = openalex_api_key

        data = oa_get(params)

        for w in data.get("results", []) or []:
            rows.append(
                {
                    "query": q,
                    "title": w.get("display_name"),
                    "year": w.get("publication_year"),
                    "type": w.get("type"),
                    "venue": venue_from_primary_location(w),
                    "cited_by": w.get("cited_by_count"),
                    "authors(first6)": first_n_authors(w, n=6),
                    "doi": w.get("doi"),
                    "openalex_id": w.get("id"),
                    "abstract": abstract_from_inverted_index(w.get("abstract_inverted_index")),
                }
            )

            if max_works is not None and len(rows) >= max_works:
                return rows

        cursor = (data.get("meta") or {}).get("next_cursor")
        if not cursor:
            break

    return rows


def fetch_openalex_for_chapter(*, chapter_id: str, queries: List[str], openalex_api_key: str) -> pd.DataFrame:
    all_rows: List[Dict[str, Any]] = []
    for qi, q in enumerate(queries, start=1):
        logger.info("[OpenAlex:%s] (%s/%s) %s", chapter_id, qi, len(queries), q)
        all_rows.extend(fetch_openalex_query(q=q, openalex_api_key=openalex_api_key, max_works=OA_MAX_WORKS_PER_QUERY))

    df_oa = pd.DataFrame(all_rows)
    if df_oa.empty:
        return df_oa

    df_oa.insert(0, "chapter_id", chapter_id)
    df_oa = (
        df_oa.drop_duplicates(subset=["chapter_id", "query", "openalex_id"], keep="first")
        .reset_index(drop=True)
    )
    return df_oa


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _cache_key(method: str, url: str, params: Optional[Dict[str, Any]], body: Optional[Dict[str, Any]]) -> str:
    blob = {"m": method.upper(), "u": url, "p": params or {}, "b": body or {}}
    s = json.dumps(blob, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha1(s).hexdigest()


def s2_cache_get(method: str, url: str, params: Optional[Dict[str, Any]], body: Optional[Dict[str, Any]]) -> Optional[Any]:
    if not S2_CACHE_ENABLED:
        return None
    key = _cache_key(method, url, params, body)
    path = S2_CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        created = datetime.fromisoformat(payload["created"])
        if _now_utc() - created > timedelta(days=S2_CACHE_TTL_DAYS):
            return None
        return payload["data"]
    except Exception:
        return None


def s2_cache_set(method: str, url: str, params: Optional[Dict[str, Any]], body: Optional[Dict[str, Any]], data: Any) -> None:
    if not S2_CACHE_ENABLED:
        return
    key = _cache_key(method, url, params, body)
    path = S2_CACHE_DIR / f"{key}.json"
    payload = {"created": _now_utc().isoformat(), "data": data}
    path.write_text(json.dumps(payload), encoding="utf-8")


def _parse_retry_after(resp: requests.Response) -> Optional[float]:
    ra = resp.headers.get("Retry-After")
    if not ra:
        return None
    try:
        return float(ra)
    except ValueError:
        return None


def s2_request(
    session: requests.Session,
    method: str,
    url: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    body: Optional[Dict[str, Any]] = None,
    max_retries: Optional[int] = None,
    max_elapsed_seconds: Optional[float] = None,
) -> Any:
    global _S2_LAST_TS  # pylint: disable=global-statement

    cached = s2_cache_get(method, url, params, body)
    if cached is not None:
        return cached

    max_retries = int(max_retries if max_retries is not None else S2_REQUEST_MAX_RETRIES)
    max_elapsed_seconds = float(max_elapsed_seconds if max_elapsed_seconds is not None else S2_REQUEST_MAX_SECONDS)

    start = time.monotonic()
    backoff = float(S2_BACKOFF_INITIAL_SEC)
    last_status: Any = None
    last_err: Optional[str] = None

    attempt = 0
    while True:
        attempt += 1
        now = time.time()
        wait = float(S2_MIN_INTERVAL) - float(now - _S2_LAST_TS)
        if wait > 0:
            time.sleep(wait)
        _S2_LAST_TS = time.time()

        resp: Optional[requests.Response]
        try:
            resp = session.request(method, url, params=params, json=body, timeout=S2_TIMEOUT_SEC)
            last_status = resp.status_code
            last_err = None
        except Exception as e:
            resp = None
            last_status = "exception"
            last_err = repr(e)

        if resp is not None and resp.status_code == 200:
            try:
                data = resp.json()
            except Exception as e:
                last_status = "json_error"
                last_err = repr(e)
            else:
                s2_cache_set(method, url, params, body, data)
                return data

        ra = None
        if resp is None:
            retryable = True
        elif resp.status_code in (429, 500, 502, 503, 504):
            retryable = True
            ra = _parse_retry_after(resp)
        elif resp.status_code in (408,):
            retryable = True
        else:
            raise RuntimeError(f"S2 error {resp.status_code} | body: {resp.text[:500]}")

        if not retryable:
            raise RuntimeError(f"S2 error (non-retryable) status={last_status}")

        elapsed = time.monotonic() - start
        if attempt >= max_retries or elapsed >= max_elapsed_seconds:
            detail = f"last_status={last_status}"
            if last_err:
                detail += f" last_err={last_err}"
            raise RuntimeError(
                f"S2 retry budget exhausted after {elapsed:.0f}s and {attempt} attempts: {method} {url} ({detail})"
            )

        wait = float(backoff)
        if ra is not None:
            wait = max(wait, float(ra))
        wait = min(float(S2_BACKOFF_MAX_SEC), wait)
        if S2_BACKOFF_JITTER:
            jitter = 1.0 + random.uniform(-float(S2_BACKOFF_JITTER), float(S2_BACKOFF_JITTER))
            wait = max(0.0, wait * jitter)

        wait = max(1.0, wait)
        remaining = float(max_elapsed_seconds) - float(elapsed)
        wait = min(wait, max(0.0, remaining))

        if S2_VERBOSE:
            logger.info(
                "[S2] status=%s retry in %.1fs | attempt %s/%s | elapsed %.0fs",
                last_status,
                wait,
                attempt,
                max_retries,
                elapsed,
            )
        time.sleep(wait)
        backoff = min(float(S2_BACKOFF_MAX_SEC), backoff * 2)


def clean_query(q: str) -> str:
    q = q.replace("-", " ")
    q = re.sub(r"\s+", " ", q).strip()
    return q


def chunks(xs: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def fetch_s2_for_chapter(*, chapter_id: str, queries: List[str], semanticscholar_api_key: str) -> pd.DataFrame:
    SEARCH_FIELDS = "paperId,title,year,authors,venue,citationCount,externalIds,url"
    DETAIL_FIELDS = "paperId,abstract"

    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-quellen-finder/1.0"})
    if semanticscholar_api_key:
        session.headers.update({"x-api-key": semanticscholar_api_key})

    rows: List[Dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for qi, q in enumerate(queries, start=1):
        q2 = clean_query(q)
        logger.info("[S2:%s] (%s/%s) %s", chapter_id, qi, len(queries), q2)

        offset = 0
        for _page in range(1, S2_MAX_PAGES_PER_QUERY + 1):
            params = {"query": q2, "fields": SEARCH_FIELDS, "limit": S2_LIMIT, "offset": offset}
            data = s2_request(session, "GET", S2_SEARCH_URL, params=params, body=None)
            time.sleep(S2_SUCCESS_SLEEP_SEC)

            papers = data.get("data", []) or []
            for p in papers:
                pid = p.get("paperId")
                if not pid:
                    continue
                key = (str(q), str(pid))
                if key in seen:
                    continue
                seen.add(key)

                authors = [a.get("name") for a in (p.get("authors") or [])[:6] if a.get("name")]
                ext = p.get("externalIds") or {}
                rows.append(
                    {
                        "chapter_id": chapter_id,
                        "query": q,
                        "paperId": pid,
                        "title": p.get("title"),
                        "year": p.get("year"),
                        "venue": p.get("venue"),
                        "citationCount": p.get("citationCount"),
                        "authors(first6)": "; ".join(authors),
                        "doi": ext.get("DOI"),
                        "s2_url": p.get("url"),
                    }
                )

            if len(papers) < S2_LIMIT:
                break
            offset += S2_LIMIT

    df_s2 = pd.DataFrame(rows)
    if df_s2.empty:
        return df_s2

    df_s2 = df_s2.drop_duplicates(subset=["chapter_id", "query", "paperId"]).reset_index(drop=True)

    if not S2_FETCH_ABSTRACTS_VIA_BATCH:
        return df_s2

    abstracts: Dict[str, Optional[str]] = {}
    unique_ids = [str(pid) for pid in df_s2["paperId"].dropna().unique().tolist() if pid]
    if unique_ids:
        logger.info("[S2:%s] fetching abstracts via batch | ids=%s", chapter_id, len(unique_ids))

    for ids in chunks(unique_ids, S2_BATCH_SIZE):
        params = {"fields": DETAIL_FIELDS}
        body = {"ids": ids}
        batch = s2_request(session, "POST", S2_BATCH_URL, params=params, body=body)
        time.sleep(S2_SUCCESS_SLEEP_SEC)

        it = batch if isinstance(batch, list) else (batch.get("data", []) or [])
        for p in it:
            pid = p.get("paperId")
            if pid:
                abstracts[str(pid)] = p.get("abstract")

    df_s2["abstract"] = df_s2["paperId"].astype(str).map(abstracts)
    return df_s2


# -----------------------------
# Stage A merge (OpenAlex + S2)
# -----------------------------


def standardize_openalex(df_in: pd.DataFrame) -> pd.DataFrame:
    d = df_in.copy()
    d["source"] = "openalex"
    d["source_id"] = d.get("openalex_id")
    d["citation_count"] = d.get("cited_by")
    for col in [
        "abstract",
        "doi",
        "title",
        "year",
        "venue",
        "type",
        "authors(first6)",
        "query",
        "chapter_id",
        "openalex_id",
    ]:
        if col not in d.columns:
            d[col] = np.nan
    return d[
        [
            "chapter_id",
            "source",
            "source_id",
            "query",
            "title",
            "year",
            "venue",
            "type",
            "authors(first6)",
            "doi",
            "citation_count",
            "abstract",
            "openalex_id",
        ]
    ]


def standardize_s2(df_in: pd.DataFrame) -> pd.DataFrame:
    d = df_in.copy()
    d["source"] = "semantic_scholar"
    d["source_id"] = d.get("paperId")
    d["citation_count"] = d.get("citationCount")
    for col in [
        "abstract",
        "doi",
        "title",
        "year",
        "venue",
        "authors(first6)",
        "query",
        "paperId",
        "s2_url",
        "chapter_id",
    ]:
        if col not in d.columns:
            d[col] = np.nan
    d["type"] = np.nan
    d["openalex_id"] = np.nan
    return d[
        [
            "chapter_id",
            "source",
            "source_id",
            "query",
            "title",
            "year",
            "venue",
            "type",
            "authors(first6)",
            "doi",
            "citation_count",
            "abstract",
            "paperId",
            "s2_url",
        ]
    ]


def normalize_doi(x):
    if not isinstance(x, str):
        return None
    x = x.strip().lower()
    if not x:
        return None
    x = re.sub(r"^https?://(dx\.)?doi\.org/", "", x)
    x = re.sub(r"^doi:\s*", "", x)
    x = x.strip()
    return x or None


def normalize_title(x):
    if not isinstance(x, str):
        return None
    x = x.strip().lower()
    if not x:
        return None
    x = re.sub(r"[\u2010-\u2015]", "-", x)
    x = re.sub(r"[^a-z0-9\s]", " ", x)
    x = re.sub(r"\s+", " ", x).strip()
    return x or None


def longest_text(series):
    vals = [v for v in series if isinstance(v, str) and v.strip()]
    if not vals:
        return None
    return max(vals, key=len)


def most_common_or_longest(series):
    vals = [v for v in series if isinstance(v, str) and v.strip()]
    if not vals:
        return None
    vc = pd.Series(vals).value_counts()
    if len(vc) and vc.iloc[0] >= 2:
        return vc.index[0]
    return max(vals, key=len)


def first_nonnull(series):
    for v in series:
        if pd.notna(v) and v not in ("", None):
            return v
    return None


def within_source_key(df_in: pd.DataFrame) -> pd.Series:
    k = []
    for _, r in df_in.iterrows():
        if r.get("doi_norm"):
            k.append(f"doi:{r['doi_norm']}")
        elif pd.notna(r.get("source_id")):
            k.append(f"id:{r['source']}:{r['source_id']}")
        else:
            y = int(r["year"]) if pd.notna(r.get("year")) else ""
            k.append(f"ty:{r['title_norm']}|{y}")
    return pd.Series(k, index=df_in.index)


def cross_source_merge_key(r: pd.Series) -> str:
    if isinstance(r.get("doi_norm"), str) and r.get("doi_norm"):
        return f"doi:{r['doi_norm']}"
    if pd.notna(r.get("year")):
        return f"ty:{r['title_norm']}|{int(round(float(r['year'])))}"
    return f"t:{r['title_norm']}"


def build_stagea(*, df_oa_raw: pd.DataFrame, df_s2_raw: pd.DataFrame, chapter_id: str) -> pd.DataFrame:
    oa_std = standardize_openalex(df_oa_raw)
    s2_std = standardize_s2(df_s2_raw)

    combined_raw = pd.concat([oa_std, s2_std], ignore_index=True)
    stageA = combined_raw.copy()

    stageA["doi_norm"] = stageA["doi"].map(normalize_doi)
    stageA["title_norm"] = stageA["title"].map(normalize_title)
    stageA["citation_count"] = pd.to_numeric(stageA["citation_count"], errors="coerce")

    stageA = stageA[stageA["title_norm"].notna()].reset_index(drop=True)
    stageA["within_key"] = within_source_key(stageA)

    agg_map = {
        "chapter_id": lambda s: s.iloc[0],
        "source": lambda s: s.iloc[0],
        "source_id": first_nonnull,
        "title": most_common_or_longest,
        "title_norm": lambda s: s.iloc[0],
        "year": lambda s: pd.to_numeric(s, errors="coerce").dropna().median() if s.notna().any() else np.nan,
        "venue": most_common_or_longest,
        "type": most_common_or_longest,
        "authors(first6)": most_common_or_longest,
        "doi": first_nonnull,
        "doi_norm": first_nonnull,
        "citation_count": lambda s: pd.to_numeric(s, errors="coerce").max(),
        "abstract": longest_text,
        "query": lambda s: "; ".join(sorted(set([q for q in s if isinstance(q, str) and q.strip()]))),
        "openalex_id": first_nonnull,
        "paperId": first_nonnull,
        "s2_url": first_nonnull,
    }

    stageA_dedup = stageA.groupby(["source", "within_key"], as_index=False).agg(agg_map).drop(columns=["within_key"])
    stageA_dedup["merge_key"] = stageA_dedup.apply(cross_source_merge_key, axis=1)

    def merge_sources(group: pd.DataFrame) -> dict:
        sources = sorted(set(group["source"].dropna().tolist()))
        source_ids = {
            src: group.loc[group["source"] == src, "source_id"].dropna().astype(str).unique().tolist()
            for src in sources
        }

        return {
            "chapter_id": chapter_id,
            "merge_key": group["merge_key"].iloc[0],
            "sources": "; ".join(sources),
            "source_count": len(sources),
            "source_ids": str(source_ids),
            "title": most_common_or_longest(group["title"]),
            "year": (
                pd.to_numeric(group["year"], errors="coerce").dropna().median()
                if group["year"].notna().any()
                else np.nan
            ),
            "venue": most_common_or_longest(group["venue"]),
            "type": most_common_or_longest(group["type"]),
            "authors(first6)": most_common_or_longest(group["authors(first6)"]),
            "doi": first_nonnull(group["doi"]),
            "doi_norm": first_nonnull(group["doi_norm"]),
            "citation_count_max": pd.to_numeric(group["citation_count"], errors="coerce").max(),
            "abstract": longest_text(group["abstract"]),
            "queries": "; ".join(
                sorted(
                    set(
                        q
                        for q in group["query"].dropna().tolist()
                        if isinstance(q, str) and q.strip()
                    )
                )
            ),
            "openalex_id": first_nonnull(group.get("openalex_id", pd.Series([], dtype=object))),
            "paperId": first_nonnull(group.get("paperId", pd.Series([], dtype=object))),
            "s2_url": first_nonnull(group.get("s2_url", pd.Series([], dtype=object))),
        }

    merged_records = [merge_sources(g) for _, g in stageA_dedup.groupby("merge_key")]
    df_stageA = pd.DataFrame(merged_records)

    df_stageA["merge_kind"] = df_stageA["merge_key"].str.split(":", n=1).str[0]
    df_stageA["has_abstract"] = df_stageA["abstract"].notna() & (df_stageA["abstract"].astype(str).str.len() > 50)
    df_stageA = df_stageA.sort_values(by="citation_count_max", ascending=False, na_position="last").reset_index(drop=True)
    return df_stageA


# -----------------------------
# Stage C finalized scoring (as in notebook)
# -----------------------------

STAGEC_W_EMBED_MAX = 0.0
STAGEC_W_EMBED = 0.7
STAGEC_CITE_WEIGHT = 0.08


def minmax_by_group(df_in: pd.DataFrame, col: str, group_col: str = "chapter_id") -> pd.Series:
    out = pd.Series(index=df_in.index, dtype=float)
    for _, g in df_in.groupby(group_col):
        x = pd.to_numeric(g[col], errors="coerce").fillna(0).to_numpy(dtype=float)
        mn, mx = float(np.min(x)), float(np.max(x))
        out.loc[g.index] = (x - mn) / (mx - mn + 1e-12)
    return out


def add_stagec_final_scores(df_in: pd.DataFrame) -> pd.DataFrame:
    required = [
        "chapter_id",
        "score_embed_max",
        "score_embed_mean_top3",
        "score_tfidf",
        "score_cite_norm",
    ]
    missing = [c for c in required if c not in df_in.columns]
    if missing:
        raise ValueError(f"Missing required columns for Stage C scoring: {missing}")

    df = df_in.copy()

    emb_max = pd.to_numeric(df["score_embed_max"], errors="coerce").fillna(0.0)
    emb_b = pd.to_numeric(df["score_embed_mean_top3"], errors="coerce").fillna(0.0)
    df["_emb_raw"] = float(STAGEC_W_EMBED_MAX) * emb_max + (1.0 - float(STAGEC_W_EMBED_MAX)) * emb_b

    df["_emb_n"] = minmax_by_group(df, "_emb_raw")
    df["_tf_n"] = minmax_by_group(df, "score_tfidf")
    df["_cite_n"] = minmax_by_group(df, "score_cite_norm")

    base = float(STAGEC_W_EMBED) * df["_emb_n"] + (1.0 - float(STAGEC_W_EMBED)) * df["_tf_n"]
    df["score_stageC_final"] = (1.0 - float(STAGEC_CITE_WEIGHT)) * base + float(STAGEC_CITE_WEIGHT) * df["_cite_n"]
    return df


# -----------------------------
# Stage C pool + scoring (TF-IDF + embeddings)
# -----------------------------

TFIDF_MAX_FEATURES = 200_000
TFIDF_MIN_DF = 2
TFIDF_NGRAM_RANGE = (1, 2)
TOP_PER_QUERY = 250

EMBED_MODEL = "text-embedding-3-small"
MAX_CHARS_PER_EMBED = 3500
EMBED_BATCH_SIZE = 64

W_EMBED_MAX = 0.70
W_EMBED_BREADTH = 0.30

EMBED_CACHE_DIR = QF_CACHE_DIR / "embed_cache"
EMBED_CACHE_DIR.mkdir(parents=True, exist_ok=True)


def minmax(x):
    x = np.asarray(x, dtype=float)
    mn, mx = np.nanmin(x), np.nanmax(x)
    return (x - mn) / (mx - mn + 1e-12)


def truncate_text(s: str, max_chars: int) -> str:
    s = "" if s is None else str(s)
    s = s.replace("\n", " ").strip()
    return s[:max_chars]


def build_chapter_query_text(bp: dict) -> str:
    parts = []
    main = bp["main_query"]
    parts.extend([main, main])
    parts.extend(bp.get("facet_queries", []))
    parts.extend(bp.get("keywords", []))
    parts.extend(bp.get("key_concepts", []))
    return " ".join(parts)


def tfidf_scores(query_text: str, vectorizer: TfidfVectorizer, X) -> np.ndarray:
    qv = vectorizer.transform([query_text])
    return cosine_similarity(qv, X).ravel()


def facet_union_pool(
    bp: dict,
    df_in: pd.DataFrame,
    *,
    vectorizer: TfidfVectorizer,
    X,
    top_per_query: int,
) -> pd.DataFrame:
    query_texts = [bp["main_query"], bp["main_query"]] + list(bp.get("facet_queries", []))
    pool_keys = set()
    for qt in query_texts:
        qv = vectorizer.transform([qt])
        sims = cosine_similarity(qv, X).ravel()
        top_idx = np.argsort(-sims)[:top_per_query]
        pool_keys.update(df_in.iloc[top_idx]["merge_key"].astype(str).tolist())
    out = df_in[df_in["merge_key"].astype(str).isin(pool_keys)].copy()
    out = out.drop_duplicates(subset=["merge_key"]).reset_index(drop=True)
    return out


def l2_normalize(mat: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(mat, axis=1, keepdims=True) + 1e-12
    return mat / norms


def hash_obj(obj: Any) -> str:
    blob = json.dumps(obj, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(blob.encode("utf-8")).hexdigest()


def save_npz(path: Path, keys: List[str], mat: np.ndarray):
    np.savez_compressed(path, keys=np.array(keys, dtype=object), embeds=mat.astype(np.float32))


def load_npz(path: Path):
    z = np.load(path, allow_pickle=True)
    return list(z["keys"]), z["embeds"].astype(np.float32)


@dataclass(frozen=True)
class EmbedBatchResult:
    embeds: np.ndarray
    requests: int
    input_tokens: int


EmbedTextsFn = Any


async def score_pool_with_embeddings(
    bp: dict,
    pool: pd.DataFrame,
    *,
    embed_texts: EmbedTextsFn,
) -> Tuple[pd.DataFrame, dict]:
    """
    Score candidate pool with OpenAI embeddings.

    Returns (pool_scored, embed_totals).
    """

    pool = pool.copy()
    pool["doc_text_trunc"] = (
        pool["title"].fillna("") + "\n\n" + pool["abstract"].fillna("")
    ).apply(lambda s: truncate_text(s, MAX_CHARS_PER_EMBED))

    keys = pool["merge_key"].astype(str).tolist()

    embed_totals = {"requests": 0, "input_tokens": 0}

    doc_hash = hash_obj({"model": EMBED_MODEL, "max_chars": MAX_CHARS_PER_EMBED, "keys": keys})[:16]
    doc_npz = EMBED_CACHE_DIR / f"eval_doc_embeds_{EMBED_MODEL}_{doc_hash}.npz"

    query_texts = [bp["main_query"], bp["main_query"]] + list(bp.get("facet_queries", []))
    q_hash = hash_obj({"model": EMBED_MODEL, "queries": query_texts})[:16]
    q_json = EMBED_CACHE_DIR / f"eval_query_embeds_{EMBED_MODEL}_{q_hash}.json"

    # Docs
    if doc_npz.exists():
        cached_keys, doc_embeds = load_npz(doc_npz)
        if cached_keys != keys:
            res: EmbedBatchResult = await embed_texts(pool["doc_text_trunc"].tolist(), model=EMBED_MODEL, batch_size=EMBED_BATCH_SIZE)
            doc_embeds = res.embeds
            embed_totals["requests"] += int(res.requests)
            embed_totals["input_tokens"] += int(res.input_tokens)
            save_npz(doc_npz, keys, doc_embeds)
    else:
        res = await embed_texts(pool["doc_text_trunc"].tolist(), model=EMBED_MODEL, batch_size=EMBED_BATCH_SIZE)
        doc_embeds = res.embeds
        embed_totals["requests"] += int(res.requests)
        embed_totals["input_tokens"] += int(res.input_tokens)
        save_npz(doc_npz, keys, doc_embeds)

    # Queries
    if q_json.exists():
        q_cached = json.loads(q_json.read_text(encoding="utf-8"))
        query_embeds = np.array(q_cached["embeddings"], dtype=np.float32)
    else:
        res_q = await embed_texts(query_texts, model=EMBED_MODEL, batch_size=EMBED_BATCH_SIZE)
        query_embeds = res_q.embeds
        embed_totals["requests"] += int(res_q.requests)
        embed_totals["input_tokens"] += int(res_q.input_tokens)
        q_json.write_text(
            json.dumps(
                {"model": EMBED_MODEL, "query_texts": query_texts, "embeddings": query_embeds.tolist()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    docN = l2_normalize(doc_embeds)
    qN = l2_normalize(query_embeds)
    S = docN @ qN.T

    pool["score_embed_max"] = S.max(axis=1)
    pool["score_embed_mean_top3"] = np.sort(S, axis=1)[:, -3:].mean(axis=1)
    pool["score_embed_norm"] = minmax(pool["score_embed_max"].values)
    pool["score_embed_mean_top3_norm"] = minmax(pool["score_embed_mean_top3"].values)
    pool["score_embed_combo"] = W_EMBED_MAX * pool["score_embed_norm"] + W_EMBED_BREADTH * pool["score_embed_mean_top3_norm"]

    # Facet assignment (exclude the two main-query columns)
    facets = list(bp.get("facet_queries", []))
    if facets:
        facet_S = S[:, 2 : 2 + len(facets)]
        facet_best_i = facet_S.argmax(axis=1).astype(int)
        pool["facet_best_i"] = facet_best_i
        pool["facet_best_query"] = [facets[i] for i in facet_best_i]
    else:
        pool["facet_best_i"] = -1
        pool["facet_best_query"] = ""

    return pool, embed_totals


def score_stagec_pool_for_chapter(
    *,
    chapter_id: str,
    stagea_df: pd.DataFrame,
    blueprint: ChapterBlueprint,
) -> pd.DataFrame:
    df = stagea_df.copy()
    if df.empty:
        return df

    for c_req in ["merge_key", "title", "abstract"]:
        if c_req not in df.columns:
            raise RuntimeError(f"[{chapter_id}] StageA missing required column: {c_req}")

    df["title"] = df["title"].fillna("")
    df["abstract"] = df["abstract"].fillna("")
    df["doc_text"] = (df["title"].astype(str) + "\n\n" + df["abstract"].astype(str)).str.strip()

    cites = pd.to_numeric(df.get("citation_count_max", 0), errors="coerce").fillna(0).clip(lower=0)
    df["score_cite"] = np.log1p(cites)
    df["score_cite_norm"] = (df["score_cite"] / df["score_cite"].max()) if df["score_cite"].max() > 0 else 0.0

    vectorizer = TfidfVectorizer(
        lowercase=True,
        stop_words="english",
        ngram_range=TFIDF_NGRAM_RANGE,
        max_features=TFIDF_MAX_FEATURES,
        min_df=TFIDF_MIN_DF,
    )
    X = vectorizer.fit_transform(df["doc_text"])

    bp = blueprint.model_dump()
    chapter_query_text = build_chapter_query_text(bp)
    df["score_tfidf"] = tfidf_scores(chapter_query_text, vectorizer=vectorizer, X=X)

    pool = facet_union_pool(bp, df_in=df, vectorizer=vectorizer, X=X, top_per_query=TOP_PER_QUERY)
    logger.info("[%s] Stage C pool size: %s (from StageA %s)", chapter_id, len(pool), len(df))
    return pool


# -----------------------------
# Stage C.3 rerank (schema + prompt builder)
# -----------------------------

STAGEC3_TOPN = 50
STAGEC3_TOPN_MAX = 150
STAGEC3_TOPN_STEP = 25
STAGEC3_MIN_NON_EXCLUDE = 20

STAGEC3_MODEL = "gpt-5-nano"
STAGEC3_PROMPT_VERSION = "v2"

STAGEC3_ALPHA_LLM = 0.2
STAGEC3_CONFIDENCE_MIN = 50

STAGEC3_CONCURRENCY = 8
STAGEC3_MAX_RETRIES = 8
STAGEC3_BACKOFF_INITIAL = 1.0
STAGEC3_BACKOFF_MAX = 30.0
STAGEC3_ABSTRACT_MAX_CHARS = 2000

STAGEC3_FORCE_RERANK = False

STAGEC3_DIR = QF_CACHE_DIR / "stageC3_rerank_cache_v1"
STAGEC3_DIR.mkdir(parents=True, exist_ok=True)


class StageC3RerankOut(BaseModel):
    label: Literal["include", "maybe", "exclude"] = Field(...)
    confidence: int = Field(..., ge=0, le=100)
    score: int = Field(..., ge=0, le=100)
    notes: str = Field("", max_length=140)


STAGEC3_RERANK_JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "label": {"type": "string", "enum": ["include", "maybe", "exclude"]},
        "confidence": {"type": "integer", "minimum": 0, "maximum": 100},
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "notes": {"type": "string"},
    },
    "required": ["label", "confidence", "score", "notes"],
    "additionalProperties": False,
}


STAGEC3_SYSTEM_INSTRUCTIONS = (
    "You validate whether a paper fits the chapter rubric.\n"
    "Return ONLY the structured output.\n\n"
    "Scoring (score is 0-100, not 0-3):\n"
    "- 90-100: excellent fit (covers multiple MUST_COVER, avoids MUST_AVOID)\n"
    "- 70-89: strong fit\n"
    "- 40-69: partial/tangential fit\n"
    "- 0-39: out of scope / wrong domain / violates MUST_AVOID\n\n"
    "label must match score: include>=70, maybe 40-69, exclude<40.\n"
    "If keywords are used in a different domain/context than the chapter, label exclude and score<=10.\n"
    "If ABSTRACT is missing, be conservative: lower confidence and avoid high scores."
)


def _stagec3_rubric_signature(bp: ChapterBlueprint) -> str:
    payload = {
        "scope_statement": bp.scope_statement,
        "must_cover": bp.must_cover,
        "must_avoid": bp.must_avoid,
        "scoring_guidance": bp.scoring_guidance,
        "prompt_version": STAGEC3_PROMPT_VERSION,
        "model": STAGEC3_MODEL,
        "abstract_max_chars": STAGEC3_ABSTRACT_MAX_CHARS,
    }
    return hashlib.sha1(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:8]


def _stagec3_prompt(bp: ChapterBlueprint, *, title: str, abstract: str) -> str:
    scope = bp.scope_statement
    must_cover = bp.must_cover or []
    must_avoid = bp.must_avoid or []
    guidance = bp.scoring_guidance or ""

    abs_txt = (abstract or "").strip()
    if STAGEC3_ABSTRACT_MAX_CHARS and len(abs_txt) > int(STAGEC3_ABSTRACT_MAX_CHARS):
        abs_txt = abs_txt[: int(STAGEC3_ABSTRACT_MAX_CHARS)]

    lines = []
    lines.append("Score this paper for inclusion in the chapter.")
    lines.append("Return only the schema fields.")
    lines.append("")
    lines.append("SCORING")
    lines.append("- score: integer 0-100 (not 0-3); use the full range")
    lines.append("- label must match score: include>=70, maybe 40-69, exclude<40")
    lines.append("- confidence: 0-100 certainty; use low confidence if ABSTRACT is missing")
    lines.append("- if domain/context mismatches the chapter, label exclude and score<=10")
    lines.append("")
    lines.append("RUBRIC")
    lines.append(f"SCOPE: {scope}")
    if guidance:
        lines.append(f"GUIDANCE: {guidance}")
    if must_cover:
        lines.append("MUST_COVER:")
        for b in must_cover:
            lines.append(f"- {b}")
    if must_avoid:
        lines.append("MUST_AVOID:")
        for b in must_avoid:
            lines.append(f"- {b}")
    lines.append("")
    lines.append("PAPER")
    lines.append(f"TITLE: {(title or '').strip()}")
    if abs_txt:
        lines.append(f"ABSTRACT: {abs_txt}")
    else:
        lines.append("ABSTRACT: (missing)")
    lines.append("")
    return "\n".join(lines)


def _minmax_series(x: pd.Series) -> pd.Series:
    v = pd.to_numeric(x, errors="coerce").fillna(0.0)
    mn, mx = float(v.min()), float(v.max())
    return (v - mn) / (mx - mn + 1e-12)


StageC3CallFn = Any


async def stagec3_rerank_topn(
    df_in: pd.DataFrame,
    *,
    blueprints_by_chapter_id: Dict[str, ChapterBlueprint],
    call_rerank_llm: StageC3CallFn,
    topn: int = STAGEC3_TOPN,
    topn_max: int = STAGEC3_TOPN_MAX,
    topn_step: int = STAGEC3_TOPN_STEP,
    min_non_exclude: int = STAGEC3_MIN_NON_EXCLUDE,
    id_col: str = "merge_key",
) -> Tuple[pd.DataFrame, dict]:
    required = ["chapter_id", "title", "abstract", "score_stageC_final"]
    missing = [c for c in required if c not in df_in.columns]
    if missing:
        raise ValueError(f"Missing required columns for Stage C.3: {missing}")

    df = df_in.copy()

    if id_col not in df.columns:
        years = df["year"] if "year" in df.columns else pd.Series([""] * len(df), index=df.index)
        df[id_col] = [
            hashlib.sha1(f"{t}|{y}".encode("utf-8")).hexdigest()[:16]
            for t, y in zip(df["title"].fillna("").astype(str), years.fillna("").astype(str))
        ]

    df["score_llm_rerank_v1"] = np.nan
    df["llm_notes"] = ""
    df["llm_label"] = ""
    df["llm_confidence"] = np.nan

    sem = asyncio.Semaphore(int(STAGEC3_CONCURRENCY))
    t0 = time.time()

    totals = {
        "seconds": 0.0,
        "requests": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "cached_files": 0,
        "topn_used_by_chapter": {},
    }

    async def _run_one(chapter_id: str, doc_id: str, title: str, abstract: str) -> dict:
        bp = blueprints_by_chapter_id[chapter_id]
        sig = _stagec3_rubric_signature(bp)
        cache_dir = STAGEC3_DIR / sig / chapter_id
        cache_dir.mkdir(parents=True, exist_ok=True)
        doc_sig = hashlib.sha1(str(doc_id).encode("utf-8")).hexdigest()[:16]
        cache_path = cache_dir / f"{doc_sig}.json"

        if cache_path.exists() and not STAGEC3_FORCE_RERANK:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            payload["_meta"] = payload.get("_meta") or {}
            payload["_meta"]["llm_cached"] = True
            payload["_meta"]["requests"] = 0
            payload["_meta"]["input_tokens"] = 0
            payload["_meta"]["cached_input_tokens"] = 0
            payload["_meta"]["output_tokens"] = 0
            return payload

        prompt = _stagec3_prompt(bp, title=title, abstract=abstract)
        last_err = None
        for attempt in range(int(STAGEC3_MAX_RETRIES)):
            try:
                async with sem:
                    out = await call_rerank_llm(model=STAGEC3_MODEL, system=STAGEC3_SYSTEM_INSTRUCTIONS, prompt=prompt)

                cache_payload = {
                    "label": str(out.get("label") or ""),
                    "confidence": int(out.get("confidence") or 0),
                    "score": int(out.get("score") or 0),
                    "notes": str(out.get("notes") or ""),
                    "_meta": out.get("_meta") or {},
                }
                cache_payload["_meta"] = {
                    **cache_payload["_meta"],
                    "llm_cached": False,
                    "rubric_sig": sig,
                    "model": STAGEC3_MODEL,
                }
                cache_path.write_text(json.dumps(cache_payload, ensure_ascii=False, indent=2), encoding="utf-8")
                return cache_payload
            except Exception as e:
                last_err = e
                backoff = min(float(STAGEC3_BACKOFF_MAX), float(STAGEC3_BACKOFF_INITIAL) * (2 ** attempt))
                backoff = backoff * (0.75 + 0.5 * random.random())
                await asyncio.sleep(backoff)

        raise RuntimeError(
            f"Stage C.3 rerank failed after retries for chapter_id={chapter_id} doc_id={doc_id}: {last_err}"
        )

    async def _wrapped(ix: int, chapter_id: str, doc_id: str, title: str, abstract: str) -> Tuple[int, dict]:
        payload = await _run_one(chapter_id, doc_id, title, abstract)
        return ix, payload

    ranked: Dict[str, list[int]] = {}
    desired: Dict[str, int] = {}

    for chapter_id, g in df.groupby("chapter_id"):
        cid = str(chapter_id)
        if cid not in blueprints_by_chapter_id:
            raise KeyError(f"Missing blueprint for chapter_id '{cid}'")

        sort_cols = ["score_stageC_final"]
        asc = [False]
        if id_col in g.columns:
            sort_cols.append(id_col)
            asc.append(True)

        ranked[cid] = g.sort_values(sort_cols, ascending=asc, kind="mergesort").index.to_list()
        desired[cid] = int(min(int(topn), len(ranked[cid])))

    enqueued: set[int] = set()

    def _enqueue_upto(cid: str, n: int) -> list[asyncio.Task]:
        tasks_local: list[asyncio.Task] = []
        for ix in ranked[cid][: int(n)]:
            if ix in enqueued:
                continue
            row = df.loc[ix]
            doc_id = str(row[id_col])
            title0 = str(row.get("title") or "")
            abstract0 = str(row.get("abstract") or "")
            tasks_local.append(asyncio.create_task(_wrapped(ix, cid, doc_id, title0, abstract0)))
            enqueued.add(ix)
        return tasks_local

    tasks: list[asyncio.Task] = []
    for cid, n in desired.items():
        tasks.extend(_enqueue_upto(cid, n))

    round_i = 0
    while tasks:
        round_i += 1
        logger.info(
            "[StageC3] Round %s: scoring %s docs | model=%s | concurrency=%s",
            round_i,
            len(tasks),
            STAGEC3_MODEL,
            STAGEC3_CONCURRENCY,
        )

        for fut in asyncio.as_completed(tasks):
            ix, payload = await fut

            df.loc[ix, "score_llm_rerank_v1"] = payload.get("score")
            df.loc[ix, "llm_notes"] = payload.get("notes", "")
            df.loc[ix, "llm_label"] = payload.get("label", "")
            df.loc[ix, "llm_confidence"] = payload.get("confidence")

            m = payload.get("_meta") or {}
            totals["requests"] += int(m.get("requests", 0) or 0)
            totals["input_tokens"] += int(m.get("input_tokens", 0) or 0)
            totals["cached_input_tokens"] += int(m.get("cached_input_tokens", 0) or 0)
            totals["output_tokens"] += int(m.get("output_tokens", 0) or 0)
            totals["cached_files"] += int(bool(m.get("llm_cached", False)))

        expanded_any = False
        for cid, n in list(desired.items()):
            idx = ranked[cid][: int(n)]
            labels = df.loc[idx, "llm_label"].fillna("").astype(str)
            non_ex = int((labels.ne("") & ~labels.eq("exclude")).sum())

            totals["topn_used_by_chapter"][cid] = int(n)

            if non_ex >= int(min_non_exclude):
                continue

            cap = int(min(int(topn_max), len(ranked[cid])))
            if int(n) >= cap:
                continue

            new_n = int(min(cap, int(n) + int(topn_step)))
            desired[cid] = new_n
            expanded_any = True
            logger.info(
                "[StageC3] Expanding chapter '%s': non_exclude=%s < %s -> topn %s->%s",
                cid,
                non_ex,
                min_non_exclude,
                n,
                new_n,
            )

        if not expanded_any:
            break

        tasks = []
        for cid, n in desired.items():
            tasks.extend(_enqueue_upto(cid, n))

    totals["seconds"] = float(time.time() - t0)

    df["_in_topn"] = False
    for cid, n in desired.items():
        df.loc[ranked[cid][: int(n)], "_in_topn"] = True

    df["score_stageC3_topn_final"] = pd.to_numeric(df["score_stageC_final"], errors="coerce").fillna(0.0)
    cite_ok = "score_cite_norm" in df.columns
    if not cite_ok:
        df["score_cite_norm"] = 0.0

    for _, g in df[df["_in_topn"]].groupby("chapter_id"):
        llm_raw = pd.to_numeric(g["score_llm_rerank_v1"], errors="coerce").fillna(0.0)
        labels = df.loc[g.index, "llm_label"].fillna("").astype(str)
        conf = pd.to_numeric(df.loc[g.index, "llm_confidence"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        label_rank = labels.map({"exclude": 0, "maybe": 1, "include": 2}).fillna(0).astype(int).to_numpy(dtype=int)
        label_rank = np.where(conf >= float(STAGEC3_CONFIDENCE_MIN), label_rank, 0)
        llm_raw = llm_raw.where(label_rank > 0, 0.0)
        llm_n = _minmax_series(llm_raw).to_numpy(dtype=float)

        stagec = pd.to_numeric(g["score_stageC_final"], errors="coerce").fillna(0.0).to_numpy(dtype=float)
        cite = pd.to_numeric(g["score_cite_norm"], errors="coerce").fillna(0.0).to_numpy(dtype=float)

        top = pd.DataFrame(
            {
                "ix": g.index.to_list(),
                "doc_id": df.loc[g.index, id_col].fillna("").astype(str).to_list(),
                "label_rank": label_rank,
                "llm_n": llm_n,
                "stagec": stagec,
                "cite": cite,
            }
        )
        top = top.sort_values(
            ["label_rank", "llm_n", "stagec", "cite", "doc_id"],
            ascending=[False, False, False, False, True],
            kind="mergesort",
        )
        boosted = top[top["label_rank"] > 0].copy()
        for r, ix in enumerate(boosted["ix"].tolist()):
            df.loc[ix, "score_stageC3_topn_final"] = 2.0 - (r * 1e-6)

    if not cite_ok:
        df = df.drop(columns=["score_cite_norm"], errors="ignore")

    return df, totals


# -----------------------------
# Stage D: MMR TF-IDF
# -----------------------------

STAGED_ENABLED = True
STAGED_K_SELECT = 20
STAGED_TOPM = 100
STAGED_LAMBDA = 0.6
STAGED_TFIDF_MAX_FEATURES = 20_000


def _build_text(title: str, abstract: str) -> str:
    t = str(title or "").strip()
    a = str(abstract or "").strip()
    return (t + ". " + a).strip()


def add_stagec3_signal_v1(
    df_in: pd.DataFrame,
    *,
    topn: int = STAGEC3_TOPN,
    stagec_col: str = "score_stageC_final",
    llm_col: str = "score_llm_rerank_v1",
    out_col: str = "score_stageC3_signal_v1",
) -> pd.DataFrame:
    df = df_in.copy()
    df[out_col] = pd.to_numeric(df[stagec_col], errors="coerce").fillna(0.0)

    for _cid, g in df.groupby("chapter_id"):
        if "_in_topn" in g.columns:
            idx = g[g["_in_topn"].fillna(False)].index
            if len(idx) == 0:
                idx = g.sort_values(stagec_col, ascending=False, kind="mergesort").head(int(topn)).index
        else:
            idx = g.sort_values(stagec_col, ascending=False, kind="mergesort").head(int(topn)).index
        llm_raw = pd.to_numeric(df.loc[idx, llm_col], errors="coerce").fillna(0.0)
        gate = pd.Series(True, index=idx)
        if "llm_label" in df.columns:
            labels = df.loc[idx, "llm_label"].fillna("").astype(str)
            gate = gate & ~labels.eq("exclude")
        if "llm_confidence" in df.columns:
            conf = pd.to_numeric(df.loc[idx, "llm_confidence"], errors="coerce").fillna(0.0)
            conf_min = float(globals().get("STAGEC3_CONFIDENCE_MIN", 0) or 0)
            if conf_min > 0:
                gate = gate & (conf >= conf_min)

        valid_idx = idx[gate.to_numpy(dtype=bool)]
        if len(valid_idx):
            llm_n_valid = _minmax_series(llm_raw.loc[valid_idx])
            df.loc[valid_idx, out_col] = 1.0 + llm_n_valid
    return df


def mmr_select(relevance: np.ndarray, sim: np.ndarray, k: int, lam: float) -> List[int]:
    n = int(len(relevance))
    if n == 0:
        return []
    k = int(min(k, n))

    chosen: List[int] = []
    remaining = list(range(n))

    first = int(np.argmax(relevance))
    chosen.append(first)
    remaining.remove(first)

    eps = 1e-12
    while len(chosen) < k and remaining:
        best_i = None
        best_score = -1e18
        for i in remaining:
            max_sim = max(float(sim[i, j]) for j in chosen) if chosen else 0.0
            s = float(lam) * float(relevance[i]) - (1.0 - float(lam)) * float(max_sim)
            if (s > best_score + eps) or (abs(s - best_score) <= eps and (best_i is None or int(i) < int(best_i))):
                best_score = s
                best_i = int(i)
        chosen.append(int(best_i))
        remaining.remove(int(best_i))
    return chosen


def add_stageD_mmr_tfidf_v2(
    df_in: pd.DataFrame,
    *,
    baseline_col: str = "score_stageC3_topn_final",
    relevance_col: str = "score_stageC3_signal_v1",
    title_col: str = "title",
    abstract_col: str = "abstract",
    id_col: str = "merge_key",
    topm: int = STAGED_TOPM,
    k_select: int = STAGED_K_SELECT,
    lam: float = STAGED_LAMBDA,
    out_col: str = "score_stageD_final",
) -> pd.DataFrame:
    df = df_in.copy()
    required = ["chapter_id", baseline_col, relevance_col, title_col, abstract_col]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns for Stage D: {missing}")

    df[out_col] = pd.to_numeric(df[baseline_col], errors="coerce").fillna(0.0)

    for _cid, g in df.groupby("chapter_id"):
        g_sorted = g.sort_values(baseline_col, ascending=False, kind="mergesort").head(int(topm)).copy()
        texts = [_build_text(t, a) for t, a in zip(g_sorted[title_col].tolist(), g_sorted[abstract_col].tolist())]
        relevance = pd.to_numeric(g_sorted[relevance_col], errors="coerce").fillna(0.0).to_numpy(dtype=float)

        vec = TfidfVectorizer(
            lowercase=True,
            stop_words="english",
            ngram_range=(1, 2),
            max_features=int(STAGED_TFIDF_MAX_FEATURES),
            min_df=1,
        )
        X = vec.fit_transform(texts)
        sim = cosine_similarity(X, X)
        chosen = mmr_select(relevance, sim, k=int(k_select), lam=float(lam))

        chosen_ix = g_sorted.iloc[chosen].index.to_list()
        chosen_ix = sorted(
            chosen_ix,
            key=lambda ix: (-(float(df.loc[ix, relevance_col] or 0.0)), str(df.loc[ix, id_col] or "")),
        )
        for r, ix in enumerate(chosen_ix):
            df.loc[ix, out_col] = 3.0 - (r * 1e-6)

    return df
