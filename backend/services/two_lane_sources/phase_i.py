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
    ensure_dir,
    load_metrics,
    read_json,
    save_metrics,
    stable_hash,
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


def _write_jsonl_atomic(path: Path, rows: List[Dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for obj in rows:
            f.write(json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n")
    tmp.replace(path)


def _clamp_i(v: Any, lo: int, hi: int) -> int:
    try:
        return max(int(lo), min(int(hi), int(v)))
    except Exception:
        return int(lo)


def _normalize_tag_ids(x: Any, max_items: int = 6) -> List[int]:
    if not isinstance(x, list):
        return []
    out: List[int] = []
    seen = set()
    for v in x:
        try:
            vv = int(v)
        except Exception:
            continue
        if vv < 1 or vv > 99 or vv in seen:
            continue
        seen.add(vv)
        out.append(vv)
        if len(out) >= int(max_items):
            break
    return out


def _usage_cost_from_meta(meta: Dict[str, Any]) -> Tuple[int, int, int, float, float]:
    usage = meta.get("usage") if isinstance(meta, dict) else {}
    usage = usage if isinstance(usage, dict) else {}
    tin = int(usage.get("input_tokens") or 0)
    tc = int(usage.get("cached_input_tokens") or 0)
    tout = int(usage.get("output_tokens") or 0)
    cost = float(meta.get("cost_usd") or 0.0) if isinstance(meta, dict) else 0.0
    lat = float(meta.get("latency_s") or 0.0) if isinstance(meta, dict) else 0.0
    return tin, tc, tout, cost, lat


def _should_retry(exc: Exception) -> bool:
    msg = str(exc)
    msg_l = msg.lower()
    if isinstance(exc, json.JSONDecodeError):
        return True
    if "429" in msg or "rate limit" in msg_l:
        return True
    if "timeout" in msg_l or "timed out" in msg_l:
        return True
    if "500" in msg or "502" in msg or "503" in msg or "504" in msg:
        return True
    if "max_output_tokens" in msg_l or "status='incomplete'" in msg_l or "incomplete_reason" in msg_l:
        return True
    if "no output_text" in msg_l:
        return True
    return False


async def run_phase_i_rerank(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    chapter_title: str,
    chapter_spec_text: str = "",
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
    if model_rerank in {"gpt-5.2", "gpt-5.4"}:
        raise ValueError(f"Rerank model '{model_rerank}' is disabled for cost reasons. Use gpt-5-nano or gpt-5-mini.")

    K = int(getattr(cfg, "rerank_top_k_pre", 40) or 40)
    CONCURRENCY = int(getattr(cfg, "rerank_concurrency", 20) or 20)
    PAIRWISE_TOP_K = int(getattr(cfg, "rerank_pairwise_top_k", 6) or 6)
    PAIRWISE_ENABLED = bool(PAIRWISE_TOP_K >= 2)
    RETRIES = 5
    POINTWISE_REASONING = "low"
    POINTWISE_MAX_OUTPUT_TOKENS = int(getattr(cfg, "rerank_pointwise_max_output_tokens", 2500) or 2500)
    POINTWISE_TIMEOUT_S = float(getattr(cfg, "rerank_pointwise_timeout_s", 300.0) or 300.0)
    PAIRWISE_REASONING = "low"
    PAIRWISE_MAX_OUTPUT_TOKENS = int(getattr(cfg, "rerank_pairwise_max_output_tokens", 1500) or 1500)
    PAIRWISE_TIMEOUT_S = float(getattr(cfg, "rerank_pairwise_timeout_s", 240.0) or 240.0)
    RERANK_CACHE_VERSION = "phase_i_v3_explained_full_context_pairwise6"

    rankings_i_path = run_ctx.run_dir / "rankings_stagei.json"
    rerank_results_path = Path(run_ctx.artifacts.rerank_results_jsonl)
    pairwise_cache_dir = ensure_dir(run_ctx.run_dir / "cache" / "rerank_pairwise")

    metrics0 = load_metrics(run_ctx)
    cached_counts = (
        (((metrics0.get("stages") or {}).get(stage) or {}).get("counts") or {})
        if isinstance(metrics0, dict)
        else {}
    )
    cached_model = str(cached_counts.get("model_used") or cached_counts.get("model") or "").strip()
    cached_version = str(cached_counts.get("rerank_cache_version") or "").strip()
    cache_metadata_matches = bool(cached_model == model_rerank and cached_version == RERANK_CACHE_VERSION)

    if (
        not force_rebuild
        and cache_metadata_matches
        and rerank_results_path.exists()
        and _has_data(rerank_results_path)
        and rankings_i_path.exists()
    ):
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

        query_plan_path = run_ctx.run_dir / "query_plan.json"
        query_plan = read_json(query_plan_path) if query_plan_path.exists() else {}
        original_chapter_title = str(chapter_title or query_plan.get("chapter_title") or "").strip()
        original_chapter_spec_text = str(chapter_spec_text or "").strip()

        required_facet_rows: List[Dict[str, Any]] = []
        for fid in facet_ids:
            w = int(weight_by_fid.get(fid) or 0)
            if w >= 4:
                required_facet_rows.append({"facet_id": fid, "label_en": label_by_fid.get(fid, fid), "weight": w})
        required_facet_rows.sort(
            key=lambda x: (-int(x.get("weight") or 0), str(x.get("label_en") or x.get("facet_id") or ""))
        )

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
            top_n = 2 if pool == "with_abstract" else 1
            threshold = T_ABS if pool == "with_abstract" else T_NOABS

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
            top_idxs = set(idx_sorted[:top_n])
            covered = {i for i, s in enumerate(scores) if float(s or 0.0) >= threshold}.union(top_idxs)

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

        def _compact_required_facets(rows: List[Dict[str, Any]], max_items: int = 5) -> List[Dict[str, Any]]:
            out: List[Dict[str, Any]] = []
            for row in list(rows or [])[: int(max_items)]:
                fid = str(row.get("facet_id") or "").strip()
                if not fid:
                    continue
                out.append(
                    {
                        "facet_id": fid,
                        "label": _truncate_i(row.get("label_en") or fid, 80),
                        "weight": int(row.get("weight") or 0),
                    }
                )
            return out

        def _compact_contract_text(max_len: int = 1400) -> str:
            summary = _truncate_i(query_plan.get("topic_summary_en") or "", 260)
            anchors = [
                str(x).strip()
                for x in (((query_plan.get("primary_context_anchors") or {}).get("en")) or [])
                if str(x).strip()
            ][:6]
            core_terms = [
                str(x).strip()
                for x in (((query_plan.get("core_object_terms") or {}).get("en")) or [])
                if str(x).strip()
            ][:6]
            must_keep = [str(x).strip() for x in (query_plan.get("must_keep_constraints") or []) if str(x).strip()][:4]
            drift = [str(x).strip() for x in (query_plan.get("drift_risks") or []) if str(x).strip()][:4]
            parts: List[str] = []
            if original_chapter_title:
                parts.append(f"Title: {original_chapter_title}")
            if summary:
                parts.append(f"Summary: {summary}")
            if core_terms:
                parts.append("Core object terms: " + ", ".join([_truncate_i(x, 48) for x in core_terms]))
            if anchors:
                parts.append("Primary anchors: " + ", ".join([_truncate_i(x, 40) for x in anchors]))
            if must_keep:
                parts.append("Must keep: " + "; ".join([_truncate_i(x, 72) for x in must_keep]))
            if drift:
                parts.append("Drift risks: " + "; ".join([_truncate_i(x, 72) for x in drift]))
            return _truncate_i("\n".join([p for p in parts if str(p).strip()]), max_len)

        def _original_chapter_input_text() -> str:
            parts: List[str] = []
            if original_chapter_title:
                parts.append(f"Original chapter title:\n{original_chapter_title}")
            if original_chapter_spec_text:
                parts.append(f"Original chapter specification:\n{original_chapter_spec_text}")
            return "\n\n".join([p for p in parts if str(p).strip()])

        def _lane_context_paragraph(lane: str) -> str:
            if lane == "authority":
                return (
                    "This is the authority lane. A source should score well here only if it is foundational for this exact "
                    "chapter debate after topical relevance has already been established. Foundational does not mean broadly "
                    "famous, highly cited, or generally important for the wider period. It means that the work would "
                    "materially help a researcher explain, compare, or evaluate the exact chapter problem."
                )
            return (
                "This is the match lane. A source should score well here when it is directly about the chapter problem or "
                "when it provides clearly useful source-based evidence for evaluating that exact target. Generic background "
                "literature should score conservatively even if it concerns neighboring themes."
            )

        def _pool_context_paragraph(pool: str) -> str:
            if pool == "without_abstract":
                return (
                    "This candidate has no abstract in the current pipeline data. That means the judgment must rely more on "
                    "title, venue, year, citations, and the evidence-tag excerpts. Be conservative. A metadata-only "
                    "candidate should not receive a strong score unless the available information is unusually direct and specific."
                )
            return (
                "This candidate has an abstract. The abstract is the main source for judging actual topical fit, argumentative "
                "centrality, and usefulness for the chapter. Evidence tags can help, but the abstract should carry more weight "
                "than the mere existence of tags."
            )

        def _metadata_explanation_paragraph() -> str:
            return (
                "How to read the candidate metadata: the title gives the quickest signal of topic and corpus; the year helps "
                "situate the work historically but does not determine relevance; the venue can indicate scholarly context but "
                "is only secondary evidence; the citation count is a weak clue about visibility, not proof of usefulness; and "
                "the abstract is the main evidence for what the source actually argues or studies."
            )

        def _evidence_tags_explanation_paragraph() -> str:
            return (
                "How to read the evidence tags: each tag is a noisy hint produced by earlier retrieval and scoring stages. "
                "The facet_id names the facet that upstream stages thought the excerpt might support. The score tells you how "
                "strongly earlier stages matched that excerpt. The excerpt itself is the actual local evidence. Do not treat a "
                "tag as a verified truth claim. Read the excerpt and decide whether it really supports the facet in a way that "
                "matters for this chapter."
            )

        def _dimension_explanation_text(lane: str, pool: str) -> str:
            return (
                "Use the dimensions as follows. topical_fit_0_4 should be based mainly on the original chapter title, the full "
                "chapter specification, and the candidate title and abstract. Ask whether the source is centrally about the "
                "chapter target problem. evidence_strength_0_4 should be based mainly on the evidence-tag excerpts and the "
                "candidate abstract. Reward specific and concrete support, not just many tags. chapter_utility_0_4 is a writing-task "
                "judgment: if you were writing this exact chapter, would this source materially help you reconstruct, compare, or "
                "test the relevant explanations? lane_fit_0_4 is secondary and should come after topical relevance; for match it "
                "means direct fit to the chapter problem, and for authority it means foundational value for this debate after "
                "relevance is already clear. A source can mention the right period or region and still be only broad context. "
                + (
                    "Because this is a without-abstract candidate, uncertainty should stay visible in the score."
                    if pool == "without_abstract"
                    else "Because this candidate has an abstract, use the abstract to decide whether the source is centrally "
                    "about the chapter target or only adjacent background."
                )
            )

        def _score_calibration_text() -> str:
            return (
                "Calibration: high scores should be rare. A score above 80 should be reserved for sources that are directly "
                "about the chapter debate or clearly indispensable for evaluating it. Scores around 50 indicate partial but "
                "real usefulness. Scores around 20 to 30 indicate adjacent background, weak support, or broad contextual "
                "literature. Presence in the candidate pool is not evidence that a source is good, because earlier stages were "
                "designed for recall and may have admitted broad or noisy matches."
            )

        def _candidate_metadata_block(cid: str, *, abstract_max_len: int = 650) -> str:
            r = scores_by_id.get(cid) or {}
            c = candidates_by_id.get(cid) or {}
            title = str(c.get("title") or r.get("title") or "").strip()
            year = c.get("year") if c.get("year") is not None else r.get("year")
            venue = str(c.get("venue") or r.get("venue") or "").strip()
            citations = int(c.get("citations") or r.get("citations") or 0)
            abstract = _truncate_i(c.get("abstract") or "", int(abstract_max_len))
            abstract_present = bool(str(c.get("abstract") or "").strip())
            parts = [
                f"title={title}",
                f"year={year}",
                f"venue={venue}",
                f"citations={citations}",
                f"abstract_present={abstract_present}",
            ]
            if abstract:
                parts.append(f"abstract={abstract}")
            return "\n".join(parts)

        def _compact_tags_json(cid: str, *, max_tags: int = 8, excerpt_max_len: int = 260) -> str:
            r = scores_by_id.get(cid) or {}
            tags = list((r.get("coverage_tags") or []))
            compact: List[Dict[str, Any]] = []
            for idx, t in enumerate(tags, start=1):
                if not isinstance(t, dict):
                    continue
                fid = str(t.get("facet_id") or "").strip()
                if not fid:
                    continue
                compact.append(
                    {
                        "tag_id": idx,
                        "facet_id": fid,
                        "score": round(float(t.get("score") or 0.0), 4),
                        "excerpt": _truncate_i(t.get("excerpt") or "", int(excerpt_max_len)),
                    }
                )
            compact.sort(key=lambda x: (-float(x.get("score") or 0.0), int(x.get("tag_id") or 0)))
            return json.dumps(compact[: int(max_tags)], ensure_ascii=False)

        compact_contract_text = _compact_contract_text()
        original_chapter_input_text = _original_chapter_input_text()
        compact_required_facets_json = json.dumps(_compact_required_facets(required_facet_rows, max_items=5), ensure_ascii=False)

        POINTWISE_JSON_SCHEMA: Dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "required": [
                "topical_fit_0_4",
                "evidence_strength_0_4",
                "chapter_utility_0_4",
                "lane_fit_0_4",
                "covered_facets",
                "evidence_tag_ids",
                "off_topic",
                "insufficient_info",
                "brief_rationale",
            ],
            "properties": {
                "topical_fit_0_4": {"type": "integer", "minimum": 0, "maximum": 4},
                "evidence_strength_0_4": {"type": "integer", "minimum": 0, "maximum": 4},
                "chapter_utility_0_4": {"type": "integer", "minimum": 0, "maximum": 4},
                "lane_fit_0_4": {"type": "integer", "minimum": 0, "maximum": 4},
                "covered_facets": {"type": "array", "items": {"type": "string", "enum": facet_ids}, "maxItems": 10},
                "evidence_tag_ids": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 99}, "maxItems": 6},
                "off_topic": {"type": "boolean"},
                "insufficient_info": {"type": "boolean"},
                "brief_rationale": {"type": "string", "maxLength": 260},
            },
        }

        PAIRWISE_JSON_SCHEMA: Dict[str, Any] = {
            "type": "object",
            "additionalProperties": False,
            "required": ["winner", "confidence_0_3", "brief_rationale"],
            "properties": {
                "winner": {"type": "string", "enum": ["A", "B", "tie"]},
                "confidence_0_3": {"type": "integer", "minimum": 0, "maximum": 3},
                "brief_rationale": {"type": "string", "maxLength": 220},
            },
        }

        SYSTEM_PROMPT = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

        PAIRWISE_SYSTEM_PROMPT = "<Prompt entfernt: wird zur Laufzeit aus Firebase geladen>"

        def _lane_guidance(lane: str) -> str:
            if lane == "authority":
                return (
                    "Authority lane: foundational value matters only after clear topical relevance has been established, "
                    "and foundational means foundational for this chapter debate rather than generally important."
                )
            return (
                "Match lane: prioritize direct chapter fit and concrete usefulness for the chapter over generic importance "
                "or neighboring relevance."
            )

        def _build_user_prompt(cid: str, lane: str, pool: str) -> str:
            return (
                "You are seeing one candidate at the final reranking stage of a high-recall literature pipeline. Earlier "
                "stages were designed to gather many possibly relevant sources, not to guarantee precision. Your job is "
                "to decide how useful this single source would actually be for writing the exact target chapter.\n\n"
                "ORIGINAL_CHAPTER_INPUT:\n"
                f"{original_chapter_input_text}\n\n"
                "CHAPTER_CONTRACT_SUMMARY:\n"
                f"{compact_contract_text}\n\n"
                "HOW_TO_INTERPRET_THE_CHAPTER_BLOCKS:\n"
                "The original chapter input gives the full task in the user’s own wording. The compact chapter contract "
                "is a distilled summary of the same target. Use the original chapter input to understand the full writing "
                "task and use the compact contract as a structured reminder of the main object, anchors, constraints, and "
                "drift risks.\n\n"
                "LANE_AND_POOL:\n"
                f"lane={lane}\n"
                f"pool={pool}\n\n"
                "LANE_GUIDANCE:\n"
                f"{_lane_guidance(lane)}\n\n"
                "LANE_EXPLANATION:\n"
                f"{_lane_context_paragraph(lane)}\n\n"
                "POOL_EXPLANATION:\n"
                f"{_pool_context_paragraph(pool)}\n\n"
                "REQUIRED_FACETS:\n"
                f"{compact_required_facets_json}\n\n"
                "REQUIRED_FACETS_EXPLANATION:\n"
                "These are the highest-priority facets for the chapter according to the earlier planning stage. They tell "
                "you what kinds of mechanisms, evidence, or evaluative dimensions matter most for the chapter. Do not "
                "assume that every good source must cover all of them, but do prefer sources that materially support one "
                "or more of them in a chapter-relevant way.\n\n"
                "CANDIDATE_METADATA:\n"
                f"{_candidate_metadata_block(cid, abstract_max_len=650)}\n\n"
                "CANDIDATE_METADATA_EXPLANATION:\n"
                f"{_metadata_explanation_paragraph()}\n\n"
                "EVIDENCE_TAGS:\n"
                f"{_compact_tags_json(cid, max_tags=8, excerpt_max_len=260)}\n\n"
                "EVIDENCE_TAGS_EXPLANATION:\n"
                f"{_evidence_tags_explanation_paragraph()}\n\n"
                "SCORING_DIMENSIONS (0-4 each):\n"
                "- topical_fit_0_4\n"
                "- evidence_strength_0_4\n"
                "- chapter_utility_0_4\n"
                "- lane_fit_0_4\n\n"
                "SCORING_DIMENSIONS_EXPLANATION:\n"
                f"{_dimension_explanation_text(lane, pool)}\n\n"
                "FOUR CASES TO DISTINGUISH:\n"
                "1. Direct chapter fit: centrally about the chapter's actual explanatory target.\n"
                "2. Strong evaluative support: not itself the core synthesis, but clearly useful source-based evidence.\n"
                "3. Broad historical context: related to the wider area, but not clearly useful for the chapter’s comparison.\n"
                "4. Off-topic literature: shares some retrieval language but does not materially help with the chapter.\n\n"
                "CALIBRATION:\n"
                f"{_score_calibration_text()}\n\n"
                "HARD RULES:\n"
                "- Set off_topic=true if the candidate is clearly outside the chapter target problem or only loosely adjacent.\n"
                "- Set insufficient_info=true if the available evidence is too thin for a confident judgment.\n"
                "- covered_facets must include only facets that are explicitly supported by the abstract or the evidence-tag excerpts.\n"
                "- evidence_tag_ids must list only the tags you actually relied on.\n"
                "- brief_rationale must be short, concrete, and reflect the real reason for the score.\n"
                "- Citation count, venue prestige, and broad adjacency must never substitute for topical fit.\n"
            )

        def _build_pairwise_user_prompt(cid_a: str, cid_b: str, lane: str) -> str:
            return (
                "You are comparing two candidates at the final reranking stage of a high-recall literature pipeline. The "
                "candidates may both be imperfect, because earlier stages were designed to maximize recall. Choose the "
                "candidate that would more likely help write the exact target chapter.\n\n"
                "ORIGINAL_CHAPTER_INPUT:\n"
                f"{original_chapter_input_text}\n\n"
                "CHAPTER_CONTRACT_SUMMARY:\n"
                f"{compact_contract_text}\n\n"
                "LANE:\n"
                f"{lane}\n"
                "POOL:\n"
                "with_abstract\n\n"
                "LANE_EXPLANATION:\n"
                f"{_lane_context_paragraph(lane)}\n\n"
                "HOW_TO_USE_THE_INPUTS:\n"
                "Use the original chapter input for the full task, the compact contract as a structured summary, the "
                "candidate metadata for central topic and argument clues, and the evidence tags as noisy but useful local "
                "hints. Prefer the source that is more central to the exact chapter target, not the source that is merely "
                "broader, more famous, or more prestigious.\n\n"
                "CANDIDATE_A_METADATA:\n"
                f"{_candidate_metadata_block(cid_a, abstract_max_len=500)}\n\n"
                "CANDIDATE_A_TAGS:\n"
                f"{_compact_tags_json(cid_a, max_tags=6, excerpt_max_len=220)}\n\n"
                "CANDIDATE_B_METADATA:\n"
                f"{_candidate_metadata_block(cid_b, abstract_max_len=500)}\n\n"
                "CANDIDATE_B_TAGS:\n"
                f"{_compact_tags_json(cid_b, max_tags=6, excerpt_max_len=220)}\n\n"
                "Choose which candidate is more useful for this exact chapter and lane. If both are similarly weak or "
                "similarly strong, return tie.\n"
            )

        def _normalize_covered_facets(covered: Any, max_items: int = 10) -> List[str]:
            covered_list = _coerce_str_list(covered)
            seen = set()
            covered2: List[str] = []
            for fid in covered_list:
                if fid not in facet_ids or fid in seen:
                    continue
                seen.add(fid)
                covered2.append(fid)
                if len(covered2) >= int(max_items):
                    break
            return covered2

        def _clean_rerank(obj: Dict[str, Any], lane: str, pool: str) -> Dict[str, Any]:
            if not isinstance(obj, dict):
                obj = {}
            if any(k in obj for k in ["topical_fit_0_4", "evidence_strength_0_4", "chapter_utility_0_4", "lane_fit_0_4"]):
                topical = _clamp_i(obj.get("topical_fit_0_4"), 0, 4)
                evid = _clamp_i(obj.get("evidence_strength_0_4"), 0, 4)
                utility = _clamp_i(obj.get("chapter_utility_0_4"), 0, 4)
                lane_fit = _clamp_i(obj.get("lane_fit_0_4"), 0, 4)
                covered2 = _normalize_covered_facets(obj.get("covered_facets"), max_items=10)
                evidence_tag_ids = _normalize_tag_ids(obj.get("evidence_tag_ids"), max_items=6)
                off_topic = bool(obj.get("off_topic"))
                insuff = bool(obj.get("insufficient_info"))
                rationale = _truncate_i(obj.get("brief_rationale") or obj.get("rationale") or "", 260)
                score = round((35 * topical + 25 * evid + 25 * utility + 15 * lane_fit) / 4.0)
                if off_topic:
                    score = min(score, 25)
                if insuff:
                    score = min(score, 35 if pool == "without_abstract" else 45)
                if lane == "authority" and topical <= 1:
                    score = min(score, 35)
                if not covered2:
                    score = min(score, 30)
                return {
                    "llm_score_0_100": int(max(0, min(100, score))),
                    "covered_facets": covered2,
                    "evidence_tag_ids": evidence_tag_ids,
                    "rationale": str(rationale or ""),
                    "brief_rationale": str(rationale or ""),
                    "insufficient_info": insuff,
                    "off_topic": off_topic,
                    "call_failed": bool(obj.get("call_failed")),
                    "rubric": {
                        "topical_fit_0_4": topical,
                        "evidence_strength_0_4": evid,
                        "chapter_utility_0_4": utility,
                        "lane_fit_0_4": lane_fit,
                    },
                }

            score = _clamp_i(obj.get("llm_score_0_100"), 0, 100)
            rationale = _truncate_i(obj.get("rationale") or obj.get("brief_rationale") or "", 260)
            rubric_obj = obj.get("rubric") if isinstance(obj.get("rubric"), dict) else {}
            return {
                "llm_score_0_100": int(score),
                "covered_facets": _normalize_covered_facets(obj.get("covered_facets"), max_items=10),
                "evidence_tag_ids": _normalize_tag_ids(obj.get("evidence_tag_ids"), max_items=6),
                "rationale": str(rationale or ""),
                "brief_rationale": str(rationale or ""),
                "insufficient_info": bool(obj.get("insufficient_info")),
                "off_topic": bool(obj.get("off_topic")),
                "call_failed": bool(obj.get("call_failed")),
                "rubric": {
                    "topical_fit_0_4": _clamp_i(rubric_obj.get("topical_fit_0_4"), 0, 4),
                    "evidence_strength_0_4": _clamp_i(rubric_obj.get("evidence_strength_0_4"), 0, 4),
                    "chapter_utility_0_4": _clamp_i(rubric_obj.get("chapter_utility_0_4"), 0, 4),
                    "lane_fit_0_4": _clamp_i(rubric_obj.get("lane_fit_0_4"), 0, 4),
                },
            }

        def _clean_pairwise_result(obj: Dict[str, Any], cid_a: str, cid_b: str) -> Dict[str, Any]:
            if not isinstance(obj, dict):
                obj = {}
            if "winner_cid" in obj:
                winner_cid = str(obj.get("winner_cid") or "tie").strip() or "tie"
                if winner_cid not in {cid_a, cid_b, "tie"}:
                    winner_cid = "tie"
                return {
                    "winner_cid": winner_cid,
                    "confidence_0_3": _clamp_i(obj.get("confidence_0_3"), 0, 3),
                    "brief_rationale": _truncate_i(obj.get("brief_rationale") or "", 220),
                    "call_failed": bool(obj.get("call_failed")),
                }
            winner = str(obj.get("winner") or "tie").strip()
            if winner == "A":
                winner_cid = cid_a
            elif winner == "B":
                winner_cid = cid_b
            else:
                winner_cid = "tie"
            return {
                "winner_cid": winner_cid,
                "confidence_0_3": _clamp_i(obj.get("confidence_0_3"), 0, 3),
                "brief_rationale": _truncate_i(obj.get("brief_rationale") or "", 220),
                "call_failed": bool(obj.get("call_failed")),
            }

        def _failure_meta(error: Exception) -> Dict[str, Any]:
            return {
                "model_requested": model_rerank,
                "model_used": model_rerank,
                "response_id": "",
                "latency_s": 0.0,
                "usage": {
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "reasoning_tokens": 0,
                },
                "cost_usd": 0.0,
                "status": "failed",
                "incomplete_reason": None,
                "error": str(error),
            }

        def _pointwise_failure_result(error: Exception) -> Dict[str, Any]:
            msg = _truncate_i(f"call_failed: {error}", 260)
            return {
                "llm_score_0_100": 0,
                "covered_facets": [],
                "evidence_tag_ids": [],
                "rationale": msg,
                "brief_rationale": msg,
                "insufficient_info": True,
                "off_topic": False,
                "call_failed": True,
                "rubric": {
                    "topical_fit_0_4": 0,
                    "evidence_strength_0_4": 0,
                    "chapter_utility_0_4": 0,
                    "lane_fit_0_4": 0,
                },
            }

        def _pairwise_failure_result(error: Exception) -> Dict[str, Any]:
            return {
                "winner_cid": "tie",
                "confidence_0_3": 0,
                "brief_rationale": _truncate_i(f"call_failed: {error}", 220),
                "call_failed": True,
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
                        schema=POINTWISE_JSON_SCHEMA,
                        reasoning_effort=POINTWISE_REASONING,
                        max_output_tokens=POINTWISE_MAX_OUTPUT_TOKENS,
                        timeout_s=POINTWISE_TIMEOUT_S,
                        operation_details={"candidateId": cid, "lane": lane, "pool": pool, "attempt": int(attempt + 1)},
                    )
                    return _clean_rerank(obj, lane=lane, pool=pool), meta
                except Exception as e:
                    last_exc = e
                    if attempt + 1 >= RETRIES or not _should_retry(e):
                        break
                    sleep_s = (2.0**attempt) + random.uniform(0.0, 0.5)
                    await asyncio.sleep(sleep_s)
            err = last_exc or RuntimeError("unknown pointwise failure")
            return _pointwise_failure_result(err), _failure_meta(err)

        async def _pairwise_compare(cid_a: str, cid_b: str, lane: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
            swap = int(stable_hash(RERANK_CACHE_VERSION, run_ctx.run_id, lane, cid_a, cid_b, length=8), 16) % 2 == 1
            left = cid_b if swap else cid_a
            right = cid_a if swap else cid_b
            user_prompt = _build_pairwise_user_prompt(left, right, lane)
            last_exc: Optional[Exception] = None
            for attempt in range(RETRIES):
                try:
                    obj, meta = await llm.json_schema_call(
                        stage=stage,
                        operation_type="quellen_finder_two_lane_rerank_pairwise",
                        model=model_rerank,
                        system_prompt=PAIRWISE_SYSTEM_PROMPT,
                        user_prompt=user_prompt,
                        schema_name="rerank_pairwise_result",
                        schema=PAIRWISE_JSON_SCHEMA,
                        reasoning_effort=PAIRWISE_REASONING,
                        max_output_tokens=PAIRWISE_MAX_OUTPUT_TOKENS,
                        timeout_s=PAIRWISE_TIMEOUT_S,
                        operation_details={
                            "candidateIdLeft": left,
                            "candidateIdRight": right,
                            "lane": lane,
                            "attempt": int(attempt + 1),
                        },
                    )
                    cleaned = _clean_pairwise_result(obj, left, right)
                    if swap:
                        winner_cid = str(cleaned.get("winner_cid") or "tie")
                        if winner_cid == left:
                            cleaned["winner_cid"] = cid_b
                        elif winner_cid == right:
                            cleaned["winner_cid"] = cid_a
                    return cleaned, meta
                except Exception as e:
                    last_exc = e
                    if attempt + 1 >= RETRIES or not _should_retry(e):
                        break
                    sleep_s = (2.0**attempt) + random.uniform(0.0, 0.5)
                    await asyncio.sleep(sleep_s)
            err = last_exc or RuntimeError("unknown pairwise failure")
            return _pairwise_failure_result(err), _failure_meta(err)

        def _pairwise_cache_path(cid_a: str, cid_b: str, lane: str) -> Path:
            left, right = sorted([str(cid_a or "").strip(), str(cid_b or "").strip()])
            fn = stable_hash(
                "rerank_pairwise",
                RERANK_CACHE_VERSION,
                run_ctx.run_id,
                lane,
                "with_abstract",
                left,
                right,
                length=24,
            )
            return pairwise_cache_dir / f"{fn}.json"

        cached_rows: List[Dict[str, Any]] = []
        cached_keys = set()
        cache_hits = 0
        bad_cache = 0
        tokens_in_cached = 0
        tokens_cached_in_cached = 0
        tokens_out_cached = 0
        cost_cached = 0.0
        latencies_cached: List[float] = []

        if not force_rebuild and cache_metadata_matches and rerank_results_path.exists() and _has_data(rerank_results_path):
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

                openai_meta = row.get("openai") if isinstance(row.get("openai"), dict) else {}
                cached_model_used = str((openai_meta or {}).get("model_used") or (openai_meta or {}).get("model_requested") or "").strip()
                if cached_model_used and cached_model_used != model_rerank:
                    bad_cache += 1
                    continue

                cleaned = _clean_rerank(rr, lane=lane, pool=pool)
                if bool(cleaned.get("call_failed")):
                    bad_cache += 1
                    continue
                if key in cached_keys:
                    continue

                cached_keys.add(key)
                cache_hits += 1
                tin, tc, tout, cost, lat = _usage_cost_from_meta(openai_meta or {})
                tokens_in_cached += tin
                tokens_cached_in_cached += tc
                tokens_out_cached += tout
                cost_cached += cost
                if float(lat or 0.0) > 0:
                    latencies_cached.append(float(lat))

                cached_rows.append(
                    {
                        "ts": str(row.get("ts") or utc_now_iso()),
                        "run_id": run_ctx.run_id,
                        "id": cid,
                        "lane": lane,
                        "pool": pool,
                        "cache_hit": True,
                        "rerank": cleaned,
                        "openai": openai_meta,
                    }
                )

        tasks_missing: List[Tuple[str, str, str]] = []
        for task in tasks:
            cid, lane, pool = task
            if (str(cid), str(lane), str(pool)) not in cached_keys:
                tasks_missing.append(task)

        if tasks_missing:
            rerank_cost_est_usd = {"gpt-5-nano": 0.30, "gpt-5-mini": 0.60}.get(model_rerank, 0.60)
            rerank_est_missing = float(rerank_cost_est_usd) * (len(tasks_missing) / max(1, len(tasks)))
            if float(llm.total_cost_usd) + float(rerank_est_missing) > float(llm.max_total_cost_usd):
                raise TwoLaneBudgetExceeded(
                    f"Two-lane pipeline budget would likely be exceeded by rerank: "
                    f"${llm.total_cost_usd:.2f} + ~${rerank_est_missing:.2f} > ${llm.max_total_cost_usd:.2f}"
                )

        sem = asyncio.Semaphore(max(1, CONCURRENCY))
        t_start = time.time()

        new_rows: List[Dict[str, Any]] = []
        runtime_exceptions = 0
        tokens_in_new = 0
        tokens_cached_in_new = 0
        tokens_out_new = 0
        cost_new = 0.0
        latencies: List[float] = []

        async def _worker(task: Tuple[str, str, str]) -> Dict[str, Any]:
            nonlocal runtime_exceptions, tokens_in_new, tokens_cached_in_new, tokens_out_new, cost_new
            cid, lane, pool = task
            async with sem:
                if check_cancel is not None:
                    await check_cancel()
                try:
                    rerank, meta = await _rerank_one(cid, lane, pool)
                except Exception as exc:
                    runtime_exceptions += 1
                    rerank = _pointwise_failure_result(exc)
                    meta = _failure_meta(exc)

                tin, tc, tout, cost, lat = _usage_cost_from_meta(meta)
                tokens_in_new += tin
                tokens_cached_in_new += tc
                tokens_out_new += tout
                cost_new += cost
                if float(lat or 0.0) > 0:
                    latencies.append(float(lat))

                done = len(cached_keys) + len(new_rows) + 1
                if done == 1 or done % 10 == 0 or done == len(tasks):
                    dt = max(0.001, time.time() - t_start)
                    rate = done / dt
                    eta_s = int((len(tasks) - done) / max(rate, 1e-6))
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

        if tasks_missing:
            results = await asyncio.gather(*[_worker(task) for task in tasks_missing])
            new_rows.extend(results)

        rows_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in cached_rows + new_rows:
            cid = str(row.get("id") or "").strip()
            lane = str(row.get("lane") or "").strip()
            pool = str(row.get("pool") or "").strip()
            if cid and lane and pool:
                rows_by_key[(cid, lane, pool)] = row

        rows_all = list(rows_by_key.values())
        rows_all.sort(key=lambda r: (str(r.get("lane") or ""), str(r.get("pool") or ""), str(r.get("id") or "")))
        _write_jsonl_atomic(rerank_results_path, rows_all)

        rerank_by_key: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        for row in rows_all:
            cid = str(row.get("id") or "").strip()
            lane = str(row.get("lane") or "").strip()
            pool = str(row.get("pool") or "").strip()
            rr = row.get("rerank")
            if cid and lane and pool and isinstance(rr, dict):
                rerank_by_key[(cid, lane, pool)] = rr

        def _stageg_lane_score(cid: str, lane: str) -> float:
            r = scores_by_id.get(cid) or {}
            sc = r.get("scores") or {}
            return float(sc.get("match_lane" if lane == "match" else "authority_lane") or 0.0)

        def _sort_key(cid: str, lane: str, pool: str) -> Tuple[bool, bool, bool, int, float]:
            rr = rerank_by_key.get((cid, lane, pool)) or {}
            return (
                bool(rr.get("call_failed")),
                bool(rr.get("insufficient_info")),
                bool(rr.get("off_topic")),
                -int(rr.get("llm_score_0_100") or 0),
                -_stageg_lane_score(cid, lane),
            )

        pairwise_rows: List[Dict[str, Any]] = []
        pairwise_stats = {
            "cache_hits": 0,
            "bad_cache": 0,
            "api_calls": 0,
            "failures": 0,
            "tokens_in_new": 0,
            "tokens_cached_in_new": 0,
            "tokens_out_new": 0,
            "cost_usd_new": 0.0,
        }
        pairwise_latencies: List[float] = []

        async def _load_or_run_pairwise(cid_a: str, cid_b: str, lane: str) -> Dict[str, Any]:
            left, right = sorted([str(cid_a or "").strip(), str(cid_b or "").strip()])
            cp = _pairwise_cache_path(left, right, lane)
            if not force_rebuild and cp.exists():
                try:
                    obj = read_json(cp)
                    pairwise = obj.get("pairwise") or {}
                    openai_meta = obj.get("openai") or {}
                    pairwise = _clean_pairwise_result(pairwise, left, right) if isinstance(pairwise, dict) else None
                    if not pairwise:
                        raise ValueError("empty pairwise result")
                    if bool(pairwise.get("call_failed")):
                        raise ValueError("cached pairwise is call_failed; force retry")
                    pairwise_stats["cache_hits"] = int(pairwise_stats["cache_hits"]) + 1
                    return {
                        "ts": utc_now_iso(),
                        "run_id": run_ctx.run_id,
                        "lane": lane,
                        "pool": "with_abstract",
                        "id_left": left,
                        "id_right": right,
                        "cache_hit": True,
                        "pairwise": pairwise,
                        "openai": openai_meta,
                    }
                except Exception:
                    pairwise_stats["bad_cache"] = int(pairwise_stats["bad_cache"]) + 1

            if check_cancel is not None:
                await check_cancel()

            pairwise, meta = await _pairwise_compare(left, right, lane)
            tin, tc, tout, cost, lat = _usage_cost_from_meta(meta)
            pairwise_stats["api_calls"] = int(pairwise_stats["api_calls"]) + 1
            pairwise_stats["tokens_in_new"] = int(pairwise_stats["tokens_in_new"]) + tin
            pairwise_stats["tokens_cached_in_new"] = int(pairwise_stats["tokens_cached_in_new"]) + tc
            pairwise_stats["tokens_out_new"] = int(pairwise_stats["tokens_out_new"]) + tout
            pairwise_stats["cost_usd_new"] = float(pairwise_stats["cost_usd_new"]) + cost
            if float(lat or 0.0) > 0:
                pairwise_latencies.append(float(lat))
            if bool((pairwise or {}).get("call_failed")):
                pairwise_stats["failures"] = int(pairwise_stats["failures"]) + 1

            row = {
                "ts": utc_now_iso(),
                "run_id": run_ctx.run_id,
                "lane": lane,
                "pool": "with_abstract",
                "id_left": left,
                "id_right": right,
                "cache_hit": False,
                "pairwise": pairwise,
                "openai": meta,
            }
            write_json(cp, row)
            return row

        rankings_i: Dict[str, Dict[str, List[str]]] = {"match": {}, "authority": {}}
        pairwise_summary: Dict[str, Dict[str, Any]] = {}

        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                ids_g = [str(x) for x in ((((rankings.get(lane) or {}).get(pool)) or [])) if str(x or "").strip()]
                top = ids_g[:K]
                tail = ids_g[K:]
                top_ok: List[str] = []
                top_fail: List[str] = []
                for cid in top:
                    rr = rerank_by_key.get((cid, lane, pool))
                    if rr is None:
                        top_fail.append(cid)
                    else:
                        top_ok.append(cid)

                top_ok_sorted = sorted(top_ok, key=lambda cid: _sort_key(cid, lane, pool))
                pair_key = f"{lane}/{pool}"
                pair_info: Dict[str, Any] = {
                    "enabled": bool(PAIRWISE_ENABLED and pool == "with_abstract"),
                    "eligible_top_k": 0,
                    "comparisons": 0,
                    "cache_hits": 0,
                    "api_calls": 0,
                    "failures": 0,
                    "ids_before": [],
                    "ids_after": [],
                }

                if bool(PAIRWISE_ENABLED) and pool == "with_abstract":
                    pair_ids = list(top_ok_sorted[: max(0, int(PAIRWISE_TOP_K))])
                    pair_info["eligible_top_k"] = int(len(pair_ids))
                    pair_info["ids_before"] = list(pair_ids)
                    if len(pair_ids) >= 2:
                        pair_scores = {cid: 0.0 for cid in pair_ids}
                        cache_hits_before = int(pairwise_stats["cache_hits"])
                        api_calls_before = int(pairwise_stats["api_calls"])
                        comparisons = 0
                        pair_failures = 0

                        for i in range(len(pair_ids)):
                            for j in range(i + 1, len(pair_ids)):
                                row = await _load_or_run_pairwise(pair_ids[i], pair_ids[j], lane)
                                pairwise_rows.append(row)
                                comparisons += 1
                                pr = row.get("pairwise") or {}
                                if bool(pr.get("call_failed")):
                                    pair_failures += 1
                                winner_cid = str(pr.get("winner_cid") or "tie").strip() or "tie"
                                conf = _clamp_i(pr.get("confidence_0_3"), 0, 3)
                                if winner_cid == "tie":
                                    pair_scores[pair_ids[i]] += 0.5
                                    pair_scores[pair_ids[j]] += 0.5
                                elif winner_cid in pair_scores:
                                    pair_scores[winner_cid] += 1.0 + (0.1 * float(conf))

                        pair_info["comparisons"] = int(comparisons)
                        pair_info["cache_hits"] = int(pairwise_stats["cache_hits"]) - cache_hits_before
                        pair_info["api_calls"] = int(pairwise_stats["api_calls"]) - api_calls_before
                        pair_info["failures"] = int(pair_failures)
                        pair_sorted = sorted(
                            pair_ids,
                            key=lambda cid: (-float(pair_scores.get(cid) or 0.0),) + _sort_key(cid, lane, pool),
                        )
                        top_ok_sorted = pair_sorted + top_ok_sorted[len(pair_ids) :]
                        pair_info["ids_after"] = list(pair_sorted)
                        pair_info["scores"] = {cid: round(float(pair_scores.get(cid) or 0.0), 3) for cid in pair_sorted}
                    else:
                        pair_info["ids_after"] = list(pair_ids)
                        pair_info["scores"] = {cid: 0.0 for cid in pair_ids}

                rankings_i[lane][pool] = top_ok_sorted + top_fail + tail
                pairwise_summary[pair_key] = pair_info

        write_json(
            rankings_i_path,
            {
                "run_id": run_ctx.run_id,
                "generated_at_utc": utc_now_iso(),
                "rankings": rankings_i,
                "pairwise_refinement": {
                    "enabled": bool(PAIRWISE_ENABLED),
                    "top_k": int(PAIRWISE_TOP_K),
                    "summary": pairwise_summary,
                },
            },
        )

        tokens_in_total = 0
        tokens_cached_in_total = 0
        tokens_out_total = 0
        cost_total = 0.0
        insuff_by_lp: Dict[str, int] = {}
        off_topic_by_lp: Dict[str, int] = {}
        pointwise_failures_total = 0
        pointwise_failures_new = 0
        pointwise_latencies: List[float] = []

        for row in rows_all:
            tin, tc, tout, cost, lat = _usage_cost_from_meta((row.get("openai") or {}))
            tokens_in_total += tin
            tokens_cached_in_total += tc
            tokens_out_total += tout
            cost_total += cost
            if float(lat or 0.0) > 0:
                pointwise_latencies.append(float(lat))
            rr = row.get("rerank") or {}
            if isinstance(rr, dict):
                key = f"{row.get('lane')}/{row.get('pool')}"
                if bool(rr.get("insufficient_info")):
                    insuff_by_lp[key] = int(insuff_by_lp.get(key) or 0) + 1
                if bool(rr.get("off_topic")):
                    off_topic_by_lp[key] = int(off_topic_by_lp.get(key) or 0) + 1
                if bool(rr.get("call_failed")):
                    pointwise_failures_total += 1
                    if not bool(row.get("cache_hit")):
                        pointwise_failures_new += 1

        pairwise_tokens_in_total = 0
        pairwise_tokens_cached_total = 0
        pairwise_tokens_out_total = 0
        pairwise_cost_total = 0.0
        pairwise_failures_total = 0
        for row in pairwise_rows:
            tin, tc, tout, cost, _lat = _usage_cost_from_meta((row.get("openai") or {}))
            pairwise_tokens_in_total += tin
            pairwise_tokens_cached_total += tc
            pairwise_tokens_out_total += tout
            pairwise_cost_total += cost
            pr = row.get("pairwise") or {}
            if isinstance(pr, dict) and bool(pr.get("call_failed")):
                pairwise_failures_total += 1

        tokens_in_total += pairwise_tokens_in_total
        tokens_cached_in_total += pairwise_tokens_cached_total
        tokens_out_total += pairwise_tokens_out_total
        cost_total += pairwise_cost_total

        stage_failures_total = int(pointwise_failures_total) + int(pairwise_failures_total)
        total_cache_hits = int(len(cached_rows)) + int(pairwise_stats["cache_hits"])
        total_bad_cache = int(bad_cache) + int(pairwise_stats["bad_cache"])
        total_api_calls = int(len(new_rows)) + int(pairwise_stats["api_calls"])
        total_tasks = int(len(tasks)) + int(len(pairwise_rows))

        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault(stage, {})["counts"] = {
            "model": model_rerank,
            "model_used": model_rerank,
            "rerank_top_k_pre": int(K),
            "rerank_concurrency": int(CONCURRENCY),
            "rerank_cache_version": str(RERANK_CACHE_VERSION),
            "pointwise_reasoning": str(POINTWISE_REASONING),
            "pointwise_max_output_tokens": int(POINTWISE_MAX_OUTPUT_TOKENS),
            "pointwise_timeout_s": float(POINTWISE_TIMEOUT_S),
            "pairwise_reasoning": str(PAIRWISE_REASONING),
            "pairwise_max_output_tokens": int(PAIRWISE_MAX_OUTPUT_TOKENS),
            "pairwise_timeout_s": float(PAIRWISE_TIMEOUT_S),
            "tasks_total": int(total_tasks),
            "cache_hits": int(total_cache_hits),
            "bad_cache": int(total_bad_cache),
            "api_calls": int(total_api_calls),
            "failures": int(stage_failures_total),
            "tokens_in_total": int(tokens_in_total),
            "tokens_cached_in_total": int(tokens_cached_in_total),
            "tokens_out_total": int(tokens_out_total),
            "tokens_in_new": int(tokens_in_new + int(pairwise_stats["tokens_in_new"])),
            "tokens_cached_in_new": int(tokens_cached_in_new + int(pairwise_stats["tokens_cached_in_new"])),
            "tokens_out_new": int(tokens_out_new + int(pairwise_stats["tokens_out_new"])),
            "cost_usd_total": float(cost_total),
            "cost_usd_new": float(float(cost_new) + float(pairwise_stats["cost_usd_new"])),
            "cost_usd_est_total": float(cost_total),
            "cost_usd_est_new": float(float(cost_new) + float(pairwise_stats["cost_usd_new"])),
            "rerank_results_jsonl": str(rerank_results_path),
            "rankings_stagei_json": str(rankings_i_path),
            "insufficient_by_lane_pool": insuff_by_lp,
            "off_topic_by_lane_pool": off_topic_by_lp,
            "pointwise_tasks_total": int(len(tasks)),
            "pointwise_cache_hits": int(len(cached_rows)),
            "pointwise_bad_cache": int(bad_cache),
            "pointwise_api_calls": int(len(new_rows)),
            "pointwise_runtime_exceptions": int(runtime_exceptions),
            "pointwise_failures_total": int(pointwise_failures_total),
            "pointwise_failures_new": int(pointwise_failures_new),
            "pairwise_enabled": bool(PAIRWISE_ENABLED),
            "pairwise_top_k": int(PAIRWISE_TOP_K),
            "pairwise_comparisons_total": int(len(pairwise_rows)),
            "pairwise_cache_hits": int(pairwise_stats["cache_hits"]),
            "pairwise_bad_cache": int(pairwise_stats["bad_cache"]),
            "pairwise_api_calls": int(pairwise_stats["api_calls"]),
            "pairwise_failures_total": int(pairwise_failures_total),
            "pairwise_cost_usd_total": float(pairwise_cost_total),
            "pairwise_cost_usd_new": float(pairwise_stats["cost_usd_new"]),
            "pairwise_summary": pairwise_summary,
            "latency_s_p50": (None if not pointwise_latencies else float(statistics.median(pointwise_latencies))),
            "pairwise_latency_s_p50": (None if not pairwise_latencies else float(statistics.median(pairwise_latencies))),
        }
        save_metrics(run_ctx, metrics)

    if check_cancel is not None:
        await check_cancel()

    return {
        "rerank_results_jsonl": str(rerank_results_path),
        "rankings_stagei_json": str(rankings_i_path),
        "tasks_total": int(total_tasks),
        "api_calls": int(total_api_calls),
        "cache_hits": int(total_cache_hits),
        "bad_cache": int(total_bad_cache),
        "failures": int(stage_failures_total),
        "cost_usd_new": float(float(cost_new) + float(pairwise_stats["cost_usd_new"])),
        "cost_usd_total": float(cost_total),
    }
