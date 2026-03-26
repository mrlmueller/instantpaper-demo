#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import statistics
import time
from argparse import Namespace
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache

from phase_e_lab import *  # noqa: F401,F403


try:
    import torch
except Exception as e:
    torch = None
    PHASE_F_TORCH_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_F_TORCH_IMPORT_ERROR = None

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception as e:
    AutoModelForSequenceClassification = None
    AutoTokenizer = None
    PHASE_F_TRANSFORMERS_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_F_TRANSFORMERS_IMPORT_ERROR = None

PhaseFOpenAI = globals().get("OpenAI")
if PhaseFOpenAI is None:
    try:
        from openai import OpenAI as PhaseFOpenAI
    except Exception:
        PhaseFOpenAI = None

PHASE_F_API_KEY = (globals().get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
PHASE_F_DEFAULT_RERANK_MODEL = "BAAI/bge-reranker-v2-m3"
PHASE_F_DEFAULT_JUDGE_MODEL = (os.getenv("OPENAI_PDF_SCAN_JUDGE_MODEL") or "gpt-5-mini").strip() or "gpt-5-mini"
PHASE_F_ALLOWED_EXCLUSION_VIOLATIONS = [
    "frontmatter_or_admin",
    "references_or_notes",
    "methods_only",
    "too_generic_without_specific_evidence",
    "weak_evidence",
    "off_topic",
]


@dataclass
class PhaseFOptions:
    force_rebuild: bool = False
    rerank_top_k: int = 60
    inject_doc_top_candidates: bool = True
    cross_encoder_model: str = PHASE_F_DEFAULT_RERANK_MODEL
    cross_encoder_batch_size: int = 8
    cross_encoder_max_length: int = 1536
    cross_encoder_subpoint_limit: int = 2
    section_excerpt_max_chars: int = 2200
    supporting_passage_count: int = 3
    passage_excerpt_max_chars: int = 520
    use_openai_judge: bool = True
    judge_model: str = PHASE_F_DEFAULT_JUDGE_MODEL
    judge_reasoning_effort: str = "low"
    judge_candidate_limit: int = 12
    judge_max_per_doc: int = 2
    judge_max_output_tokens: int = 550
    top_candidate_preview_count: int = 20
    cross_encoder_weight: float = 0.72
    fused_prior_weight: float = 0.16
    evidence_weight: float = 0.12
    llm_judge_blend: float = 0.20
    generic_title_penalty: float = 0.035
    weak_evidence_penalty: float = 0.05
    single_passage_penalty: float = 0.02

    def normalized(self) -> "PhaseFOptions":
        return PhaseFOptions(
            force_rebuild=bool(self.force_rebuild),
            rerank_top_k=max(10, int(self.rerank_top_k)),
            inject_doc_top_candidates=bool(self.inject_doc_top_candidates),
            cross_encoder_model=str(self.cross_encoder_model or PHASE_F_DEFAULT_RERANK_MODEL).strip() or PHASE_F_DEFAULT_RERANK_MODEL,
            cross_encoder_batch_size=max(1, int(self.cross_encoder_batch_size)),
            cross_encoder_max_length=max(128, int(self.cross_encoder_max_length)),
            cross_encoder_subpoint_limit=max(0, int(self.cross_encoder_subpoint_limit)),
            section_excerpt_max_chars=max(400, int(self.section_excerpt_max_chars)),
            supporting_passage_count=max(1, int(self.supporting_passage_count)),
            passage_excerpt_max_chars=max(160, int(self.passage_excerpt_max_chars)),
            use_openai_judge=bool(self.use_openai_judge),
            judge_model=str(self.judge_model or PHASE_F_DEFAULT_JUDGE_MODEL).strip() or PHASE_F_DEFAULT_JUDGE_MODEL,
            judge_reasoning_effort=str(self.judge_reasoning_effort or "low").strip() or "low",
            judge_candidate_limit=max(0, int(self.judge_candidate_limit)),
            judge_max_per_doc=max(1, int(self.judge_max_per_doc)),
            judge_max_output_tokens=max(200, int(self.judge_max_output_tokens)),
            top_candidate_preview_count=max(5, int(self.top_candidate_preview_count)),
            cross_encoder_weight=max(0.0, float(self.cross_encoder_weight)),
            fused_prior_weight=max(0.0, float(self.fused_prior_weight)),
            evidence_weight=max(0.0, float(self.evidence_weight)),
            llm_judge_blend=max(0.0, min(1.0, float(self.llm_judge_blend))),
            generic_title_penalty=max(0.0, float(self.generic_title_penalty)),
            weak_evidence_penalty=max(0.0, float(self.weak_evidence_penalty)),
            single_passage_penalty=max(0.0, float(self.single_passage_penalty)),
        )


if BaseModel is not None:

    class LLMJudgeVerdictModel(BaseModel):
        usefulness_raw: int = Field(ge=0, le=5)
        topic_match_raw: int = Field(ge=0, le=5)
        coverage_raw: int = Field(ge=0, le=5)
        exclusion_violations: List[str] = Field(default_factory=list, max_length=6)
        top_evidence_passage_ids: List[str] = Field(default_factory=list, max_length=3)
        notes: str = Field(default="", max_length=400)

else:
    LLMJudgeVerdictModel = None


def phase_f_capabilities() -> Dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "torch_available": bool(torch is not None),
        "transformers_available": bool(AutoModelForSequenceClassification is not None and AutoTokenizer is not None),
        "cuda_available": bool(torch is not None and torch.cuda.is_available()),
        "openai_available": bool(PhaseFOpenAI is not None),
        "openai_api_key_present": bool(PHASE_F_API_KEY),
        "optional_import_errors": {
            "torch": PHASE_F_TORCH_IMPORT_ERROR,
            "transformers": PHASE_F_TRANSFORMERS_IMPORT_ERROR,
        },
    }


def clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except Exception:
        return 0.0


def logistic(value: Any) -> float:
    try:
        return 1.0 / (1.0 + math.exp(-float(value)))
    except Exception:
        return 0.0


def safe_mean(values: Iterable[Any]) -> float:
    seq = [float(v) for v in values if v is not None]
    return float(sum(seq) / len(seq)) if seq else 0.0


def build_global_query_text(query_plan: Dict[str, Any]) -> str:
    must_terms = list(query_plan.get("must_terms") or [])[:8]
    supported_should = list(query_plan.get("retrieval_should_terms") or query_plan.get("corpus_supported_should_terms") or [])[:8]
    bridge_terms = list(query_plan.get("bridge_terms") or [])[:8]
    must_line = "must: " + " | ".join(clean_text(x) for x in must_terms if clean_text(x))
    related_line = "related: " + " | ".join(clean_text(x) for x in supported_should if clean_text(x))
    bridge_line = "bridge: " + " | ".join(clean_text(x) for x in bridge_terms if clean_text(x))
    return build_compact_query_text(
        [
            clean_text(query_plan.get("chapter_title")),
            truncate_words(clean_text(query_plan.get("chapter_summary")), max_words=40),
            must_line if must_terms else "",
            related_line if supported_should else "",
            bridge_line if bridge_terms else "",
        ],
        separator=" || ",
        max_words=112,
        max_chars=680,
    )


def build_subpoint_query_text(subpoint: Dict[str, Any], bridge_terms: Optional[List[str]] = None) -> str:
    must_terms = [clean_text(x) for x in list(subpoint.get("must_terms") or [])[:6] if clean_text(x)]
    should_terms = [clean_text(x) for x in list(subpoint.get("should_terms") or [])[:6] if clean_text(x)]
    bridge_terms = [clean_text(x) for x in list(bridge_terms or [])[:4] if clean_text(x)]
    return build_compact_query_text(
        [
            clean_text(subpoint.get("label")),
            truncate_words(clean_text(subpoint.get("summary")), max_words=26),
            ("must: " + " | ".join(must_terms)) if must_terms else "",
            ("related: " + " | ".join(should_terms)) if should_terms else "",
            ("bridge: " + " | ".join(bridge_terms)) if bridge_terms else "",
        ],
        separator=" || ",
        max_words=88,
        max_chars=520,
    )


def row_sigmoid(logits_tensor: Any) -> List[float]:
    if torch is None:
        return []
    if logits_tensor.ndim == 1:
        return [logistic(float(x)) for x in logits_tensor.detach().cpu().tolist()]
    if logits_tensor.ndim == 2 and logits_tensor.shape[-1] == 1:
        return [logistic(float(x[0])) for x in logits_tensor.detach().cpu().tolist()]
    if logits_tensor.ndim == 2 and logits_tensor.shape[-1] >= 2:
        probs = torch.softmax(logits_tensor, dim=-1)
        return [float(x[-1]) for x in probs.detach().cpu().tolist()]
    return [logistic(float(x)) for x in logits_tensor.reshape(-1).detach().cpu().tolist()]


@lru_cache(maxsize=4)
def load_cross_encoder_bundle(model_name: str):
    if AutoTokenizer is None or AutoModelForSequenceClassification is None or torch is None:
        missing = []
        if AutoTokenizer is None or AutoModelForSequenceClassification is None:
            missing.append("transformers")
        if torch is None:
            missing.append("torch")
        raise RuntimeError(f"Cross-encoder reranker dependencies missing: {', '.join(missing)}")
    print(f"  [cross-encoder] Loading model {model_name}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    model.eval()
    print(f"  [cross-encoder] Model loaded on {device}")
    max_pos = getattr(getattr(model, "config", None), "max_position_embeddings", None)
    tokenizer_limit = getattr(tokenizer, "model_max_length", None)
    return {
        "tokenizer": tokenizer,
        "model": model,
        "device": device,
        "max_position_embeddings": max_pos,
        "tokenizer_model_max_length": tokenizer_limit,
        "architecture": type(model).__name__,
        "num_labels": int(getattr(getattr(model, "config", None), "num_labels", 1) or 1),
    }


def effective_max_length(bundle: Dict[str, Any], requested: int) -> int:
    candidates = [int(requested)]
    for raw in [bundle.get("max_position_embeddings"), bundle.get("tokenizer_model_max_length")]:
        if isinstance(raw, int) and 32 <= raw < 100000:
            candidates.append(int(raw))
    return max(32, min(candidates))


def score_cross_encoder_pairs(pairs: List[Dict[str, str]], options: PhaseFOptions) -> Dict[str, Any]:
    bundle = load_cross_encoder_bundle(options.cross_encoder_model)
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    device = bundle["device"]
    batch_size = max(1, int(options.cross_encoder_batch_size))
    max_length = effective_max_length(bundle, int(options.cross_encoder_max_length))
    rows = []
    total_batches = (len(pairs) + batch_size - 1) // batch_size
    print(f"  [cross-encoder] {len(pairs)} pairs, batch_size={batch_size}, device={device}, {total_batches} batches")
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(pairs), batch_size):
            batch_idx = start // batch_size + 1
            if batch_idx == 1 or batch_idx % 10 == 0 or batch_idx == total_batches:
                elapsed_so_far = time.perf_counter() - started
                print(f"  [cross-encoder] batch {batch_idx}/{total_batches} ({elapsed_so_far:.1f}s)")
            batch = pairs[start : start + batch_size]
            enc = tokenizer(
                [str(item.get("query") or "") for item in batch],
                [str(item.get("candidate_text") or "") for item in batch],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = model(**enc).logits
            probs = row_sigmoid(logits)
            raw_logits = logits.detach().cpu().reshape(len(batch), -1).tolist()
            for idx, item in enumerate(batch):
                rows.append(
                    {
                        **item,
                        "raw_logit": float(raw_logits[idx][-1] if raw_logits[idx] else 0.0),
                        "score_prob": round(float(probs[idx]), 8),
                    }
                )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "rows": rows,
        "runtime": {
            "pair_count": len(pairs),
            "elapsed_ms": elapsed_ms,
            "batch_size": batch_size,
            "max_length": max_length,
            "device": device,
            "architecture": bundle.get("architecture"),
            "num_labels": bundle.get("num_labels"),
            "max_position_embeddings": bundle.get("max_position_embeddings"),
        },
    }


def build_candidate_text(pack: Dict[str, Any], options: PhaseFOptions) -> str:
    evidence_lines = []
    for item in list(pack.get("evidence_rows") or [])[: int(options.supporting_passage_count)]:
        evidence_lines.append(
            f"[{item.get('passage_id')}] pages {item.get('page_start')}-{item.get('page_end')} | lanes={', '.join(item.get('lanes') or [])}\n{truncate_text(clean_text(item.get('text') or ''), max_len=options.passage_excerpt_max_chars)}"
        )
    return clean_text(
        "\n\n".join(
            part
            for part in [
                f"Document: {clean_text(pack.get('doc_title') or pack.get('doc_id') or 'Untitled document')}",
                f"Section path: {clean_text(pack.get('section_path_text') or pack.get('title') or 'Untitled section')}",
                f"Section type: {clean_text(pack.get('section_type') or 'body_other')} | pages {pack.get('page_start')}-{pack.get('page_end')} | fused rank {pack.get('fused_rank')}",
                ("Key evidence passages:\n" + "\n\n".join(evidence_lines)) if evidence_lines else "",
                "Section excerpt:\n" + truncate_text(clean_text(pack.get("section_excerpt") or ""), max_len=options.section_excerpt_max_chars),
            ]
            if clean_text(part)
        )
    )


def choose_candidate_subpoints(candidate_row: Dict[str, Any], active_subpoint_ids: List[str], options: PhaseFOptions) -> List[str]:
    subpoint_support = dict(candidate_row.get("subpoint_support") or {})
    ranked = []
    for subpoint_id, payload in subpoint_support.items():
        ranked.append(
            (
                1 if payload.get("trusted") else 0,
                float(payload.get("raw_total_score") or 0.0),
                float(payload.get("normalized_score") or 0.0),
                str(subpoint_id),
            )
        )
    ranked.sort(reverse=True)
    picked = [subpoint_id for _, _, _, subpoint_id in ranked if subpoint_id in set(active_subpoint_ids)]
    if not picked:
        picked = [subpoint_id for _, _, _, subpoint_id in ranked]
    if not picked:
        picked = list(active_subpoint_ids or [])
    return picked[: int(options.cross_encoder_subpoint_limit)]


def candidate_evidence_density(candidate_row: Dict[str, Any]) -> float:
    support_count = min(int(candidate_row.get("supporting_passage_count") or 0), 4) / 4.0
    lane_count = min(int(candidate_row.get("lane_count") or 0), 5) / 5.0
    trusted_subpoints = min(int(candidate_row.get("trusted_subpoint_count") or 0), 3) / 3.0
    return round((0.45 * support_count) + (0.30 * lane_count) + (0.25 * trusted_subpoints), 8)


def select_rerank_candidates(fused_rows: List[Dict[str, Any]], options: PhaseFOptions) -> List[Dict[str, Any]]:
    top_rows = list(fused_rows[: int(options.rerank_top_k)])
    if not bool(options.inject_doc_top_candidates):
        return top_rows
    seen = {str(row.get("section_id") or "") for row in top_rows if str(row.get("section_id") or "")}
    injected = []
    for row in fused_rows:
        sid = str(row.get("section_id") or "")
        if not sid or sid in seen:
            continue
        doc_id = str(row.get("doc_id") or "")
        if any(str(existing.get("doc_id") or "") == doc_id for existing in top_rows + injected):
            continue
        injected.append(row)
        seen.add(sid)
    return top_rows + injected


def build_candidate_packs(
    candidates: List[Dict[str, Any]],
    documents: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    passages: List[Dict[str, Any]],
    active_subpoint_ids: List[str],
    options: PhaseFOptions,
) -> List[Dict[str, Any]]:
    doc_lookup = {str(row.get("doc_id") or ""): row for row in documents if str(row.get("doc_id") or "")}
    section_lookup = {str(row.get("section_id") or ""): row for row in sections if str(row.get("section_id") or "")}
    passage_lookup = {str(row.get("passage_id") or ""): row for row in passages if str(row.get("passage_id") or "")}
    section_passages_by_section = defaultdict(list)
    for passage in passages:
        sid = str(passage.get("section_id") or "")
        if sid:
            section_passages_by_section[sid].append(passage)
    for sid in list(section_passages_by_section.keys()):
        section_passages_by_section[sid].sort(key=lambda row: (int(row.get("page_start") or 0), int(row.get("passage_index") or 0)))
    packs = []
    for row in candidates:
        sid = str(row.get("section_id") or "")
        section = section_lookup.get(sid)
        if not section:
            continue
        doc = doc_lookup.get(str(row.get("doc_id") or ""), {})
        evidence_rows = []
        for item in list(row.get("supporting_passages") or [])[: int(options.supporting_passage_count)]:
            pid = str(item.get("passage_id") or "")
            passage = passage_lookup.get(pid)
            if not passage:
                continue
            evidence_rows.append(
                {
                    "passage_id": pid,
                    "page_start": (passage.get("page_span") or {}).get("page_start"),
                    "page_end": (passage.get("page_span") or {}).get("page_end"),
                    "lanes": list(item.get("lanes") or []),
                    "best_lane_score": item.get("best_lane_score"),
                    "text": truncate_text(clean_text(passage.get("contextualized_text") or passage.get("text") or ""), max_len=options.passage_excerpt_max_chars),
                }
            )
        if not evidence_rows:
            fallback_passages = list(section_passages_by_section.get(sid) or [])[: max(1, int(options.supporting_passage_count))]
            for passage in fallback_passages:
                evidence_rows.append(
                    {
                        "passage_id": str(passage.get("passage_id") or ""),
                        "page_start": (passage.get("page_span") or {}).get("page_start") or passage.get("page_start"),
                        "page_end": (passage.get("page_span") or {}).get("page_end") or passage.get("page_end"),
                        "lanes": ["fallback_section_passage"],
                        "best_lane_score": None,
                        "text": truncate_text(clean_text(passage.get("contextualized_text") or passage.get("text") or ""), max_len=options.passage_excerpt_max_chars),
                    }
                )
        chosen_subpoints = choose_candidate_subpoints(row, active_subpoint_ids, options)
        title_path = [clean_text(x) for x in list(section.get("title_path") or []) if clean_text(x)]
        supporting_passage_ids = [str(item.get("passage_id") or "") for item in evidence_rows if str(item.get("passage_id") or "")]
        pack = {
            "candidate_id": sid,
            "doc_id": str(row.get("doc_id") or ""),
            "doc_title": clean_text(doc.get("title") or ""),
            "section_id": sid,
            "title": clean_text(row.get("title") or section.get("title") or "Untitled Section"),
            "section_path": title_path,
            "section_path_text": " / ".join(title_path) or clean_text(row.get("title") or section.get("title") or "Untitled Section"),
            "section_type": str(row.get("section_type") or section.get("section_type") or "body_other"),
            "page_start": row.get("page_start") or section.get("page_start"),
            "page_end": row.get("page_end") or section.get("page_end"),
            "fused_rank": row.get("fused_rank"),
            "fused_score": row.get("fused_score"),
            "selection_score": row.get("selection_score"),
            "quality_flags": list(section.get("quality_flags") or row.get("quality_flags") or []),
            "generic_title": bool(row.get("generic_title")),
            "trusted_subpoint_ids": list(row.get("trusted_subpoint_ids") or []),
            "chosen_subpoint_ids": chosen_subpoints,
            "supporting_passage_ids": supporting_passage_ids,
            "supporting_passage_count": max(int(row.get("supporting_passage_count") or 0), len(supporting_passage_ids)),
            "lane_count": int(row.get("lane_count") or 0),
            "anchor_support_total": float(row.get("anchor_support_total") or 0.0),
            "section_excerpt": truncate_text(clean_text(section.get("contextualized_text") or section.get("text") or ""), max_len=options.section_excerpt_max_chars),
            "evidence_rows": evidence_rows,
            "source_candidate": row,
        }
        pack["candidate_text"] = build_candidate_text(pack, options)
        packs.append(pack)
    return packs


def build_phase_f_cache_result(run_ctx: Any) -> Dict[str, Any]:
    rerank_dir = Path(run_ctx.artifacts.rerank_dir)
    config_path = rerank_dir / "phase_f_config.json"
    runtime_path = rerank_dir / "phase_f_runtime.json"
    summary_path = rerank_dir / "phase_f_summary.json"
    assessment_path = rerank_dir / "phase_f_assessment.json"
    candidate_packs_path = rerank_dir / "phase_f_candidate_packs.jsonl"
    cross_encoder_path = rerank_dir / "cross_encoder.jsonl"
    llm_judge_path = rerank_dir / "llm_judge.jsonl"
    rerank_results_path = rerank_dir / "rerank_results.jsonl"
    if not all(path.exists() for path in [config_path, runtime_path, summary_path, assessment_path, candidate_packs_path, cross_encoder_path, llm_judge_path, rerank_results_path]):
        raise FileNotFoundError("Phase F cache is incomplete.")
    summary = read_json(summary_path)
    assessment_json = read_json(assessment_path)
    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "candidate_packs_path": candidate_packs_path,
        "cross_encoder_path": cross_encoder_path,
        "llm_judge_path": llm_judge_path,
        "rerank_results_path": rerank_results_path,
        "candidate_pack_rows": read_jsonl_rows(candidate_packs_path),
        "cross_encoder_rows": read_jsonl_rows(cross_encoder_path),
        "llm_judge_rows": read_jsonl_rows(llm_judge_path),
        "rerank_result_rows": read_jsonl_rows(rerank_results_path),
        "summary": summary,
        "assessment": assessment_json.get("assessment") or {},
        "qc_rows": assessment_json.get("qc_rows") or [],
        "metrics_update": summary.get("metrics_update") or {},
        "cross_encoder_runtime": summary.get("cross_encoder_runtime") or {},
        "judge_runtime": summary.get("judge_runtime") or {},
        "cache_hit": True,
    }


def build_judge_messages(
    *,
    chapter_title: str,
    chapter_summary: str,
    must_terms: List[str],
    active_subpoints: List[Dict[str, Any]],
    candidate_pack: Dict[str, Any],
) -> Dict[str, Any]:
    subpoint_lines = []
    for subpoint in active_subpoints[:4]:
        subpoint_lines.append(
            f"- {clean_text(subpoint.get('subpoint_id'))}: {clean_text(subpoint.get('label'))} | {truncate_words(clean_text(subpoint.get('summary')), max_words=18)}"
        )
    evidence_lines = []
    for item in list(candidate_pack.get("evidence_rows") or [])[:3]:
        evidence_lines.append(
            f"- [{item.get('passage_id')}] pages {item.get('page_start')}-{item.get('page_end')}: {truncate_text(clean_text(item.get('text') or ''), max_len=420)}"
        )
    system_prompt = (
        "You are judging whether a retrieved PDF section is useful for writing a target chapter. "
        "Be generous to strongly intertwined material, not only exact keyword matches. "
        "A section can be useful if it contributes theory, mechanisms, empirical findings, or framing that would materially help write the chapter. "
        "Do not reward frontmatter, references, pure methods, or generic sections without specific evidence. "
        "Return only the structured schema."
    )
    user_prompt = clean_text(
        "\n\n".join(
            [
                f"Chapter title: {chapter_title}",
                f"Chapter summary: {chapter_summary}",
                "Must terms: " + " | ".join(clean_text(x) for x in must_terms[:8] if clean_text(x)),
                "Important chapter facets:\n" + ("\n".join(subpoint_lines) if subpoint_lines else "- none"),
                f"Candidate document: {clean_text(candidate_pack.get('doc_title') or candidate_pack.get('doc_id') or 'Untitled document')}",
                f"Candidate section: {clean_text(candidate_pack.get('section_path_text') or candidate_pack.get('title') or 'Untitled section')}",
                f"Section type/pages: {clean_text(candidate_pack.get('section_type') or 'body_other')} | {candidate_pack.get('page_start')}-{candidate_pack.get('page_end')}",
                "Section excerpt:\n" + truncate_text(clean_text(candidate_pack.get("section_excerpt") or ""), max_len=1600),
                "Evidence passages:\n" + ("\n".join(evidence_lines) if evidence_lines else "- none"),
                "Allowed exclusion_violations values: " + ", ".join(PHASE_F_ALLOWED_EXCLUSION_VIOLATIONS),
                "Scoring guidance: usefulness_raw judges overall usefulness to the chapter, topic_match_raw judges topical relevance, coverage_raw judges how much substantive usable content this section contains.",
            ]
        )
    )
    return {"system_prompt": system_prompt, "messages": [{"role": "user", "content": user_prompt}]}


def call_openai_llm_judge(
    *,
    run_ctx: Any,
    candidate_pack: Dict[str, Any],
    chapter_title: str,
    chapter_summary: str,
    must_terms: List[str],
    active_subpoints: List[Dict[str, Any]],
    options: PhaseFOptions,
    stable_hash_fn: Any,
    record_usage: bool = True,
) -> Dict[str, Any]:
    if PhaseFOpenAI is None or LLMJudgeVerdictModel is None:
        raise RuntimeError("OpenAI or pydantic is unavailable for the Phase F LLM judge.")
    if not PHASE_F_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = PhaseFOpenAI(api_key=PHASE_F_API_KEY)
    prompt_payload = build_judge_messages(
        chapter_title=chapter_title,
        chapter_summary=chapter_summary,
        must_terms=must_terms,
        active_subpoints=active_subpoints,
        candidate_pack=candidate_pack,
    )
    messages = prompt_payload["messages"]
    prompt_cache_key = f"phase_f::{stable_hash_fn(run_ctx.run_id, str(candidate_pack.get('candidate_id')), 'judge', length=20)}"
    attempts = [
        {
            "api_mode": "responses.parse",
            "model": options.judge_model,
            "reasoning_effort": options.judge_reasoning_effort,
            "max_output_tokens": options.judge_max_output_tokens,
            "verbosity": "low",
        },
        {
            "api_mode": "chat.completions.parse",
            "model": options.judge_model,
            "reasoning_effort": options.judge_reasoning_effort,
            "max_completion_tokens": options.judge_max_output_tokens,
            "verbosity": "low",
        },
    ]
    if str(options.judge_model or "").strip() != "gpt-5-nano":
        attempts.append(
            {
                "api_mode": "responses.parse",
                "model": "gpt-5-nano",
                "reasoning_effort": "low",
                "max_output_tokens": options.judge_max_output_tokens,
                "verbosity": "low",
            }
        )
    attempt_traces = []
    last_error = None
    for attempt in attempts:
        try:
            if attempt["api_mode"] == "responses.parse":
                response = client.responses.parse(
                    model=attempt["model"],
                    instructions=prompt_payload["system_prompt"],
                    input=build_responses_input(messages),
                    text_format=LLMJudgeVerdictModel,
                    reasoning={"effort": attempt["reasoning_effort"]},
                    max_output_tokens=attempt["max_output_tokens"],
                    text={"verbosity": attempt["verbosity"]},
                    prompt_cache_key=prompt_cache_key,
                    store=False,
                )
                payload = parse_structured_response_payload(response)
            else:
                response = client.beta.chat.completions.parse(
                    model=attempt["model"],
                    messages=messages,
                    response_format=LLMJudgeVerdictModel,
                    reasoning_effort=attempt["reasoning_effort"],
                    max_completion_tokens=attempt["max_completion_tokens"],
                    verbosity=attempt["verbosity"],
                    prompt_cache_key=prompt_cache_key,
                    store=False,
                )
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError("Structured LLM judge returned no parsed payload.")
                payload = parsed.model_dump()
            usage = extract_openai_usage_payload(getattr(response, "usage", None))
            cost = estimate_openai_text_cost_usd(str(getattr(response, "model", None) or attempt["model"]), usage)
            payload["exclusion_violations"] = [value for value in list(payload.get("exclusion_violations") or []) if value in set(PHASE_F_ALLOWED_EXCLUSION_VIOLATIONS)]
            allowed_passage_ids = {str(item.get("passage_id") or "") for item in list(candidate_pack.get("evidence_rows") or []) if str(item.get("passage_id") or "")}
            payload["top_evidence_passage_ids"] = [
                passage_id
                for passage_id in list(payload.get("top_evidence_passage_ids") or [])
                if str(passage_id or "") in allowed_passage_ids
            ][:3]
            api_call_entry = {
                "stage": "phase_f",
                "provider": "openai",
                "model": str(getattr(response, "model", None) or attempt["model"]),
                "input_tokens": int(usage.get("input_tokens") or 0),
                "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
                "output_tokens": int(usage.get("output_tokens") or 0),
                "cost_usd": float(cost.get("estimated_cost_usd") or 0.0),
                "meta": {
                    "api_mode": attempt["api_mode"],
                    "candidate_id": candidate_pack.get("candidate_id"),
                    "pricing_model": cost.get("pricing_model"),
                    "pricing_source_url": cost.get("pricing_source_url"),
                    "pricing_verified_date": cost.get("pricing_verified_date"),
                },
            }
            if record_usage:
                record_api_call(run_ctx, **api_call_entry)
            return {
                "payload": payload,
                "usage": usage,
                "cost": cost,
                "model_used": str(getattr(response, "model", None) or attempt["model"]),
                "api_mode": attempt["api_mode"],
                "attempts": attempt_traces + [attempt],
                "api_call_entry": api_call_entry,
            }
        except Exception as e:
            last_error = e
            attempt_traces.append({**attempt, "error_type": type(e).__name__, "error_message": str(e)})
    raise RuntimeError(str(last_error or "Phase F LLM judge failed"))


def judge_composite_score(payload: Dict[str, Any]) -> float:
    usefulness = clamp01((payload.get("usefulness_raw") or 0) / 5.0)
    topic_match = clamp01((payload.get("topic_match_raw") or 0) / 5.0)
    coverage = clamp01((payload.get("coverage_raw") or 0) / 5.0)
    penalty = min(0.45, 0.08 * len(list(payload.get("exclusion_violations") or [])))
    return round(max(0.0, (0.50 * usefulness) + (0.35 * topic_match) + (0.15 * coverage) - penalty), 8)


def build_phase_f_preview(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    preview = []
    for row in rows[: int(limit)]:
        preview.append(
            {
                "rerank_rank": row.get("rerank_rank"),
                "doc_id": row.get("doc_id"),
                "title": row.get("title"),
                "section_type": row.get("section_type"),
                "pages": f"{row.get('page_start')}-{row.get('page_end')}",
                "rerank_score": row.get("rerank_score"),
                "cross_encoder_score": row.get("cross_encoder_score"),
                "judge_score": row.get("judge_score"),
                "best_subpoint_id": row.get("best_subpoint_id"),
                "supporting_passages": row.get("supporting_passage_count"),
                "generic_title": row.get("generic_title"),
            }
        )
    return preview


def maybe_existing(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0


def resolve_phase_f_judge_concurrency(*, candidate_count: int) -> int:
    if int(candidate_count) <= 1:
        return 1
    # The judge is I/O-bound (HTTP API calls), not CPU-bound.
    # Use 8 concurrent workers (OpenAI rate limits are the real cap).
    return max(1, min(int(candidate_count), 8))


def judge_payload_is_inconsistent(payload: Dict[str, Any]) -> bool:
    notes = clean_text(payload.get("notes")).lower()
    raw_total = int(payload.get("usefulness_raw") or 0) + int(payload.get("topic_match_raw") or 0) + int(payload.get("coverage_raw") or 0)
    positive_markers = [
        "highly relevant",
        "strongly relevant",
        "materially help",
        "materially useful",
        "useful for",
        "relevant for",
        "relevant to",
        "strongly useful",
        "highly useful",
        "helpful for",
    ]
    general_positive_markers = [
        " useful",
        " relevant",
        " helpful",
        "section discusses",
        "section explains",
        "section covers",
        "section provides",
    ]
    negative_markers = [
        "not useful",
        "not relevant",
        "not helpful",
        "off topic",
        "off-topic",
        "irrelevant",
    ]
    if raw_total <= 1 and any(marker in notes for marker in positive_markers):
        return True
    if raw_total <= 1 and any(marker in notes for marker in general_positive_markers):
        if not any(marker in notes for marker in negative_markers):
            return True
    return False


def run_phase_f(run_ctx: Any, *, options: PhaseFOptions, stable_hash_fn=None, log_event_fn=None, run_logger=None) -> Dict[str, Any]:
    opt = options.normalized()
    rerank_dir = ensure_dir(Path(run_ctx.artifacts.rerank_dir))
    config_path = rerank_dir / "phase_f_config.json"
    runtime_path = rerank_dir / "phase_f_runtime.json"
    summary_path = rerank_dir / "phase_f_summary.json"
    assessment_path = rerank_dir / "phase_f_assessment.json"
    candidate_packs_path = rerank_dir / "phase_f_candidate_packs.jsonl"
    cross_encoder_path = rerank_dir / "cross_encoder.jsonl"
    llm_judge_path = rerank_dir / "llm_judge.jsonl"
    rerank_results_path = rerank_dir / "rerank_results.jsonl"

    if not bool(opt.force_rebuild):
        try:
            cached_result = build_phase_f_cache_result(run_ctx)
            from pdf_reporting import update_run_pdf_reports

            update_run_pdf_reports(run_ctx, phase_name="phase_f")
            return cached_result
        except Exception:
            pass

    write_json(runtime_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_f", "options": json_safe(asdict(opt)), "capabilities": phase_f_capabilities()})
    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_f", "options": json_safe(asdict(opt))})

    retrieval_dir = Path(run_ctx.artifacts.retrieval_dir)
    normalized_dir = Path(run_ctx.artifacts.normalized_dir)
    fused_path = retrieval_dir / "fused_candidates.jsonl"
    sections_path = normalized_dir / "sections.jsonl"
    passages_path = normalized_dir / "passages.jsonl"
    documents_path = normalized_dir / "documents.jsonl"
    query_plan_path = Path(run_ctx.artifacts.query_plan_json)
    phase_e_support_path = retrieval_dir / "phase_e_subpoint_support.json"
    if not fused_path.exists():
        raise FileNotFoundError("Phase E fused candidates are required before Phase F can run.")
    if not all(path.exists() for path in [sections_path, passages_path, documents_path, query_plan_path, phase_e_support_path]):
        raise FileNotFoundError("Phase F requires Phase C, Phase D, and Phase E artifacts.")

    fused_rows = read_jsonl_rows(fused_path)
    documents = read_jsonl_rows(documents_path)
    sections = read_jsonl_rows(sections_path)
    passages = read_jsonl_rows(passages_path)
    query_plan = dict((read_json(query_plan_path).get("query_plan") or {}))
    phase_e_support = read_json(phase_e_support_path)
    active_subpoint_ids = list(phase_e_support.get("active_subpoint_ids") or [])
    active_subpoints = [
        dict(subpoint)
        for subpoint in list(query_plan.get("subpoints") or [])
        if str(subpoint.get("subpoint_id") or "") in set(active_subpoint_ids)
    ]
    if not active_subpoints:
        active_subpoints = list(query_plan.get("subpoints") or [])

    selected_candidates = select_rerank_candidates(fused_rows, opt)
    candidate_packs = build_candidate_packs(selected_candidates, documents, sections, passages, active_subpoint_ids, opt)
    write_jsonl_rows(candidate_packs_path, [{k: v for k, v in pack.items() if k != "source_candidate"} for pack in candidate_packs])

    warnings, failures = [], []
    cross_encoder_rows = []
    cross_encoder_runtime = {}
    llm_judge_rows = []
    judge_runtime = {"enabled": bool(opt.use_openai_judge)}

    if not candidate_packs:
        warnings.append("Phase E produced no fused candidates to rerank.")
        write_jsonl_rows(cross_encoder_path, [])
        write_jsonl_rows(llm_judge_path, [])
        write_jsonl_rows(rerank_results_path, [])
        score_rows = []
    else:
        if torch is None or AutoTokenizer is None or AutoModelForSequenceClassification is None:
            failures.append("local cross-encoder reranker dependencies are unavailable")
            score_rows = []
        else:
            global_query = build_global_query_text(query_plan)
            bridge_rows = list(query_plan.get("bridge_term_rows") or [])
            global_bridge_terms = [clean_text(item) for item in list(query_plan.get("bridge_terms") or []) if clean_text(item)]
            subpoint_query_by_id = {
                str(subpoint.get("subpoint_id") or ""): build_subpoint_query_text(
                    subpoint,
                    bridge_terms=unique_clean_terms(
                        [
                            row.get("term")
                            for row in bridge_rows
                            if row.get("term")
                            and (
                                not (row.get("linked_source_anchors") or [])
                                or (
                                    {
                                        normalize_match_key(item)
                                        for item in (row.get("linked_source_anchors") or [])
                                        if clean_text(item)
                                    }
                                    & {
                                        normalize_match_key(item)
                                        for item in list(subpoint.get("source_anchors") or []) + list(subpoint.get("must_terms") or []) + list(subpoint.get("should_terms") or [])
                                        if clean_text(item)
                                    }
                                )
                            )
                        ]
                        or global_bridge_terms,
                        limit=4,
                        max_words=5,
                        max_chars=80,
                    ),
                )
                for subpoint in list(query_plan.get("subpoints") or [])
                if str(subpoint.get("subpoint_id") or "")
            }
            pair_rows = []
            for pack in candidate_packs:
                pair_rows.append(
                    {
                        "candidate_id": pack.get("candidate_id"),
                        "query_kind": "global",
                        "subpoint_id": None,
                        "query": global_query,
                        "candidate_text": pack.get("candidate_text"),
                    }
                )
                for subpoint_id in list(pack.get("chosen_subpoint_ids") or []):
                    query_text = subpoint_query_by_id.get(str(subpoint_id))
                    if not clean_text(query_text):
                        continue
                    pair_rows.append(
                        {
                            "candidate_id": pack.get("candidate_id"),
                            "query_kind": "subpoint",
                            "subpoint_id": str(subpoint_id),
                            "query": query_text,
                            "candidate_text": pack.get("candidate_text"),
                        }
                    )
            ce_payload = score_cross_encoder_pairs(pair_rows, opt)
            raw_ce_rows = list(ce_payload.get("rows") or [])
            cross_encoder_runtime = {
                **dict(ce_payload.get("runtime") or {}),
                "model": opt.cross_encoder_model,
                "candidate_count": len(candidate_packs),
                "global_query_length_chars": len(global_query),
            }
            ce_by_candidate = defaultdict(lambda: {"global": None, "subpoints": []})
            for row in raw_ce_rows:
                cid = str(row.get("candidate_id") or "")
                if row.get("query_kind") == "global":
                    ce_by_candidate[cid]["global"] = row
                else:
                    ce_by_candidate[cid]["subpoints"].append(row)
            fused_rank_values = [int(pack.get("fused_rank") or 0) for pack in candidate_packs if int(pack.get("fused_rank") or 0) > 0]
            min_rank = min(fused_rank_values) if fused_rank_values else 1
            max_rank = max(fused_rank_values) if fused_rank_values else max(1, len(candidate_packs))
            score_rows = []
            for pack in candidate_packs:
                cid = str(pack.get("candidate_id") or "")
                ce_info = ce_by_candidate.get(cid) or {}
                global_row = dict(ce_info.get("global") or {})
                subpoint_rows = sorted(
                    list(ce_info.get("subpoints") or []),
                    key=lambda row: (float(row.get("score_prob") or 0.0), float(row.get("raw_logit") or 0.0)),
                    reverse=True,
                )
                best_subpoint = subpoint_rows[0] if subpoint_rows else {}
                global_prob = clamp01(global_row.get("score_prob"))
                best_subpoint_prob = clamp01(best_subpoint.get("score_prob"))
                mean_subpoint_prob = clamp01(safe_mean(row.get("score_prob") for row in subpoint_rows))
                evidence_density = candidate_evidence_density(pack["source_candidate"])
                fused_rank = int(pack.get("fused_rank") or 0)
                if max_rank > min_rank and fused_rank > 0:
                    fused_prior_norm = 1.0 - ((fused_rank - min_rank) / max(1.0, float(max_rank - min_rank)))
                else:
                    fused_prior_norm = 1.0 if fused_rank > 0 else 0.0
                cross_encoder_score = round((0.62 * global_prob) + (0.28 * best_subpoint_prob) + (0.10 * mean_subpoint_prob), 8)
                base_score = (
                    (float(opt.cross_encoder_weight) * cross_encoder_score)
                    + (float(opt.fused_prior_weight) * clamp01(fused_prior_norm))
                    + (float(opt.evidence_weight) * evidence_density)
                )
                penalties = 0.0
                if bool(pack.get("generic_title")) and evidence_density < 0.55:
                    penalties += float(opt.generic_title_penalty)
                if int(pack.get("supporting_passage_count") or 0) <= 0:
                    penalties += float(opt.weak_evidence_penalty)
                elif int(pack.get("supporting_passage_count") or 0) == 1:
                    penalties += float(opt.single_passage_penalty)
                base_score = round(max(0.0, base_score - penalties), 8)
                cross_encoder_rows.append(
                    {
                        "candidate_id": cid,
                        "doc_id": pack.get("doc_id"),
                        "section_id": pack.get("section_id"),
                        "title": pack.get("title"),
                        "query_kinds_scored": ["global"] + [f"subpoint:{row.get('subpoint_id')}" for row in subpoint_rows],
                        "global_score_prob": global_prob,
                        "global_raw_logit": global_row.get("raw_logit"),
                        "best_subpoint_id": best_subpoint.get("subpoint_id"),
                        "best_subpoint_score_prob": best_subpoint_prob,
                        "best_subpoint_raw_logit": best_subpoint.get("raw_logit"),
                        "mean_subpoint_score_prob": mean_subpoint_prob,
                        "scored_subpoints": [
                            {
                                "subpoint_id": row.get("subpoint_id"),
                                "score_prob": row.get("score_prob"),
                                "raw_logit": row.get("raw_logit"),
                            }
                            for row in subpoint_rows
                        ],
                        "cross_encoder_score": cross_encoder_score,
                        "fused_prior_norm": round(clamp01(fused_prior_norm), 8),
                        "evidence_density": evidence_density,
                        "penalties_applied": round(penalties, 8),
                        "base_score_pre_judge": base_score,
                    }
                )
                score_rows.append(
                    {
                        **{k: v for k, v in pack.items() if k not in {"source_candidate", "candidate_text", "evidence_rows"}},
                        "candidate_text": pack.get("candidate_text"),
                        "evidence_rows": list(pack.get("evidence_rows") or []),
                        "cross_encoder_score": cross_encoder_score,
                        "global_score_prob": global_prob,
                        "global_raw_logit": global_row.get("raw_logit"),
                        "best_subpoint_id": best_subpoint.get("subpoint_id"),
                        "best_subpoint_score_prob": best_subpoint_prob,
                        "best_subpoint_raw_logit": best_subpoint.get("raw_logit"),
                        "mean_subpoint_score_prob": mean_subpoint_prob,
                        "fused_prior_norm": round(clamp01(fused_prior_norm), 8),
                        "evidence_density": evidence_density,
                        "base_score_pre_judge": base_score,
                    }
                )
            write_jsonl_rows(cross_encoder_path, cross_encoder_rows)

    if not maybe_existing(cross_encoder_path):
        write_jsonl_rows(cross_encoder_path, cross_encoder_rows)

    if score_rows and bool(opt.use_openai_judge) and PhaseFOpenAI is not None and PHASE_F_API_KEY and LLMJudgeVerdictModel is not None and int(opt.judge_candidate_limit) > 0:
        pre_judge_ranked = sorted(
            score_rows,
            key=lambda row: (float(row.get("base_score_pre_judge") or 0.0), float(row.get("cross_encoder_score") or 0.0), -int(row.get("fused_rank") or 0)),
            reverse=True,
        )
        doc_buckets = defaultdict(list)
        for row in pre_judge_ranked:
            doc_buckets[str(row.get("doc_id") or "")].append(row)
        ordered_doc_ids = sorted(
            [doc_id for doc_id in doc_buckets.keys() if doc_id],
            key=lambda doc_id: (
                float((doc_buckets.get(doc_id) or [{}])[0].get("base_score_pre_judge") or 0.0),
                float((doc_buckets.get(doc_id) or [{}])[0].get("cross_encoder_score") or 0.0),
            ),
            reverse=True,
        )
        effective_candidate_limit = max(int(opt.judge_candidate_limit), min(24, len(ordered_doc_ids)))
        judge_candidates = []
        for pass_index in range(int(opt.judge_max_per_doc)):
            for doc_id in ordered_doc_ids:
                bucket = doc_buckets.get(doc_id) or []
                if pass_index >= len(bucket):
                    continue
                row = bucket[pass_index]
                if float(row.get("base_score_pre_judge") or 0.0) < 0.12 and pass_index > 0:
                    continue
                judge_candidates.append(row)
                if len(judge_candidates) >= effective_candidate_limit:
                    break
            if len(judge_candidates) >= effective_candidate_limit:
                break
        resolved_judge_concurrency = resolve_phase_f_judge_concurrency(candidate_count=len(judge_candidates))
        judge_runtime.update(
            {
                "candidate_limit": len(judge_candidates),
                "model": opt.judge_model,
                "resolved_concurrency": resolved_judge_concurrency,
                "cpu_count": available_cpu_count(),
            }
        )
        judge_started = time.perf_counter()
        judge_results = []

        def run_judge_candidate(index: int, row: Dict[str, Any]):
            try:
                judge_payload = call_openai_llm_judge(
                    run_ctx=run_ctx,
                    candidate_pack=row,
                    chapter_title=clean_text(query_plan.get("chapter_title")),
                    chapter_summary=clean_text(query_plan.get("chapter_summary")),
                    must_terms=list(query_plan.get("must_terms") or []),
                    active_subpoints=active_subpoints,
                    options=opt,
                    stable_hash_fn=stable_hash_fn or stable_hash,
                    record_usage=False,
                )
                return index, row, judge_payload, None
            except Exception as e:
                return index, row, None, e

        total_judge = len(judge_candidates)
        print(f"  [llm-judge] {total_judge} candidates, concurrency={resolved_judge_concurrency}")
        if resolved_judge_concurrency <= 1:
            for index, row in enumerate(judge_candidates):
                judge_results.append(run_judge_candidate(index, row))
                print(f"  [llm-judge] {index + 1}/{total_judge} done")
        else:
            with ThreadPoolExecutor(max_workers=resolved_judge_concurrency) as executor:
                futures = [
                    executor.submit(run_judge_candidate, index, row)
                    for index, row in enumerate(judge_candidates)
                ]
                done_count = 0
                for future in as_completed(futures):
                    judge_results.append(future.result())
                    done_count += 1
                    if done_count == 1 or done_count % 4 == 0 or done_count == total_judge:
                        elapsed_j = time.perf_counter() - judge_started
                        print(f"  [llm-judge] {done_count}/{total_judge} done ({elapsed_j:.1f}s)")

        for _, row, judge_payload, error in sorted(judge_results, key=lambda item: item[0]):
            if error is None and judge_payload is not None:
                api_call_entry = dict(judge_payload.get("api_call_entry") or {})
                if api_call_entry:
                    record_api_call(run_ctx, **api_call_entry)
                payload = dict(judge_payload.get("payload") or {})
                inconsistent = judge_payload_is_inconsistent(payload)
                llm_judge_rows.append(
                    {
                        "candidate_id": row.get("candidate_id"),
                        "doc_id": row.get("doc_id"),
                        "section_id": row.get("section_id"),
                        "title": row.get("title"),
                        "judge_model": judge_payload.get("model_used"),
                        "judge_api_mode": judge_payload.get("api_mode"),
                        "judge_inconsistent": inconsistent,
                        "judge_score": None if inconsistent else judge_composite_score(payload),
                        **payload,
                    }
                )
                continue
            warnings.append(f"LLM judge failed for candidate {row.get('candidate_id')}: {type(error).__name__}")
            llm_judge_rows.append(
                {
                    "candidate_id": row.get("candidate_id"),
                    "doc_id": row.get("doc_id"),
                    "section_id": row.get("section_id"),
                    "title": row.get("title"),
                    "judge_error_type": type(error).__name__,
                    "judge_error_message": str(error),
                    "judge_score": None,
                }
            )
        judge_runtime["elapsed_ms"] = round((time.perf_counter() - judge_started) * 1000.0, 3)
        judge_runtime["completed_count"] = len([row for row in llm_judge_rows if row.get("judge_score") is not None])
    else:
        if bool(opt.use_openai_judge) and not (PhaseFOpenAI is not None and PHASE_F_API_KEY and LLMJudgeVerdictModel is not None):
            warnings.append("OpenAI judge was requested but OpenAI/Pydantic/API key support is unavailable; cross-encoder only reranking was used")
        judge_runtime.update({"candidate_limit": 0, "completed_count": 0})
    inconsistent_judge_count = len([row for row in llm_judge_rows if bool(row.get("judge_inconsistent"))])
    if inconsistent_judge_count:
        warnings.append(f"{inconsistent_judge_count} LLM judge rows were inconsistent and excluded from score blending")
    write_jsonl_rows(llm_judge_path, llm_judge_rows)

    judge_by_candidate = {str(row.get("candidate_id") or ""): row for row in llm_judge_rows if str(row.get("candidate_id") or "")}
    rerank_rows = []
    for row in score_rows:
        judge_row = dict(judge_by_candidate.get(str(row.get("candidate_id") or "")) or {})
        judge_score = judge_row.get("judge_score")
        final_score = float(row.get("base_score_pre_judge") or 0.0)
        if judge_score is not None:
            final_score = ((1.0 - float(opt.llm_judge_blend)) * final_score) + (float(opt.llm_judge_blend) * clamp01(judge_score))
        result = {
            "candidate_id": row.get("candidate_id"),
            "doc_id": row.get("doc_id"),
            "doc_title": row.get("doc_title"),
            "section_id": row.get("section_id"),
            "title": row.get("title"),
            "section_path": row.get("section_path"),
            "section_type": row.get("section_type"),
            "page_start": row.get("page_start"),
            "page_end": row.get("page_end"),
            "fused_rank": row.get("fused_rank"),
            "fused_score": row.get("fused_score"),
            "selection_score": row.get("selection_score"),
            "cross_encoder_score": row.get("cross_encoder_score"),
            "global_score_prob": row.get("global_score_prob"),
            "best_subpoint_id": row.get("best_subpoint_id"),
            "best_subpoint_score_prob": row.get("best_subpoint_score_prob"),
            "mean_subpoint_score_prob": row.get("mean_subpoint_score_prob"),
            "fused_prior_norm": row.get("fused_prior_norm"),
            "evidence_density": row.get("evidence_density"),
            "supporting_passage_count": row.get("supporting_passage_count"),
            "supporting_passage_ids": row.get("supporting_passage_ids"),
            "trusted_subpoint_ids": row.get("trusted_subpoint_ids"),
            "chosen_subpoint_ids": row.get("chosen_subpoint_ids"),
            "generic_title": row.get("generic_title"),
            "quality_flags": row.get("quality_flags"),
            "judge_score": judge_score,
            "judge_usefulness_raw": judge_row.get("usefulness_raw"),
            "judge_topic_match_raw": judge_row.get("topic_match_raw"),
            "judge_coverage_raw": judge_row.get("coverage_raw"),
            "judge_exclusion_violations": judge_row.get("exclusion_violations"),
            "judge_top_evidence_passage_ids": judge_row.get("top_evidence_passage_ids"),
            "judge_notes": judge_row.get("notes"),
            "base_score_pre_judge": row.get("base_score_pre_judge"),
            "rerank_score": round(clamp01(final_score), 8),
            "candidate_text": row.get("candidate_text"),
            "evidence_rows": row.get("evidence_rows"),
        }
        rerank_rows.append(result)
    rerank_rows.sort(
        key=lambda row: (
            float(row.get("rerank_score") or 0.0),
            float(row.get("cross_encoder_score") or 0.0),
            -int(row.get("fused_rank") or 0),
            str(row.get("doc_id") or ""),
            str(row.get("title") or ""),
        ),
        reverse=True,
    )
    doc_rank_counter = Counter()
    for idx, row in enumerate(rerank_rows, 1):
        row["rerank_rank"] = idx
        doc_id = str(row.get("doc_id") or "")
        doc_rank_counter[doc_id] += 1
        row["doc_rank"] = int(doc_rank_counter[doc_id])
    write_jsonl_rows(rerank_results_path, rerank_rows)

    rerank_scores = [float(row.get("rerank_score") or 0.0) for row in rerank_rows]
    score_distribution = {
        "count": len(rerank_scores),
        "max": round(max(rerank_scores), 8) if rerank_scores else None,
        "min": round(min(rerank_scores), 8) if rerank_scores else None,
        "mean": round(statistics.fmean(rerank_scores), 8) if rerank_scores else None,
        "pstdev": round(statistics.pstdev(rerank_scores), 8) if len(rerank_scores) >= 2 else 0.0,
    }
    top20 = rerank_rows[:20]
    top20_unique_docs = len({str(row.get("doc_id") or "") for row in top20 if str(row.get("doc_id") or "")})
    generic_top10 = sum(1 for row in rerank_rows[:10] if bool(row.get("generic_title")))
    per_doc_top_rows = []
    seen_doc_ids = set()
    for row in rerank_rows:
        doc_id = str(row.get("doc_id") or "")
        if doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)
        per_doc_top_rows.append(
            {
                "doc_id": doc_id,
                "doc_title": row.get("doc_title"),
                "top_title": row.get("title"),
                "rerank_rank": row.get("rerank_rank"),
                "rerank_score": row.get("rerank_score"),
                "cross_encoder_score": row.get("cross_encoder_score"),
                "judge_score": row.get("judge_score"),
            }
        )
    judged_rows = [row for row in rerank_rows if row.get("judge_score") is not None]
    disagreement_values = [abs(float(row.get("judge_score") or 0.0) - float(row.get("cross_encoder_score") or 0.0)) for row in judged_rows]
    disagreement_avg = round(statistics.fmean(disagreement_values), 8) if disagreement_values else None
    if score_rows and not rerank_rows:
        failures.append("Phase F did not produce a reranked candidate table.")
    if cross_encoder_rows and score_distribution.get("pstdev") is not None and float(score_distribution.get("pstdev") or 0.0) < 0.01:
        warnings.append("rerank score distribution is unusually flat")
    if generic_top10 > 4:
        warnings.append(f"generic titles dominate the top10 ({generic_top10})")
    if top20 and top20_unique_docs < 2:
        warnings.append(f"top20 unique docs is low ({top20_unique_docs})")
    if disagreement_avg is not None and disagreement_avg > 0.4:
        warnings.append(f"cross-encoder and LLM judge disagreement is elevated ({disagreement_avg})")

    qc_rows = [
        qc_row(check="reranked_candidate_count", status="OK" if rerank_rows or not candidate_packs else "FAIL", value=len(rerank_rows), expected=">= 1 when candidate packs exist", why="Phase G needs a reranked section table.", fix="inspect fused candidates, cross_encoder.jsonl, and rerank_results.jsonl"),
        qc_row(check="cross_encoder_available", status="OK" if cross_encoder_rows or not candidate_packs else "FAIL", value=bool(cross_encoder_rows), expected="True when candidates exist", why="Cross-encoder reranking is the mandatory precision layer.", fix="check transformers/torch imports and the local reranker model"),
        qc_row(check="score_distribution", status="OK" if float(score_distribution.get("pstdev") or 0.0) >= 0.01 or len(rerank_rows) <= 1 else "WARN", value=score_distribution.get("pstdev"), expected=">= 0.01 preferred", why="A flat score distribution indicates weak separation between candidates.", fix="inspect candidate text packing or reranker model choice"),
        qc_row(check="judge_disagreement", status="OK" if disagreement_avg is None or disagreement_avg <= 0.4 else "WARN", value=disagreement_avg, expected="<= 0.40 preferred", why="Large disagreement can indicate ambiguous evidence or poor score blending.", fix="inspect llm_judge.jsonl and top reranked candidates"),
        qc_row(check="top_candidates_per_pdf", status="OK" if top20_unique_docs >= 2 or len(top20) <= 1 else "WARN", value=top20_unique_docs, expected=">= 2 in top20 when multiple PDFs exist", why="The reranked list should retain multi-document coverage when multiple PDFs are useful.", fix="inspect per_doc_top_rows and fused selection"),
    ]

    status = "failed" if failures else ("success_with_warnings" if warnings else "success")
    quality_band = "insufficient" if failures else ("acceptable_with_issues" if warnings else "high")
    assessment = {
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": not failures,
        "failures": failures,
        "warnings": warnings,
        "counts": {
            "candidate_pack_count": len(candidate_packs),
            "cross_encoder_count": len(cross_encoder_rows),
            "llm_judge_count": len([row for row in llm_judge_rows if row.get("judge_score") is not None]),
            "llm_judge_inconsistent_count": inconsistent_judge_count,
            "rerank_result_count": len(rerank_rows),
            "top20_unique_docs": top20_unique_docs,
            "generic_top10": generic_top10,
        },
        "score_distribution": score_distribution,
        "judge_disagreement_avg": disagreement_avg,
        "qc_rows": qc_rows,
    }

    preview_rows = build_phase_f_preview(rerank_rows, opt.top_candidate_preview_count)
    metrics_update = {
        "status": status,
        "quality_band": quality_band,
        "cross_encoder_model": opt.cross_encoder_model,
        "judge_model": opt.judge_model if bool(opt.use_openai_judge) else None,
        "candidate_pack_count": len(candidate_packs),
        "cross_encoder_count": len(cross_encoder_rows),
        "llm_judge_count": len([row for row in llm_judge_rows if row.get("judge_score") is not None]),
        "llm_judge_inconsistent_count": inconsistent_judge_count,
        "rerank_result_count": len(rerank_rows),
        "top20_unique_docs": top20_unique_docs,
        "judge_disagreement_avg": disagreement_avg,
        "phase_f_summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
        "phase_f_assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
    }
    summary = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_f",
        "options": json_safe(asdict(opt)),
        "cross_encoder_runtime": cross_encoder_runtime,
        "judge_runtime": judge_runtime,
        "score_distribution": score_distribution,
        "judge_disagreement_avg": disagreement_avg,
        "candidate_packs_path": rel_to_run(Path(run_ctx.run_dir), candidate_packs_path),
        "cross_encoder_path": rel_to_run(Path(run_ctx.run_dir), cross_encoder_path),
        "llm_judge_path": rel_to_run(Path(run_ctx.run_dir), llm_judge_path),
        "rerank_results_path": rel_to_run(Path(run_ctx.run_dir), rerank_results_path),
        "per_doc_top_rows": per_doc_top_rows,
        "preview_rows": preview_rows,
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": qc_rows,
        "metrics_update": metrics_update,
    }
    write_json(summary_path, summary)
    write_json(
        assessment_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_f",
            "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
            "qc_rows": qc_rows,
            "score_distribution": score_distribution,
            "judge_disagreement_avg": disagreement_avg,
            "rerank_results_path": rel_to_run(Path(run_ctx.run_dir), rerank_results_path),
        },
    )

    if log_event_fn is not None:
        log_event_fn(
            run_ctx,
            stage="phase_f",
            event="phase_finished",
            status=status,
            cross_encoder_model=opt.cross_encoder_model,
            rerank_result_count=len(rerank_rows),
            llm_judge_count=len([row for row in llm_judge_rows if row.get("judge_score") is not None]),
            top20_unique_docs=top20_unique_docs,
            judge_disagreement_avg=disagreement_avg,
        )
    if run_logger is not None:
        run_logger.info(
            "Phase F finished | status=%s | rerank_results=%s | judged=%s | top20_unique_docs=%s | disagreement=%s | cross_encoder_model=%s",
            status,
            len(rerank_rows),
            len([row for row in llm_judge_rows if row.get("judge_score") is not None]),
            top20_unique_docs,
            disagreement_avg,
            opt.cross_encoder_model,
        )

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_f")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "candidate_packs_path": candidate_packs_path,
        "cross_encoder_path": cross_encoder_path,
        "llm_judge_path": llm_judge_path,
        "rerank_results_path": rerank_results_path,
        "candidate_pack_rows": [{k: v for k, v in pack.items() if k != "source_candidate"} for pack in candidate_packs],
        "cross_encoder_rows": cross_encoder_rows,
        "llm_judge_rows": llm_judge_rows,
        "rerank_result_rows": rerank_rows,
        "summary": summary,
        "assessment": assessment,
        "qc_rows": qc_rows,
        "metrics_update": metrics_update,
        "cross_encoder_runtime": cross_encoder_runtime,
        "judge_runtime": judge_runtime,
        "cache_hit": False,
    }


def phase_summary_exists(run_ctx: Any, phase_name: str) -> bool:
    mapping = {
        "phase_b": Path(run_ctx.artifacts.parser_dir) / "phase_b_summary.json",
        "phase_c": Path(run_ctx.artifacts.normalized_dir) / "phase_c_summary.json",
        "phase_d": Path(run_ctx.artifacts.retrieval_dir) / "phase_d_summary.json",
        "phase_e": Path(run_ctx.artifacts.retrieval_dir) / "phase_e_summary.json",
    }
    path = mapping.get(phase_name)
    return bool(path and path.exists())


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase F lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_f_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
    parser.add_argument("--force-rebuild-phase-f", action="store_true")
    parser.add_argument("--suite-manifest", default="benchmark/small_gold/manifests/suite_manifest.json")
    parser.add_argument("--chapter-index", type=int, default=0)
    parser.add_argument("--doc-limit", type=int, default=None)
    parser.add_argument("--include-doc-id", action="append", default=[])
    parser.add_argument("--exclude-doc-id", action="append", default=[])
    parser.add_argument("--chapter-title", default="")
    parser.add_argument("--chapter-description", default="")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--pdf-dir", default="")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=20)
    parser.add_argument("--grobid-base-url", default=(os.getenv("GROBID_URL") or os.getenv("GROBID_BASE_URL") or "").strip())
    parser.add_argument("--planner-model", default=(os.getenv("OPENAI_PDF_SCAN_PLANNER_MODEL") or os.getenv("OPENAI_PDF_SCAN_MODEL") or "gpt-5-mini").strip() or "gpt-5-mini")
    parser.add_argument("--planner-reasoning-effort", default="low")
    parser.add_argument("--no-openai-planner", action="store_true")
    parser.add_argument("--embed-model", default=(os.getenv("OPENAI_PDF_SCAN_EMBED_MODEL") or "text-embedding-3-small").strip() or "text-embedding-3-small")
    parser.add_argument("--no-openai-dense", action="store_true")
    parser.add_argument("--rerank-model", default=PHASE_F_DEFAULT_RERANK_MODEL)
    parser.add_argument("--rerank-top-k", type=int, default=60)
    parser.add_argument("--rerank-batch-size", type=int, default=8)
    parser.add_argument("--rerank-max-length", type=int, default=1536)
    parser.add_argument("--judge-model", default=PHASE_F_DEFAULT_JUDGE_MODEL)
    parser.add_argument("--no-openai-judge", action="store_true")
    parser.add_argument("--judge-candidate-limit", type=int, default=12)
    parser.add_argument("--judge-max-per-doc", type=int, default=2)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    phase_a_args = Namespace(
        input_mode=args.input_mode,
        pipeline_version=args.pipeline_version,
        force_rebuild=bool(args.force_rebuild_phase_a),
        runs_root="",
        suite_manifest=args.suite_manifest,
        chapter_index=int(args.chapter_index),
        doc_limit=args.doc_limit,
        include_doc_id=list(args.include_doc_id or []),
        exclude_doc_id=list(args.exclude_doc_id or []),
        chapter_title=str(args.chapter_title or ""),
        chapter_description=str(args.chapter_description or ""),
        pdf=list(args.pdf or []),
        pdf_dir=str(args.pdf_dir or ""),
        pdf_glob=str(args.pdf_glob or "*.pdf"),
        pdf_recursive=bool(args.pdf_recursive),
        max_pdfs=int(args.max_pdfs),
    )
    phase_a_result = run_phase_a(phase_a_args)
    run_ctx = phase_a_result["run_ctx"]
    pdf_manifest = phase_a_result["manifest_rows"]

    from phase_b_lab import PhaseBOptions, run_phase_b
    from phase_c_lab import PhaseCOptions, run_phase_c
    from phase_d_lab import PhaseDOptions, run_phase_d
    from phase_e_lab import PhaseEOptions, run_phase_e

    if bool(args.force_rebuild_phase_b) or not phase_summary_exists(run_ctx, "phase_b"):
        phase_b_logger = setup_run_logger(run_ctx)
        phase_b_options = PhaseBOptions(
            force_rebuild=bool(args.force_rebuild_phase_b),
            doc_limit=args.doc_limit,
            include_doc_ids=list(args.include_doc_id or []),
            exclude_doc_ids=list(args.exclude_doc_id or []),
            min_page_words=20,
            min_doc_chars=200,
            try_docling=True,
            docling_page_limit=400,
            docling_max_file_size_bytes=50 * 1024 * 1024,
            docling_do_ocr=False,
            docling_do_table_structure=False,
            docling_document_timeout_sec=180,
            docling_num_threads=4,
            docling_enable_chunking=True,
            docling_chunk_size=20,
            docling_chunk_max_pages=400,
            docling_chunk_num_threads=1,
            try_grobid=True,
            grobid_page_limit=400,
            grobid_base_url=str(args.grobid_base_url or "").strip(),
            grobid_process_path="/api/processFulltextDocument",
            grobid_timeout_sec=120,
            grobid_consolidate_header=0,
            grobid_consolidate_citations=0,
            grobid_include_raw_citations=0,
        )
        with stage_timer(run_ctx, "phase_b"):
            phase_b_result = run_phase_b(run_ctx, pdf_manifest, phase_b_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_b_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_b", {}).update(phase_b_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_c) or not phase_summary_exists(run_ctx, "phase_c"):
        phase_c_logger = setup_run_logger(run_ctx)
        phase_c_options = PhaseCOptions(
            force_rebuild=bool(args.force_rebuild_phase_c),
            min_section_words=20,
            passage_target_words=180,
            passage_max_words=260,
            passage_min_words=70,
            use_heuristic_recovery=True,
            repair_titles_from_anchor_blocks=True,
            heuristic_recovery_disable_when_strong_outline=True,
            heuristic_recovery_disable_when_docling_rich=True,
            enable_numbered_gap_fill_when_docling_noisy=True,
            docling_noise_ratio_for_gap_fill=0.22,
            docling_numbered_gap_fill_max_words=18,
            docling_supplement_strong_outline_numbering_depth=2,
        )
        with stage_timer(run_ctx, "phase_c"):
            phase_c_result = run_phase_c(run_ctx, phase_c_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_c_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_c", {}).update(phase_c_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_d) or not phase_summary_exists(run_ctx, "phase_d"):
        phase_d_logger = setup_run_logger(run_ctx)
        phase_d_options = PhaseDOptions(
            force_rebuild=bool(args.force_rebuild_phase_d),
            use_openai_planner=not bool(args.no_openai_planner),
            allow_heuristic_fallback=True,
            openai_model=str(args.planner_model or "gpt-5-mini").strip() or "gpt-5-mini",
            reasoning_effort=str(args.planner_reasoning_effort or "low").strip() or "low",
            max_completion_tokens=1400,
            temperature=0.0,
            must_term_limit=8,
            should_term_limit=14,
            exclusion_limit=8,
            subpoint_limit=6,
            drift_risk_limit=8,
            source_anchor_limit=24,
            subpoint_source_anchor_limit=3,
            max_summary_chars=480,
            max_subpoint_summary_chars=320,
            min_anchor_token_overlap=0.67,
        )
        with stage_timer(run_ctx, "phase_d"):
            phase_d_result = run_phase_d(
                run_ctx,
                chapter_title=phase_a_result["config"].chapter_title,
                chapter_spec_text=phase_a_result["config"].chapter_spec_text,
                options=phase_d_options,
                stable_hash_fn=stable_hash,
                log_event_fn=log_event,
                run_logger=phase_d_logger,
            )
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_d", {}).update(phase_d_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    if bool(args.force_rebuild_phase_e) or not phase_summary_exists(run_ctx, "phase_e"):
        phase_e_logger = setup_run_logger(run_ctx)
        phase_e_options = PhaseEOptions(
            force_rebuild=bool(args.force_rebuild_phase_e),
            candidate_limit_per_lane=80,
            fused_candidate_limit=120,
            per_view_limit_multiplier=2,
            rrf_k=60,
            lexical_k1=1.2,
            lexical_b=0.75,
            use_openai_dense=not bool(args.no_openai_dense),
            allow_lexical_only_fallback=True,
            openai_embedding_model=str(args.embed_model or "text-embedding-3-small").strip() or "text-embedding-3-small",
            openai_timeout_sec=300,
            dense_batch_size=64,
            dense_section_max_chars=4200,
            dense_passage_max_chars=2400,
            dense_query_max_chars=1600,
            dense_dimensions=None,
            dense_min_similarity=0.05,
            top_candidate_preview_count=20,
            selection_strategy="xquad",
            use_supported_subpoint_selection=True,
            abstain_when_no_supported_subpoints=True,
            generic_evidence_bonus=0.01,
            generic_anchor_score_threshold=1.0,
            subpoint_min_supported_candidates=1,
            subpoint_max_preview_rows=10,
            diversity_lambda=0.45,
        )
        with stage_timer(run_ctx, "phase_e"):
            phase_e_result = run_phase_e(run_ctx, options=phase_e_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_e_logger)
            metrics = load_metrics(run_ctx)
            metrics.setdefault("stages", {}).setdefault("phase_e", {}).update(phase_e_result["metrics_update"])
            save_metrics(run_ctx, metrics)

    phase_f_logger = setup_run_logger(run_ctx)
    phase_f_options = PhaseFOptions(
        force_rebuild=bool(args.force_rebuild_phase_f),
        rerank_top_k=int(args.rerank_top_k),
        inject_doc_top_candidates=True,
        cross_encoder_model=str(args.rerank_model or PHASE_F_DEFAULT_RERANK_MODEL).strip() or PHASE_F_DEFAULT_RERANK_MODEL,
        cross_encoder_batch_size=int(args.rerank_batch_size),
        cross_encoder_max_length=int(args.rerank_max_length),
        cross_encoder_subpoint_limit=2,
        section_excerpt_max_chars=2200,
        supporting_passage_count=3,
        passage_excerpt_max_chars=520,
        use_openai_judge=not bool(args.no_openai_judge),
        judge_model=str(args.judge_model or PHASE_F_DEFAULT_JUDGE_MODEL).strip() or PHASE_F_DEFAULT_JUDGE_MODEL,
        judge_reasoning_effort="low",
        judge_candidate_limit=int(args.judge_candidate_limit),
        judge_max_per_doc=int(args.judge_max_per_doc),
        judge_max_output_tokens=550,
        top_candidate_preview_count=20,
    )
    with stage_timer(run_ctx, "phase_f"):
        phase_f_result = run_phase_f(run_ctx, options=phase_f_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_f_logger)
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_f", {}).update(phase_f_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))
    print_section("Phase F Lab - Rerank Capabilities")
    print_kv({
        "torch_available": phase_f_capabilities().get("torch_available"),
        "transformers_available": phase_f_capabilities().get("transformers_available"),
        "cuda_available": phase_f_capabilities().get("cuda_available"),
        "openai_available": phase_f_capabilities().get("openai_available"),
        "openai_api_key_present": phase_f_capabilities().get("openai_api_key_present"),
        "cross_encoder_model": phase_f_options.cross_encoder_model,
        "judge_model": phase_f_options.judge_model if phase_f_options.use_openai_judge else "disabled",
        "cache_hit": phase_f_result.get("cache_hit"),
    })
    print_section("Phase F Lab - What Happened")
    print_kv({
        "run_id": run_ctx.run_id,
        "candidate_packs_jsonl": rel(phase_f_result["candidate_packs_path"]),
        "cross_encoder_jsonl": rel(phase_f_result["cross_encoder_path"]),
        "llm_judge_jsonl": rel(phase_f_result["llm_judge_path"]),
        "rerank_results_jsonl": rel(phase_f_result["rerank_results_path"]),
        "phase_f_summary_json": rel(phase_f_result["summary_path"]),
        "phase_f_assessment_json": rel(phase_f_result["assessment_path"]),
        "candidate_packs": len(phase_f_result["candidate_pack_rows"]),
        "rerank_results": len(phase_f_result["rerank_result_rows"]),
        "judged_rows": len([row for row in phase_f_result["llm_judge_rows"] if row.get("judge_score") is not None]),
        "phase_status": phase_f_result["assessment"].get("status"),
    })
    print_section("Phase F Lab - Cross-Encoder Runtime")
    print_kv(phase_f_result.get("cross_encoder_runtime") or {})
    print_section("Phase F Lab - Judge Runtime")
    print_kv(phase_f_result.get("judge_runtime") or {})
    print_section("Phase F Lab - Per-PDF Tops")
    print_table((phase_f_result.get("summary") or {}).get("per_doc_top_rows") or [], columns=["doc_id", "doc_title", "top_title", "rerank_rank", "rerank_score", "cross_encoder_score", "judge_score"], max_rows=25, max_col_width=54)
    print_section("Phase F Lab - Rerank Preview")
    print_table((phase_f_result.get("summary") or {}).get("preview_rows") or [], columns=["rerank_rank", "doc_id", "title", "section_type", "pages", "rerank_score", "cross_encoder_score", "judge_score", "best_subpoint_id", "supporting_passages", "generic_title"], max_rows=20, max_col_width=54)
    print_section("Phase F Lab - QC")
    print_table(phase_f_result["qc_rows"], columns=["check", "status", "value", "expected", "why", "fix"], max_rows=20, max_col_width=48)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
