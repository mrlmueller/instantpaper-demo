from __future__ import annotations

import asyncio
import json
import random
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .pipeline import (
    PipelineConfig,
    RunContext,
    TwoLaneBudgetExceeded,
    TwoLaneOpenAI,
    _iter_jsonl_dicts,
    _json_default,
    _truncate,
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


def _coerce_str_list(x: Any) -> List[str]:
    if not isinstance(x, list):
        return []
    out: List[str] = []
    for v in x:
        s = str(v or "").strip()
        if s:
            out.append(s)
    return out


def _truncate_i(text: Any, max_len: int = 240) -> str:
    t = str(text or "").strip()
    if len(t) <= max_len:
        return t
    return t[: max(0, max_len - 1)].rstrip() + "…"


def _should_retry(exc: Exception) -> bool:
    msg = str(exc)
    if isinstance(exc, json.JSONDecodeError):
        return True
    if "429" in msg or "rate limit" in msg.lower():
        return True
    if "timeout" in msg.lower() or "timed out" in msg.lower():
        return True
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return True
    return False


async def run_phase_i_rerank(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    chapter_title: str,
    check_cancel,
    force_rebuild: bool = True,
) -> Dict[str, Any]:
    if check_cancel is not None:
        await check_cancel()

    stage = "phase_i_rerank"

    facet_index_path = run_ctx.run_dir / "facets_index.json"
    scores_final_path = run_ctx.run_dir / "scores_final.jsonl"
    rankings_g_path = run_ctx.run_dir / "rankings_stageg.json"

    if not facet_index_path.exists():
        raise RuntimeError(f"Missing {facet_index_path}. Run Phase F first.")
    if not scores_final_path.exists():
        raise RuntimeError(f"Missing {scores_final_path}. Run Phase G first.")
    if not rankings_g_path.exists():
        raise RuntimeError(f"Missing {rankings_g_path}. Run Phase G first.")

    model_rerank = str(getattr(cfg, "openai_model_rerank", "gpt-5-nano") or "gpt-5-nano").strip()
    if model_rerank == "gpt-5.2":
        raise ValueError("Rerank model 'gpt-5.2' is disabled for cost reasons. Use gpt-5-nano or gpt-5-mini.")

    K = int(getattr(cfg, "rerank_top_k_pre", 40) or 40)
    CONCURRENCY = int(getattr(cfg, "rerank_concurrency", 20) or 20)
    RETRIES = 3

    rankings_i_path = run_ctx.run_dir / "rankings_stagei.json"
    rerank_results_path = Path(run_ctx.artifacts.rerank_results_jsonl)

    if not force_rebuild and rerank_results_path.exists() and _has_data(rerank_results_path) and rankings_i_path.exists():
        try:
            metrics0 = load_metrics(run_ctx)
            cached_model = (
                (((metrics0.get("stages") or {}).get(stage) or {}).get("counts") or {}).get("model_used")
                if isinstance(metrics0, dict)
                else None
            )
            if cached_model and str(cached_model).strip() and str(cached_model).strip() != model_rerank:
                # Settings changed: do not treat cached rerank as valid.
                pass
            else:
                return {
                    "rerank_results_jsonl": str(rerank_results_path),
                    "rankings_stagei_json": str(rankings_i_path),
                    "tasks_total": None,
                    "api_calls": 0,
                    "failures": 0,
                    "cost_usd_new": 0.0,
                    "cache_hit": True,
                }
        except Exception:
            return {
                "rerank_results_jsonl": str(rerank_results_path),
                "rankings_stagei_json": str(rankings_i_path),
                "tasks_total": None,
                "api_calls": 0,
                "failures": 0,
                "cost_usd_new": 0.0,
                "cache_hit": True,
            }

    with stage_timer(run_ctx, stage):
        facet_index = read_json(facet_index_path)
        facet_ids = [str(x) for x in (facet_index.get("facet_ids") or [])]
        facets = list((facet_index.get("facets") or []))
        label_by_fid = {
            str(f.get("facet_id")): str(f.get("facet_label_en") or f.get("facet_label_de") or f.get("facet_id"))
            for f in facets
            if isinstance(f, dict) and f.get("facet_id")
        }
        weight_by_fid = {
            str(f.get("facet_id")): int(f.get("importance_weight") or 0)
            for f in facets
            if isinstance(f, dict) and f.get("facet_id")
        }

        required_facet_rows = []
        for fid in facet_ids:
            w = int(weight_by_fid.get(fid) or 0)
            if w >= 4:
                required_facet_rows.append({"facet_id": fid, "label_en": label_by_fid.get(fid, fid), "weight": w})

        candidates_expanded_path = run_ctx.run_dir / "candidates_expanded.jsonl"
        candidates_path = candidates_expanded_path if _has_data(candidates_expanded_path) else Path(run_ctx.artifacts.candidates_normalized_jsonl)

        candidates_by_id: Dict[str, Dict[str, Any]] = {}
        if candidates_path.exists():
            for c in _iter_jsonl_dicts(candidates_path):
                cid = str(c.get("id") or "").strip()
                if cid:
                    candidates_by_id[cid] = c

        scores_by_id: Dict[str, Dict[str, Any]] = {}
        for r in _iter_jsonl_dicts(scores_final_path):
            cid = str(r.get("id") or "").strip()
            if cid:
                scores_by_id[cid] = r
        if not scores_by_id:
            raise RuntimeError(f"No records in {scores_final_path}")

        T_ABS = float(getattr(cfg, "scoring_t", 0.30) or 0.30)
        T_NOABS = float(getattr(cfg, "scoring_t_noabs", 0.35) or 0.35)

        def _compute_coverage_tags_fallback(r: Dict[str, Any]) -> List[Dict[str, Any]]:
            pool = str(r.get("pool") or "").strip() or "with_abstract"
            topN = 2 if pool == "with_abstract" else 1
            T = T_ABS if pool == "with_abstract" else T_NOABS

            sc = (r.get("facet_scores") or {}).get("scores")
            scores = list(sc) if isinstance(sc, list) else []
            if len(scores) < len(facet_ids):
                scores = scores + [0.0] * (len(facet_ids) - len(scores))
            if len(scores) > len(facet_ids):
                scores = scores[: len(facet_ids)]

            ev = r.get("evidence_chunks")
            evidence = list(ev) if isinstance(ev, list) else []
            if len(evidence) < len(facet_ids):
                evidence = evidence + [None] * (len(facet_ids) - len(evidence))
            if len(evidence) > len(facet_ids):
                evidence = evidence[: len(facet_ids)]

            idx_sorted = sorted(range(len(scores)), key=lambda i: float(scores[i] or 0.0), reverse=True)
            top_idxs = set(idx_sorted[:topN])
            covered = {i for i, s in enumerate(scores) if float(s or 0.0) >= T}.union(top_idxs)

            tags: List[Dict[str, Any]] = []
            cid = str(r.get("id") or "").strip()
            c = candidates_by_id.get(cid) or {}
            title = str(c.get("title") or r.get("title") or "").strip()
            venue = str(c.get("venue") or r.get("venue") or "").strip()
            year = c.get("year") if c.get("year") is not None else r.get("year")
            abstract = str(c.get("abstract") or "").strip()

            for i in covered:
                fid = facet_ids[i]
                excerpt = None
                if i < len(evidence) and isinstance(evidence[i], str) and evidence[i].strip():
                    excerpt = evidence[i]
                if not excerpt:
                    if abstract:
                        excerpt = abstract
                    else:
                        excerpt = f"{title} | {venue} | {year or ''}".strip(" |")
                excerpt = _truncate_i(excerpt, 240)
                if not excerpt:
                    excerpt = _truncate_i(title, 240)
                tags.append(
                    {
                        "facet_id": fid,
                        "facet_label_en": label_by_fid.get(fid, fid),
                        "score": float(scores[i] or 0.0),
                        "excerpt": excerpt,
                    }
                )

            tags.sort(key=lambda t: (-float(t.get("score") or 0.0), str(t.get("facet_id") or "")))
            return tags

        for _cid, _r in scores_by_id.items():
            if not isinstance(_r.get("coverage_tags"), list) or len(_r.get("coverage_tags") or []) == 0:
                _r["coverage_tags"] = _compute_coverage_tags_fallback(_r)

        rankings_g = read_json(rankings_g_path)
        rankings = rankings_g.get("rankings") or {}

        tasks: List[Tuple[str, str, str]] = []
        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                ids = list((((rankings.get(lane) or {}).get(pool)) or []))
                for cid in ids[:K]:
                    cids = str(cid or "").strip()
                    if cids:
                        tasks.append((cids, lane, pool))

        if not tasks:
            raise RuntimeError("No rerank tasks found. rankings_stageg.json appears empty.")

        tasks_set = {(str(cid), str(lane), str(pool)) for cid, lane, pool in tasks}

        cached_rows: List[Dict[str, Any]] = []
        cached_keys = set()
        cache_hits = 0
        bad_cache = 0
        tokens_in_cached = 0
        tokens_cached_in_cached = 0
        tokens_out_cached = 0
        cost_cached = 0.0
        latencies_cached: List[float] = []

        if not force_rebuild and rerank_results_path.exists() and _has_data(rerank_results_path):
            for row in _iter_jsonl_dicts(rerank_results_path):
                cid = str(row.get("id") or "").strip()
                lane = str(row.get("lane") or "").strip()
                pool = str(row.get("pool") or "").strip()
                key = (cid, lane, pool)
                if not cid or not lane or not pool or key not in tasks_set:
                    continue

                rr = row.get("rerank")
                if not isinstance(rr, dict):
                    bad_cache += 1
                    continue

                openai_meta = row.get("openai") if isinstance(row.get("openai"), dict) else None
                cached_model_used = (
                    str((openai_meta or {}).get("model_used") or (openai_meta or {}).get("model_requested") or "").strip()
                    if isinstance(openai_meta, dict)
                    else ""
                )
                if cached_model_used and cached_model_used != model_rerank:
                    bad_cache += 1
                    continue

                if key in cached_keys:
                    continue
                cached_keys.add(key)
                cache_hits += 1

                usage = (openai_meta or {}).get("usage") if isinstance(openai_meta, dict) else {}
                if isinstance(usage, dict):
                    tokens_in_cached += int(usage.get("input_tokens") or 0)
                    tokens_cached_in_cached += int(usage.get("cached_input_tokens") or 0)
                    tokens_out_cached += int(usage.get("output_tokens") or 0)
                if isinstance(openai_meta, dict):
                    cost_cached += float(openai_meta.get("cost_usd") or 0.0)
                    try:
                        lat = float(openai_meta.get("latency_s") or 0.0)
                        if lat > 0:
                            latencies_cached.append(lat)
                    except Exception:
                        pass

                cached_rows.append(
                    {
                        "ts": str(row.get("ts") or utc_now_iso()),
                        "run_id": run_ctx.run_id,
                        "id": cid,
                        "lane": lane,
                        "pool": pool,
                        "cache_hit": True,
                        "rerank": rr,
                        "openai": openai_meta,
                    }
                )

        tasks_missing: List[Tuple[str, str, str]] = []
        for task in tasks:
            cid, lane, pool = task
            if (str(cid), str(lane), str(pool)) not in cached_keys:
                tasks_missing.append(task)

        if tasks_missing:
            # Smart pre-check (user requirement): rerank is the largest single cost component.
            rerank_cost_est_usd = {"gpt-5-nano": 0.30, "gpt-5-mini": 0.60}.get(model_rerank, 0.60)
            rerank_est_missing = float(rerank_cost_est_usd) * (len(tasks_missing) / max(1, len(tasks)))
            if float(llm.total_cost_usd) + float(rerank_est_missing) > float(llm.max_total_cost_usd):
                raise TwoLaneBudgetExceeded(
                    f"Two-lane pipeline budget would likely be exceeded by rerank: "
                    f"${llm.total_cost_usd:.2f} + ~${rerank_est_missing:.2f} > ${llm.max_total_cost_usd:.2f}"
                )

        RERANK_JSON_SCHEMA: Dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["llm_score_0_100", "covered_facets", "rationale", "insufficient_info"],
            "properties": {
                "llm_score_0_100": {"type": "integer", "minimum": 0, "maximum": 100},
                "covered_facets": {"type": "array", "items": {"type": "string", "enum": facet_ids}, "maxItems": 12},
                "rationale": {"type": "string", "maxLength": 800},
                "insufficient_info": {"type": "boolean"},
            },
        }

        SYSTEM_PROMPT = """You are reranking scientific sources for a chapter in an academic paper.
You MUST only use the provided evidence excerpts (coverage_tags) and candidate metadata.
Do NOT infer content that is not supported by the excerpts/metadata.
If evidence is insufficient, set insufficient_info=true and keep the score conservative.

Without-abstract honesty rule:
- If pool==\"without_abstract\", set insufficient_info=true unless the metadata/excerpts clearly support MULTIPLE required facets.

Output ONLY valid JSON matching the provided schema. No Markdown. No extra keys."""

        def _lane_guidance(lane: str) -> str:
            if lane == "authority":
                return (
                    "authority lane: allow broader/foundational works, but they must still be relevant to the chapter. "
                    "Reward strong scholarly importance only if relevance is supported by excerpts."
                )
            return "match lane: prioritize topical fit + coverage of the required facets; prefer concrete excerpt support."

        def _build_user_prompt(cid: str, lane: str, pool: str) -> str:
            r = scores_by_id.get(cid) or {}
            c = candidates_by_id.get(cid) or {}

            title = str(c.get("title") or r.get("title") or "").strip()
            year = c.get("year") if c.get("year") is not None else r.get("year")
            venue = str(c.get("venue") or r.get("venue") or "").strip()
            citations = int(c.get("citations") or r.get("citations") or 0)
            url = str(c.get("url") or r.get("url") or "").strip()
            authors = c.get("authors")
            if isinstance(authors, list):
                authors = [str(a.get("name") if isinstance(a, dict) else a or "").strip() for a in authors]
            authors_list = [a for a in (authors or []) if str(a).strip()]
            authors_list = authors_list[:6]

            tags = list((r.get("coverage_tags") or []))
            tags_compact = []
            for t in tags:
                if not isinstance(t, dict):
                    continue
                fid = str(t.get("facet_id") or "").strip()
                if not fid:
                    continue
                tags_compact.append(
                    {
                        "facet_id": fid,
                        "score": float(t.get("score") or 0.0),
                        "excerpt": _truncate_i(t.get("excerpt") or "", 240),
                    }
                )
            tags_compact.sort(key=lambda x: -float(x.get("score") or 0.0))

            required_facets_json = json.dumps(required_facet_rows, ensure_ascii=False)
            tags_json = json.dumps(tags_compact, ensure_ascii=False)

            abstract_present = bool(str(c.get("abstract") or "").strip())

            return (
                "CHAPTER_TITLE:\n"
                f"{chapter_title}\n\n"
                "LANE:\n"
                f"{lane}\n\n"
                "POOL:\n"
                f"{pool}\n\n"
                "LANE_GUIDANCE:\n"
                f"{_lane_guidance(lane)}\n\n"
                "FACETS_REQUIRED (weight>=4):\n"
                f"{required_facets_json}\n\n"
                "ALL_FACET_IDS:\n"
                f"{json.dumps(facet_ids, ensure_ascii=False)}\n\n"
                "CANDIDATE_METADATA:\n"
                f"title={title}\nyear={year}\nvenue={venue}\ncitations={citations}\nurl={url}\n"
                f"authors={json.dumps(authors_list, ensure_ascii=False)}\nabstract_present={abstract_present}\n\n"
                "CANDIDATE_EVIDENCE (coverage_tags):\n"
                f"{tags_json}\n\n"
                "INSTRUCTIONS:\n"
                "- Score 0..100 for usefulness for this chapter (higher = better).\n"
                "- covered_facets: choose ONLY facets explicitly supported by the excerpts; keep it short (<=12).\n"
                "- rationale: cite the excerpts/metadata you used; do not invent.\n"
                "- insufficient_info: true if the evidence is too thin to judge confidently.\n"
            )

        def _clean_rerank(obj: Dict[str, Any]) -> Dict[str, Any]:
            score = int(obj.get("llm_score_0_100") or 0)
            score = max(0, min(100, score))
            covered = _coerce_str_list(obj.get("covered_facets"))
            seen = set()
            covered2 = []
            for fid in covered:
                if fid not in facet_ids:
                    continue
                if fid in seen:
                    continue
                seen.add(fid)
                covered2.append(fid)
                if len(covered2) >= 12:
                    break
            rationale = _truncate_i(obj.get("rationale") or "", 800)
            insuff = bool(obj.get("insufficient_info"))
            return {
                "llm_score_0_100": int(score),
                "covered_facets": covered2,
                "rationale": str(rationale or ""),
                "insufficient_info": bool(insuff),
            }

        async def _rerank_one(cid: str, lane: str, pool: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
            user_prompt = _build_user_prompt(cid, lane, pool)
            last_exc: Optional[Exception] = None
            for attempt in range(RETRIES):
                try:
                    obj, meta = await llm.json_schema_call(
                        stage=stage,
                        operation_type="quellen_finder_two_lane_rerank",
                        model=model_rerank,
                        system_prompt=SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        schema_name="rerank_result",
                        schema=RERANK_JSON_SCHEMA,
                        reasoning_effort="medium",
                        max_output_tokens=8000,
                        timeout_s=180.0,
                        operation_details={"candidateId": cid, "lane": lane, "pool": pool, "attempt": int(attempt + 1)},
                    )
                    return _clean_rerank(obj), meta
                except Exception as e:
                    last_exc = e
                    if attempt + 1 >= RETRIES or not _should_retry(e):
                        raise
                    sleep_s = (2.0**attempt) + random.uniform(0.0, 0.5)
                    await asyncio.sleep(sleep_s)
            raise RuntimeError(f"Phase I rerank failed after {RETRIES} attempts: {last_exc}")

        sem = asyncio.Semaphore(max(1, CONCURRENCY))
        t_start = time.time()

        new_rows: List[Dict[str, Any]] = []
        failures = 0
        tokens_in_new = 0
        tokens_cached_in_new = 0
        tokens_out_new = 0
        cost_new = 0.0
        latencies: List[float] = []

        async def _worker(task: Tuple[str, str, str]) -> Optional[Dict[str, Any]]:
            nonlocal failures, tokens_in_new, tokens_cached_in_new, tokens_out_new, cost_new
            cid, lane, pool = task
            async with sem:
                if check_cancel is not None:
                    await check_cancel()
                try:
                    rerank, meta = await _rerank_one(cid, lane, pool)
                except Exception:
                    failures += 1
                    return None

                usage = (meta.get("usage") or {}) if isinstance(meta, dict) else {}
                tokens_in_new += int(usage.get("input_tokens") or 0)
                tokens_cached_in_new += int(usage.get("cached_input_tokens") or 0)
                tokens_out_new += int(usage.get("output_tokens") or 0)
                cost_new += float(meta.get("cost_usd") or 0.0)
                try:
                    latencies.append(float(meta.get("latency_s") or 0.0))
                except Exception:
                    pass

                done = len(cached_keys) + len(new_rows) + failures
                if done == 1 or done % 10 == 0 or done == len(tasks):
                    dt = max(0.001, time.time() - t_start)
                    rate = done / dt
                    eta_s = int((len(tasks) - done) / max(rate, 1e-6))
                    # Keep this lightweight; detailed per-call info is in cost logs.
                    _ = eta_s

                return {
                    "ts": utc_now_iso(),
                    "run_id": run_ctx.run_id,
                    "id": cid,
                    "lane": lane,
                    "pool": pool,
                    "cache_hit": False,
                    "rerank": rerank,
                    "openai": meta,
                }

        results = await asyncio.gather(*[_worker(t) for t in tasks_missing]) if tasks_missing else []
        for row in results:
            if row is not None:
                new_rows.append(row)

        rows_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in cached_rows + new_rows:
            cid = str(row.get("id") or "").strip()
            lane = str(row.get("lane") or "").strip()
            pool = str(row.get("pool") or "").strip()
            if cid and lane and pool:
                rows_by_key[(cid, lane, pool)] = row

        all_rows = list(rows_by_key.values())
        all_rows.sort(key=lambda r: (str(r.get("lane") or ""), str(r.get("pool") or ""), str(r.get("id") or "")))
        ensure_dir(rerank_results_path.parent)
        tmp = rerank_results_path.with_suffix(rerank_results_path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for obj in all_rows:
                f.write(json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n")
        tmp.replace(rerank_results_path)

        rerank_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in all_rows:
            cid = str(row.get("id") or "").strip()
            lane = str(row.get("lane") or "").strip()
            pool = str(row.get("pool") or "").strip()
            rr = row.get("rerank")
            if cid and lane and pool and isinstance(rr, dict):
                rerank_by_key[(cid, lane, pool)] = rr

        rankings_i: Dict[str, Dict[str, List[str]]] = {"match": {}, "authority": {}}

        def _stageg_lane_score(cid: str, lane: str) -> float:
            r = scores_by_id.get(cid) or {}
            sc = r.get("scores") or {}
            return float(sc.get("match_lane" if lane == "match" else "authority_lane") or 0.0)

        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                ids_g = list((((rankings.get(lane) or {}).get(pool)) or []))
                top = ids_g[:K]
                tail = ids_g[K:]
                top_ok = []
                top_fail = []
                for cid in top:
                    cids = str(cid or "").strip()
                    rr = rerank_by_key.get((cids, lane, pool))
                    if rr is None:
                        top_fail.append(cids)
                    else:
                        top_ok.append(cids)

                def _sort_key(cids: str):
                    rr = rerank_by_key.get((cids, lane, pool)) or {}
                    insuff = bool(rr.get("insufficient_info"))
                    llm_score = int(rr.get("llm_score_0_100") or 0)
                    sg = _stageg_lane_score(cids, lane)
                    return (insuff, -llm_score, -sg)

                top_ok_sorted = sorted(top_ok, key=_sort_key)
                rankings_i[lane][pool] = top_ok_sorted + top_fail + [str(x) for x in tail if str(x or "").strip()]

        write_json(rankings_i_path, {"run_id": run_ctx.run_id, "generated_at_utc": utc_now_iso(), "rankings": rankings_i})

        insuff_by_lp: Dict[str, int] = {}
        for row in all_rows:
            rr = row.get("rerank") or {}
            if isinstance(rr, dict) and bool(rr.get("insufficient_info")):
                k = f"{row.get('lane')}/{row.get('pool')}"
                insuff_by_lp[k] = int(insuff_by_lp.get(k) or 0) + 1

        latencies_all = [float(x) for x in (latencies_cached + latencies) if isinstance(x, (int, float)) and float(x) > 0]
        cost_total = float(cost_cached) + float(cost_new)
        tokens_in_total = int(tokens_in_cached) + int(tokens_in_new)
        tokens_cached_in_total = int(tokens_cached_in_cached) + int(tokens_cached_in_new)
        tokens_out_total = int(tokens_out_cached) + int(tokens_out_new)

        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault(stage, {})["counts"] = {
            "model": model_rerank,
            "model_used": model_rerank,
            "rerank_top_k_pre": int(K),
            "rerank_concurrency": int(CONCURRENCY),
            "tasks_total": int(len(tasks)),
            "cache_hits": int(cache_hits),
            "bad_cache": int(bad_cache),
            "api_calls": int(cache_hits + len(new_rows)),
            "failures": int(failures),
            "tokens_in_total": int(tokens_in_total),
            "tokens_cached_in_total": int(tokens_cached_in_total),
            "tokens_out_total": int(tokens_out_total),
            "tokens_in_new": int(tokens_in_new),
            "tokens_cached_in_new": int(tokens_cached_in_new),
            "tokens_out_new": int(tokens_out_new),
            "cost_usd_total": float(cost_total),
            "cost_usd_new": float(cost_new),
            # Backward-compat keys for older rollups
            "cost_usd_est_total": float(cost_total),
            "cost_usd_est_new": float(cost_new),
            "rerank_results_jsonl": str(rerank_results_path),
            "rankings_stagei_json": str(rankings_i_path),
            "insufficient_by_lane_pool": insuff_by_lp,
            "latency_s_p50": (None if not latencies_all else float(statistics.median(latencies_all))),
        }
        save_metrics(run_ctx, metrics)

    if check_cancel is not None:
        await check_cancel()

    return {
        "rerank_results_jsonl": str(rerank_results_path),
        "rankings_stagei_json": str(rankings_i_path),
        "tasks_total": int(len(tasks)),
        "api_calls": int(cache_hits + len(new_rows)),
        "cache_hits": int(cache_hits),
        "bad_cache": int(bad_cache),
        "failures": int(failures),
        "cost_usd_new": float(cost_new),
        "cost_usd_total": float(float(cost_cached) + float(cost_new)),
    }
