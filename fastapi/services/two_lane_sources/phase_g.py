from __future__ import annotations

import json
import math
from bisect import bisect_right
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from .pipeline import (
    PipelineConfig,
    RunContext,
    _iter_jsonl_dicts,
    _json_default,
    ensure_dir,
    load_metrics,
    read_json,
    save_metrics,
    stage_timer,
    utc_now_iso,
    write_json,
)


def _has_data(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    return True
    except Exception:
        return False
    return False


def _f(x: Any) -> float:
    try:
        return float(x)
    except Exception:
        return 0.0


def _i(x: Any) -> int:
    try:
        return int(x)
    except Exception:
        return 0


def _clip01(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def _softclip(x: float) -> float:
    try:
        x = float(x)
    except Exception:
        return 0.0
    return x if x > 0.0 else 0.0


def compute_match_g1(
    *,
    facet_scores: List[float],
    facet_weights: List[int],
    t: float,
    m: int,
    w_best: float,
    w_topm: float,
    w_cov: float,
) -> Dict[str, float]:
    # Exact Phase G1 aggregation (ported from the notebook)
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


def compute_authority_scores_g2(cands: List[Dict[str, Any]]) -> Dict[str, float]:
    # Exact Phase G2 (practical) implementation (ported from the notebook)
    current_year = int(date.today().year)

    vals: List[float] = []
    cpy_by_id: Dict[str, float] = {}
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
        cpy_by_id[cid] = cpy
        vals.append(cpy)

    vals_pos = sorted(v for v in vals if v > 0)

    def _percentile(x: float) -> float:
        if x <= 0 or not vals_pos:
            return 0.0
        i = bisect_right(vals_pos, x)
        # prevents 1.0; reduces saturation when many candidates have cpy=0
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
        cpy = cpy_by_id.get(cid, 0.0)
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


async def run_phase_g_lane_fusion(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    check_cancel,
) -> Dict[str, Any]:
    if check_cancel is not None:
        await check_cancel()

    stage = "phase_g"

    facet_index_path = run_ctx.run_dir / "facets_index.json"
    if not facet_index_path.exists():
        raise RuntimeError(f"Missing {facet_index_path}. Run Phase F first.")

    facet_index = read_json(facet_index_path)
    facet_ids = list((facet_index.get("facet_ids") or []))
    facet_rows = list((facet_index.get("facets") or []))
    weight_by_fid: Dict[str, int] = {}
    for fr in facet_rows:
        fid = str((fr or {}).get("facet_id") or "").strip()
        if not fid:
            continue
        try:
            weight_by_fid[fid] = int((fr or {}).get("importance_weight") or 1)
        except Exception:
            weight_by_fid[fid] = 1
    facet_weights = [int(weight_by_fid.get(str(fid), 1)) for fid in facet_ids]
    if len(facet_weights) != len(facet_ids):
        facet_weights = (facet_weights + [1] * len(facet_ids))[: len(facet_ids)]

    m = int(getattr(cfg, "match_m", 3))
    w_best = float(getattr(cfg, "match_weight_best", 0.55))
    w_topm = float(getattr(cfg, "match_weight_top_m", 0.25))
    w_cov = float(getattr(cfg, "match_weight_cov", 0.20))
    t_abs = float(getattr(cfg, "scoring_t", 0.30))
    t_noabs = float(getattr(cfg, "scoring_t_noabs", 0.35))

    scores_stage1_path = run_ctx.run_dir / "scores_stage1.jsonl"
    scores_stage2_path = run_ctx.run_dir / "scores_stage2.jsonl"
    shortlists_path = run_ctx.run_dir / "shortlists_stage1.json"

    if not scores_stage1_path.exists():
        raise RuntimeError(f"Missing {scores_stage1_path}. Run Phase F first.")
    if not shortlists_path.exists():
        raise RuntimeError(f"Missing {shortlists_path}. Run Phase F first.")

    candidates_expanded_path = run_ctx.run_dir / "candidates_expanded.jsonl"
    candidates_path = candidates_expanded_path if _has_data(candidates_expanded_path) else Path(run_ctx.artifacts.candidates_normalized_jsonl)

    candidates_by_id: Dict[str, Dict[str, Any]] = {}
    candidates_list: List[Dict[str, Any]] = []
    for c in _iter_jsonl_dicts(candidates_path):
        cid = str(c.get("id") or "").strip()
        if not cid:
            continue
        candidates_by_id[cid] = c
        candidates_list.append(c)

    authority_by_id = compute_authority_scores_g2(candidates_list)

    stage1_by_id: Dict[str, Dict[str, Any]] = {}
    for r in _iter_jsonl_dicts(scores_stage1_path):
        cid = str(r.get("id") or "").strip()
        if not cid:
            continue
        stage1_by_id[cid] = r

    stage2_by_id: Dict[str, Dict[str, Any]] = {}
    if scores_stage2_path.exists():
        for r in _iter_jsonl_dicts(scores_stage2_path):
            cid = str(r.get("id") or "").strip()
            if not cid:
                continue
            stage2_by_id[cid] = r

    shortlists = read_json(shortlists_path)

    ids_needed: List[str] = []
    seen = set()
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            for cid in (shortlists.get(lane, {}).get(pool, []) or []):
                cid = str(cid)
                if cid and cid not in seen:
                    seen.add(cid)
                    ids_needed.append(cid)

    scores_final_by_id: Dict[str, Dict[str, Any]] = {}
    missing_candidates = 0
    missing_stage1 = 0

    with stage_timer(run_ctx, stage):
        for cid in ids_needed:
            c = candidates_by_id.get(cid)
            s1 = stage1_by_id.get(cid)
            s2 = stage2_by_id.get(cid)

            if c is None:
                missing_candidates += 1
                c = {}
            if s1 is None:
                missing_stage1 += 1
                continue

            pool = str((c.get("pool") or s1.get("pool") or "")).strip() or "unknown"

            authority = _f(authority_by_id.get(cid, s1.get("authority")))

            use_stage2 = bool(s2) and pool == "with_abstract"
            if use_stage2:
                stage_used = "stage2"
                facet_scores = list(s2.get("facet_scores_stage2") or [])
                evidence = list(s2.get("evidence_chunks") or [])
            else:
                stage_used = "stage1"
                facet_scores = list(s1.get("facet_scores_stage1") or [])
                evidence = []

            facet_scores = [float(x) if x is not None else 0.0 for x in facet_scores]
            if len(facet_scores) != len(facet_weights):
                if len(facet_scores) > len(facet_weights):
                    facet_scores = facet_scores[: len(facet_weights)]
                else:
                    facet_scores = facet_scores + [0.0] * (len(facet_weights) - len(facet_scores))

            t = float(t_noabs if pool == "without_abstract" else t_abs)
            parts = compute_match_g1(
                facet_scores=facet_scores,
                facet_weights=facet_weights,
                t=t,
                m=m,
                w_best=w_best,
                w_topm=w_topm,
                w_cov=w_cov,
            )
            semantic_stage1 = _f(s1.get("semantic_stage1", s1.get("match_stage1")))
            semantic_stage2 = (
                float(s2.get("semantic_stage2"))
                if use_stage2 and s2.get("semantic_stage2") is not None
                else None
            )
            match = float(semantic_stage2 if semantic_stage2 is not None else semantic_stage1)
            best = float(parts["best"])
            top_m = float(parts["top_m"])
            cov = float(parts["cov"])

            match_lane = 0.80 * match + 0.20 * authority
            authority_lane = 0.80 * authority + 0.20 * match

            title = str(c.get("title") or "")
            doi = str(c.get("doi") or "")
            year = c.get("year") if c.get("year") is not None else s1.get("year")
            citations = _i(c.get("citations") if c.get("citations") is not None else s1.get("citations"))

            scores_final_by_id[cid] = {
                "id": cid,
                "pool": pool,
                "title": title,
                "doi": doi or None,
                "year": year,
                "citations": citations,
                "venue": c.get("venue"),
                "url": c.get("url"),
                "provider_ids": c.get("provider_ids") or {},
                "scores": {
                    "match": match,
                    "authority": authority,
                    "match_lane": match_lane,
                    "authority_lane": authority_lane,
                    "semantic_stage1": semantic_stage1,
                    "semantic_stage2": semantic_stage2,
                    "semantic_source": stage_used,
                    "facet_match_aux": float(parts["match"]),
                    "best": best,
                    "top_m": top_m,
                    "cov": cov,
                },
                "facet_scores": {
                    "stage": stage_used,
                    "scores": facet_scores,
                },
                "evidence_chunks": evidence,
            }

        scores_final_path = run_ctx.run_dir / "scores_final.jsonl"
        ensure_dir(scores_final_path.parent)
        tmp = scores_final_path.with_suffix(scores_final_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for cid in sorted(scores_final_by_id.keys()):
                f.write(json.dumps(scores_final_by_id[cid], ensure_ascii=False, default=_json_default) + "\n")
        tmp.replace(scores_final_path)

        rankings: Dict[str, Dict[str, List[str]]] = {
            "match": {"with_abstract": [], "without_abstract": []},
            "authority": {"with_abstract": [], "without_abstract": []},
        }

        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                ids = [str(x) for x in (shortlists.get(lane, {}).get(pool, []) or [])]

                def _lane_score(cid: str) -> float:
                    r = scores_final_by_id.get(cid) or {}
                    s = (r.get("scores") or {})
                    return _f(s.get("match_lane" if lane == "match" else "authority_lane"))

                ids_sorted = sorted(ids, key=_lane_score, reverse=True)
                rankings[lane][pool] = ids_sorted

        rankings_path = run_ctx.run_dir / "rankings_stageg.json"
        write_json(
            rankings_path,
            {
                "run_id": run_ctx.run_id,
                "generated_at_utc": utc_now_iso(),
                "rankings": rankings,
            },
        )

        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault(stage, {})["artifacts"] = {
            "scores_final_jsonl": str(scores_final_path),
            "rankings_json": str(rankings_path),
        }
        metrics["stages"][stage]["counts"] = {
            "shortlist_unique_ids": len(ids_needed),
            "missing_candidates": missing_candidates,
            "missing_stage1_scores": missing_stage1,
            "stage2_available": len(stage2_by_id),
        }
        save_metrics(run_ctx, metrics)

    if check_cancel is not None:
        await check_cancel()

    return {
        "scores_final_jsonl": str(run_ctx.run_dir / "scores_final.jsonl"),
        "rankings_stageg_json": str(run_ctx.run_dir / "rankings_stageg.json"),
        "shortlist_unique_ids": int(len(ids_needed)),
    }
