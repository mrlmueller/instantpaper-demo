from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from openai import OpenAI


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "sources-v2" / "runs"
OUTPUT_DIR = REPO_ROOT / "sources-v2" / "prompt_research" / "probe_outputs"
CACHE_DIR = OUTPUT_DIR / "phase_i_rerank_probe_cache"
USAGE_LOG_PATH = OUTPUT_DIR / "phase_i_rerank_probe_usage.jsonl"

NANO_MODEL = "gpt-5-nano"
REFERENCE_MODEL = "gpt-5-mini"

MODEL_PRICES_USD_PER_1M: Dict[str, Dict[str, float]] = {
    "gpt-5-nano": {"input": 0.05, "cached": 0.005, "output": 0.40},
    "gpt-5-mini": {"input": 0.25, "cached": 0.025, "output": 2.00},
}

DEFAULT_RUN_IDS = [
    "ca79147de41f8edbfb47c9e5",
    "25e6243ac55a5904fb1fcdfe",
]


def _now_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _sanitize(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {str(k): _sanitize(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_sanitize(v) for v in obj]
    if isinstance(obj, Path):
        return str(obj)
    return obj


def _write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_sanitize(obj), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_sanitize(obj), ensure_ascii=False) + "\n")


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _clean_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip())


def _truncate(text: Any, max_len: int = 240) -> str:
    s = _clean_space(text)
    return s if len(s) <= max_len else (s[: max_len - 1] + "…")


def _stable_hash(*parts: Any, length: int = 24) -> str:
    import hashlib

    payload = "\n".join([_clean_space(p) for p in parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def _response_to_jsonable(response: Any) -> Dict[str, Any]:
    if hasattr(response, "model_dump"):
        return response.model_dump(mode="json")
    if hasattr(response, "dict"):
        return response.dict()
    if isinstance(response, dict):
        return response
    return {"repr": repr(response)}


def _extract_usage(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    if usage is None and isinstance(response, dict):
        usage = response.get("usage")
    if usage is None:
        return {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    if isinstance(usage, dict):
        in_tok = int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0)
        out_tok = int(usage.get("output_tokens") or usage.get("completion_tokens") or 0)
        in_det = usage.get("input_tokens_details") or {}
        cached = int(in_det.get("cached_tokens") or usage.get("cached_input_tokens") or 0)
        return {"input_tokens": in_tok, "cached_input_tokens": cached, "output_tokens": out_tok}
    in_tok = int(getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None) or 0)
    out_tok = int(getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None) or 0)
    in_det = getattr(usage, "input_tokens_details", None)
    cached = 0
    if in_det is not None:
        cached = int(getattr(in_det, "cached_tokens", None) or 0)
    cached = max(cached, int(getattr(usage, "cached_input_tokens", None) or 0))
    return {"input_tokens": in_tok, "cached_input_tokens": cached, "output_tokens": out_tok}


def _extract_output_text_or_refusal(response: Any) -> Tuple[str, Optional[str]]:
    txt = getattr(response, "output_text", None)
    if isinstance(txt, str) and txt.strip():
        return txt, None

    parts: List[str] = []
    refusal: Optional[str] = None
    output = getattr(response, "output", None)
    if not isinstance(output, list):
        output = response.get("output") if isinstance(response, dict) else []
    for item in output or []:
        content = item.get("content") if isinstance(item, dict) else getattr(item, "content", None)
        if not isinstance(content, list):
            continue
        for c in content:
            ctype = c.get("type") if isinstance(c, dict) else getattr(c, "type", None)
            if ctype in {"output_text", "text"}:
                t = c.get("text") if isinstance(c, dict) else getattr(c, "text", None)
                if t:
                    parts.append(str(t))
            elif ctype == "refusal":
                r = c.get("refusal") if isinstance(c, dict) else getattr(c, "refusal", None)
                if r:
                    refusal = str(r)
    return "\n".join([p for p in parts if _clean_space(p)]), refusal


def _cost_from_usage(model: str, usage: Dict[str, int]) -> float:
    price = MODEL_PRICES_USD_PER_1M[model]
    in_tok = int(usage.get("input_tokens") or 0)
    cached = int(usage.get("cached_input_tokens") or 0)
    out_tok = int(usage.get("output_tokens") or 0)
    uncached = max(0, in_tok - cached)
    return (
        (uncached / 1_000_000.0) * price["input"]
        + (cached / 1_000_000.0) * price["cached"]
        + (out_tok / 1_000_000.0) * price["output"]
    )


def _call_json_schema(
    client: OpenAI,
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    schema_name: str,
    schema: Dict[str, Any],
    reasoning_effort: str,
    max_output_tokens: int,
    timeout_s: float = 180.0,
    max_retries: int = 5,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    last_err: Optional[Exception] = None
    attempts_meta: List[Dict[str, Any]] = []
    for attempt in range(int(max_retries) + 1):
        t0 = time.time()
        response = client.responses.create(
            model=model,
            input=[
                {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
            ],
            reasoning={"effort": reasoning_effort},
            max_output_tokens=int(max_output_tokens),
            text={
                "format": {
                    "type": "json_schema",
                    "name": schema_name,
                    "schema": schema,
                    "strict": True,
                }
            },
            timeout=float(timeout_s),
        )
        raw_text, refusal = _extract_output_text_or_refusal(response)
        if refusal:
            raise RuntimeError(f"Model refusal: {refusal}")
        if not raw_text.strip():
            usage = _extract_usage(response)
            attempts_meta.append(
                {
                    "attempt": attempt + 1,
                    "latency_s": round(time.time() - t0, 3),
                    "usage": usage,
                    "cost_usd": round(_cost_from_usage(model, usage), 8),
                    "response": _response_to_jsonable(response),
                    "error": "empty_output",
                }
            )
            last_err = RuntimeError("Empty model output")
            continue
        try:
            obj = json.loads(raw_text)
        except Exception as exc:
            usage = _extract_usage(response)
            attempts_meta.append(
                {
                    "attempt": attempt + 1,
                    "latency_s": round(time.time() - t0, 3),
                    "usage": usage,
                    "cost_usd": round(_cost_from_usage(model, usage), 8),
                    "response": _response_to_jsonable(response),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            last_err = exc
            if attempt >= int(max_retries):
                raise
            time.sleep(0.75 * (attempt + 1))
            continue
        usage = _extract_usage(response)
        attempts_meta.append(
            {
                "attempt": attempt + 1,
                "latency_s": round(time.time() - t0, 3),
                "usage": usage,
                "cost_usd": round(_cost_from_usage(model, usage), 8),
                "response": _response_to_jsonable(response),
                "error": None,
            }
        )
        total_usage = {
            "input_tokens": sum(int((a.get("usage") or {}).get("input_tokens") or 0) for a in attempts_meta),
            "cached_input_tokens": sum(int((a.get("usage") or {}).get("cached_input_tokens") or 0) for a in attempts_meta),
            "output_tokens": sum(int((a.get("usage") or {}).get("output_tokens") or 0) for a in attempts_meta),
        }
        meta = {
            "model_requested": model,
            "model_used": getattr(response, "model", None) or model,
            "latency_s": round(sum(float(a.get("latency_s") or 0.0) for a in attempts_meta), 3),
            "usage": total_usage,
            "cost_estimate": {"total_cost_usd": round(sum(float(a.get("cost_usd") or 0.0) for a in attempts_meta), 8)},
            "response": attempts_meta[-1]["response"],
            "attempt": attempt + 1,
            "attempts": attempts_meta,
        }
        return obj, meta
    raise RuntimeError(f"Structured output parse failed after {len(attempts_meta)} attempts: {last_err}")


@dataclass
class RunData:
    run_id: str
    run_dir: Path
    chapter_title: str
    chapter_spec: str
    chapter_contract: str
    facet_ids: List[str]
    required_facets: List[Dict[str, Any]]
    scores_by_id: Dict[str, Dict[str, Any]]
    candidates_by_id: Dict[str, Dict[str, Any]]
    rankings: Dict[str, Dict[str, List[str]]]


@dataclass
class Task:
    run_id: str
    chapter_title: str
    chapter_contract: str
    lane: str
    pool: str
    cid: str
    candidate: Dict[str, Any]
    score_row: Dict[str, Any]
    required_facets: List[Dict[str, Any]]
    facet_ids: List[str]
    tags: List[Dict[str, Any]]
    base_lane_score: float


def _extract_chapter_input(run_dir: Path) -> Tuple[str, str]:
    p = run_dir / "query_plan_attempt1.user_prompt.txt"
    text = p.read_text(encoding="utf-8") if p.exists() else ""
    m_title = re.search(r"CHAPTER_TITLE:\s*(.*?)\n\s*\nCHAPTER_SPEC", text, flags=re.S)
    m_spec = re.search(r"CHAPTER_SPEC.*?:\s*(.*?)\n\s*\nTASK:", text, flags=re.S)
    title = _clean_space(m_title.group(1) if m_title else "")
    spec = _clean_space(m_spec.group(1) if m_spec else "")
    return title, spec


def _build_chapter_contract(plan: Dict[str, Any], title: str, spec: str) -> str:
    core = ((plan.get("core_object_terms") or {}).get("en") or [])[:8]
    anchors = ((plan.get("primary_context_anchors") or {}).get("en") or [])[:8]
    must_keep = (plan.get("must_keep_constraints") or [])[:6]
    drift = (plan.get("drift_risks") or [])[:5]
    parts = [
        f"Chapter title: {title}",
        f"Chapter spec: {spec}",
        f"Topic summary: {_clean_space(plan.get('topic_summary_en'))}",
        "Core object terms: " + ", ".join([_clean_space(x) for x in core if _clean_space(x)]),
        "Primary anchors: " + ", ".join([_clean_space(x) for x in anchors if _clean_space(x)]),
        "Must keep: " + ", ".join([_clean_space(x) for x in must_keep if _clean_space(x)]),
        "Drift risks: " + ", ".join([_clean_space(x) for x in drift if _clean_space(x)]),
    ]
    return "\n".join([p for p in parts if _clean_space(p)])


def _load_run(run_id: str) -> RunData:
    run_dir = RUNS_ROOT / run_id
    title, spec = _extract_chapter_input(run_dir)
    plan = _read_json(run_dir / "query_plan.json")
    rankings = _read_json(run_dir / "rankings_stageg.json")["rankings"]

    scores_by_id: Dict[str, Dict[str, Any]] = {}
    for row in _iter_jsonl(run_dir / "scores_final.jsonl"):
        cid = str(row.get("id") or "").strip()
        if cid:
            scores_by_id[cid] = row

    cand_path = run_dir / "candidates_expanded.jsonl"
    if not cand_path.exists():
        cand_path = run_dir / "candidates_normalized.jsonl"
    candidates_by_id: Dict[str, Dict[str, Any]] = {}
    for c in _iter_jsonl(cand_path):
        cid = str(c.get("id") or "").strip()
        if cid:
            candidates_by_id[cid] = c

    cov_path = run_dir / "coverage_tags.jsonl"
    if cov_path.exists():
        for rec in _iter_jsonl(cov_path):
            cid = str(rec.get("id") or "").strip()
            if cid and cid in scores_by_id:
                scores_by_id[cid]["coverage_tags"] = rec.get("coverage_tags") or []

    facet_ids = [str(f.get("facet_id") or "") for f in (plan.get("facets") or []) if str(f.get("facet_id") or "").strip()]
    required = []
    for f in (plan.get("facets") or []):
        try:
            w = int(f.get("importance_weight") or 0)
        except Exception:
            w = 0
        if w >= 4:
            required.append(
                {
                    "facet_id": str(f.get("facet_id") or "").strip(),
                    "facet_label_en": _clean_space(f.get("facet_label_en")),
                    "importance_weight": w,
                }
            )

    return RunData(
        run_id=run_id,
        run_dir=run_dir,
        chapter_title=title,
        chapter_spec=spec,
        chapter_contract=_build_chapter_contract(plan, title, spec),
        facet_ids=facet_ids,
        required_facets=required,
        scores_by_id=scores_by_id,
        candidates_by_id=candidates_by_id,
        rankings=rankings,
    )


def _compact_tags(tags: List[Dict[str, Any]], *, shuffle: bool = False) -> List[Dict[str, Any]]:
    compact = []
    for idx, tag in enumerate(tags, start=1):
        if not isinstance(tag, dict):
            continue
        fid = str(tag.get("facet_id") or "").strip()
        if not fid:
            continue
        compact.append(
            {
                "tag_id": idx,
                "facet_id": fid,
                "score": round(float(tag.get("score") or 0.0), 4),
                "excerpt": _truncate(tag.get("excerpt") or "", 260),
            }
        )
    compact.sort(key=lambda x: (-float(x["score"]), int(x["tag_id"])))
    if shuffle:
        rng = random.Random(1337)
        rng.shuffle(compact)
    return compact


def _compact_required_facets(required_facets: List[Dict[str, Any]], max_items: int = 6) -> List[Dict[str, Any]]:
    compact: List[Dict[str, Any]] = []
    for row in list(required_facets or [])[: int(max_items)]:
        compact.append(
            {
                "facet_id": str(row.get("facet_id") or "").strip(),
                "label": _truncate(row.get("facet_label_en") or "", 80),
            }
        )
    return [r for r in compact if r["facet_id"]]


def _compact_chapter_contract(text: str, max_len: int = 1400) -> str:
    lines = [_clean_space(line) for line in str(text or "").splitlines() if _clean_space(line)]
    joined = "\n".join(lines)
    return _truncate(joined, max_len)


def _build_tasks(run: RunData, top_k: int = 40) -> List[Task]:
    tasks: List[Task] = []
    for lane in ["match", "authority"]:
        for pool in ["with_abstract", "without_abstract"]:
            ids = list((run.rankings.get(lane) or {}).get(pool) or [])[: int(top_k)]
            for cid in ids:
                cid = str(cid)
                row = run.scores_by_id.get(cid) or {}
                cand = run.candidates_by_id.get(cid) or {}
                tags = list(row.get("coverage_tags") or [])
                tasks.append(
                    Task(
                        run_id=run.run_id,
                        chapter_title=run.chapter_title,
                        chapter_contract=run.chapter_contract,
                        lane=lane,
                        pool=pool,
                        cid=cid,
                        candidate=cand,
                        score_row=row,
                        required_facets=run.required_facets,
                        facet_ids=run.facet_ids,
                        tags=tags,
                        base_lane_score=float(((row.get("scores") or {}).get(f"{lane}_lane")) or 0.0),
                    )
                )
    return tasks


BASELINE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["llm_score_0_100", "covered_facets", "rationale", "insufficient_info"],
    "properties": {
        "llm_score_0_100": {"type": "integer", "minimum": 0, "maximum": 100},
        "covered_facets": {"type": "array", "items": {"type": "string"}, "maxItems": 12},
        "rationale": {"type": "string", "maxLength": 800},
        "insufficient_info": {"type": "boolean"},
    },
}


CONTRACT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["final_score_0_100", "covered_facets", "evidence_tag_ids", "brief_rationale", "insufficient_info"],
    "properties": {
        "final_score_0_100": {"type": "integer", "minimum": 0, "maximum": 100},
        "covered_facets": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "evidence_tag_ids": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 99}, "maxItems": 6},
        "brief_rationale": {"type": "string", "maxLength": 260},
        "insufficient_info": {"type": "boolean"},
    },
}


RUBRIC_SCHEMA = {
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
        "covered_facets": {"type": "array", "items": {"type": "string"}, "maxItems": 10},
        "evidence_tag_ids": {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 99}, "maxItems": 6},
        "off_topic": {"type": "boolean"},
        "insufficient_info": {"type": "boolean"},
        "brief_rationale": {"type": "string", "maxLength": 260},
    },
}


REFERENCE_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["grade_0_3", "direct_use", "off_topic", "brief_rationale"],
    "properties": {
        "grade_0_3": {"type": "integer", "minimum": 0, "maximum": 3},
        "direct_use": {"type": "boolean"},
        "off_topic": {"type": "boolean"},
        "brief_rationale": {"type": "string", "maxLength": 280},
    },
}


def _lane_guidance(lane: str) -> str:
    if lane == "authority":
        return "Authority lane: foundational value matters, but only after clear topical relevance to the chapter is established."
    return "Match lane: prioritize direct topical fit and chapter usefulness over prestige."


def _candidate_metadata_block(task: Task, *, include_authors: bool = False, abstract_max_len: int = 900) -> str:
    c = task.candidate or {}
    row = task.score_row or {}
    title = _clean_space(c.get("title") or row.get("title"))
    year = c.get("year") if c.get("year") is not None else row.get("year")
    venue = _clean_space(c.get("venue") or row.get("venue"))
    citations = int(c.get("citations") or row.get("citations") or 0)
    authors = c.get("authors") or []
    if authors and isinstance(authors[0], dict):
        authors = [str(a.get("name") or "").strip() for a in authors]
    authors = [a for a in authors if _clean_space(a)][:6]
    abstract = _truncate(c.get("abstract") or "", abstract_max_len)
    parts = [
        f"title={title}",
        f"year={year}",
        f"venue={venue}",
        f"citations={citations}",
        f"abstract_present={bool(_clean_space(c.get('abstract') or ''))}",
    ]
    if include_authors:
        parts.append(f"authors={json.dumps(authors, ensure_ascii=False)}")
    if abstract:
        parts.append(f"abstract={abstract}")
    return "\n".join(parts)


def _build_baseline_prompt(task: Task, *, shuffle_tags: bool = False) -> Tuple[str, str, Dict[str, Any], str, int]:
    tags_json = json.dumps(_compact_tags(task.tags, shuffle=shuffle_tags), ensure_ascii=False)
    required_json = json.dumps(task.required_facets, ensure_ascii=False)
    system_prompt = (
        "You are reranking scientific sources for a chapter in an academic paper.\n"
        "You MUST only use the provided evidence excerpts (coverage_tags) and candidate metadata.\n"
        "Do NOT infer content that is not supported by the excerpts/metadata.\n"
        "If evidence is insufficient, set insufficient_info=true and keep the score conservative.\n\n"
        "Without-abstract honesty rule:\n"
        "- If pool==\"without_abstract\", set insufficient_info=true unless the metadata/excerpts clearly support MULTIPLE required facets.\n\n"
        "Output ONLY valid JSON matching the provided schema. No Markdown. No extra keys."
    )
    user_prompt = (
        f"CHAPTER_TITLE:\n{task.chapter_title}\n\n"
        f"LANE:\n{task.lane}\n\n"
        f"POOL:\n{task.pool}\n\n"
        f"LANE_GUIDANCE:\n{_lane_guidance(task.lane)}\n\n"
        f"FACETS_REQUIRED (weight>=4):\n{required_json}\n\n"
        f"ALL_FACET_IDS:\n{json.dumps(task.facet_ids, ensure_ascii=False)}\n\n"
        f"CANDIDATE_METADATA:\n{_candidate_metadata_block(task, include_authors=True, abstract_max_len=1200)}\n\n"
        f"CANDIDATE_EVIDENCE (coverage_tags):\n{tags_json}\n\n"
        "INSTRUCTIONS:\n"
        "- Score 0..100 for usefulness for this chapter (higher = better).\n"
        "- covered_facets: choose ONLY facets explicitly supported by the excerpts; keep it short (<=12).\n"
        "- rationale: cite the excerpts/metadata you used; do not invent.\n"
        "- insufficient_info: true if the evidence is too thin to judge confidently.\n"
    )
    return system_prompt, user_prompt, BASELINE_SCHEMA, "medium", 8000


def _build_contract_prompt(
    task: Task,
    *,
    shuffle_tags: bool = False,
    reasoning_effort: str = "low",
    max_output_tokens: int = 320,
) -> Tuple[str, str, Dict[str, Any], str, int]:
    tags_json = json.dumps(_compact_tags(task.tags, shuffle=shuffle_tags), ensure_ascii=False)
    required_json = json.dumps(_compact_required_facets(task.required_facets, max_items=5), ensure_ascii=False)
    chapter_contract = _compact_chapter_contract(task.chapter_contract, max_len=900)
    system_prompt = (
        "You are scoring whether a scientific source is useful for one specific chapter.\n"
        "Use ONLY the candidate metadata and numbered evidence tags.\n"
        "Do not reward generic adjacency. Do not reward prestige unless relevance is supported.\n"
        "If evidence is thin, keep the score conservative and set insufficient_info=true.\n"
        "Return strict JSON only."
    )
    user_prompt = (
        f"CHAPTER_CONTRACT:\n{chapter_contract}\n\n"
        f"LANE:\n{task.lane}\nPOOL:\n{task.pool}\n\n"
        f"LANE_GUIDANCE:\n{_lane_guidance(task.lane)}\n\n"
        f"REQUIRED_FACETS:\n{required_json}\n\n"
        f"CANDIDATE_METADATA:\n{_candidate_metadata_block(task, include_authors=False, abstract_max_len=650)}\n\n"
        f"EVIDENCE_TAGS:\n{tags_json}\n\n"
        "SCORING BANDS:\n"
        "- 90-100: direct, central, clearly useful for this chapter, strongly supported.\n"
        "- 70-89: clearly useful, good topical fit, evidence adequate.\n"
        "- 50-69: partly useful or somewhat adjacent; limited but real support.\n"
        "- 30-49: weak or generic background value only.\n"
        "- 0-29: off-topic, misleading, or unsupported.\n\n"
        "OUTPUT RULES:\n"
        "- covered_facets: only facets explicitly supported by the evidence tags.\n"
        "- evidence_tag_ids: list only the tag_ids you actually used.\n"
        "- brief_rationale: one short sentence, no invented content.\n"
        "- For without_abstract items, be especially conservative.\n"
    )
    return system_prompt, user_prompt, CONTRACT_SCHEMA, reasoning_effort, max_output_tokens


def _build_rubric_prompt(task: Task, *, shuffle_tags: bool = False, reasoning_effort: str = "medium") -> Tuple[str, str, Dict[str, Any], str, int]:
    tags_json = json.dumps(_compact_tags(task.tags, shuffle=shuffle_tags), ensure_ascii=False)
    required_json = json.dumps(_compact_required_facets(task.required_facets, max_items=5), ensure_ascii=False)
    chapter_contract = _compact_chapter_contract(task.chapter_contract, max_len=900)
    system_prompt = (
        "You are a careful scientific-source judge.\n"
        "Use ONLY the chapter contract, candidate metadata, and numbered evidence tags.\n"
        "Your job is to score dimensions consistently, not to write an essay.\n"
        "Treat generic but high-status papers as weak unless they clearly help this exact chapter.\n"
        "Return strict JSON only."
    )
    user_prompt = (
        f"CHAPTER_CONTRACT:\n{chapter_contract}\n\n"
        f"LANE:\n{task.lane}\nPOOL:\n{task.pool}\n\n"
        f"LANE_GUIDANCE:\n{_lane_guidance(task.lane)}\n\n"
        f"REQUIRED_FACETS:\n{required_json}\n\n"
        f"CANDIDATE_METADATA:\n{_candidate_metadata_block(task, include_authors=False, abstract_max_len=650)}\n\n"
        f"EVIDENCE_TAGS:\n{tags_json}\n\n"
        "DIMENSION DEFINITIONS (0-4 each):\n"
        "- topical_fit_0_4: how directly the source matches the chapter object/question.\n"
        "- evidence_strength_0_4: how strong and specific the provided evidence tags are.\n"
        "- chapter_utility_0_4: how likely the source is to help write this chapter.\n"
        "- lane_fit_0_4: for match, direct topical fit; for authority, foundational value AFTER relevance.\n\n"
        "HARD RULES:\n"
        "- off_topic=true if the candidate is clearly outside the chapter's target problem.\n"
        "- insufficient_info=true if evidence is too thin for a confident score.\n"
        "- Without-abstract items should usually be conservative unless multiple strong evidence tags support them.\n"
        "- covered_facets must be explicitly supported only.\n"
        "- evidence_tag_ids must only include tags you actually used.\n"
        "- brief_rationale must be short and concrete.\n"
    )
    max_out = 2200 if reasoning_effort == "medium" else 800
    return system_prompt, user_prompt, RUBRIC_SCHEMA, reasoning_effort, max_out


def _build_rubric_object_gate_prompt(task: Task, *, shuffle_tags: bool = False) -> Tuple[str, str, Dict[str, Any], str, int]:
    tags_json = json.dumps(_compact_tags(task.tags, shuffle=shuffle_tags), ensure_ascii=False)
    required_json = json.dumps(_compact_required_facets(task.required_facets, max_items=5), ensure_ascii=False)
    chapter_contract = _compact_chapter_contract(task.chapter_contract, max_len=900)
    system_prompt = (
        "You are a careful scientific-source judge.\n"
        "Use ONLY the chapter contract, candidate metadata, and numbered evidence tags.\n"
        "A source cannot rank highly unless the evidence shows clear connection to the chapter's actual object, corpus, or domain.\n"
        "Method overlap without object overlap is not enough.\n"
        "Authority does not rescue off-target papers.\n"
        "Return strict JSON only."
    )
    user_prompt = (
        f"CHAPTER_CONTRACT:\n{chapter_contract}\n\n"
        f"LANE:\n{task.lane}\nPOOL:\n{task.pool}\n\n"
        f"LANE_GUIDANCE:\n{_lane_guidance(task.lane)}\n\n"
        f"REQUIRED_FACETS:\n{required_json}\n\n"
        f"CANDIDATE_METADATA:\n{_candidate_metadata_block(task, include_authors=False, abstract_max_len=650)}\n\n"
        f"EVIDENCE_TAGS:\n{tags_json}\n\n"
        "DIMENSION DEFINITIONS (0-4 each):\n"
        "- topical_fit_0_4: direct match to the chapter object/question, not just a shared method.\n"
        "- evidence_strength_0_4: strength and specificity of the provided evidence tags.\n"
        "- chapter_utility_0_4: likely usefulness for actually writing the chapter.\n"
        "- lane_fit_0_4: for match, direct topical fit; for authority, foundational value only AFTER object fit.\n\n"
        "OBJECT GATE:\n"
        "- If title/abstract/evidence do not clearly connect the source to the chapter object/domain, set topical_fit_0_4<=1.\n"
        "- If the source is mainly about another domain/object, set off_topic=true.\n"
        "- If object fit is missing, authority papers should not be scored as strong simply because they are broad or influential.\n\n"
        "HARD RULES:\n"
        "- off_topic=true if the candidate is clearly outside the chapter's target problem.\n"
        "- insufficient_info=true if evidence is too thin for a confident score.\n"
        "- Without-abstract items should usually be conservative unless multiple strong evidence tags support them.\n"
        "- covered_facets must be explicitly supported only.\n"
        "- evidence_tag_ids must only include tags you actually used.\n"
        "- brief_rationale must be short and concrete.\n"
    )
    return system_prompt, user_prompt, RUBRIC_SCHEMA, "low", 800


def _reference_prompt(task: Task) -> Tuple[str, str, Dict[str, Any], str, int]:
    tags_json = json.dumps(_compact_tags(task.tags, shuffle=False), ensure_ascii=False)
    required_json = json.dumps(_compact_required_facets(task.required_facets, max_items=6), ensure_ascii=False)
    chapter_contract = _compact_chapter_contract(task.chapter_contract, max_len=1000)
    system_prompt = (
        "You are a senior researcher judging whether a source would genuinely help write a chapter.\n"
        "Use the chapter contract, title, abstract, metadata, and evidence tags.\n"
        "Reward direct usefulness; do not reward generic adjacency.\n"
        "Return strict JSON only."
    )
    user_prompt = (
        f"CHAPTER_CONTRACT:\n{chapter_contract}\n\n"
        f"LANE:\n{task.lane}\nPOOL:\n{task.pool}\n\n"
        f"REQUIRED_FACETS:\n{required_json}\n\n"
        f"CANDIDATE_METADATA:\n{_candidate_metadata_block(task, include_authors=False, abstract_max_len=750)}\n\n"
        f"EVIDENCE_TAGS:\n{tags_json}\n\n"
        "GRADE SCALE:\n"
        "- 3: directly useful / likely cite-worthy for this lane and chapter.\n"
        "- 2: useful but not central.\n"
        "- 1: marginal / generic context only.\n"
        "- 0: off-topic or not useful.\n"
    )
    return system_prompt, user_prompt, REFERENCE_SCHEMA, "low", 1000


def _normalize_covered(covered: Any, facet_ids: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for fid in list(covered or []):
        fid = str(fid or "").strip()
        if fid and fid in facet_ids and fid not in seen:
            seen.add(fid)
            out.append(fid)
    return out


def _variant_result(task: Task, variant: str, obj: Dict[str, Any]) -> Dict[str, Any]:
    if variant == "baseline_current":
        score = int(max(0, min(100, int(obj.get("llm_score_0_100") or 0))))
        return {
            "variant": variant,
            "score": score,
            "insufficient_info": bool(obj.get("insufficient_info")),
            "covered_facets": _normalize_covered(obj.get("covered_facets"), task.facet_ids),
            "evidence_tag_ids": [],
            "brief_rationale": _truncate(obj.get("rationale") or "", 260),
            "off_topic": False,
        }
    if variant.startswith("contract_"):
        score = int(max(0, min(100, int(obj.get("final_score_0_100") or 0))))
        return {
            "variant": variant,
            "score": score,
            "insufficient_info": bool(obj.get("insufficient_info")),
            "covered_facets": _normalize_covered(obj.get("covered_facets"), task.facet_ids),
            "evidence_tag_ids": [int(x) for x in (obj.get("evidence_tag_ids") or [])[:6] if isinstance(x, int)],
            "brief_rationale": _truncate(obj.get("brief_rationale") or "", 260),
            "off_topic": False,
        }
    if variant.startswith("rubric_"):
        topical = int(max(0, min(4, int(obj.get("topical_fit_0_4") or 0))))
        evid = int(max(0, min(4, int(obj.get("evidence_strength_0_4") or 0))))
        util = int(max(0, min(4, int(obj.get("chapter_utility_0_4") or 0))))
        lane_fit = int(max(0, min(4, int(obj.get("lane_fit_0_4") or 0))))
        score = round((35 * topical + 25 * evid + 25 * util + 15 * lane_fit) / 4.0)
        off_topic = bool(obj.get("off_topic"))
        insufficient = bool(obj.get("insufficient_info"))
        covered = _normalize_covered(obj.get("covered_facets"), task.facet_ids)
        evidence_ids = [int(x) for x in (obj.get("evidence_tag_ids") or [])[:6] if isinstance(x, int)]
        if off_topic:
            score = min(score, 25)
        if insufficient:
            score = min(score, 35 if task.pool == "without_abstract" else 45)
        if task.lane == "authority" and topical <= 1:
            score = min(score, 35)
        if not covered:
            score = min(score, 30)
        return {
            "variant": variant,
            "score": int(max(0, min(100, score))),
            "insufficient_info": insufficient,
            "covered_facets": covered,
            "evidence_tag_ids": evidence_ids,
            "brief_rationale": _truncate(obj.get("brief_rationale") or "", 260),
            "off_topic": off_topic,
            "rubric": {
                "topical_fit_0_4": topical,
                "evidence_strength_0_4": evid,
                "chapter_utility_0_4": util,
                "lane_fit_0_4": lane_fit,
            },
        }
    raise ValueError(f"Unknown variant: {variant}")


def _rerank_key(task: Task) -> Tuple[str, str, str, str]:
    return task.run_id, task.lane, task.pool, task.cid


def _sort_ranked(
    results_by_variant: Dict[str, Dict[Tuple[str, str, str, str], Dict[str, Any]]],
    tasks: List[Task],
) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    out: Dict[str, Dict[str, Dict[str, List[str]]]] = {}
    task_index = {_rerank_key(t): t for t in tasks}
    for variant in sorted(results_by_variant.keys()):
        variant_rows = results_by_variant.get(variant) or {}
        out[variant] = {}
        for run_id in sorted(set(t.run_id for t in tasks)):
            out[variant][run_id] = {}
            for lane in ["match", "authority"]:
                for pool in ["with_abstract", "without_abstract"]:
                    keys = [k for k in variant_rows if k[0] == run_id and k[1] == lane and k[2] == pool]
                    keys.sort(
                        key=lambda k: (
                            bool(variant_rows[k].get("insufficient_info")),
                            -int(variant_rows[k].get("score") or 0),
                            -float(task_index[k].base_lane_score),
                        )
                    )
                    out[variant][run_id][f"{lane}/{pool}"] = [k[3] for k in keys]
    return out


def _dcg(grades: List[int], k: int) -> float:
    total = 0.0
    for i, g in enumerate(grades[:k], start=1):
        total += (2 ** int(g) - 1) / math.log2(i + 1)
    return total


def _ndcg(ids: List[str], grades_by_id: Dict[str, int], k: int) -> Optional[float]:
    if not ids:
        return None
    gains = [int(grades_by_id.get(cid, 0)) for cid in ids[:k]]
    ideal = sorted(grades_by_id.values(), reverse=True)
    denom = _dcg(ideal, k)
    if denom <= 0:
        return None
    return _dcg(gains, k) / denom


def _precision(ids: List[str], grades_by_id: Dict[str, int], k: int, threshold: int = 2) -> float:
    top = ids[:k]
    if not top:
        return 0.0
    return sum(1 for cid in top if int(grades_by_id.get(cid, 0)) >= threshold) / float(len(top))


def _build_reference_tasks(
    rankings_by_variant: Dict[str, Dict[str, Dict[str, List[str]]]],
    task_index: Dict[Tuple[str, str, str, str], Task],
    top_k: int = 20,
) -> List[Task]:
    chosen: Dict[Tuple[str, str, str, str], Task] = {}
    for variant_payload in rankings_by_variant.values():
        for run_id, lp in variant_payload.items():
            for lane_pool, ids in lp.items():
                lane, pool = lane_pool.split("/", 1)
                for cid in ids[: int(top_k)]:
                    key = (run_id, lane, pool, cid)
                    if key in task_index:
                        chosen[key] = task_index[key]
    return list(chosen.values())


def _clone_rankings(rankings: Dict[str, Dict[str, Dict[str, List[str]]]]) -> Dict[str, Dict[str, Dict[str, List[str]]]]:
    return {
        variant: {
            run_id: {lane_pool: list(ids) for lane_pool, ids in payload.items()}
            for run_id, payload in variant_payload.items()
        }
        for variant, variant_payload in rankings.items()
    }


def _pairwise_prompt(task_a: Task, task_b: Task) -> Tuple[str, str, Dict[str, Any], str, int]:
    system_prompt = (
        "You are comparing two scientific sources for one chapter.\n"
        "Use ONLY the chapter contract, metadata, and evidence tags.\n"
        "Choose the source that is more useful for this exact chapter and lane.\n"
        "Return strict JSON only."
    )
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["winner", "confidence_0_3", "brief_rationale"],
        "properties": {
            "winner": {"type": "string", "enum": ["A", "B", "tie"]},
            "confidence_0_3": {"type": "integer", "minimum": 0, "maximum": 3},
            "brief_rationale": {"type": "string", "maxLength": 220},
        },
    }
    user_prompt = (
        f"CHAPTER_CONTRACT:\n{_compact_chapter_contract(task_a.chapter_contract, max_len=900)}\n\n"
        f"LANE:\n{task_a.lane}\nPOOL:\n{task_a.pool}\n\n"
        f"CANDIDATE_A_METADATA:\n{_candidate_metadata_block(task_a, include_authors=False, abstract_max_len=500)}\n\n"
        f"CANDIDATE_A_TAGS:\n{json.dumps(_compact_tags(task_a.tags), ensure_ascii=False)}\n\n"
        f"CANDIDATE_B_METADATA:\n{_candidate_metadata_block(task_b, include_authors=False, abstract_max_len=500)}\n\n"
        f"CANDIDATE_B_TAGS:\n{json.dumps(_compact_tags(task_b.tags), ensure_ascii=False)}\n\n"
        "Choose which candidate is more useful for this chapter and lane.\n"
    )
    return system_prompt, user_prompt, schema, "low", 800


def _pairwise_group_keys(
    runs: List[RunData],
    *,
    restrict_pool: str = "with_abstract",
) -> List[Tuple[str, str, str]]:
    out: List[Tuple[str, str, str]] = []
    for run in runs:
        for lane in ["match", "authority"]:
            out.append((run.run_id, lane, restrict_pool))
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-id", action="append", dest="run_ids")
    parser.add_argument("--budget-usd", type=float, default=3.0)
    parser.add_argument("--top-k", type=int, default=40)
    parser.add_argument("--reference-top-k", type=int, default=20)
    parser.add_argument("--pairwise-top-k", type=int, default=8)
    parser.add_argument("--stability-per-group", type=int, default=4)
    args = parser.parse_args()

    api_key = (os.getenv("OPENAI_API_KEY") or "").strip()
    if not api_key:
        raise SystemExit("OPENAI_API_KEY missing")

    run_ids = args.run_ids or DEFAULT_RUN_IDS
    client = OpenAI(api_key=api_key)

    runs = [_load_run(run_id) for run_id in run_ids]
    tasks = [task for run in runs for task in _build_tasks(run, top_k=args.top_k)]
    task_index = {_rerank_key(t): t for t in tasks}

    variants = {
        "baseline_current": lambda task, shuffle=False: _build_baseline_prompt(task, shuffle_tags=shuffle),
        "contract_low": lambda task, shuffle=False: _build_contract_prompt(task, shuffle_tags=shuffle, reasoning_effort="low", max_output_tokens=640),
        "rubric_low": lambda task, shuffle=False: _build_rubric_prompt(task, shuffle_tags=shuffle, reasoning_effort="low"),
        "rubric_object_gate": lambda task, shuffle=False: _build_rubric_object_gate_prompt(task, shuffle_tags=shuffle),
        "rubric_medium": lambda task, shuffle=False: _build_rubric_prompt(task, shuffle_tags=shuffle, reasoning_effort="medium"),
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    spent = 0.0
    results_by_variant: Dict[str, Dict[Tuple[str, str, str, str], Dict[str, Any]]] = {variant: {} for variant in variants}

    def _cache_file(
        kind: str,
        variant: str,
        key: Tuple[str, str, str, str],
        suffix: str = ".json",
        trial_label: str = "",
    ) -> Path:
        run_id, lane, pool, cid = key
        return CACHE_DIR / kind / variant / run_id / f"{_stable_hash(run_id, lane, pool, cid, variant, trial_label, length=32)}{suffix}"

    def _run_variant(
        variant: str,
        task: Task,
        *,
        shuffle: bool = False,
        force_refresh: bool = False,
        trial_label: str = "",
        allow_failure_fallback: bool = True,
    ) -> Dict[str, Any]:
        nonlocal spent
        key = _rerank_key(task)
        cache_kind = "pointwise_shuffled" if shuffle else "pointwise"
        cache_path = _cache_file(cache_kind, variant, key, trial_label=trial_label)
        if cache_path.exists() and not force_refresh:
            return _read_json(cache_path)["result"]

        system_prompt, user_prompt, schema, effort, max_out = variants[variant](task, shuffle)
        try:
            obj, meta = _call_json_schema(
                client,
                model=NANO_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=f"{variant}_result",
                schema=schema,
                reasoning_effort=effort,
                max_output_tokens=max_out,
            )
        except Exception as exc:
            if not allow_failure_fallback:
                raise RuntimeError(
                    f"Pointwise call failed variant={variant} run={task.run_id} lane={task.lane} pool={task.pool} cid={task.cid}: {exc}"
                ) from exc
            result = {
                "variant": variant,
                "score": 0,
                "insufficient_info": True,
                "covered_facets": [],
                "evidence_tag_ids": [],
                "brief_rationale": _truncate(f"call_failed: {exc}", 260),
                "off_topic": False,
                "call_failed": True,
            }
            _write_json(
                cache_path,
                {
                    "task": _sanitize(task.__dict__),
                    "result": result,
                    "openai": {"error": str(exc)},
                    "variant": variant,
                    "shuffle": shuffle,
                    "trial_label": trial_label,
                    "fallback": True,
                },
            )
            _append_jsonl(
                USAGE_LOG_PATH,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "kind": "pointwise",
                    "variant": variant,
                    "shuffle": shuffle,
                    "run_id": task.run_id,
                    "lane": task.lane,
                    "pool": task.pool,
                    "cid": task.cid,
                    "trial_label": trial_label,
                    "model": NANO_MODEL,
                    "usage": None,
                    "cost_usd": None,
                    "error": str(exc),
                    "fallback": True,
                },
            )
            return result
        result = _variant_result(task, variant, obj)
        result["call_failed"] = False
        _write_json(cache_path, {"task": _sanitize(task.__dict__), "result": result, "openai": meta, "variant": variant, "shuffle": shuffle})
        cost = float((meta.get("cost_estimate") or {}).get("total_cost_usd") or 0.0)
        spent += cost
        _append_jsonl(
            USAGE_LOG_PATH,
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "pointwise",
                "variant": variant,
                "shuffle": shuffle,
                "run_id": task.run_id,
                "lane": task.lane,
                "pool": task.pool,
                "cid": task.cid,
                "trial_label": trial_label,
                "model": NANO_MODEL,
                "usage": meta.get("usage"),
                "cost_usd": round(cost, 8),
            },
        )
        return result

    def _pairwise_cache_path(
        base_variant: str,
        run_id: str,
        lane: str,
        pool: str,
        cid_a: str,
        cid_b: str,
        *,
        swapped: bool,
    ) -> Path:
        payload = [run_id, lane, pool, cid_a, cid_b, "swapped" if swapped else "forward"]
        return CACHE_DIR / "pairwise" / base_variant / run_id / f"{_stable_hash(*payload, length=32)}.json"

    def _run_pairwise(base_variant: str, task_a: Task, task_b: Task, *, allow_failure_fallback: bool = True) -> Dict[str, Any]:
        nonlocal spent
        key_a = _rerank_key(task_a)
        key_b = _rerank_key(task_b)
        swap = int(_stable_hash(*key_a, *key_b, length=8), 16) % 2 == 1
        left = task_b if swap else task_a
        right = task_a if swap else task_b
        cache_path = _pairwise_cache_path(
            base_variant,
            task_a.run_id,
            task_a.lane,
            task_a.pool,
            task_a.cid,
            task_b.cid,
            swapped=swap,
        )
        if cache_path.exists():
            return _read_json(cache_path)["result"]
        if spent > float(args.budget_usd):
            raise RuntimeError(f"Budget exceeded during pairwise runs: {spent:.4f} > {args.budget_usd:.4f}")
        system_prompt, user_prompt, schema, effort, max_out = _pairwise_prompt(left, right)
        try:
            obj, meta = _call_json_schema(
                client,
                model=NANO_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name=f"{base_variant}_pairwise_result",
                schema=schema,
                reasoning_effort=effort,
                max_output_tokens=max_out,
            )
        except Exception as exc:
            if not allow_failure_fallback:
                raise RuntimeError(
                    f"Pairwise call failed base_variant={base_variant} run={task_a.run_id} lane={task_a.lane} pool={task_a.pool} cid_a={task_a.cid} cid_b={task_b.cid}: {exc}"
                ) from exc
            result = {
                "winner_cid": "tie",
                "confidence_0_3": 0,
                "brief_rationale": _truncate(f"call_failed: {exc}", 220),
                "swapped": swap,
                "call_failed": True,
            }
            _write_json(
                cache_path,
                {
                    "task_a": _sanitize(task_a.__dict__),
                    "task_b": _sanitize(task_b.__dict__),
                    "result": result,
                    "openai": {"error": str(exc)},
                    "base_variant": base_variant,
                    "fallback": True,
                },
            )
            _append_jsonl(
                USAGE_LOG_PATH,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "kind": "pairwise",
                    "variant": base_variant,
                    "run_id": task_a.run_id,
                    "lane": task_a.lane,
                    "pool": task_a.pool,
                    "cid_a": task_a.cid,
                    "cid_b": task_b.cid,
                    "swapped": swap,
                    "model": NANO_MODEL,
                    "usage": None,
                    "cost_usd": None,
                    "error": str(exc),
                    "fallback": True,
                },
            )
            return result
        winner = str(obj.get("winner") or "tie").strip().lower()
        confidence = int(max(0, min(3, int(obj.get("confidence_0_3") or 0))))
        if swap:
            if winner == "a":
                mapped = task_b.cid
            elif winner == "b":
                mapped = task_a.cid
            else:
                mapped = "tie"
        else:
            if winner == "a":
                mapped = task_a.cid
            elif winner == "b":
                mapped = task_b.cid
            else:
                mapped = "tie"
        result = {
            "winner_cid": mapped,
            "confidence_0_3": confidence,
            "brief_rationale": _truncate(obj.get("brief_rationale") or "", 220),
            "swapped": swap,
            "call_failed": False,
        }
        _write_json(
            cache_path,
            {
                "task_a": _sanitize(task_a.__dict__),
                "task_b": _sanitize(task_b.__dict__),
                "result": result,
                "openai": meta,
                "base_variant": base_variant,
            },
        )
        cost = float((meta.get("cost_estimate") or {}).get("total_cost_usd") or 0.0)
        spent += cost
        _append_jsonl(
            USAGE_LOG_PATH,
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "pairwise",
                "variant": base_variant,
                "run_id": task_a.run_id,
                "lane": task_a.lane,
                "pool": task_a.pool,
                "cid_a": task_a.cid,
                "cid_b": task_b.cid,
                "swapped": swap,
                "model": NANO_MODEL,
                "usage": meta.get("usage"),
                "cost_usd": round(cost, 8),
            },
        )
        return result

    for variant in variants:
        for task in tasks:
            if spent > float(args.budget_usd):
                raise RuntimeError(f"Budget exceeded during pointwise runs: {spent:.4f} > {args.budget_usd:.4f}")
            results_by_variant[variant][_rerank_key(task)] = _run_variant(variant, task, shuffle=False)

    rankings_by_variant = _sort_ranked(results_by_variant, tasks)

    pairwise_rows: List[Dict[str, Any]] = []
    if int(args.pairwise_top_k) >= 2:
        refined = _clone_rankings(rankings_by_variant)
        for base_variant in ["contract_low", "rubric_low", "rubric_object_gate", "rubric_medium"]:
            variant_name = f"{base_variant}_pairwise_top{int(args.pairwise_top_k)}"
            refined[variant_name] = _clone_rankings({base_variant: rankings_by_variant[base_variant]})[base_variant]
            for run_id, lane, pool in _pairwise_group_keys(runs, restrict_pool="with_abstract"):
                lane_pool = f"{lane}/{pool}"
                ids = list(rankings_by_variant[base_variant][run_id][lane_pool])[: int(args.pairwise_top_k)]
                if len(ids) < 2:
                    continue
                wins = {cid: 0.0 for cid in ids}
                comps = 0
                failures = 0
                for i in range(len(ids)):
                    for j in range(i + 1, len(ids)):
                        task_a = task_index[(run_id, lane, pool, ids[i])]
                        task_b = task_index[(run_id, lane, pool, ids[j])]
                        res = _run_pairwise(base_variant, task_a, task_b)
                        comps += 1
                        if bool(res.get("call_failed")):
                            failures += 1
                        winner_cid = str(res.get("winner_cid") or "tie")
                        conf_bonus = 0.1 * int(res.get("confidence_0_3") or 0)
                        if winner_cid == task_a.cid:
                            wins[task_a.cid] += 1.0 + conf_bonus
                        elif winner_cid == task_b.cid:
                            wins[task_b.cid] += 1.0 + conf_bonus
                        else:
                            wins[task_a.cid] += 0.5
                            wins[task_b.cid] += 0.5
                ordered = sorted(
                    ids,
                    key=lambda cid: (
                        -float(wins.get(cid, 0.0)),
                        ids.index(cid),
                    ),
                )
                refined[variant_name][run_id][lane_pool] = ordered + list(rankings_by_variant[base_variant][run_id][lane_pool][len(ids):])
                pairwise_rows.append(
                    {
                        "variant": variant_name,
                        "base_variant": base_variant,
                        "run_id": run_id,
                        "lane": lane,
                        "pool": pool,
                        "pairwise_top_k": int(args.pairwise_top_k),
                        "comparisons": comps,
                        "call_failed": failures,
                        "wins": {cid: round(float(wins[cid]), 3) for cid in ordered},
                    }
                )
        rankings_by_variant = refined

    # Stability / shuffle sensitivity on a stratified sample.
    sampled_tasks: List[Task] = []
    for run in runs:
        for lane in ["match", "authority"]:
            for pool in ["with_abstract", "without_abstract"]:
                subset = [t for t in tasks if t.run_id == run.run_id and t.lane == lane and t.pool == pool][: int(args.stability_per_group)]
                sampled_tasks.extend(subset)

    stability_rows: List[Dict[str, Any]] = []
    for variant in ["contract_low", "rubric_low", "rubric_object_gate", "rubric_medium"]:
        for task in sampled_tasks:
            if spent > float(args.budget_usd):
                raise RuntimeError(f"Budget exceeded during stability runs: {spent:.4f} > {args.budget_usd:.4f}")
            repeat_a = _run_variant(variant, task, shuffle=False, force_refresh=True, trial_label="repeat_a")
            repeat_b = _run_variant(variant, task, shuffle=False, force_refresh=True, trial_label="repeat_b")
            shuffled = _run_variant(variant, task, shuffle=True, force_refresh=True, trial_label="shuffle")
            stability_rows.append(
                {
                    "variant": variant,
                    "run_id": task.run_id,
                    "lane": task.lane,
                    "pool": task.pool,
                    "cid": task.cid,
                    "repeat_diff": abs(int(repeat_a["score"]) - int(repeat_b["score"])),
                    "shuffle_diff": abs(int(repeat_a["score"]) - int(shuffled["score"])),
                    "repeat_insuff_flip": bool(repeat_a["insufficient_info"]) != bool(repeat_b["insufficient_info"]),
                    "shuffle_insuff_flip": bool(repeat_a["insufficient_info"]) != bool(shuffled["insufficient_info"]),
                    "repeat_a_failed": bool(repeat_a.get("call_failed")),
                    "repeat_b_failed": bool(repeat_b.get("call_failed")),
                    "shuffle_failed": bool(shuffled.get("call_failed")),
                }
            )

    # Reference labels on pooled top candidates.
    ref_tasks = _build_reference_tasks(rankings_by_variant, task_index, top_k=args.reference_top_k)
    reference_rows: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
    for task in ref_tasks:
        key = _rerank_key(task)
        cache_path = _cache_file("reference", "gpt5mini", key)
        if cache_path.exists():
            reference_rows[key] = _read_json(cache_path)["result"]
            continue
        if spent > float(args.budget_usd):
            raise RuntimeError(f"Budget exceeded during reference runs: {spent:.4f} > {args.budget_usd:.4f}")
        system_prompt, user_prompt, schema, effort, max_out = _reference_prompt(task)
        try:
            obj, meta = _call_json_schema(
                client,
                model=REFERENCE_MODEL,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                schema_name="reference_grade",
                schema=schema,
                reasoning_effort=effort,
                max_output_tokens=max_out,
            )
            result = {
                "grade_0_3": int(obj.get("grade_0_3") or 0),
                "direct_use": bool(obj.get("direct_use")),
                "off_topic": bool(obj.get("off_topic")),
                "brief_rationale": _truncate(obj.get("brief_rationale") or "", 280),
                "call_failed": False,
            }
        except Exception as exc:
            result = {
                "grade_0_3": None,
                "direct_use": None,
                "off_topic": None,
                "brief_rationale": _truncate(f"call_failed: {exc}", 280),
                "call_failed": True,
            }
            meta = {"error": str(exc)}
        reference_rows[key] = result
        _write_json(cache_path, {"task": _sanitize(task.__dict__), "result": result, "openai": meta})
        cost = float((meta.get("cost_estimate") or {}).get("total_cost_usd") or 0.0) if isinstance(meta, dict) else 0.0
        spent += cost
        _append_jsonl(
            USAGE_LOG_PATH,
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "kind": "reference",
                "run_id": task.run_id,
                "lane": task.lane,
                "pool": task.pool,
                "cid": task.cid,
                "model": REFERENCE_MODEL,
                "usage": meta.get("usage") if isinstance(meta, dict) else None,
                "cost_usd": round(cost, 8),
                "error": meta.get("error") if isinstance(meta, dict) else None,
                "fallback": bool(result.get("call_failed")),
            },
        )

    grades_by_group: Dict[Tuple[str, str, str], Dict[str, int]] = {}
    for key, ref in reference_rows.items():
        if bool(ref.get("call_failed")) or ref.get("grade_0_3") is None:
            continue
        run_id, lane, pool, cid = key
        grades_by_group.setdefault((run_id, lane, pool), {})[cid] = int(ref.get("grade_0_3") or 0)

    metrics_rows: List[Dict[str, Any]] = []
    for variant, variant_payload in rankings_by_variant.items():
        for run_id, lp in variant_payload.items():
            for lane_pool, ids in lp.items():
                lane, pool = lane_pool.split("/", 1)
                grades = grades_by_group.get((run_id, lane, pool), {})
                if not grades:
                    continue
                metrics_rows.append(
                    {
                        "variant": variant,
                        "run_id": run_id,
                        "lane": lane,
                        "pool": pool,
                        "ndcg_10": _ndcg(ids, grades, 10),
                        "ndcg_20": _ndcg(ids, grades, 20),
                        "p_at_5": _precision(ids, grades, 5),
                        "p_at_10": _precision(ids, grades, 10),
                        "grade_mean_top20": round(sum(grades.get(cid, 0) for cid in ids[:20]) / max(1, len(ids[:20])), 4),
                        "off_topic_top20": round(sum(1 for cid in ids[:20] if grades.get(cid, 0) == 0) / max(1, len(ids[:20])), 4),
                    }
                )

    pointwise_failure_rows: List[Dict[str, Any]] = []
    for variant, rows_by_key in results_by_variant.items():
        rows = list(rows_by_key.values())
        pointwise_failure_rows.append(
            {
                "variant": variant,
                "call_failed_rate": round(sum(1 for r in rows if bool(r.get("call_failed"))) / max(1, len(rows)), 4),
                "mean_score": round(statistics.mean([float(r.get("score") or 0.0) for r in rows]), 4) if rows else 0.0,
            }
        )

    result = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "run_ids": run_ids,
        "tasks_total": len(tasks),
        "reference_items": len(reference_rows),
        "spent_usd_est": round(spent, 6),
        "metrics_rows": metrics_rows,
        "pointwise_failure_rows": pointwise_failure_rows,
        "stability_rows": stability_rows,
        "pairwise_rows": pairwise_rows,
        "rankings_by_variant": rankings_by_variant,
    }

    slug = _now_slug()
    json_path = OUTPUT_DIR / f"phase_i_rerank_probe_{slug}.json"
    _write_json(json_path, result)

    lines: List[str] = []
    lines.append("# Phase I Rerank Probe Summary")
    lines.append("")
    lines.append(f"- generated_at: `{result['generated_at']}`")
    lines.append(f"- run_ids: `{', '.join(run_ids)}`")
    lines.append(f"- tasks_total: `{len(tasks)}`")
    lines.append(f"- reference_items: `{len(reference_rows)}`")
    lines.append(f"- estimated_spend_usd: `${spent:.4f}`")
    lines.append("")
    lines.append("## Aggregate Metrics")
    lines.append("")
    for variant in sorted(set(r["variant"] for r in metrics_rows)):
        rows = [r for r in metrics_rows if r["variant"] == variant]
        if not rows:
            continue
        lines.append(f"### {variant}")
        lines.append("")
        lines.append(
            "- "
            + ", ".join(
                [
                    f"mean_ndcg20={statistics.mean([float(r['ndcg_20'] or 0.0) for r in rows]):.3f}",
                    f"mean_p10={statistics.mean([float(r['p_at_10'] or 0.0) for r in rows]):.3f}",
                    f"mean_off_topic_top20={statistics.mean([float(r['off_topic_top20'] or 0.0) for r in rows]):.3f}",
                ]
            )
        )
    lines.append("")
    lines.append("## Operational Failure Rate")
    lines.append("")
    for row in pointwise_failure_rows:
        lines.append(f"- {row['variant']}: call_failed_rate={row['call_failed_rate']:.3f}, mean_score={row['mean_score']:.2f}")
    lines.append("")
    lines.append("## Stability")
    lines.append("")
    for variant in sorted(set(r["variant"] for r in stability_rows)):
        rows = [r for r in stability_rows if r["variant"] == variant]
        lines.append(
            f"- {variant}: repeat_diff_mean={statistics.mean([r['repeat_diff'] for r in rows]):.2f}, "
            f"shuffle_diff_mean={statistics.mean([r['shuffle_diff'] for r in rows]):.2f}, "
            f"repeat_insuff_flip_rate={sum(1 for r in rows if r['repeat_insuff_flip'])/max(1,len(rows)):.3f}, "
            f"shuffle_insuff_flip_rate={sum(1 for r in rows if r['shuffle_insuff_flip'])/max(1,len(rows)):.3f}, "
            f"call_failed_rate={sum(1 for r in rows if r['repeat_a_failed'] or r['repeat_b_failed'] or r['shuffle_failed'])/max(1,len(rows)):.3f}"
        )
    lines.append("")
    if pairwise_rows:
        lines.append("## Pairwise Refinement")
        lines.append("")
        for row in pairwise_rows:
            lines.append(
                f"- {row['variant']} | {row['run_id']} | {row['lane']}/{row['pool']}: comparisons={row['comparisons']}, call_failed={row['call_failed']}, leaders={list(row['wins'].items())[:3]}"
            )
        lines.append("")
    lines.append("## Top-10 Preview By Variant")
    lines.append("")
    for variant in sorted(rankings_by_variant.keys()):
        for run_id in run_ids:
            for lane_pool in ["match/with_abstract", "authority/with_abstract"]:
                ids = rankings_by_variant[variant][run_id][lane_pool][:10]
                lines.append(f"### {variant} | {run_id} | {lane_pool}")
                lines.append("")
                lane, pool = lane_pool.split("/", 1)
                for rank, cid in enumerate(ids, start=1):
                    task = task_index[(run_id, lane, pool, cid)]
                    title = _clean_space(task.candidate.get("title") or task.score_row.get("title"))
                    lines.append(f"{rank}. `{cid}` | {_truncate(title, 140)}")
                lines.append("")

    md_path = OUTPUT_DIR / f"phase_i_rerank_probe_{slug}.summary.md"
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"json": str(json_path), "summary": str(md_path), "spent_usd_est": round(spent, 6)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
