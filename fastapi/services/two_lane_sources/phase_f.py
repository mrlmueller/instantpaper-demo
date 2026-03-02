from __future__ import annotations

import asyncio
import json
import math
import re
import time
from array import array
from bisect import bisect_right
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from .pipeline import (
    PipelineConfig,
    QueryPlan,
    RunContext,
    TwoLaneOpenAI,
    _iter_jsonl_dicts,
    _json_default,
    _truncate,
    append_jsonl,
    ensure_dir,
    load_metrics,
    log_event,
    read_json,
    save_metrics,
    stable_hash,
    stage_timer,
    utc_now_iso,
    write_json,
)


def _clip01(x: float) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def _softclip(x: float) -> float:
    return float(x) if x > 0 else 0.0


def _f32_norm(vec: array) -> float:
    s = 0.0
    for x in vec:
        s += float(x) * float(x)
    return math.sqrt(s) if s > 0 else 0.0


def _f32_dot(a: array, b: array) -> float:
    s = 0.0
    for x, y in zip(a, b):
        s += float(x) * float(y)
    return s


def _cos(a: array, inv_norm_a: float, b: array, inv_norm_b: float) -> float:
    if inv_norm_a <= 0 or inv_norm_b <= 0:
        return 0.0
    return _f32_dot(a, b) * inv_norm_a * inv_norm_b


def _text_hash(text: str) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    return stable_hash(s, length=24)


async def embed_texts_dedup(
    *,
    run_ctx: RunContext,
    cfg: PipelineConfig,
    llm: TwoLaneOpenAI,
    texts: List[str],
    model: str,
    kind: str,
    stage: str,
) -> Tuple[List[array], Dict[str, Any]]:
    hashes = [_text_hash(t) for t in texts]
    positions_by_hash: Dict[str, List[int]] = {}
    for i, h in enumerate(hashes):
        positions_by_hash.setdefault(h, []).append(i)

    items = sorted(positions_by_hash.items(), key=lambda kv: kv[0])
    unique_texts = [texts[pos_list[0]] for _h, pos_list in items]

    vecs_unique, meta = await llm.embed_texts(
        stage=stage,
        operation_type="quellen_finder_two_lane_embeddings",
        model=model,
        texts=unique_texts,
        batch_size=int(cfg.embedding_batch_size or 256),
        operation_details={"kind": str(kind)},
    )

    out: List[Optional[array]] = [None] * len(texts)
    for (_h, pos_list), v in zip(items, vecs_unique):
        for i in pos_list:
            out[i] = v

    vecs_final = [v for v in out if v is not None]
    if len(vecs_final) != len(out):
        raise RuntimeError("Embedding pipeline produced missing vectors.")

    stats = {
        "texts": int(len(texts)),
        "unique_hashes": int(len(items)),
        "model": str(model),
        "kind": str(kind),
        "api_calls": int(meta.get("api_calls") or 0),
        "batches": int(meta.get("batches") or 0),
        "prompt_tokens": int(meta.get("prompt_tokens") or 0),
        "cost_usd": float(meta.get("cost_usd") or 0.0),
    }

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["embeddings"] = stats
    save_metrics(run_ctx, metrics)

    return vecs_final, stats


def facet_embed_text(f: Any, *, lang: str) -> str:
    if lang == "en":
        terms = []
        try:
            terms = list((f.canonical_terms.en or []))  # type: ignore[attr-defined]
        except Exception:
            terms = []
        return (str(getattr(f, "text_en", "") or "")).strip() + "\nCanonical terms: " + ", ".join(terms)
    terms = []
    try:
        terms = list((f.canonical_terms.de or []))  # type: ignore[attr-defined]
    except Exception:
        terms = []
    return (str(getattr(f, "text_de", "") or "")).strip() + "\nKanonische Begriffe: " + ", ".join(terms)


def candidate_meta_view(c: Dict[str, Any], *, rich: bool = False) -> str:
    title = (c.get("title") or "").strip()
    venue = (c.get("venue") or "").strip()
    year = c.get("year")
    doi = (c.get("doi") or "").strip()
    url = (c.get("url") or "").strip()
    authors = c.get("authors") or []
    authors_s = ", ".join([a for a in authors[:12] if a])
    ext = c.get("external_ids") or {}
    lang = c.get("language") or ""

    lines = [
        f"Title: {title}",
        f"Venue: {venue}",
        f"Year: {year or ''}",
        f"Authors: {authors_s}",
    ]
    if rich:
        if doi:
            lines.append(f"DOI: {doi}")
        if ext.get("arxiv"):
            lines.append(f"arXiv: {ext.get('arxiv')}")
        if ext.get("pmid"):
            lines.append(f"PMID: {ext.get('pmid')}")
        if ext.get("pmcid"):
            lines.append(f"PMCID: {ext.get('pmcid')}")
        if lang:
            lines.append(f"Language: {lang}")
        if url:
            lines.append(f"URL: {url}")

    return "\n".join([ln for ln in lines if ln and not ln.endswith(": ")])


def compute_match(
    *,
    facet_scores: List[float],
    facet_weights: List[int],
    t: float,
    m: int,
    w_best: float,
    w_topm: float,
    w_cov: float,
) -> Dict[str, float]:
    assert len(facet_scores) == len(facet_weights)
    if not facet_scores:
        return {"best": 0.0, "top_m": 0.0, "cov": 0.0, "match": 0.0}

    g = [float(w) * float(s) for w, s in zip(facet_weights, facet_scores)]
    best = (max(g) / 5.0) if g else 0.0

    idxs = sorted(range(len(g)), key=lambda i: g[i], reverse=True)[: max(1, int(m))]
    num = sum(g[i] for i in idxs)
    den = sum(float(facet_weights[i]) for i in idxs) or 1.0
    top_m = num / den

    wsum = sum(float(w) for w in facet_weights) or 1.0
    cov_num = 0.0
    for w, s in zip(facet_weights, facet_scores):
        cov_num += float(w) * _softclip(float(s) - float(t))
    cov = cov_num / wsum

    match = float(w_best) * best + float(w_topm) * top_m + float(w_cov) * cov
    return {"best": best, "top_m": top_m, "cov": cov, "match": match}


def compute_authority_scores(cands: List[Dict[str, Any]]) -> Dict[str, float]:
    current_year = int(date.today().year)

    vals: List[float] = []
    per_id: Dict[str, float] = {}
    for c in cands:
        cid = str(c.get("id") or "")
        citations = int(c.get("citations") or 0)
        year = c.get("year")
        try:
            y = int(year) if year is not None else None
        except Exception:
            y = None
        if not y:
            age_years = 10
        else:
            age_years = max(1, current_year - y + 1)
        cpy = float(citations) / float(age_years)
        per_id[cid] = cpy
        vals.append(cpy)

    vals_pos = sorted(v for v in vals if v > 0)

    def _percentile(x: float) -> float:
        if x <= 0 or not vals_pos:
            return 0.0
        i = bisect_right(vals_pos, x)
        return float(i) / float(len(vals_pos) + 1)

    def _recency(y: Optional[int]) -> float:
        if not y:
            return 0.5
        z = (float(y) - float(current_year - 5)) / 2.0
        try:
            return 1.0 / (1.0 + math.exp(-z))
        except Exception:
            return 0.5

    review_terms = [
        "review",
        "survey",
        "handbook",
        "overview",
        "introduction",
        "handbuch",
        "überblick",
        "ueberblick",
        "einführung",
        "einfuehrung",
    ]

    out: Dict[str, float] = {}
    for c in cands:
        cid = str(c.get("id") or "")
        cpy = per_id.get(cid, 0.0)
        c_norm = _percentile(cpy)

        year = c.get("year")
        try:
            y = int(year) if year is not None else None
        except Exception:
            y = None
        rec = _recency(y)

        bonus = 0.0
        title = str(c.get("title") or "").casefold()
        if any(t in title for t in review_terms):
            bonus += 0.05
        if c.get("venue_is_core") is True:
            bonus += 0.03

        auth = _clip01(0.85 * float(c_norm) + 0.15 * float(rec) + float(bonus))
        out[cid] = auth

    return out


def chunk_abstract(text: str, *, target_min: int = 250, target_max: int = 400) -> List[str]:
    t = re.sub(r"\s+", " ", str(text or "").strip())
    max_abs_chars = 6000
    t = t[:max_abs_chars]
    if not t:
        return []

    sents = re.split(r"(?<=[.!?])\s+", t)
    sents = [s.strip() for s in sents if s.strip()]
    if not sents:
        return [t[:target_max]]

    chunks: List[str] = []
    i = 0
    while i < len(sents):
        cur = sents[i]
        j = i + 1
        while j < len(sents) and (len(cur) + 1 + len(sents[j])) <= target_max:
            cur = cur + " " + sents[j]
            j += 1

        if len(cur) < target_min and j < len(sents):
            if (len(cur) + 1 + len(sents[j])) <= target_max:
                cur = cur + " " + sents[j]
                j += 1

        if len(cur) > target_max:
            cur = cur[:target_max]

        chunks.append(cur)
        if j <= i + 1:
            i = j
        else:
            i = j - 1

    out: List[str] = []
    for c in chunks:
        if not out or c != out[-1]:
            out.append(c)
    return out


def s2_recommendations_expand(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    seeds: List[str],
    limit: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Fetch S2 recommendations (paperIds), hydrate via graph /paper/batch, and return paper dicts."""

    recs_path = run_ctx.artifacts.semanticscholar_recommendations_jsonl

    already: Dict[str, set[str]] = {}
    try:
        for rec in _iter_jsonl_dicts(recs_path):
            sp = str(rec.get("seed_paperId") or "")
            rp = str(rec.get("paperId") or "")
            if sp and rp:
                already.setdefault(sp, set()).add(rp)
    except Exception:
        already = {}

    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
    if cfg.semanticscholar_api_key:
        session.headers.update({"x-api-key": cfg.semanticscholar_api_key})

    def _req_json(method: str, url: str, *, params=None, body=None, max_attempts: int = 8) -> Any:
        attempt = 0
        backoff = 1.0
        while True:
            attempt += 1
            try:
                r = session.request(method, url, params=params, json=body, timeout=float(cfg.semanticscholar_timeout_s))
                if r.status_code in (429, 500, 502, 503, 504):
                    raise RuntimeError(f"status={r.status_code}")
                if r.status_code >= 400:
                    raise RuntimeError(f"S2 HTTP {r.status_code}: {r.text[:400]}")
                return r.json()
            except Exception:
                if attempt >= max_attempts:
                    raise
                time.sleep(min(60.0, backoff))
                backoff *= 2.0

    rec_base = "https://api.semanticscholar.org/recommendations/v1/papers"

    fetched = 0
    new_ids: List[str] = []

    for sp in seeds:
        have = already.get(sp, set())
        if len(have) >= int(limit):
            continue

        time.sleep(max(0.0, 1.0 / float(cfg.semanticscholar_rps or 1.0)))

        data = _req_json(
            "POST",
            rec_base,
            params={"limit": int(limit), "fields": "paperId"},
            body={"positivePaperIds": [sp], "negativePaperIds": []},
        )

        recs = []
        if isinstance(data, dict) and isinstance(data.get("recommendedPapers"), list):
            recs = data.get("recommendedPapers") or []
        elif isinstance(data, list):
            recs = data

        rank = 0
        for it in recs:
            if not isinstance(it, dict):
                continue
            pid = it.get("paperId")
            if not pid:
                continue
            pid_s = str(pid)
            if pid_s in have:
                continue
            rank += 1
            have.add(pid_s)
            new_ids.append(pid_s)
            fetched += 1
            append_jsonl(
                recs_path,
                {
                    "ts": utc_now_iso(),
                    "seed_paperId": sp,
                    "paperId": pid_s,
                    "rank": rank,
                },
            )
        already[sp] = have

    hydrated: List[Dict[str, Any]] = []
    if new_ids:
        base = cfg.semanticscholar_base_url.rstrip("/")
        batch_url = base + "/paper/batch"
        fields = "paperId,title,year,authors,venue,url,externalIds,citationCount,influentialCitationCount,abstract"

        uniq = list(dict.fromkeys(new_ids))
        for chunk in [uniq[i : i + 500] for i in range(0, len(uniq), 500)]:
            time.sleep(max(0.0, 1.0 / float(cfg.semanticscholar_rps or 1.0)))
            data = _req_json("POST", batch_url, params={"fields": fields}, body={"ids": chunk}, max_attempts=10)
            if isinstance(data, list):
                hydrated.extend([x for x in data if isinstance(x, dict)])
            elif isinstance(data, dict) and isinstance(data.get("data"), list):
                hydrated.extend([x for x in data.get("data") if isinstance(x, dict)])

    return hydrated, {"seeds": len(seeds), "new_recommendations": fetched, "hydrated": len(hydrated)}


def _norm_doi_recs(x: Any) -> Optional[str]:
    if not x:
        return None
    s = str(x).strip()
    s = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("/").lower()
    if not s:
        return None
    if s.startswith("10."):
        return s
    m = re.search(r"10\.[0-9]{4,9}/[^\s]+", s)
    return (m.group(0).lower().rstrip(".")) if m else None


def _norm_title_recs(x: Any) -> str:
    s = str(x or "").casefold()
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _first_author_lastname_recs(authors: List[str]) -> str:
    if not authors:
        return ""
    a = str(authors[0] or "").strip()
    if not a:
        return ""
    parts = re.split(r"\s+", a)
    last = parts[-1] if parts else ""
    last = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\-']+", "", last)
    return last.casefold()


def _dedup_keys_recs(c: Dict[str, Any]) -> List[str]:
    keys: List[str] = []
    doi = _norm_doi_recs(c.get("doi"))
    ext = c.get("external_ids") or {}
    arxiv = ext.get("arxiv")
    pmid = ext.get("pmid")
    pmcid = ext.get("pmcid")

    if doi:
        keys.append(f"doi:{doi}")
    if arxiv:
        keys.append(f"arxiv:{str(arxiv).strip().lower()}")
    if pmid:
        keys.append(f"pmid:{str(pmid).strip()}")
    if pmcid:
        keys.append(f"pmcid:{str(pmcid).strip().upper()}")

    t = _norm_title_recs(c.get("title") or "")
    y = c.get("year")
    try:
        y = int(y) if y is not None else None
    except Exception:
        y = None
    ln = _first_author_lastname_recs(c.get("authors") or [])
    if t and y and ln:
        keys.append(f"fallback:{t}|{y}|{ln}")

    pri = {"doi": 0, "arxiv": 1, "pmid": 2, "pmcid": 3, "fallback": 4}
    return sorted(set(keys), key=lambda k: (pri.get(k.split(":", 1)[0], 99), k))


def _merge_candidate_dict_recs(dst: Dict[str, Any], src: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(dst)

    a = (out.get("abstract") or "").strip()
    b = (src.get("abstract") or "").strip()
    if a and b:
        out["abstract"] = a if len(a) >= len(b) else b
    else:
        out["abstract"] = a or b or None

    for k in ["title", "venue", "url"]:
        va = (out.get(k) or "").strip()
        vb = (src.get(k) or "").strip()
        if vb and (not va or len(vb) > len(va)):
            out[k] = vb

    ya = out.get("year")
    yb = src.get("year")
    if (ya is None or ya == "") and isinstance(yb, int):
        out["year"] = yb

    out["doi"] = _norm_doi_recs(out.get("doi") or src.get("doi"))

    ext2 = dict(out.get("external_ids") or {})
    for k, v in (src.get("external_ids") or {}).items():
        if v and (k not in ext2 or not ext2.get(k) or len(str(v)) > len(str(ext2.get(k)))):
            ext2[k] = v
    out["external_ids"] = ext2

    a_auth = out.get("authors") or []
    b_auth = src.get("authors") or []
    if len(b_auth) > len(a_auth):
        out["authors"] = b_auth

    pids = {k: list(v) for k, v in (out.get("provider_ids") or {}).items()}
    for k, vs in (src.get("provider_ids") or {}).items():
        pids.setdefault(k, [])
        pids[k].extend(list(vs or []))
        seen2 = set()
        uniq: List[str] = []
        for x in pids[k]:
            x = str(x or "").strip()
            if not x or x in seen2:
                continue
            seen2.add(x)
            uniq.append(x)
        pids[k] = uniq
    out["provider_ids"] = pids

    out["intents"] = sorted(set((out.get("intents") or []) + (src.get("intents") or [])))

    try:
        out["citations"] = max(int(out.get("citations") or 0), int(src.get("citations") or 0))
    except Exception:
        out["citations"] = int(out.get("citations") or 0)

    abs_txt = (out.get("abstract") or "").strip()
    out["pool"] = "with_abstract" if abs_txt else "without_abstract"

    if out.get("venue_is_core") is True or src.get("venue_is_core") is True:
        out["venue_is_core"] = True
    elif out.get("venue_is_core") is False or src.get("venue_is_core") is False:
        out["venue_is_core"] = False
    else:
        out["venue_is_core"] = None

    return out


def _paper_to_candidate_recs(p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    title = (p.get("title") or "").strip()
    if not title:
        return None

    ext = p.get("externalIds") or {}
    doi = _norm_doi_recs(ext.get("DOI"))

    external_ids: Dict[str, str] = {}
    if ext.get("ArXiv"):
        external_ids["arxiv"] = str(ext.get("ArXiv")).strip().lower()
    if ext.get("PubMed"):
        external_ids["pmid"] = re.sub(r"\D+", "", str(ext.get("PubMed")))
    if ext.get("PubMedCentral"):
        pmc = str(ext.get("PubMedCentral")).strip().upper()
        if pmc and not pmc.startswith("PMC"):
            pmc = "PMC" + pmc
        external_ids["pmcid"] = pmc

    authors = []
    for a in (p.get("authors") or [])[:80]:
        if isinstance(a, dict) and a.get("name"):
            authors.append(str(a.get("name")).strip())
    authors = [a for a in authors if a]

    abstract = (p.get("abstract") or "").strip() or None
    pool = "with_abstract" if abstract else "without_abstract"

    pid = (p.get("paperId") or "").strip()

    cid = doi or ("pmid:" + external_ids["pmid"] if external_ids.get("pmid") else None)
    if not cid:
        cid = "cand_" + stable_hash(title, str(p.get("year") or ""), length=24)

    year = p.get("year")
    year = int(year) if isinstance(year, int) else None

    return {
        "id": cid,
        "doi": doi,
        "external_ids": external_ids,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": (p.get("venue") or "").strip() or None,
        "venue_is_core": None,
        "url": (p.get("url") or "").strip() or None,
        "language": None,
        "languages": [],
        "abstract": abstract,
        "provider_ids": {"semanticscholar": [pid] if pid else []},
        "intents": ["match"],
        "citations": int(p.get("citationCount") or 0),
        "influential_citations": int(p.get("influentialCitationCount") or 0),
        "pool": pool,
    }


def merge_recommendation_papers(
    *,
    candidates: List[Dict[str, Any]],
    papers: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    index: Dict[str, str] = {}
    merged_by_id: Dict[str, Dict[str, Any]] = {str(c.get("id") or ""): dict(c) for c in candidates}

    for cid0, c0 in merged_by_id.items():
        for k in _dedup_keys_recs(c0):
            index[k] = cid0

    new_added = 0
    merged = 0

    for p in papers:
        cand = _paper_to_candidate_recs(p)
        if not cand:
            continue
        keys = _dedup_keys_recs(cand)
        hit = None
        for k in keys:
            if k in index:
                hit = index[k]
                break
        if hit is None:
            merged_by_id[cand["id"]] = cand
            for k in keys:
                index[k] = cand["id"]
            new_added += 1
        else:
            merged_by_id[hit] = _merge_candidate_dict_recs(merged_by_id[hit], cand)
            merged += 1

    return list(merged_by_id.values()), {"new_candidates_added": int(new_added), "merged_into_existing": int(merged)}


async def run_phase_f_embeddings_and_scoring(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    force_rebuild: bool,
    check_cancel,
) -> Dict[str, Any]:
    if check_cancel is not None:
        await check_cancel()

    plan = QueryPlan.model_validate(read_json(run_ctx.artifacts.query_plan_json))
    facets = list(plan.facets)
    facet_ids = [f.facet_id for f in facets]
    facet_weights = [int(f.importance_weight) for f in facets]

    candidates = list(_iter_jsonl_dicts(Path(run_ctx.artifacts.candidates_normalized_jsonl)))
    if not candidates:
        raise RuntimeError("No candidates found. Run Phase E first.")

    facet_index_path = run_ctx.run_dir / "facets_index.json"
    write_json(
        facet_index_path,
        {
            "facet_ids": facet_ids,
            "facets": [
                {
                    "facet_id": f.facet_id,
                    "facet_label_en": f.facet_label_en,
                    "facet_label_de": f.facet_label_de,
                    "importance_weight": int(f.importance_weight),
                    "facet_type": f.facet_type,
                }
                for f in facets
            ],
        },
    )

    # F2: facet embeddings
    facet_texts: List[str] = []
    facet_meta: List[Dict[str, Any]] = []
    for f in facets:
        for lang in ["en", "de"]:
            facet_texts.append(facet_embed_text(f, lang=lang))
            facet_meta.append({"facet_id": f.facet_id, "lang": lang})

    if check_cancel is not None:
        await check_cancel()
    with stage_timer(run_ctx, "phase_f_facet_embeddings"):
        facet_vecs, facet_embed_stats = await embed_texts_dedup(
            run_ctx=run_ctx,
            cfg=cfg,
            llm=llm,
            texts=facet_texts,
            model=str(cfg.embedding_model),
            kind="facet",
            stage="phase_f_facet_embeddings",
        )

    facet_en: Dict[str, array] = {}
    facet_de: Dict[str, array] = {}
    facet_en_invnorm: Dict[str, float] = {}
    facet_de_invnorm: Dict[str, float] = {}
    for meta, vec in zip(facet_meta, facet_vecs):
        fid = str(meta["facet_id"])
        lang = str(meta["lang"])
        inv = 1.0 / (_f32_norm(vec) or 1.0)
        if lang == "en":
            facet_en[fid] = vec
            facet_en_invnorm[fid] = inv
        else:
            facet_de[fid] = vec
            facet_de_invnorm[fid] = inv

    # F3/F7: metadata embeddings + stage1 scoring
    meta_texts: List[str] = []
    for c in candidates:
        pool = str(c.get("pool") or "")
        meta_texts.append(candidate_meta_view(c, rich=(pool == "without_abstract")))

    if check_cancel is not None:
        await check_cancel()
    with stage_timer(run_ctx, "phase_f_metadata_embeddings"):
        meta_vecs, meta_embed_stats = await embed_texts_dedup(
            run_ctx=run_ctx,
            cfg=cfg,
            llm=llm,
            texts=meta_texts,
            model=str(cfg.embedding_model),
            kind="meta",
            stage="phase_f_metadata_embeddings",
        )

    meta_embed_stats_recs: Optional[Dict[str, Any]] = None

    authority_by_id = compute_authority_scores(candidates)
    stage1_records: List[Dict[str, Any]] = []

    with stage_timer(run_ctx, "phase_f_stage1_scoring"):
        for c, v_meta in zip(candidates, meta_vecs):
            cid = str(c.get("id") or "")
            pool = str(c.get("pool") or "")
            inv_meta = 1.0 / (_f32_norm(v_meta) or 1.0)

            scores: List[float] = []
            for f in facets:
                fid = f.facet_id
                s_en = _cos(facet_en[fid], facet_en_invnorm[fid], v_meta, inv_meta)
                s_de = _cos(facet_de[fid], facet_de_invnorm[fid], v_meta, inv_meta)
                scores.append(max(float(s_en), float(s_de)))

            t = float(cfg.scoring_t_noabs if pool == "without_abstract" else cfg.scoring_t)
            parts = compute_match(
                facet_scores=scores,
                facet_weights=facet_weights,
                t=t,
                m=int(cfg.match_m),
                w_best=float(cfg.match_weight_best),
                w_topm=float(cfg.match_weight_top_m),
                w_cov=float(cfg.match_weight_cov),
            )

            match = float(parts["match"])
            auth = float(authority_by_id.get(cid, 0.0))
            match_lane = 0.80 * match + 0.20 * auth
            authority_lane = 0.80 * auth + 0.20 * match

            stage1_records.append(
                {
                    "id": cid,
                    "pool": pool,
                    "year": c.get("year"),
                    "citations": int(c.get("citations") or 0),
                    "match_stage1": match,
                    "authority": auth,
                    "match_lane": match_lane,
                    "authority_lane": authority_lane,
                    "best": float(parts["best"]),
                    "top_m": float(parts["top_m"]),
                    "cov": float(parts["cov"]),
                    "facet_scores_stage1": scores,
                }
            )

    # F4: Semantic Scholar neighbor-search booster (recommendations expansion)
    seed_count = int(cfg.s2_neighbor_seed_count or 0)
    recs_limit = int(cfg.s2_recs_limit_per_seed or 0)

    recs_stats: Dict[str, Any] = {"enabled": False}
    candidates_expanded_path: Optional[Path] = None
    expanded_candidates = candidates

    if seed_count > 0 and recs_limit > 0:
        recs_stats["enabled"] = True

        cand_by_id_tmp = {str(c.get("id") or ""): c for c in candidates}

        def _s2_pid(cid: str) -> Optional[str]:
            c = cand_by_id_tmp.get(cid) or {}
            pids = (c.get("provider_ids") or {}).get("semanticscholar") or []
            return str(pids[0]) if pids else None

        rows_sorted = sorted(
            stage1_records,
            key=lambda r: (0 if str(r.get("pool") or "") == "with_abstract" else 1, -float(r.get("match_lane") or 0.0)),
        )

        seeds: List[str] = []
        seen = set()
        for r in rows_sorted:
            cid = str(r.get("id") or "")
            sp = _s2_pid(cid)
            if not sp or sp in seen:
                continue
            seen.add(sp)
            seeds.append(sp)
            if len(seeds) >= seed_count:
                break

        if seeds:
            if check_cancel is not None:
                await check_cancel()
            with stage_timer(run_ctx, "phase_f_s2_recommendations"):
                papers, recs_stats2 = await asyncio.to_thread(
                    s2_recommendations_expand,
                    cfg=cfg,
                    run_ctx=run_ctx,
                    seeds=seeds,
                    limit=recs_limit,
                )
            recs_stats.update(recs_stats2)

            expanded_candidates, merge_stats = merge_recommendation_papers(candidates=candidates, papers=papers)
            recs_stats.update(merge_stats)

            candidates_expanded_path = run_ctx.run_dir / "candidates_expanded.jsonl"
            tmpx = candidates_expanded_path.with_suffix(candidates_expanded_path.suffix + ".tmp")
            with tmpx.open("w", encoding="utf-8") as f:
                for cc in expanded_candidates:
                    f.write(json.dumps(cc, ensure_ascii=False, default=_json_default) + "\n")
            tmpx.replace(candidates_expanded_path)

            existing_ids = {str(r.get("id") or "") for r in stage1_records}
            new_ids = [str(c.get("id") or "") for c in expanded_candidates if str(c.get("id") or "") not in existing_ids]

            if new_ids:
                new_set = set(new_ids)
                new_cands = [c for c in expanded_candidates if str(c.get("id") or "") in new_set]
                new_meta_texts = []
                for c in new_cands:
                    pool = str(c.get("pool") or "")
                    new_meta_texts.append(candidate_meta_view(c, rich=(pool == "without_abstract")))

                if check_cancel is not None:
                    await check_cancel()
                new_vecs, stats_new = await embed_texts_dedup(
                    run_ctx=run_ctx,
                    cfg=cfg,
                    llm=llm,
                    texts=new_meta_texts,
                    model=str(cfg.embedding_model),
                    kind="meta_recs",
                    stage="phase_f_metadata_embeddings",
                )
                meta_embed_stats_recs = stats_new

                for c, v_meta in zip(new_cands, new_vecs):
                    cid = str(c.get("id") or "")
                    pool = str(c.get("pool") or "")
                    inv_meta = 1.0 / (_f32_norm(v_meta) or 1.0)

                    scores: List[float] = []
                    for f in facets:
                        fid = f.facet_id
                        s_en = _cos(facet_en[fid], facet_en_invnorm[fid], v_meta, inv_meta)
                        s_de = _cos(facet_de[fid], facet_de_invnorm[fid], v_meta, inv_meta)
                        scores.append(max(float(s_en), float(s_de)))

                    t = float(cfg.scoring_t_noabs if pool == "without_abstract" else cfg.scoring_t)
                    parts = compute_match(
                        facet_scores=scores,
                        facet_weights=facet_weights,
                        t=t,
                        m=int(cfg.match_m),
                        w_best=float(cfg.match_weight_best),
                        w_topm=float(cfg.match_weight_top_m),
                        w_cov=float(cfg.match_weight_cov),
                    )

                    stage1_records.append(
                        {
                            "id": cid,
                            "pool": pool,
                            "year": c.get("year"),
                            "citations": int(c.get("citations") or 0),
                            "match_stage1": float(parts["match"]),
                            "authority": 0.0,
                            "match_lane": 0.0,
                            "authority_lane": 0.0,
                            "best": float(parts["best"]),
                            "top_m": float(parts["top_m"]),
                            "cov": float(parts["cov"]),
                            "facet_scores_stage1": scores,
                        }
                    )

            candidates = expanded_candidates
            authority_by_id = compute_authority_scores(candidates)
            for r in stage1_records:
                cid = str(r.get("id") or "")
                match = float(r.get("match_stage1") or 0.0)
                auth = float(authority_by_id.get(cid, 0.0))
                r["authority"] = auth
                r["match_lane"] = 0.80 * match + 0.20 * auth
                r["authority_lane"] = 0.80 * auth + 0.20 * match

    # Persist stage1 scores
    scores_stage1_path = run_ctx.run_dir / "scores_stage1.jsonl"
    tmp_s1 = scores_stage1_path.with_suffix(scores_stage1_path.suffix + ".tmp")
    with tmp_s1.open("w", encoding="utf-8") as f:
        for r in stage1_records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    tmp_s1.replace(scores_stage1_path)

    # F5: Prune after Stage 1
    n1_with_abs = int(cfg.prune_n1)
    n1_no_abs = int(getattr(cfg, "prune_n1_without_abstract", 300) or 300)

    intents_by_id = {str(c.get("id") or ""): set(c.get("intents") or []) for c in candidates}

    cand_by_id = {str(c.get("id") or ""): c for c in candidates}
    anchors_all_prune: List[str] = []
    try:
        anchors_all_prune = list((plan.primary_context_anchors.en or [])) + list((plan.primary_context_anchors.de or []))
    except Exception:
        anchors_all_prune = []
    anchors_all_prune = [a for a in anchors_all_prune if str(a or "").strip()]

    def _anchor_hit_meta(cid: str) -> bool:
        if not anchors_all_prune:
            return False
        c = cand_by_id.get(cid) or {}
        text = f"{c.get('title') or ''} {c.get('venue') or ''} {c.get('year') or ''}".casefold()
        for a in anchors_all_prune:
            aa = str(a or "").casefold().strip()
            if aa and aa in text:
                return True
        return False

    noabs_auth_min_match = 0.22

    shortlists: Dict[str, Dict[str, List[str]]] = {
        "match": {"with_abstract": [], "without_abstract": []},
        "authority": {"with_abstract": [], "without_abstract": []},
    }

    available_total = {"match": {"with_abstract": 0, "without_abstract": 0}, "authority": {"with_abstract": 0, "without_abstract": 0}}
    available_after_gate = {"match": {"with_abstract": 0, "without_abstract": 0}, "authority": {"with_abstract": 0, "without_abstract": 0}}
    kept_intent_mix = {
        "match": {
            "with_abstract": {"match_only": 0, "authority_only": 0, "both": 0, "none": 0},
            "without_abstract": {"match_only": 0, "authority_only": 0, "both": 0, "none": 0},
        },
        "authority": {
            "with_abstract": {"match_only": 0, "authority_only": 0, "both": 0, "none": 0},
            "without_abstract": {"match_only": 0, "authority_only": 0, "both": 0, "none": 0},
        },
    }

    pool_by_id = {str(r.get("id") or "").strip(): str(r.get("pool") or "").strip() for r in stage1_records if str(r.get("id") or "").strip()}

    def _intent_bucket(cid: str) -> str:
        intents = intents_by_id.get(str(cid), set())
        has_match = "match" in intents
        has_auth = "authority" in intents
        if has_match and has_auth:
            return "both"
        if has_match:
            return "match_only"
        if has_auth:
            return "authority_only"
        return "none"

    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            keep = n1_with_abs if pool == "with_abstract" else n1_no_abs
            key = f"{lane}_lane"

            rows = [r for r in stage1_records if str(r.get("pool") or "") == pool]
            available_total[lane][pool] = len(rows)

            if lane == "authority" and pool == "without_abstract":
                rows = [
                    r
                    for r in rows
                    if float(r.get("match_stage1") or 0.0) >= noabs_auth_min_match or _anchor_hit_meta(str(r.get("id") or ""))
                ]

            available_after_gate[lane][pool] = len(rows)
            rows_sorted = sorted(rows, key=lambda x: float(x.get(key) or 0.0), reverse=True)
            ids = [str(r.get("id") or "").strip() for r in rows_sorted[:keep] if str(r.get("id") or "").strip()]

            seen2 = set()
            ids2: List[str] = []
            for cid in ids:
                if cid and cid not in seen2:
                    seen2.add(cid)
                    ids2.append(cid)
            shortlists[lane][pool] = ids2

            mix = {"match_only": 0, "authority_only": 0, "both": 0, "none": 0}
            for cid in ids2:
                b = _intent_bucket(cid)
                mix[b] = int(mix.get(b, 0)) + 1
            kept_intent_mix[lane][pool] = mix

    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = list(shortlists.get(lane, {}).get(pool, []) or [])
            keep = n1_with_abs if pool == "with_abstract" else n1_no_abs
            assert len(ids) <= keep, f"shortlist longer than keep in {lane}/{pool}: {len(ids)} > {keep}"
            assert len(ids) == len(set(ids)), f"duplicate ids in shortlist {lane}/{pool}"
            bad_missing = [cid for cid in ids if str(cid) not in pool_by_id]
            assert not bad_missing, f"shortlist id missing from stage1_records in {lane}/{pool}: {bad_missing[:5]}"
            bad_pool = [cid for cid in ids if pool_by_id.get(str(cid)) != pool]
            assert not bad_pool, f"pool leak detected in {lane}/{pool}: {bad_pool[:5]}"

    shortlists_path = run_ctx.run_dir / "shortlists_stage1.json"
    write_json(shortlists_path, shortlists)

    # F6: Stage 2 (with_abstract shortlist only)
    stage2_ids = set(shortlists["match"]["with_abstract"]) | set(shortlists["authority"]["with_abstract"])
    record_by_id = {str(r.get("id") or ""): r for r in stage1_records}

    chunk_texts: List[str] = []
    chunk_owner: List[Tuple[str, int]] = []

    for cid in sorted(stage2_ids):
        c = cand_by_id.get(cid) or {}
        abstract = (c.get("abstract") or "").strip()
        if not abstract:
            continue
        chunks = chunk_abstract(abstract)[:25]
        for j, ch in enumerate(chunks):
            chunk_texts.append(ch)
            chunk_owner.append((cid, j))

    stage2_records: Dict[str, Dict[str, Any]] = {}
    chunk_embed_stats: Optional[Dict[str, Any]] = None

    if chunk_texts:
        if check_cancel is not None:
            await check_cancel()
        with stage_timer(run_ctx, "phase_f_chunk_embeddings"):
            chunk_vecs, chunk_embed_stats = await embed_texts_dedup(
                run_ctx=run_ctx,
                cfg=cfg,
                llm=llm,
                texts=chunk_texts,
                model=str(cfg.embedding_model),
                kind="chunk",
                stage="phase_f_chunk_embeddings",
            )

        chunks_by_cid: Dict[str, List[Tuple[str, array]]] = {}
        for (cid, _j), txt, vec in zip(chunk_owner, chunk_texts, chunk_vecs):
            chunks_by_cid.setdefault(cid, []).append((txt, vec))

        with stage_timer(run_ctx, "phase_f_stage2_scoring"):
            for cid, items in chunks_by_cid.items():
                chunk_inv: List[float] = [1.0 / (_f32_norm(v) or 1.0) for _txt, v in items]

                facet_scores2: List[float] = []
                evidence: List[Optional[str]] = []

                for f in facets:
                    fid = f.facet_id
                    scores_this_facet: List[float] = []
                    best_s = -1e9
                    best_chunk = None

                    for (txt, v), inv_v in zip(items, chunk_inv):
                        s_en = _cos(facet_en[fid], facet_en_invnorm[fid], v, inv_v)
                        s_de = _cos(facet_de[fid], facet_de_invnorm[fid], v, inv_v)
                        s = max(float(s_en), float(s_de))
                        scores_this_facet.append(s)
                        if s > best_s:
                            best_s = s
                            best_chunk = txt

                    scores_this_facet.sort(reverse=True)
                    if len(scores_this_facet) >= 2:
                        agg = 0.5 * (scores_this_facet[0] + scores_this_facet[1])
                    elif scores_this_facet:
                        agg = scores_this_facet[0]
                    else:
                        agg = 0.0

                    facet_scores2.append(float(agg))
                    evidence.append(_truncate(best_chunk, 240) if best_chunk else None)

                parts2 = compute_match(
                    facet_scores=facet_scores2,
                    facet_weights=facet_weights,
                    t=float(cfg.scoring_t),
                    m=int(cfg.match_m),
                    w_best=float(cfg.match_weight_best),
                    w_topm=float(cfg.match_weight_top_m),
                    w_cov=float(cfg.match_weight_cov),
                )

                stage2_records[cid] = {
                    "id": cid,
                    "facet_scores_stage2": facet_scores2,
                    "evidence_chunks": evidence,
                    "match_stage2": float(parts2["match"]),
                    "best2": float(parts2["best"]),
                    "top_m2": float(parts2["top_m"]),
                    "cov2": float(parts2["cov"]),
                }

        for cid, r2 in stage2_records.items():
            r1 = record_by_id.get(cid)
            if not r1:
                continue
            match2 = float(r2.get("match_stage2") or 0.0)
            auth = float(r1.get("authority") or 0.0)
            r1["match"] = match2
            r1["match_lane"] = 0.80 * match2 + 0.20 * auth
            r1["authority_lane"] = 0.80 * auth + 0.20 * match2
            r1["facet_scores_stage2"] = r2.get("facet_scores_stage2")

        for lane in ["match", "authority"]:
            ids = shortlists[lane]["with_abstract"]
            ids_sorted = sorted(ids, key=lambda cid: float(record_by_id.get(cid, {}).get(f"{lane}_lane") or 0.0), reverse=True)
            shortlists[lane]["with_abstract"] = ids_sorted

        write_json(shortlists_path, shortlists)

    scores_stage2_path = run_ctx.run_dir / "scores_stage2.jsonl"
    tmp_s2 = scores_stage2_path.with_suffix(scores_stage2_path.suffix + ".tmp")
    with tmp_s2.open("w", encoding="utf-8") as f:
        for cid in sorted(stage2_records.keys()):
            f.write(json.dumps(stage2_records[cid], ensure_ascii=False) + "\n")
    tmp_s2.replace(scores_stage2_path)

    # Metrics
    emb_rows = [facet_embed_stats, meta_embed_stats]
    if meta_embed_stats_recs is not None:
        emb_rows.append(meta_embed_stats_recs)
    if chunk_embed_stats is not None:
        emb_rows.append(chunk_embed_stats)
    tokens_total = sum(int(r.get("prompt_tokens") or 0) for r in emb_rows)
    cost_total = sum(float(r.get("cost_usd") or 0.0) for r in emb_rows)

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault("phase_f", {})["embeddings"] = {
        "facet": facet_embed_stats,
        "meta": meta_embed_stats,
        "meta_recs": meta_embed_stats_recs,
        "chunk": chunk_embed_stats,
    }
    metrics["stages"]["phase_f"]["embeddings_total"] = {
        "prompt_tokens": int(tokens_total),
        "cost_usd_est": float(cost_total),
    }
    metrics["stages"]["phase_f"]["counts"] = {
        "candidates": len(candidates),
        "facets": len(facets),
        "stage2_candidates": len(stage2_ids),
        "stage2_scored": len(stage2_records),
        "recs": recs_stats,
        "prune": {
            "available_total": available_total,
            "available_after_gate": available_after_gate,
            "kept": {
                lane: {
                    pool: len(shortlists.get(lane, {}).get(pool, []) or [])
                    for pool in ["with_abstract", "without_abstract"]
                }
                for lane in ["match", "authority"]
            },
            "kept_intent_mix": kept_intent_mix,
        },
        "artifacts": {
            "facets_index_json": str(facet_index_path),
            "scores_stage1_jsonl": str(scores_stage1_path),
            "scores_stage2_jsonl": str(scores_stage2_path),
            "shortlists_stage1_json": str(shortlists_path),
            "candidates_expanded_jsonl": (str(candidates_expanded_path) if candidates_expanded_path else None),
        },
    }
    save_metrics(run_ctx, metrics)

    _ = force_rebuild
    return metrics["stages"]["phase_f"]["counts"]
