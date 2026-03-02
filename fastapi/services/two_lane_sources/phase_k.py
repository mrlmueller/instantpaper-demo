from __future__ import annotations

import json
import subprocess
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .pipeline import (
    PipelineConfig,
    RunContext,
    _iter_jsonl_dicts,
    _truncate,
    stable_hash,
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


def _git_head(repo_root: Path) -> Optional[str]:
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL)
            .strip()
            or None
        )
    except Exception:
        return None


def _git_dirty(repo_root: Path) -> Optional[bool]:
    try:
        out = subprocess.check_output(["git", "status", "--porcelain"], cwd=str(repo_root), text=True, stderr=subprocess.DEVNULL)
        return bool(str(out or "").strip())
    except Exception:
        return None


async def run_phase_k_output(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    chapter_title: str,
    chapter_spec_text: str,
    top_n: int,
    check_cancel,
    force_rebuild: bool = True,
) -> Dict[str, Any]:
    if check_cancel is not None:
        await check_cancel()

    stage = "phase_k_output"
    output_path = Path(run_ctx.artifacts.output_json)

    if not force_rebuild and output_path.exists():
        try:
            out0 = json.loads(output_path.read_text(encoding="utf-8"))
            if isinstance(out0, dict) and str(out0.get("schema_version") or "") == "two_lane_output_v1":
                if int(out0.get("top_n") or 0) == int(top_n):
                    return {
                        "output_json": str(output_path),
                        "rankings_used_json": str(out0.get("artifacts", {}).get("rankings_used_json") or ""),
                        "rerank_rows_loaded": int(out0.get("rerank_rows_loaded") or 0),
                        "top_n": int(out0.get("top_n") or int(top_n)),
                        "cache_hit": True,
                    }
        except Exception:
            pass

    facet_index_path = run_ctx.run_dir / "facets_index.json"
    scores_final_path = run_ctx.run_dir / "scores_final.jsonl"
    rankings_i_path = run_ctx.run_dir / "rankings_stagei.json"
    rankings_g_path = run_ctx.run_dir / "rankings_stageg.json"

    if not facet_index_path.exists():
        raise RuntimeError(f"Missing {facet_index_path}. Run Phase F first.")
    if not scores_final_path.exists():
        raise RuntimeError(f"Missing {scores_final_path}. Run Phase G first.")

    rankings_path = rankings_i_path if rankings_i_path.exists() else rankings_g_path
    if not rankings_path.exists():
        raise RuntimeError(f"Missing {rankings_path}. Run Phase G (Phase I optional) first.")

    candidates_expanded_path = run_ctx.run_dir / "candidates_expanded.jsonl"
    candidates_path = candidates_expanded_path if _has_data(candidates_expanded_path) else Path(run_ctx.artifacts.candidates_normalized_jsonl)
    if not candidates_path.exists():
        raise RuntimeError(f"Missing candidates file: {candidates_path}. Run Phase E/F first.")

    rerank_path = Path(run_ctx.artifacts.rerank_results_jsonl)

    TOP_N = int(top_n)
    classic_year_max = int(getattr(cfg, "authority_classic_year_max", 2004) or 2004)
    recent_year_window = int(getattr(cfg, "authority_recent_year_window", 8) or 8)
    bucket_quotas = dict(getattr(cfg, "authority_bucket_quotas", {}) or {})

    facet_index = json.loads(facet_index_path.read_text(encoding="utf-8"))
    facet_ids = [str(x) for x in (facet_index.get("facet_ids") or [])]
    facets = list((facet_index.get("facets") or []))
    label_by_fid = {
        str(f.get("facet_id")): str(f.get("facet_label_en") or f.get("facet_label_de") or f.get("facet_id"))
        for f in facets
        if isinstance(f, dict) and f.get("facet_id")
    }

    scores_by_id: Dict[str, Dict[str, Any]] = {}
    for r in _iter_jsonl_dicts(scores_final_path):
        cid = str(r.get("id") or "").strip()
        if cid:
            scores_by_id[cid] = r
    if not scores_by_id:
        raise RuntimeError(f"No records found in {scores_final_path}")

    candidates_by_id: Dict[str, Dict[str, Any]] = {}
    for c in _iter_jsonl_dicts(candidates_path):
        cid = str(c.get("id") or "").strip()
        if cid:
            candidates_by_id[cid] = c

    rerank_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
    rerank_loaded = 0
    if rerank_path.exists() and _has_data(rerank_path):
        for rec in _iter_jsonl_dicts(rerank_path):
            cid = str(rec.get("id") or "").strip()
            lane = str(rec.get("lane") or "").strip()
            pool = str(rec.get("pool") or "").strip()
            rr = rec.get("rerank")
            if cid and lane and pool and isinstance(rr, dict):
                rerank_by_key[(cid, lane, pool)] = rr
                rerank_loaded += 1

    rankings_obj = json.loads(rankings_path.read_text(encoding="utf-8"))
    rankings = rankings_obj.get("rankings") or {}

    def _pool_of(cid: str) -> str:
        c = candidates_by_id.get(cid) or {}
        p = str(c.get("pool") or "").strip()
        if p:
            return p
        r = scores_by_id.get(cid) or {}
        return str(r.get("pool") or "").strip()

    def _year_of(cid: str) -> Optional[int]:
        c = candidates_by_id.get(cid) or {}
        y = c.get("year")
        if y is None:
            y = (scores_by_id.get(cid) or {}).get("year")
        try:
            return int(y) if y is not None and str(y).strip() else None
        except Exception:
            return None

    def _bucket_for_year(y: Optional[int]) -> str:
        if not y:
            return "mid"
        current_year = int(date.today().year)
        recent_min = int(current_year - int(recent_year_window))
        if int(y) <= int(classic_year_max):
            return "classic"
        if int(y) >= int(recent_min):
            return "recent"
        return "mid"

    def _select_authority_primary(ids_ranked: List[str]) -> Tuple[List[str], Dict[str, int], Dict[str, int]]:
        ids_ranked = [str(x) for x in (ids_ranked or []) if str(x or "").strip()]
        avail = {"classic": 0, "recent": 0, "mid": 0}
        for cid in ids_ranked:
            b = _bucket_for_year(_year_of(cid))
            avail[b] = int(avail.get(b) or 0) + 1

        selected: List[str] = []
        selected_set = set()
        picked = {"classic": 0, "recent": 0, "mid": 0}

        order = ["classic", "recent", "mid"]
        for b in order:
            q = int(bucket_quotas.get(b, 0) or 0)
            if q <= 0:
                continue
            for cid in ids_ranked:
                if len(selected) >= TOP_N:
                    break
                if cid in selected_set:
                    continue
                if _bucket_for_year(_year_of(cid)) != b:
                    continue
                selected.append(cid)
                selected_set.add(cid)
                picked[b] = int(picked.get(b) or 0) + 1
                if int(picked.get(b) or 0) >= q:
                    break
            if len(selected) >= TOP_N:
                break

        for cid in ids_ranked:
            if len(selected) >= TOP_N:
                break
            if cid in selected_set:
                continue
            selected.append(cid)
            selected_set.add(cid)

        return selected, picked, avail

    def _card(cid: str, lane: str, pool: str) -> Dict[str, Any]:
        c = candidates_by_id.get(cid) or {}
        r = scores_by_id.get(cid) or {}

        provider_ids = c.get("provider_ids") or r.get("provider_ids") or {}
        providers = [k for k, vs in (provider_ids or {}).items() if vs]
        provider = None
        if len(providers) == 1:
            provider = providers[0]
        elif len(providers) > 1:
            provider = "mixed"

        tags_in = list(r.get("coverage_tags") or [])
        tags: List[Dict[str, Any]] = []
        for t in tags_in:
            if not isinstance(t, dict):
                continue
            fid = str(t.get("facet_id") or "").strip()
            if not fid:
                continue
            tags.append(
                {
                    "facet_id": fid,
                    "facet_label_en": str(t.get("facet_label_en") or label_by_fid.get(fid) or fid),
                    "score": float(t.get("score") or 0.0),
                    "excerpt": _truncate(str(t.get("excerpt") or "").strip(), 240),
                }
            )
        tags = sorted(tags, key=lambda x: (-float(x.get("score") or 0.0), str(x.get("facet_id") or "")))

        rr = rerank_by_key.get((cid, lane, pool))
        if isinstance(rr, dict):
            rr = {
                "llm_score_0_100": int(rr.get("llm_score_0_100") or 0),
                "covered_facets": list(rr.get("covered_facets") or []),
                "rationale": _truncate(str(rr.get("rationale") or "").strip(), 800),
                "insufficient_info": bool(rr.get("insufficient_info")),
            }
        else:
            rr = None

        abstract = str(c.get("abstract") or "").strip()
        abstract_out = abstract if abstract else None

        citations = int(c.get("citations") or r.get("citations") or 0)
        infl = int(c.get("influential_citations") or 0)

        return {
            "id": cid,
            "doi": c.get("doi") or r.get("doi"),
            "title": c.get("title") or r.get("title") or "",
            "authors": list(c.get("authors") or []),
            "year": c.get("year") if c.get("year") is not None else r.get("year"),
            "venue": c.get("venue") if c.get("venue") is not None else r.get("venue"),
            "url": c.get("url") if c.get("url") is not None else r.get("url"),
            "language": c.get("language") if c.get("language") is not None else r.get("language"),
            "abstract": abstract_out,
            "citations": citations,
            "influential_citations": infl,
            "citation_metrics": {"citations": citations, "influential_citations": infl},
            "provider": provider,
            "provider_ids": provider_ids,
            "external_ids": c.get("external_ids") or {},
            "sources": list(c.get("sources") or []),
            "pool": pool,
            "scores": r.get("scores") or {},
            "coverage_tags": tags,
            "rerank": rr,
        }

    final_rankings: Dict[str, Dict[str, List[str]]] = {
        "match": {"with_abstract": [], "without_abstract": []},
        "authority": {"with_abstract": [], "without_abstract": []},
    }
    top_cards: Dict[str, Dict[str, List[Dict[str, Any]]]] = {
        "match": {"with_abstract": [], "without_abstract": []},
        "authority": {"with_abstract": [], "without_abstract": []},
    }
    authority_bucket_meta: Dict[str, Dict[str, Dict[str, int]]] = {"with_abstract": {}, "without_abstract": {}}

    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = [str(x) for x in (rankings.get(lane, {}).get(pool, []) or [])]
            ids = [cid for cid in ids if _pool_of(cid) == pool]
            final_rankings[lane][pool] = ids

            if lane == "authority":
                primary_ids, picked, avail = _select_authority_primary(ids)
                authority_bucket_meta[pool] = {"picked": picked, "available": avail}
            else:
                primary_ids = ids[:TOP_N]

            top_cards[lane][pool] = [_card(cid, lane, pool) for cid in primary_ids]

    git_head = _git_head(run_ctx.repo_root)
    git_dirty = _git_dirty(run_ctx.repo_root)
    cfg_masked = cfg.model_dump(mode="json")
    for k in ("openai_api_key", "openalex_api_key", "semanticscholar_api_key"):
        if k in cfg_masked:
            cfg_masked[k] = None
    cfg_hash = stable_hash(json.dumps(cfg_masked, ensure_ascii=False, sort_keys=True), length=24) if cfg_masked else None

    output_obj: Dict[str, Any] = {
        "schema_version": "two_lane_output_v1",
        "run_id": run_ctx.run_id,
        "generated_at_utc": utc_now_iso(),
        "pipeline_version": getattr(cfg, "pipeline_version", "two_lane_v1"),
        "chapter_title": chapter_title,
        "chapter_spec_text": chapter_spec_text,
        "git": {"head": git_head, "dirty": git_dirty},
        "config_hash": cfg_hash,
        "artifacts": {
            "candidates_jsonl": str(candidates_path),
            "scores_final_jsonl": str(scores_final_path),
            "rerank_results_jsonl": (str(rerank_path) if rerank_path.exists() else None),
            "rankings_used_json": str(rankings_path),
            "output_json": str(run_ctx.artifacts.output_json),
        },
        "facets": facets,
        "rankings": final_rankings,
        "top": top_cards,
        "authority_lane": {
            "with_abstract": {"primary_top_20": top_cards["authority"]["with_abstract"], "coverage_top_up": []},
            "without_abstract": {"primary_top_20": top_cards["authority"]["without_abstract"], "coverage_top_up": []},
            "time_stratification": {
                "classic_year_max": int(classic_year_max),
                "recent_year_window": int(recent_year_window),
                "bucket_quotas": bucket_quotas,
                "meta": authority_bucket_meta,
            },
        },
        "match_lane": {
            "with_abstract": {"primary_top_20": top_cards["match"]["with_abstract"], "coverage_top_up": []},
            "without_abstract": {"primary_top_20": top_cards["match"]["without_abstract"], "coverage_top_up": []},
        },
        "top_n": int(TOP_N),
        "rerank_rows_loaded": int(rerank_loaded),
    }

    write_json(output_path, output_obj)

    if check_cancel is not None:
        await check_cancel()

    return {
        "output_json": str(output_path),
        "rankings_used_json": str(rankings_path),
        "rerank_rows_loaded": int(rerank_loaded),
        "top_n": int(TOP_N),
    }
