from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from .pipeline import (
    PipelineConfig,
    RunContext,
    _iter_jsonl_dicts,
    _json_default,
    _truncate,
    ensure_dir,
    load_metrics,
    log_event,
    read_json,
    save_metrics,
    stage_timer,
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


def _pad_list(xs: List[Any], n: int, fill: Any) -> List[Any]:
    xs = list(xs or [])
    if len(xs) > n:
        return xs[:n]
    if len(xs) < n:
        return xs + [fill] * (n - len(xs))
    return xs


async def run_phase_h_coverage_tags(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    check_cancel,
) -> Dict[str, Any]:
    if check_cancel is not None:
        await check_cancel()

    stage = "phase_h_coverage_tags"

    facet_index_path = run_ctx.run_dir / "facets_index.json"
    scores_final_path = run_ctx.run_dir / "scores_final.jsonl"
    rankings_path = run_ctx.run_dir / "rankings_stageg.json"

    for p in [facet_index_path, scores_final_path, rankings_path]:
        if not p.exists():
            raise RuntimeError(f"Missing {p}. Run Phase F/G first.")

    with stage_timer(run_ctx, stage):
        facet_index = read_json(facet_index_path)
        facet_ids = list((facet_index.get("facet_ids") or []))
        facet_rows = list((facet_index.get("facets") or []))
        if not facet_ids:
            raise RuntimeError(f"Empty facet_ids in {facet_index_path}")

        label_by_fid: Dict[str, str] = {}
        for fr in facet_rows:
            fid = str((fr or {}).get("facet_id") or "").strip()
            if not fid:
                continue
            label_by_fid[fid] = str((fr or {}).get("facet_label_en") or (fr or {}).get("facet_label_de") or fid)

        candidates_expanded_path = run_ctx.run_dir / "candidates_expanded.jsonl"
        candidates_path = candidates_expanded_path if _has_data(candidates_expanded_path) else Path(run_ctx.artifacts.candidates_normalized_jsonl)

        candidates_by_id: Dict[str, Dict[str, Any]] = {}
        for c in _iter_jsonl_dicts(candidates_path):
            cid = str(c.get("id") or "").strip()
            if cid:
                candidates_by_id[cid] = c

        scores_final_by_id: Dict[str, Dict[str, Any]] = {}
        for r in _iter_jsonl_dicts(scores_final_path):
            cid = str(r.get("id") or "").strip()
            if cid:
                scores_final_by_id[cid] = r
        if not scores_final_by_id:
            raise RuntimeError(f"No records found in {scores_final_path}")

        try:
            T_ABS = float(getattr(cfg, "scoring_t", 0.30))
        except Exception:
            T_ABS = 0.30
        try:
            T_NOABS = float(getattr(cfg, "scoring_t_noabs", 0.35))
        except Exception:
            T_NOABS = 0.35

        TOPN_ABS = 2
        TOPN_NOABS = 1

        records_total = 0
        tags_total = 0
        fallback_excerpt_tags = 0
        empty_excerpt_fallbacks = 0
        records_by_pool: Dict[str, int] = {"with_abstract": 0, "without_abstract": 0, "unknown": 0}
        tags_by_pool: Dict[str, int] = {"with_abstract": 0, "without_abstract": 0, "unknown": 0}

        def _excerpt_for_tag(cid: str, r: Dict[str, Any], ix: int) -> str:
            nonlocal fallback_excerpt_tags, empty_excerpt_fallbacks
            ev = list(r.get("evidence_chunks") or [])
            if ix < len(ev):
                e = ev[ix]
                if isinstance(e, str) and e.strip():
                    return _truncate(e.strip(), 240)

            fallback_excerpt_tags += 1
            c = candidates_by_id.get(cid) or {}
            abs_txt = str(c.get("abstract") or "").strip()
            if abs_txt:
                ex = _truncate(abs_txt, 240)
            else:
                title = str(c.get("title") or r.get("title") or "").strip()
                venue = str(c.get("venue") or r.get("venue") or "").strip()
                year = c.get("year") if c.get("year") is not None else r.get("year")
                year_s = str(year).strip() if year is not None and str(year).strip() else ""
                meta = " | ".join([x for x in [title, venue, year_s] if str(x or "").strip()])
                ex = _truncate(meta, 240)

            if not str(ex or "").strip():
                empty_excerpt_fallbacks += 1
                title = str(r.get("title") or c.get("title") or "").strip()
                ex = _truncate(title, 240)
            return str(ex or "").strip()

        for cid, r in scores_final_by_id.items():
            records_total += 1
            pool = str(r.get("pool") or "").strip() or "unknown"
            if pool not in records_by_pool:
                records_by_pool[pool] = 0
                tags_by_pool[pool] = 0
            records_by_pool[pool] = int(records_by_pool.get(pool, 0) or 0) + 1

            fs_obj = r.get("facet_scores") or {}
            if not isinstance(fs_obj, dict):
                fs_obj = {}
            raw_scores = list((fs_obj.get("scores") or []))
            scores = [_f(x) for x in raw_scores]
            scores = _pad_list(scores, len(facet_ids), 0.0)
            fs_obj["scores"] = scores
            r["facet_scores"] = fs_obj

            ev = _pad_list(list(r.get("evidence_chunks") or []), len(facet_ids), None)
            r["evidence_chunks"] = ev

            if pool == "with_abstract":
                T = float(T_ABS)
                topN = int(TOPN_ABS)
            elif pool == "without_abstract":
                T = float(T_NOABS)
                topN = int(TOPN_NOABS)
            else:
                T = float(T_ABS)
                topN = int(TOPN_ABS)

            covered = {i for i, s in enumerate(scores) if float(s) >= float(T)}
            idxs_sorted = sorted(range(len(facet_ids)), key=lambda i: (-float(scores[i]), str(facet_ids[i])))
            for i in idxs_sorted[: max(0, int(topN))]:
                covered.add(i)

            tags: List[Dict[str, Any]] = []
            for i in sorted(covered):
                if i >= len(facet_ids):
                    continue
                fid = str(facet_ids[i])
                tags.append(
                    {
                        "facet_id": fid,
                        "facet_label_en": str(label_by_fid.get(fid) or fid),
                        "score": float(scores[i]),
                        "excerpt": _excerpt_for_tag(cid, r, i),
                    }
                )

            tags_sorted = sorted(tags, key=lambda t: (-float(t.get("score") or 0.0), str(t.get("facet_id") or "")))
            r["coverage_tags"] = tags_sorted

            tags_total += len(tags_sorted)
            tags_by_pool[pool] = int(tags_by_pool.get(pool, 0) or 0) + len(tags_sorted)

        coverage_tags_path = run_ctx.run_dir / "coverage_tags.jsonl"
        ensure_dir(coverage_tags_path.parent)
        tmp = coverage_tags_path.with_suffix(coverage_tags_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for cid in sorted(scores_final_by_id.keys()):
                rr = scores_final_by_id[cid]
                f.write(
                    json.dumps(
                        {
                            "id": cid,
                            "pool": rr.get("pool"),
                            "coverage_tags": (rr.get("coverage_tags") or []),
                        },
                        ensure_ascii=False,
                        default=_json_default,
                    )
                    + "\n"
                )
        tmp.replace(coverage_tags_path)

        tmp2 = scores_final_path.with_suffix(scores_final_path.suffix + ".tmp")
        with tmp2.open("w", encoding="utf-8") as f:
            for cid in sorted(scores_final_by_id.keys()):
                f.write(json.dumps(scores_final_by_id[cid], ensure_ascii=False, default=_json_default) + "\n")
        tmp2.replace(scores_final_path)

        log_event(
            run_ctx,
            stage=stage,
            event="cache_write",
            provider="coverage_tags",
            path=str(coverage_tags_path),
            records=records_total,
            tags=tags_total,
        )

        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault(stage, {})["counts"] = {
            "records_scored_final": int(records_total),
            "coverage_tags_total": int(tags_total),
            "records_by_pool": records_by_pool,
            "tags_by_pool": tags_by_pool,
            "fallback_excerpt_tags": int(fallback_excerpt_tags),
            "empty_excerpt_fallbacks": int(empty_excerpt_fallbacks),
            "scores_final_jsonl": str(scores_final_path),
            "coverage_tags_jsonl": str(coverage_tags_path),
        }
        save_metrics(run_ctx, metrics)

    if check_cancel is not None:
        await check_cancel()

    return {
        "records_scored_final": int(records_total),
        "coverage_tags_total": int(tags_total),
        "coverage_tags_jsonl": str(run_ctx.run_dir / "coverage_tags.jsonl"),
    }

