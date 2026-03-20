#!/usr/bin/env python3
from __future__ import annotations

import argparse
import math
import re
import time
from argparse import Namespace
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from itertools import combinations

from phase_d_lab import *  # noqa: F401,F403

# Phase E.0 - High-recall candidate generation helpers


try:
    import numpy as np
except Exception as e:
    np = None
    PHASE_E_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_E_IMPORT_ERROR = None

PhaseEOpenAI = globals().get("OpenAI")
if PhaseEOpenAI is None:
    try:
        from openai import OpenAI as PhaseEOpenAI
    except Exception:
        PhaseEOpenAI = None

PHASE_E_API_KEY = (globals().get("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
PHASE_E_EMBED_PRICING = {"text-embedding-3-small": 0.02, "text-embedding-3-large": 0.13, "text-embedding-ada-002": 0.10}
PHASE_E_PRICING_URL = "https://platform.openai.com/docs/pricing"
PHASE_E_PRICING_DATE = "2026-03-15"
PHASE_E_VIEW_WEIGHTS = {
    "section_title_lexical": {"title_lexical": 1.0, "must_terms_lexical": 0.9, "should_terms_lexical": 0.92, "bridge_lexical": 0.95, "subpoint": 0.8, "subpoint_lexical": 1.0, "summary_semantic": 0.5, "bridge_semantic": 0.55, "support_context_semantic": 0.62, "broad_fallback": 0.55},
    "section_body_lexical": {"title_lexical": 0.75, "must_terms_lexical": 1.0, "should_terms_lexical": 0.95, "bridge_lexical": 1.05, "subpoint": 0.9, "subpoint_lexical": 1.05, "summary_semantic": 0.7, "bridge_semantic": 0.8, "support_context_semantic": 0.82, "broad_fallback": 0.75},
    "section_dense": {"title_lexical": 0.8, "must_terms_lexical": 0.8, "should_terms_lexical": 0.85, "bridge_lexical": 0.8, "subpoint": 0.95, "subpoint_lexical": 0.88, "summary_semantic": 1.0, "bridge_semantic": 1.0, "support_context_semantic": 1.04, "broad_fallback": 0.85},
    "passage_lexical": {"title_lexical": 0.7, "must_terms_lexical": 1.0, "should_terms_lexical": 0.96, "bridge_lexical": 1.0, "subpoint": 0.9, "subpoint_lexical": 1.0, "summary_semantic": 0.65, "bridge_semantic": 0.75, "support_context_semantic": 0.8, "broad_fallback": 0.8},
    "passage_dense": {"title_lexical": 0.8, "must_terms_lexical": 0.8, "should_terms_lexical": 0.84, "bridge_lexical": 0.8, "subpoint": 0.95, "subpoint_lexical": 0.86, "summary_semantic": 1.0, "bridge_semantic": 1.0, "support_context_semantic": 1.02, "broad_fallback": 0.85},
}
PHASE_E_FUSION_WEIGHTS = {"section_title_lexical": 1.0, "section_body_lexical": 1.05, "section_dense": 1.15, "passage_lexical": 0.95, "passage_dense": 1.05}
PHASE_E_SECTION_LANES = {"section_title_lexical", "section_body_lexical", "section_dense"}
PHASE_E_PASSAGE_LANES = {"passage_lexical", "passage_dense"}
PHASE_E_STOPWORDS = {"a","an","and","are","as","at","be","bei","by","das","dem","den","der","des","die","ein","eine","einer","eines","for","from","im","in","into","is","ist","mit","of","on","or","the","to","und","von","with","zu"}
PHASE_E_DOC_RESCUE_VIEW_WEIGHTS = {"title_lexical": 1.0, "must_terms_lexical": 1.0, "should_terms_lexical": 1.05, "bridge_lexical": 1.15, "subpoint": 0.95, "subpoint_lexical": 1.0, "summary_semantic": 0.55, "bridge_semantic": 0.8, "support_context_semantic": 0.9, "broad_fallback": 0.8}

@dataclass
class PhaseEOptions:
    force_rebuild: bool = False
    candidate_limit_per_lane: int = 80
    fused_candidate_limit: int = 120
    per_view_limit_multiplier: int = 2
    rrf_k: int = 60
    lexical_k1: float = 1.2
    lexical_b: float = 0.75
    use_openai_dense: bool = True
    allow_lexical_only_fallback: bool = True
    openai_embedding_model: str = "text-embedding-3-small"
    openai_timeout_sec: int = 300
    dense_batch_size: int = 64
    dense_section_max_chars: int = 4200
    dense_passage_max_chars: int = 2400
    dense_query_max_chars: int = 1600
    dense_dimensions: Optional[int] = None
    dense_min_similarity: float = 0.05
    top_candidate_preview_count: int = 20
    selection_strategy: str = "xquad"
    use_supported_subpoint_selection: bool = True
    abstain_when_no_supported_subpoints: bool = True
    generic_evidence_bonus: float = 0.01
    generic_anchor_score_threshold: float = 1.0
    single_support_penalty: float = 0.008
    zero_support_penalty: float = 0.025
    generic_low_support_penalty: float = 0.01
    subpoint_min_supported_candidates: int = 1
    subpoint_max_preview_rows: int = 10
    diversity_lambda: float = 0.45
    enable_doc_title_rescue: bool = False
    doc_rescue_doc_limit: int = 8
    doc_rescue_sections_per_doc: int = 4
    doc_rescue_score_scale: float = 0.08
    def normalized(self) -> "PhaseEOptions":
        return PhaseEOptions(
            force_rebuild=bool(self.force_rebuild), candidate_limit_per_lane=max(10,int(self.candidate_limit_per_lane)), fused_candidate_limit=max(20,int(self.fused_candidate_limit)), per_view_limit_multiplier=max(1,int(self.per_view_limit_multiplier)), rrf_k=max(1,int(self.rrf_k)), lexical_k1=max(0.1,float(self.lexical_k1)), lexical_b=min(1.0,max(0.0,float(self.lexical_b))), use_openai_dense=bool(self.use_openai_dense), allow_lexical_only_fallback=bool(self.allow_lexical_only_fallback), openai_embedding_model=str(self.openai_embedding_model or "text-embedding-3-small").strip() or "text-embedding-3-small", openai_timeout_sec=max(30,int(self.openai_timeout_sec)), dense_batch_size=max(1,int(self.dense_batch_size)), dense_section_max_chars=max(400,int(self.dense_section_max_chars)), dense_passage_max_chars=max(300,int(self.dense_passage_max_chars)), dense_query_max_chars=max(120,int(self.dense_query_max_chars)), dense_dimensions=None if self.dense_dimensions in {None,0,"",False} else int(self.dense_dimensions), dense_min_similarity=float(self.dense_min_similarity), top_candidate_preview_count=max(5,int(self.top_candidate_preview_count)), selection_strategy=(str(self.selection_strategy or "xquad").strip().lower() or "xquad"), use_supported_subpoint_selection=bool(self.use_supported_subpoint_selection), abstain_when_no_supported_subpoints=bool(self.abstain_when_no_supported_subpoints), generic_evidence_bonus=max(0.0,float(self.generic_evidence_bonus)), generic_anchor_score_threshold=max(0.0,float(self.generic_anchor_score_threshold)), single_support_penalty=max(0.0,float(self.single_support_penalty)), zero_support_penalty=max(0.0,float(self.zero_support_penalty)), generic_low_support_penalty=max(0.0,float(self.generic_low_support_penalty)), subpoint_min_supported_candidates=max(1,int(self.subpoint_min_supported_candidates)), subpoint_max_preview_rows=max(3,int(self.subpoint_max_preview_rows)), diversity_lambda=max(0.0,float(self.diversity_lambda)), enable_doc_title_rescue=bool(self.enable_doc_title_rescue), doc_rescue_doc_limit=max(1,int(self.doc_rescue_doc_limit)), doc_rescue_sections_per_doc=max(1,int(self.doc_rescue_sections_per_doc)), doc_rescue_score_scale=max(0.0,float(self.doc_rescue_score_scale))
        )

def phase_e_capabilities() -> Dict[str, Any]:
    return {"python_executable": sys.executable, "python_version": sys.version.split()[0], "numpy_available": bool(np is not None), "openai_available": bool(PhaseEOpenAI is not None), "openai_api_key_present": bool(PHASE_E_API_KEY), "import_error": PHASE_E_IMPORT_ERROR}

def tok(text: Any) -> List[str]:
    s = ascii_fold(clean_text(text)).lower()
    return [t for t in re.findall(r"[a-z0-9]+", s) if len(t) >= 2 and t not in PHASE_E_STOPWORDS]

class BM25:
    def __init__(self, docs: List[List[str]], k1: float, b: float):
        self.k1, self.b, self.n = float(k1), float(b), len(docs)
        self.post, self.lens, df = {}, [], Counter()
        for i, toks in enumerate(docs):
            tf = Counter(toks); self.lens.append(sum(tf.values()))
            for term, freq in tf.items():
                self.post.setdefault(term, {})[i] = int(freq)
                df[term] += 1
        self.avg = sum(self.lens) / max(1, len(self.lens))
        self.idf = {t: math.log(1.0 + ((self.n - f + 0.5) / (f + 0.5))) for t, f in df.items()}
    def score(self, q: List[str]):
        s = np.zeros(self.n, dtype=np.float32)
        for term, qf in Counter(q).items():
            post, idf = self.post.get(term) or {}, float(self.idf.get(term) or 0.0)
            if not post or idf <= 0.0:
                continue
            for i, freq in post.items():
                denom = freq + self.k1 * (1.0 - self.b + self.b * (self.lens[i] / max(1e-9, self.avg)))
                s[i] += float(qf) * idf * ((freq * (self.k1 + 1.0)) / max(1e-9, denom))
        return s

def phase_e_views(obj: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for k in ["title_lexical", "summary_semantic", "must_terms_lexical", "should_terms_lexical", "bridge_lexical", "bridge_semantic", "support_context_semantic", "broad_fallback"]:
        v = dict(obj.get(k) or {})
        if clean_text(v.get("query_text")):
            rows.append(v)
    for v in obj.get("subpoint_views") or []:
        if clean_text((v or {}).get("query_text")):
            rows.append(dict(v))
    for v in obj.get("subpoint_lexical_views") or []:
        if clean_text((v or {}).get("query_text")):
            rows.append(dict(v))
    return rows

def prior(section_type: str, flags: List[str], pref: List[str], penalized: List[str]) -> float:
    mult = 1.0
    flag_set = set(flags or [])
    if section_type in set(pref or []):
        mult *= 1.08
    if section_type in set(penalized or []):
        mult *= 0.25
    if "tiny_section" in flag_set:
        mult *= 0.65
    if "synthetic" in flag_set:
        mult *= 0.85
    return mult

def trunc(text: Any, n: int) -> str:
    s = clean_text(text)
    return s if len(s) <= int(n) else (s[: max(1, int(n) - 1)] + "…")

def embed_price(model: str, input_tokens: Optional[int]) -> Dict[str, Any]:
    picked = next((m for m in sorted(PHASE_E_EMBED_PRICING, key=len, reverse=True) if model == m or str(model).startswith(m + "-")), None)
    out = {"pricing_found": bool(picked), "pricing_model": picked, "model_name": model or None, "pricing_source_url": PHASE_E_PRICING_URL, "pricing_verified_date": PHASE_E_PRICING_DATE, "estimated_cost_usd": None, "cost_components_usd": None}
    if picked and isinstance(input_tokens, int):
        cost = (float(input_tokens) / 1_000_000.0) * float(PHASE_E_EMBED_PRICING[picked])
        out["estimated_cost_usd"] = round(cost, 10)
        out["cost_components_usd"] = {"input_cost_usd": round(cost, 10)}
    return out

def embed_texts(texts: List[str], model: str, batch_size: int, timeout_sec: int, dimensions: Optional[int]):
    client = PhaseEOpenAI(api_key=PHASE_E_API_KEY, timeout=timeout_sec)
    vecs, prompt_tokens, total_tokens, used_model = [], 0, 0, model
    for start in range(0, len(texts), max(1, int(batch_size))):
        batch = texts[start : start + max(1, int(batch_size))]
        kw = {"model": model, "input": batch}
        if dimensions is not None:
            kw["dimensions"] = int(dimensions)
        resp = None
        last_error = None
        for attempt in range(5):
            try:
                resp = client.embeddings.create(**kw)
                break
            except Exception as exc:
                last_error = exc
                status_code = getattr(exc, "status_code", None)
                if status_code != 429 and "RateLimitError" not in type(exc).__name__:
                    raise
                time.sleep(min(8.0, 1.0 * (2 ** attempt)))
        if resp is None:
            raise last_error
        used_model = str(getattr(resp, "model", None) or model)
        usage = getattr(resp, "usage", None)
        prompt_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
        total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        for item in sorted(list(getattr(resp, "data", None) or []), key=lambda x: int(getattr(x, "index", 0))):
            vecs.append(list(getattr(item, "embedding")))
    mat = np.asarray(vecs, dtype=np.float32) if vecs else np.zeros((0, 0), dtype=np.float32)
    norms = np.linalg.norm(mat, axis=1, keepdims=True) if getattr(mat, "size", 0) else np.zeros((0, 0), dtype=np.float32)
    if getattr(mat, "size", 0):
        norms[norms == 0] = 1.0
        mat = mat / norms
    usage = {"input_tokens": prompt_tokens or None, "total_tokens": total_tokens or prompt_tokens or None, "output_tokens": 0}
    return mat, usage, {**embed_price(used_model, usage.get("input_tokens")), "usage": usage}


def resolve_phase_e_dense_task_concurrency(*, task_count: int) -> int:
    if int(task_count) <= 1:
        return 1
    cpu_count = available_cpu_count()
    if cpu_count <= 2:
        auto = 1
    elif cpu_count <= 4:
        auto = 2
    else:
        auto = 3
    return max(1, min(int(task_count), auto))

def build_inputs(sections: List[Dict[str, Any]], passages: List[Dict[str, Any]], opt: PhaseEOptions):
    sec_lookup = {str(r.get("section_id")): r for r in sections if str(r.get("section_id") or "")}
    pass_lookup = {str(r.get("passage_id")): r for r in passages if str(r.get("passage_id") or "")}
    out = {"section_title_lexical": {"items": [], "texts": []}, "section_body_lexical": {"items": [], "texts": []}, "section_dense": {"items": [], "texts": []}, "passage_lexical": {"items": [], "texts": []}, "passage_dense": {"items": [], "texts": []}}
    for r in sections:
        sid = str(r.get("section_id") or "")
        if not sid:
            continue
        if not bool(r.get("retrieval_eligible", True)):
            continue
        meta = {"item_id": sid, "unit_type": "section", "doc_id": str(r.get("doc_id") or ""), "section_id": sid, "passage_id": None, "title": clean_text(r.get("title") or "Untitled Section"), "section_type": str(r.get("section_type") or "body_other"), "page_start": r.get("page_start"), "page_end": r.get("page_end"), "quality_flags": list(r.get("quality_flags") or [])}
        title_text = clean_text(" / ".join([clean_text(x) for x in (r.get("title_path") or []) if clean_text(x)]) or r.get("title") or "")
        body_text = clean_text(r.get("contextualized_text") or r.get("text") or "")
        if title_text:
            out["section_title_lexical"]["items"].append(dict(meta))
            out["section_title_lexical"]["texts"].append(title_text)
        if body_text:
            out["section_body_lexical"]["items"].append(dict(meta))
            out["section_body_lexical"]["texts"].append(body_text)
            out["section_dense"]["items"].append(dict(meta))
            out["section_dense"]["texts"].append(trunc(body_text, opt.dense_section_max_chars))
    for r in passages:
        pid, sid = str(r.get("passage_id") or ""), str(r.get("section_id") or "")
        if not pid or sid not in sec_lookup:
            continue
        txt = clean_text(r.get("contextualized_text") or r.get("text") or "")
        if not txt:
            continue
        sec = sec_lookup[sid]
        if not bool(sec.get("retrieval_eligible", True)):
            continue
        meta = {"item_id": pid, "unit_type": "passage", "doc_id": str(r.get("doc_id") or ""), "section_id": sid, "passage_id": pid, "title": clean_text(sec.get("title") or "Untitled Section"), "section_type": str(sec.get("section_type") or "body_other"), "page_start": (r.get("page_span") or {}).get("page_start"), "page_end": (r.get("page_span") or {}).get("page_end"), "quality_flags": list(sec.get("quality_flags") or [])}
        out["passage_lexical"]["items"].append(dict(meta))
        out["passage_lexical"]["texts"].append(txt)
        out["passage_dense"]["items"].append(dict(meta))
        out["passage_dense"]["texts"].append(trunc(txt, opt.dense_passage_max_chars))
    return sec_lookup, pass_lookup, out
def finalize_lane(rows_map: Dict[str, Dict[str, Any]], lane: str, limit: int) -> List[Dict[str, Any]]:
    rows = []
    for row in rows_map.values():
        vm = sorted(row.get("view_matches") or [], key=lambda m: (float(m.get("score") or 0.0), -int(m.get("rank_in_view") or 0)), reverse=True)
        if not vm:
            continue
        vals = [float(m.get("score") or 0.0) for m in vm]
        lane_score = vals[0] + (0.2 * sum(vals[1:3]) if len(vals) > 1 else 0.0)
        row.update({"lane": lane, "lane_score": round(lane_score, 8), "best_view_id": vm[0].get("view_id"), "best_view_kind": vm[0].get("view_kind"), "matched_view_ids": [m.get("view_id") for m in vm], "matched_view_count": len(vm), "view_matches": vm})
        rows.append(row)
    rows.sort(key=lambda r: (float(r.get("lane_score") or 0.0), r.get("unit_type") == "section", -len(r.get("view_matches") or []), str(r.get("doc_id") or ""), str(r.get("title") or "")), reverse=True)
    rows = rows[: int(limit)]
    for i, row in enumerate(rows, 1):
        row["lane_rank"] = i
    return rows

def score_text_lane(lane: str, items: List[Dict[str, Any]], texts: List[str], views: List[Dict[str, Any]], plan: Dict[str, Any], opt: PhaseEOptions) -> List[Dict[str, Any]]:
    if not items or not texts:
        return []
    idx = BM25([tok(t) for t in texts], opt.lexical_k1, opt.lexical_b)
    agg = {}
    top_k = min(len(items), max(40, int(opt.candidate_limit_per_lane) * int(opt.per_view_limit_multiplier)))
    for view in views:
        kind = str(view.get("kind") or "")
        weight = float((PHASE_E_VIEW_WEIGHTS.get(lane) or {}).get(kind, 0.0))
        q = tok(view.get("query_text"))
        if weight <= 0.0 or not q:
            continue
        scores = idx.score(q)
        for rank_in_view, ix in enumerate(np.argsort(-scores)[:top_k], 1):
            raw = float(scores[ix])
            if raw <= 0.0:
                break
            item = items[int(ix)]
            mult = prior(str(item.get("section_type") or "body_other"), list(item.get("quality_flags") or []), list(view.get("preferred_section_types") or []), list(plan.get("penalized_section_types") or []))
            score = raw * weight * mult
            if score <= 0.0:
                continue
            row = agg.setdefault(str(item.get("item_id")), {**item, "view_matches": []})
            row["view_matches"].append({"view_id": view.get("view_id"), "view_kind": kind, "score": round(score, 8), "raw_score": round(raw, 8), "query_weight": weight, "prior_multiplier": round(mult, 6), "rank_in_view": rank_in_view})
    return finalize_lane(agg, lane, opt.candidate_limit_per_lane)

def score_dense_lane(lane: str, items: List[Dict[str, Any]], mat, query_mats: Dict[str, Any], views: List[Dict[str, Any]], plan: Dict[str, Any], opt: PhaseEOptions) -> List[Dict[str, Any]]:
    if not items or mat is None or getattr(mat, "size", 0) == 0:
        return []
    agg = {}
    top_k = min(len(items), max(40, int(opt.candidate_limit_per_lane) * int(opt.per_view_limit_multiplier)))
    for view in views:
        kind = str(view.get("kind") or "")
        weight = float((PHASE_E_VIEW_WEIGHTS.get(lane) or {}).get(kind, 0.0))
        qmat = query_mats.get(str(view.get("view_id")))
        if weight <= 0.0 or qmat is None or getattr(qmat, "size", 0) == 0:
            continue
        sims = np.matmul(mat, qmat[0])
        for rank_in_view, ix in enumerate(np.argsort(-sims)[:top_k], 1):
            raw = float(sims[ix])
            if raw < float(opt.dense_min_similarity):
                break
            item = items[int(ix)]
            mult = prior(str(item.get("section_type") or "body_other"), list(item.get("quality_flags") or []), list(view.get("preferred_section_types") or []), list(plan.get("penalized_section_types") or []))
            score = raw * weight * mult
            if score <= 0.0:
                continue
            row = agg.setdefault(str(item.get("item_id")), {**item, "view_matches": []})
            row["view_matches"].append({"view_id": view.get("view_id"), "view_kind": kind, "score": round(score, 8), "raw_score": round(raw, 8), "query_weight": weight, "prior_multiplier": round(mult, 6), "rank_in_view": rank_in_view})
    return finalize_lane(agg, lane, opt.candidate_limit_per_lane)

PHASE_E_LEXICAL_LANES = {"section_title_lexical", "section_body_lexical", "passage_lexical"}
PHASE_E_GENERIC_SECTION_TITLES = {"introduction", "conclusion", "discussion", "results", "research design", "methods", "method", "abstract", "background"}
PHASE_E_ANCHOR_UNIGRAM_ALLOWLIST = {
    "autonomy", "bias", "biases", "confidence", "debiasing", "ethics", "ethical", "explainability",
    "heuristic", "heuristics", "manipulation", "manipulative", "nudging", "perceived", "ratings",
    "reviews", "risk", "signals", "transparency", "trust", "uncertainty"
}
PHASE_E_ANCHOR_UNIGRAM_BLOCKLIST = {
    "abschnitte", "analysis", "approaches", "background", "commerce", "complex", "context", "decision",
    "entscheidungspsychologie", "empirische", "evidence", "factors", "kauf", "kaufe", "kaufen", "kaufen",
    "kognitive", "literature", "methods", "modellen", "modelle", "online", "produkte", "product", "products",
    "results", "section", "sections", "study", "systems", "theoretische", "theory", "users", "webshop", "wirkung"
}

def is_informative_anchor_unigram(token: Any) -> bool:
    value = ascii_fold(clean_text(token)).lower().strip()
    if not value or value in PHASE_E_STOPWORDS or value in PHASE_E_ANCHOR_UNIGRAM_BLOCKLIST:
        return False
    if value in PHASE_E_ANCHOR_UNIGRAM_ALLOWLIST:
        return True
    return len(value) >= 10

def is_informative_anchor_unigram(token: Any) -> bool:
    value = ascii_fold(clean_text(token)).lower().strip()
    if not value or value in PHASE_E_STOPWORDS or value in PHASE_E_ANCHOR_UNIGRAM_BLOCKLIST:
        return False
    if value in PHASE_E_ANCHOR_UNIGRAM_ALLOWLIST:
        return True
    return len(value) >= 10

def subpoint_id_from_view_id(view_id: Any) -> Optional[str]:
    value = str(view_id or "").strip()
    if value.startswith("subpoint::"):
        return value.split("::", 1)[1].strip() or None
    if value.startswith("subpoint_lexical::"):
        return value.split("::", 1)[1].strip() or None
    return None

def is_generic_section_title(title: Any) -> bool:
    low = clean_text(title).lower().strip()
    if low in PHASE_E_GENERIC_SECTION_TITLES:
        return True
    return bool(re.fullmatch(r"\d+\.?\s+(introduction|discussion|conclusion|results|methods?)", low))

def contains_token_phrase(hay_tokens: List[str], needle_tokens: List[str]) -> bool:
    if not needle_tokens:
        return False
    if len(needle_tokens) == 1:
        return needle_tokens[0] in set(hay_tokens)
    if len(needle_tokens) > len(hay_tokens):
        return False
    for start in range(len(hay_tokens) - len(needle_tokens) + 1):
        if hay_tokens[start : start + len(needle_tokens)] == needle_tokens:
            return True
    return False

def dedupe_anchor_entries(entries: List[Dict[str, Any]], *, limit: int = 18) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for entry in entries:
        toks = tuple(entry.get("tokens") or [])
        if not toks:
            continue
        key = (entry.get("kind"), toks)
        if key in seen:
            continue
        seen.add(key)
        out.append({"phrase": entry.get("phrase") or " ".join(toks), "tokens": list(toks), "kind": entry.get("kind") or "phrase"})
        if len(out) >= int(limit):
            break
    return out

def extract_anchor_entries(text: Any, *, allow_unigrams: bool = False, max_entries: int = 18) -> List[Dict[str, Any]]:
    raw = clean_text(text)
    if not raw:
        return []
    entries = []
    segments = [seg.strip() for seg in re.split(r"[|;:,()/]", raw) if clean_text(seg)]
    for seg in segments:
        tokens = tok(seg)
        if not tokens:
            continue
        if allow_unigrams:
            for token in tokens:
                if is_informative_anchor_unigram(token):
                    entries.append({"phrase": token, "tokens": [token], "kind": "unigram"})
        if 2 <= len(tokens) <= 6:
            entries.append({"phrase": " ".join(tokens), "tokens": list(tokens), "kind": "segment"})
        for n in (4, 3, 2):
            if len(tokens) < n:
                continue
            for start in range(len(tokens) - n + 1):
                gram = tokens[start : start + n]
                entries.append({"phrase": " ".join(gram), "tokens": list(gram), "kind": "phrase"})
    return dedupe_anchor_entries(entries, limit=max_entries)

def build_subpoint_specs(query_plan: Dict[str, Any], retrieval_views: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    rows = []
    subpoint_view_map = {}
    method_cue_tokens = {"measurement", "measure", "messung", "messinstrumenten", "skalen", "skala", "experimental", "experimentellen", "design", "designs", "evaluation", "evaluationsmethoden", "instrument", "instruments", "methoden"}
    if isinstance(retrieval_views, dict):
        for raw_view in list(retrieval_views.get("subpoint_views") or []):
            view = dict(raw_view or {})
            subpoint_id = subpoint_id_from_view_id(view.get("view_id"))
            if subpoint_id:
                subpoint_view_map[subpoint_id] = view
    for raw in list(query_plan.get("subpoints") or []):
        sp = dict(raw or {})
        subpoint_id = str(sp.get("subpoint_id") or sp.get("id") or "").strip()
        if not subpoint_id:
            continue
        query_view = dict(subpoint_view_map.get(subpoint_id) or {})
        explicit_terms = []
        for term in list(sp.get("must_terms") or []) + list(sp.get("should_terms") or []):
            if clean_text(term):
                explicit_terms.append(clean_text(term))
        anchor_entries = []
        for term in explicit_terms:
            tt = tok(term)
            if tt:
                anchor_entries.append({"phrase": term, "tokens": tt, "kind": "explicit"})
        anchor_entries.extend(extract_anchor_entries(sp.get("label") or "", allow_unigrams=True, max_entries=16))
        anchor_entries.extend(extract_anchor_entries(sp.get("summary") or "", allow_unigrams=True, max_entries=24))
        if clean_text(query_view.get("query_text")):
            anchor_entries.extend(extract_anchor_entries(query_view.get("query_text") or "", allow_unigrams=True, max_entries=32))
        query_blob = " ".join([clean_text(sp.get("label") or ""), clean_text(sp.get("summary") or ""), clean_text(query_view.get("query_text") or "")])
        rows.append({
            "subpoint_id": subpoint_id,
            "view_id": f"subpoint::{subpoint_id}",
            "label": clean_text(sp.get("label") or subpoint_id),
            "summary": clean_text(sp.get("summary") or ""),
            "query_text": clean_text(query_view.get("query_text") or ""),
            "preferred_section_types": list(sp.get("preferred_section_types") or []),
            "must_terms": list(sp.get("must_terms") or []),
            "should_terms": list(sp.get("should_terms") or []),
            "requires_preferred_section_type_for_broad_support": bool(set(tok(query_blob)) & method_cue_tokens),
            "anchor_entries": dedupe_anchor_entries(anchor_entries, limit=40),
        })
    return rows

def compute_subpoint_anchor_support(title_tokens: List[str], body_tokens: List[str], spec: Dict[str, Any]) -> Dict[str, Any]:
    explicit_hits, phrase_hits, title_unigram_hits, body_unigram_hits = [], [], [], []
    broad_phrase_norm = {"perceived risk", "decision confidence"}
    broad_unigram_norm = {"confidence", "perceived", "risk", "trust", "uncertainty"}
    title_set, body_set = set(title_tokens), set(body_tokens)
    for entry in list(spec.get("anchor_entries") or []):
        phrase_tokens = list(entry.get("tokens") or [])
        if not phrase_tokens:
            continue
        kind = str(entry.get("kind") or "phrase")
        phrase = str(entry.get("phrase") or " ".join(phrase_tokens))
        if len(phrase_tokens) == 1:
            token = phrase_tokens[0]
            if token in title_set:
                if kind == "explicit":
                    explicit_hits.append(phrase)
                else:
                    title_unigram_hits.append(token)
            elif token in body_set:
                if kind == "explicit":
                    explicit_hits.append(phrase)
                else:
                    body_unigram_hits.append(token)
            continue
        if contains_token_phrase(title_tokens, phrase_tokens) or contains_token_phrase(body_tokens, phrase_tokens):
            if kind == "explicit":
                explicit_hits.append(phrase)
            else:
                phrase_hits.append(phrase)
    explicit_hits = sorted(set(explicit_hits))
    phrase_hits = sorted(set(phrase_hits))
    title_unigram_hits = sorted(set(title_unigram_hits))
    body_unigram_hits = sorted(set(body_unigram_hits))
    unigram_hits = sorted(set(title_unigram_hits + body_unigram_hits))
    broad_phrase_hits = [value for value in phrase_hits if ascii_fold(clean_text(value)).lower() in broad_phrase_norm]
    non_broad_phrase_hits = [value for value in phrase_hits if ascii_fold(clean_text(value)).lower() not in broad_phrase_norm]
    non_broad_unigram_hits = [value for value in unigram_hits if value not in broad_unigram_norm]
    anchor_score = (3.0 * len(explicit_hits)) + (1.6 * len(phrase_hits)) + (1.15 * len(title_unigram_hits)) + (0.55 * len(body_unigram_hits))
    return {
        "explicit_hits": explicit_hits,
        "phrase_hits": phrase_hits,
        "broad_phrase_hits": broad_phrase_hits,
        "non_broad_phrase_hits": non_broad_phrase_hits,
        "title_unigram_hits": title_unigram_hits,
        "body_unigram_hits": body_unigram_hits,
        "unigram_hits": unigram_hits,
        "non_broad_unigram_hits": non_broad_unigram_hits,
        "anchor_score": round(anchor_score, 6),
    }

def annotate_subpoint_support(prelim_rows: List[Dict[str, Any]], sec_lookup: Dict[str, Any], subpoint_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    for cand in prelim_rows:
        sec = sec_lookup.get(str(cand.get("section_id") or "")) or {}
        title_tokens = tok(clean_text(sec.get("title") or ""))
        body_tokens = tok(clean_text(sec.get("contextualized_text") or sec.get("text") or ""))
        sub_map = {}
        trusted_ids = []
        anchor_total = 0.0
        for spec in subpoint_specs:
            subpoint_id = str(spec.get("subpoint_id") or "")
            lane_scores = dict(((cand.get("subpoint_lane_scores") or {}).get(subpoint_id) or {}))
            lexical_lanes = sorted([lane for lane in lane_scores if lane in PHASE_E_LEXICAL_LANES])
            dense_lanes = sorted([lane for lane in lane_scores if lane not in PHASE_E_LEXICAL_LANES])
            anchor = compute_subpoint_anchor_support(title_tokens, body_tokens, spec)
            raw_view_score = round(sum(float(v or 0.0) for v in lane_scores.values()), 8)
            title_hit_count = len(anchor.get("title_unigram_hits") or [])
            body_hit_count = len(anchor.get("body_unigram_hits") or [])
            unigram_hit_count = len(anchor.get("unigram_hits") or [])
            support_reason = None
            if anchor["explicit_hits"]:
                trusted = True
                support_reason = "explicit_anchor"
            elif anchor["phrase_hits"]:
                trusted = True
                support_reason = "phrase_anchor"
            elif unigram_hit_count >= 2 and len(lexical_lanes) >= 1 and raw_view_score >= 6.0:
                trusted = True
                support_reason = "multi_unigram_plus_lexical"
            elif title_hit_count >= 1 and len(lexical_lanes) >= 1 and raw_view_score >= 10.0:
                trusted = True
                support_reason = "title_anchor_plus_lexical"
            elif body_hit_count >= 2 and len(lexical_lanes) >= 1 and raw_view_score >= 6.0:
                trusted = True
                support_reason = "body_anchor_plus_lexical"
            else:
                trusted = False
            preferred_type_match = str(cand.get("section_type") or "") in set(spec.get("preferred_section_types") or [])
            if trusted and bool(spec.get("requires_preferred_section_type_for_broad_support")) and not preferred_type_match:
                if not anchor.get("non_broad_phrase_hits") and not anchor.get("non_broad_unigram_hits") and not anchor.get("explicit_hits"):
                    trusted = False
                    support_reason = None
            raw_total = round(raw_view_score + float(anchor["anchor_score"]), 8)
            sub_map[subpoint_id] = {
                "label": spec.get("label"),
                "view_id": spec.get("view_id"),
                "lane_scores": {k: round(float(v), 8) for k, v in lane_scores.items()},
                "lexical_lanes": lexical_lanes,
                "lexical_lane_count": len(lexical_lanes),
                "dense_lanes": dense_lanes,
                "dense_lane_count": len(dense_lanes),
                "raw_view_score": raw_view_score,
                "preferred_type_match": preferred_type_match,
                **anchor,
                "support_reason": support_reason,
                "trusted": trusted,
                "raw_total_score": raw_total,
            }
            if trusted:
                trusted_ids.append(subpoint_id)
                anchor_total += float(anchor["anchor_score"])
        cand["generic_title"] = is_generic_section_title(cand.get("title"))
        cand["subpoint_support"] = sub_map
        cand["trusted_subpoint_ids"] = sorted(set(trusted_ids))
        cand["trusted_subpoint_count"] = len(set(trusted_ids))
        cand["anchor_support_total"] = round(anchor_total, 6)
        cand["word_count"] = max(1, int(sec.get("word_count") or len(tok(sec.get("text") or "")) or 1))
    return prelim_rows

def build_subpoint_support_inventory(prelim_rows: List[Dict[str, Any]], query_plan: Dict[str, Any], subpoint_specs: List[Dict[str, Any]], opt: PhaseEOptions) -> Dict[str, Any]:
    penalized_types = set(query_plan.get("penalized_section_types") or [])
    rows, supported_ids, unsupported_ids = [], [], []
    for spec in subpoint_specs:
        subpoint_id = str(spec.get("subpoint_id") or "")
        trusted = []
        surfaced = []
        for cand in prelim_rows:
            support = dict((cand.get("subpoint_support") or {}).get(subpoint_id) or {})
            if float(support.get("raw_total_score") or 0.0) <= 0.0:
                continue
            surfaced.append(cand)
            if bool(support.get("trusted")) and str(cand.get("section_type") or "") not in penalized_types:
                trusted.append(cand)
        trusted.sort(key=lambda row: (float(((row.get("subpoint_support") or {}).get(subpoint_id) or {}).get("raw_total_score") or 0.0), float(row.get("fused_score") or 0.0), int(row.get("supporting_passage_count") or 0)), reverse=True)
        surfaced.sort(key=lambda row: (float(((row.get("subpoint_support") or {}).get(subpoint_id) or {}).get("raw_total_score") or 0.0), float(row.get("fused_score") or 0.0)), reverse=True)
        trusted_docs = sorted({str(row.get("doc_id") or "") for row in trusted if str(row.get("doc_id") or "")})
        supported = len(trusted) >= int(opt.subpoint_min_supported_candidates)
        if supported:
            supported_ids.append(subpoint_id)
        else:
            unsupported_ids.append(subpoint_id)
        top_pool = trusted if trusted else surfaced
        rows.append({
            "subpoint_id": subpoint_id,
            "label": spec.get("label"),
            "supported": supported,
            "trusted_candidate_count": len(trusted),
            "trusted_doc_count": len(trusted_docs),
            "trusted_doc_ids": trusted_docs,
            "top_candidate_title": (top_pool[0].get("title") if top_pool else None),
            "top_candidate_doc_id": (top_pool[0].get("doc_id") if top_pool else None),
            "top_candidate_score": ((((top_pool[0].get("subpoint_support") or {}).get(subpoint_id) or {}).get("raw_total_score")) if top_pool else None),
            "anchor_examples": (((((top_pool[0].get("subpoint_support") or {}).get(subpoint_id) or {}).get("phrase_hits") or [])[:3] or (((top_pool[0].get("subpoint_support") or {}).get(subpoint_id) or {}).get("title_unigram_hits") or [])[:3] or (((top_pool[0].get("subpoint_support") or {}).get(subpoint_id) or {}).get("body_unigram_hits") or [])[:3]) if top_pool else []),
        })
    rows.sort(key=lambda row: (not bool(row.get("supported")), -(int(row.get("trusted_candidate_count") or 0)), str(row.get("subpoint_id") or "")))
    return {"rows": rows, "supported_subpoint_ids": supported_ids, "unsupported_subpoint_ids": unsupported_ids}

def candidate_generic_bonus(cand: Dict[str, Any], opt: PhaseEOptions) -> float:
    if not bool(cand.get("generic_title")):
        return 0.0
    if int(cand.get("supporting_passage_count") or 0) < 1:
        return 0.0
    if float(cand.get("anchor_support_total") or 0.0) < float(opt.generic_anchor_score_threshold):
        return 0.0
    return float(opt.generic_evidence_bonus)


def candidate_evidence_adjustment(cand: Dict[str, Any], opt: PhaseEOptions) -> float:
    support_count = int(cand.get("supporting_passage_count") or 0)
    generic_title = bool(cand.get("generic_title"))
    penalty = 0.0
    if support_count <= 0:
        penalty += float(opt.zero_support_penalty)
    elif support_count == 1:
        penalty += float(opt.single_support_penalty)
    if generic_title and support_count <= 1:
        penalty += float(opt.generic_low_support_penalty)
    return -penalty

def select_phase_e_candidates(prelim_rows: List[Dict[str, Any]], active_subpoint_ids: List[str], opt: PhaseEOptions) -> List[Dict[str, Any]]:
    rows = []
    max_scores = {subpoint_id: max([float(((cand.get("subpoint_support") or {}).get(subpoint_id) or {}).get("raw_total_score") or 0.0) for cand in prelim_rows] + [0.0]) for subpoint_id in list(active_subpoint_ids or [])}
    for cand in prelim_rows:
        row = json.loads(json.dumps(cand))
        base = float(row.get("fused_score") or 0.0) + candidate_generic_bonus(row, opt) + candidate_evidence_adjustment(row, opt)
        row["selection_base_score"] = round(base, 8)
        for subpoint_id in list(active_subpoint_ids or []):
            support = dict((row.get("subpoint_support") or {}).get(subpoint_id) or {})
            denom = float(max_scores.get(subpoint_id) or 0.0)
            support["normalized_score"] = round((float(support.get("raw_total_score") or 0.0) / denom), 8) if denom > 0.0 else 0.0
            row.setdefault("subpoint_support", {})[subpoint_id] = support
        rows.append(row)
    if str(opt.selection_strategy or "xquad").lower() != "xquad" or not active_subpoint_ids:
        rows.sort(key=lambda row: (float(row.get("selection_base_score") or 0.0), int(row.get("trusted_subpoint_count") or 0), int(row.get("supporting_passage_count") or 0), str(row.get("doc_id") or ""), str(row.get("title") or "")), reverse=True)
        return rows
    selected, covered = [], {subpoint_id: 0.0 for subpoint_id in active_subpoint_ids}
    remaining = list(rows)
    while remaining and len(selected) < int(opt.fused_candidate_limit):
        best_ix, best_value = None, None
        for ix, row in enumerate(remaining):
            novelty = 0.0
            for subpoint_id in active_subpoint_ids:
                support = dict((row.get("subpoint_support") or {}).get(subpoint_id) or {})
                novelty += float(support.get("normalized_score") or 0.0) * (1.0 / (1.0 + float(covered.get(subpoint_id) or 0.0)))
            value = float(row.get("selection_base_score") or 0.0) + (float(opt.diversity_lambda) * novelty)
            if best_value is None or value > best_value:
                best_ix, best_value = ix, value
        chosen = remaining.pop(int(best_ix))
        chosen["selection_score"] = round(float(best_value or 0.0), 8)
        selected.append(chosen)
        for subpoint_id in active_subpoint_ids:
            covered[subpoint_id] = float(covered.get(subpoint_id) or 0.0) + float((((chosen.get("subpoint_support") or {}).get(subpoint_id) or {}).get("normalized_score") or 0.0))
    if len(selected) < int(opt.fused_candidate_limit):
        seen = {str(row.get("section_id") or "") for row in selected}
        for row in rows:
            if str(row.get("section_id") or "") in seen:
                continue
            selected.append(row)
            if len(selected) >= int(opt.fused_candidate_limit):
                break
    return selected


def looks_like_low_signal_doc_title(title: Any) -> bool:
    cleaned = clean_text(title)
    lowered = ascii_fold(cleaned).lower()
    if not cleaned:
        return True
    if "proof" in lowered:
        return True
    if len(tok(cleaned)) < 2:
        return True
    return False


def build_doc_rescue_items(documents: List[Dict[str, Any]], sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    sections_by_doc = {}
    for row in sections:
        doc_id = str(row.get("doc_id") or "")
        if doc_id:
            sections_by_doc.setdefault(doc_id, []).append(row)
    for rows in sections_by_doc.values():
        rows.sort(key=lambda row: (int(row.get("page_start") or 0), int(row.get("level") or 0), str(row.get("title") or "")))

    items = []
    for row in documents:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        raw_title = clean_text(row.get("title") or "")
        heading_preview = []
        snippet_preview = []
        fallback_title = None
        for sec in sections_by_doc.get(doc_id, []):
            if not bool(sec.get("retrieval_eligible", True)):
                continue
            sec_title = clean_text(sec.get("title") or "")
            if sec_title and sec_title not in heading_preview and len(heading_preview) < 8:
                heading_preview.append(sec_title)
            if fallback_title is None and sec_title and count_words(sec_title) >= 4 and not is_generic_section_title(sec_title):
                fallback_title = sec_title
            sec_type = str(sec.get("section_type") or "body_other")
            sec_text = clean_text(sec.get("text") or sec.get("contextualized_text") or "")
            if sec_type in {"abstract", "introduction", "discussion", "conclusion", "results", "body_other"} and count_words(sec_text) >= 18 and len(snippet_preview) < 2:
                snippet = truncate_words(sec_text, max_words=26)
                if snippet and snippet not in snippet_preview:
                    snippet_preview.append(snippet)
        doc_title = fallback_title if looks_like_low_signal_doc_title(raw_title) and fallback_title else raw_title
        doc_summary = build_compact_query_text(
            [
                doc_title,
                ("headings: " + " | ".join(heading_preview[:6])) if heading_preview else "",
                ("preview: " + " || ".join(snippet_preview[:2])) if snippet_preview else "",
            ],
            separator=" || ",
            max_words=150,
            max_chars=1200,
        )
        if not clean_text(doc_summary):
            continue
        items.append(
            {
                "doc_id": doc_id,
                "doc_title": doc_title,
                "doc_summary": doc_summary,
                "heading_preview": heading_preview[:8],
                "snippet_preview": snippet_preview[:2],
            }
        )
    return items


def score_doc_title_rescue_rows(documents: List[Dict[str, Any]], sections: List[Dict[str, Any]], views: List[Dict[str, Any]], opt: PhaseEOptions) -> List[Dict[str, Any]]:
    items = build_doc_rescue_items(documents, sections)
    if not items:
        return []
    idx = BM25([tok(item["doc_summary"]) for item in items], opt.lexical_k1, opt.lexical_b)
    agg = {}
    top_k = min(len(items), max(int(opt.doc_rescue_doc_limit) * 3, 12))
    for view in views:
        kind = str(view.get("kind") or "")
        weight = float(PHASE_E_DOC_RESCUE_VIEW_WEIGHTS.get(kind, 0.0))
        q = tok(view.get("query_text"))
        if weight <= 0.0 or not q:
            continue
        scores = idx.score(q)
        for rank_in_view, ix in enumerate(np.argsort(-scores)[:top_k], 1):
            raw = float(scores[ix])
            if raw <= 0.0:
                break
            item = items[int(ix)]
            row = agg.setdefault(
                item["doc_id"],
                {
                    "doc_id": item["doc_id"],
                    "doc_title": item["doc_title"],
                    "doc_summary": item.get("doc_summary"),
                    "heading_preview": list(item.get("heading_preview") or []),
                    "snippet_preview": list(item.get("snippet_preview") or []),
                    "view_matches": [],
                },
            )
            row["view_matches"].append(
                {
                    "view_id": view.get("view_id"),
                    "view_kind": kind,
                    "score": round(raw * weight, 8),
                    "raw_score": round(raw, 8),
                    "query_weight": weight,
                    "rank_in_view": rank_in_view,
                }
            )
    rows = []
    for row in agg.values():
        matches = sorted(list(row.get("view_matches") or []), key=lambda item: float(item.get("score") or 0.0), reverse=True)
        if not matches:
            continue
        values = [float(item.get("score") or 0.0) for item in matches]
        doc_score = values[0] + (0.2 * sum(values[1:3]) if len(values) > 1 else 0.0)
        rows.append(
            {
                **row,
                "view_matches": matches,
                "doc_score": round(doc_score, 8),
                "best_view_id": matches[0].get("view_id"),
                "best_view_kind": matches[0].get("view_kind"),
            }
        )
    rows.sort(key=lambda row: (float(row.get("doc_score") or 0.0), len(row.get("view_matches") or []), str(row.get("doc_title") or "")), reverse=True)
    for idx, row in enumerate(rows, 1):
        row["doc_rank"] = idx
    return rows


def select_doc_rescue_sections(
    doc_id: str,
    sections: List[Dict[str, Any]],
    prelim_map: Dict[str, Dict[str, Any]],
    query_plan: Dict[str, Any],
    opt: PhaseEOptions,
) -> List[Dict[str, Any]]:
    preferred_types = set(query_plan.get("preferred_section_types") or [])
    penalized_types = set(query_plan.get("penalized_section_types") or [])
    rescue_terms = unique_clean_terms(
        list(query_plan.get("bridge_terms") or []) + list(query_plan.get("retrieval_should_terms") or []) + list(query_plan.get("must_terms") or []),
        limit=18,
        max_words=5,
        max_chars=80,
    )
    candidates = []
    for sec in sections:
        if str(sec.get("doc_id") or "") != doc_id or not bool(sec.get("retrieval_eligible", True)):
            continue
        section_type = str(sec.get("section_type") or "body_other")
        if section_type in penalized_types:
            continue
        section_id = str(sec.get("section_id") or "")
        prelim_row = prelim_map.get(section_id) or {}
        title = clean_text(sec.get("title") or "")
        body = clean_text(sec.get("contextualized_text") or sec.get("text") or "")
        title_hits = sum(1 for term in rescue_terms if text_contains_term(title, term))
        body_hits = sum(1 for term in rescue_terms if text_contains_term(body, term))
        prelim_score = float(prelim_row.get("fused_score") or 0.0)
        matched_lane_count = len(prelim_row.get("component_lane_scores") or {})
        score = (3.5 * prelim_score) + (2.0 * title_hits) + (0.65 * body_hits)
        if prelim_row:
            score += 0.65 + (0.08 * matched_lane_count)
        if section_type in preferred_types:
            score += 0.5
        if section_type in {"abstract", "introduction", "discussion", "conclusion", "results", "body_other"}:
            score += 0.15
        if int(sec.get("page_start") or 0) <= 3:
            score += 0.15
        if is_generic_section_title(title) and title_hits <= 0 and body_hits <= 0 and prelim_score <= 0.0:
            score -= 0.25
        candidates.append(
            {
                "section_id": section_id,
                "title": title,
                "section_type": section_type,
                "page_start": int(sec.get("page_start") or 0),
                "page_end": int(sec.get("page_end") or 0),
                "prelim_score": round(prelim_score, 8),
                "rescue_score": round(score, 8),
            }
        )
    candidates.sort(key=lambda row: (float(row.get("rescue_score") or 0.0), float(row.get("prelim_score") or 0.0), not is_generic_section_title(row.get("title")), -int(row.get("page_start") or 0), str(row.get("title") or "")), reverse=True)
    if candidates and float(candidates[0].get("rescue_score") or 0.0) <= 0.0:
        candidates.sort(key=lambda row: (str(row.get("section_type") or "") in preferred_types, -int(row.get("page_start") or 0)), reverse=True)
    return candidates[: int(opt.doc_rescue_sections_per_doc)]


def inject_doc_title_rescue_candidates(
    prelim_rows: List[Dict[str, Any]],
    documents: List[Dict[str, Any]],
    sections: List[Dict[str, Any]],
    passages: List[Dict[str, Any]],
    views: List[Dict[str, Any]],
    query_plan: Dict[str, Any],
    opt: PhaseEOptions,
) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    if not bool(opt.enable_doc_title_rescue):
        return prelim_rows, []
    doc_scores = score_doc_title_rescue_rows(documents, sections, views, opt)
    if not doc_scores:
        return prelim_rows, []
    prelim_map = {str(row.get("section_id") or ""): row for row in prelim_rows if str(row.get("section_id") or "")}
    sections_by_doc = {}
    for row in sections:
        doc_id = str(row.get("doc_id") or "")
        if doc_id:
            sections_by_doc.setdefault(doc_id, []).append(row)
    passages_by_section = {}
    for row in passages:
        sid = str(row.get("section_id") or "")
        if sid:
            passages_by_section.setdefault(sid, []).append(row)
    for rows in passages_by_section.values():
        rows.sort(key=lambda row: (int(row.get("page_start") or 0), int(row.get("passage_index") or 0)))

    doc_existing_best = {}
    for row in prelim_rows:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        doc_existing_best[doc_id] = max(float(row.get("fused_score") or 0.0), float(doc_existing_best.get(doc_id) or 0.0))
    doc_scores = sorted(
        doc_scores,
        key=lambda row: (
            float(row.get("doc_score") or 0.0) - (0.35 * float(doc_existing_best.get(str(row.get("doc_id") or ""), 0.0) or 0.0)),
            float(row.get("doc_score") or 0.0),
            len(row.get("view_matches") or []),
        ),
        reverse=True,
    )

    injected_rows = []
    for doc_row in doc_scores[: int(opt.doc_rescue_doc_limit)]:
        doc_id = str(doc_row.get("doc_id") or "")
        ranked_sections = select_doc_rescue_sections(doc_id, sections_by_doc.get(doc_id, []), prelim_map, query_plan, opt)
        for section_row in ranked_sections:
            section_id = str(section_row.get("section_id") or "")
            section = next((row for row in sections_by_doc.get(doc_id, []) if str(row.get("section_id") or "") == section_id), None)
            if not section:
                continue
            rescue_score = round(float(doc_row.get("doc_score") or 0.0) * max(float(section_row.get("rescue_score") or 0.0), 0.1) * float(opt.doc_rescue_score_scale), 8)
            if rescue_score <= 0.0:
                continue
            row = prelim_map.get(section_id)
            if row is None:
                support_passages = [
                    {
                        "passage_id": str(p.get("passage_id") or ""),
                        "page_start": (p.get("page_span") or {}).get("page_start"),
                        "page_end": (p.get("page_span") or {}).get("page_end"),
                        "best_lane_score": rescue_score,
                        "lanes": ["doc_title_rescue"],
                    }
                    for p in passages_by_section.get(section_id, [])[:3]
                    if str(p.get("passage_id") or "")
                ]
                row = {
                    "doc_id": doc_id,
                    "section_id": section_id,
                    "title": clean_text(section.get("title") or "Untitled Section"),
                    "section_type": str(section.get("section_type") or "body_other"),
                    "page_start": section.get("page_start"),
                    "page_end": section.get("page_end"),
                    "quality_flags": list(section.get("quality_flags") or []),
                    "parser_sources": list(section.get("parser_sources") or []),
                    "fused_score": rescue_score,
                    "component_lane_scores": {"doc_title_rescue": rescue_score},
                    "component_lane_ranks": {"doc_title_rescue": int(doc_row.get("doc_rank") or 0)},
                    "best_views_by_lane": {"doc_title_rescue": doc_row.get("best_view_id")},
                    "supporting_passages": support_passages,
                    "supporting_passage_ids": [item.get("passage_id") for item in support_passages],
                    "supporting_passage_count": len(support_passages),
                    "passage_only_support": False,
                    "subpoint_lane_scores": {},
                    "lane_count": 1,
                    "doc_title_rescue": True,
                }
                prelim_map[section_id] = row
                injected_rows.append({"doc_id": doc_id, "section_id": section_id, "title": row["title"], "rescue_score": rescue_score, "doc_score": doc_row.get("doc_score"), "doc_rank": doc_row.get("doc_rank")})
            else:
                row["fused_score"] = round(float(row.get("fused_score") or 0.0) + rescue_score, 8)
                row.setdefault("component_lane_scores", {})["doc_title_rescue"] = rescue_score
                row.setdefault("component_lane_ranks", {})["doc_title_rescue"] = int(doc_row.get("doc_rank") or 0)
                row.setdefault("best_views_by_lane", {})["doc_title_rescue"] = doc_row.get("best_view_id")
                row["lane_count"] = len(row.get("component_lane_ranks") or {})
                row["doc_title_rescue"] = True
                injected_rows.append({"doc_id": doc_id, "section_id": section_id, "title": row["title"], "rescue_score": rescue_score, "doc_score": doc_row.get("doc_score"), "doc_rank": doc_row.get("doc_rank"), "boosted_existing": True})
    return list(prelim_map.values()), injected_rows

def run_phase_e(run_ctx: Any, *, options: PhaseEOptions, stable_hash_fn=None, log_event_fn=None, run_logger=None) -> Dict[str, Any]:
    opt = options.normalized()
    retrieval_dir = ensure_dir(Path(run_ctx.artifacts.retrieval_dir))
    lanes_dir = ensure_dir(retrieval_dir / "lanes")
    fused_path = retrieval_dir / "fused_candidates.jsonl"
    config_path = retrieval_dir / "phase_e_config.json"
    runtime_path = retrieval_dir / "phase_e_runtime.json"
    summary_path = retrieval_dir / "phase_e_summary.json"
    assessment_path = retrieval_dir / "phase_e_assessment.json"
    dense_trace_path = retrieval_dir / "phase_e_dense_trace.json"
    subpoint_support_path = retrieval_dir / "phase_e_subpoint_support.json"
    doc_rescue_path = retrieval_dir / "phase_e_doc_rescue.json"

    write_json(runtime_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_e", "options": json_safe(asdict(opt)), "capabilities": phase_e_capabilities()})
    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_e", "options": json_safe(asdict(opt))})

    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    passages_path = Path(run_ctx.artifacts.normalized_dir) / "passages.jsonl"
    documents_path = Path(run_ctx.artifacts.normalized_dir) / "documents.jsonl"
    query_plan_path = Path(run_ctx.artifacts.query_plan_json)
    query_views_path = Path(run_ctx.artifacts.retrieval_dir) / "query_views.json"
    if not sections_path.exists() or not passages_path.exists() or not documents_path.exists():
        raise FileNotFoundError("Phase C outputs are required before Phase E can run.")
    if not query_plan_path.exists() or not query_views_path.exists():
        raise FileNotFoundError("Phase D outputs are required before Phase E can run.")

    documents = read_jsonl_rows(documents_path)
    sections = read_jsonl_rows(sections_path)
    passages = read_jsonl_rows(passages_path)
    query_plan = dict((read_json(query_plan_path).get("query_plan") or {}))
    retrieval_views = read_json(query_views_path)
    views = phase_e_views(retrieval_views)
    subpoint_specs = build_subpoint_specs(query_plan, retrieval_views)
    all_subpoint_ids = [str(spec.get("subpoint_id") or "") for spec in subpoint_specs if str(spec.get("subpoint_id") or "")]

    sec_lookup, pass_lookup, lane_inputs = build_inputs(sections, passages, opt)
    lane_rows = {lane: [] for lane in ["section_title_lexical", "section_body_lexical", "section_dense", "passage_lexical", "passage_dense"]}
    lane_paths = {lane: lanes_dir / f"{lane}.jsonl" for lane in lane_rows}
    dense_trace = {"dense_mode": "disabled"}

    lane_rows["section_title_lexical"] = score_text_lane("section_title_lexical", lane_inputs["section_title_lexical"]["items"], lane_inputs["section_title_lexical"]["texts"], views, query_plan, opt)
    lane_rows["section_body_lexical"] = score_text_lane("section_body_lexical", lane_inputs["section_body_lexical"]["items"], lane_inputs["section_body_lexical"]["texts"], views, query_plan, opt)
    lane_rows["passage_lexical"] = score_text_lane("passage_lexical", lane_inputs["passage_lexical"]["items"], lane_inputs["passage_lexical"]["texts"], views, query_plan, opt)

    if bool(opt.use_openai_dense) and PhaseEOpenAI is not None and PHASE_E_API_KEY and np is not None:
        q_texts = [trunc(v.get("query_text"), opt.dense_query_max_chars) for v in views]
        dense_jobs = [("queries", q_texts)]
        if lane_inputs["section_dense"]["texts"]:
            dense_jobs.append(("sections", list(lane_inputs["section_dense"]["texts"])))
        if lane_inputs["passage_dense"]["texts"]:
            dense_jobs.append(("passages", list(lane_inputs["passage_dense"]["texts"])))
        resolved_dense_task_concurrency = resolve_phase_e_dense_task_concurrency(task_count=len(dense_jobs))
        dense_results: Dict[str, Any] = {}

        def run_dense_job(job_name: str, texts: List[str]):
            mat, usage, cost = embed_texts(texts, opt.openai_embedding_model, opt.dense_batch_size, opt.openai_timeout_sec, opt.dense_dimensions)
            return job_name, mat, usage, cost

        if resolved_dense_task_concurrency <= 1:
            for job_name, texts in dense_jobs:
                _, mat, usage, cost = run_dense_job(job_name, texts)
                dense_results[job_name] = (mat, usage, cost)
        else:
            with ThreadPoolExecutor(max_workers=resolved_dense_task_concurrency) as executor:
                future_map = {
                    executor.submit(run_dense_job, job_name, texts): job_name
                    for job_name, texts in dense_jobs
                }
                for future in as_completed(future_map):
                    job_name, mat, usage, cost = future.result()
                    dense_results[job_name] = (mat, usage, cost)

        qmat, qusage, qcost = dense_results["queries"]
        query_mats = {str(v.get("view_id")): qmat[i : i + 1] for i, v in enumerate(views)}
        if "sections" in dense_results:
            smat, susage, _ = dense_results["sections"]
        else:
            smat, susage = np.zeros((0, 0), dtype=np.float32), {"input_tokens": None, "total_tokens": None, "output_tokens": 0}
        if "passages" in dense_results:
            pmat, pusage, _ = dense_results["passages"]
        else:
            pmat, pusage = np.zeros((0, 0), dtype=np.float32), {"input_tokens": None, "total_tokens": None, "output_tokens": 0}
        input_tokens = sum(v for v in [qusage.get("input_tokens"), susage.get("input_tokens"), pusage.get("input_tokens")] if isinstance(v, int)) or None
        total_tokens = sum(v for v in [qusage.get("total_tokens"), susage.get("total_tokens"), pusage.get("total_tokens")] if isinstance(v, int)) or None
        dense_trace = {
            "dense_mode": "openai",
            "model_used": qcost.get("model_name") or opt.openai_embedding_model,
            "usage": {"input_tokens": input_tokens, "total_tokens": total_tokens, "output_tokens": 0},
            "cost": {**embed_price(qcost.get("model_name") or opt.openai_embedding_model, input_tokens), "usage": {"input_tokens": input_tokens, "total_tokens": total_tokens, "output_tokens": 0}},
            "query_count": len(views),
            "section_count": len(lane_inputs["section_dense"]["items"]),
            "passage_count": len(lane_inputs["passage_dense"]["items"]),
            "resolved_task_concurrency": resolved_dense_task_concurrency,
            "cpu_count": available_cpu_count(),
        }
        lane_rows["section_dense"] = score_dense_lane("section_dense", lane_inputs["section_dense"]["items"], smat, query_mats, views, query_plan, opt)
        lane_rows["passage_dense"] = score_dense_lane("passage_dense", lane_inputs["passage_dense"]["items"], pmat, query_mats, views, query_plan, opt)
    elif bool(opt.use_openai_dense):
        dense_trace = {"dense_mode": "skipped_missing_openai", "errors": ["OpenAI embeddings unavailable or OPENAI_API_KEY missing."]}

    dense_usage = dict(dense_trace.get("usage") or {})
    dense_cost = dict(dense_trace.get("cost") or {})
    if dense_trace.get("dense_mode") == "openai" and (any(isinstance(dense_usage.get(key), int) and int(dense_usage.get(key)) > 0 for key in ["input_tokens", "total_tokens"]) or float(dense_cost.get("estimated_cost_usd") or 0.0) > 0.0):
        record_api_call(
            run_ctx,
            stage="phase_e",
            provider="openai",
            model=str(dense_trace.get("model_used") or opt.openai_embedding_model),
            input_tokens=int(dense_usage.get("input_tokens") or 0),
            cached_input_tokens=0,
            output_tokens=int(dense_usage.get("output_tokens") or 0),
            cost_usd=float(dense_cost.get("estimated_cost_usd") or 0.0),
            meta={
                "api_mode": "embeddings.create",
                "pricing_model": dense_cost.get("pricing_model"),
                "pricing_source_url": dense_cost.get("pricing_source_url"),
                "pricing_verified_date": dense_cost.get("pricing_verified_date"),
                "query_count": dense_trace.get("query_count"),
                "section_count": dense_trace.get("section_count"),
                "passage_count": dense_trace.get("passage_count"),
                "dense_dimensions": opt.dense_dimensions,
            },
        )

    for lane, rows in lane_rows.items():
        write_jsonl_rows(lane_paths[lane], rows)

    fused = {}
    for lane, rows in lane_rows.items():
        lane_weight = float(PHASE_E_FUSION_WEIGHTS.get(lane, 1.0))
        for row in rows:
            sid = str(row.get("section_id") or "")
            sec = sec_lookup.get(sid)
            if not sec:
                continue
            cand = fused.setdefault(
                sid,
                {
                    "doc_id": str(sec.get("doc_id") or ""),
                    "section_id": sid,
                    "title": clean_text(sec.get("title") or "Untitled Section"),
                    "section_type": str(sec.get("section_type") or "body_other"),
                    "page_start": sec.get("page_start"),
                    "page_end": sec.get("page_end"),
                    "quality_flags": list(sec.get("quality_flags") or []),
                    "parser_sources": list(sec.get("parser_sources") or []),
                    "fused_score": 0.0,
                    "component_lane_scores": {},
                    "component_lane_ranks": {},
                    "best_views_by_lane": {},
                    "supporting_passages": {},
                    "passage_only_support": True,
                    "subpoint_lane_scores": {},
                },
            )
            rk = int(row.get("lane_rank") or 0)
            if rk <= 0:
                continue
            cand["fused_score"] += lane_weight / (float(opt.rrf_k) + float(rk))
            cand["component_lane_scores"][lane] = float(row.get("lane_score") or 0.0)
            cand["component_lane_ranks"][lane] = rk
            cand["best_views_by_lane"][lane] = row.get("best_view_id")
            if lane in PHASE_E_SECTION_LANES:
                cand["passage_only_support"] = False
            for match in list(row.get("view_matches") or []):
                subpoint_id = subpoint_id_from_view_id(match.get("view_id"))
                if not subpoint_id:
                    continue
                lane_map = cand["subpoint_lane_scores"].setdefault(subpoint_id, {})
                lane_map[lane] = round(float(lane_map.get(lane) or 0.0) + float(match.get("score") or 0.0), 8)
            pid = str(row.get("passage_id") or "")
            if lane in PHASE_E_PASSAGE_LANES and pid and pid in pass_lookup:
                pr = pass_lookup[pid]
                cur = cand["supporting_passages"].setdefault(
                    pid,
                    {
                        "passage_id": pid,
                        "page_start": (pr.get("page_span") or {}).get("page_start"),
                        "page_end": (pr.get("page_span") or {}).get("page_end"),
                        "best_lane_score": 0.0,
                        "lanes": [],
                    },
                )
                cur["best_lane_score"] = max(float(cur.get("best_lane_score") or 0.0), float(row.get("lane_score") or 0.0))
                cur["lanes"] = sorted(set(list(cur.get("lanes") or []) + [lane]))

    prelim_rows = []
    for cand in fused.values():
        sup = sorted(
            list((cand.get("supporting_passages") or {}).values()),
            key=lambda x: (float(x.get("best_lane_score") or 0.0), len(x.get("lanes") or []), str(x.get("passage_id") or "")),
            reverse=True,
        )[:8]
        cand["supporting_passages"] = sup
        cand["supporting_passage_ids"] = [x.get("passage_id") for x in sup]
        cand["supporting_passage_count"] = len(sup)
        cand["lane_count"] = len(cand.get("component_lane_ranks") or {})
        cand["fused_score"] = round(float(cand.get("fused_score") or 0.0), 8)
        cand["subpoint_lane_scores"] = {
            str(subpoint_id): {str(lane): round(float(score), 8) for lane, score in dict(score_map or {}).items()}
            for subpoint_id, score_map in dict(cand.get("subpoint_lane_scores") or {}).items()
        }
        prelim_rows.append(cand)

    prelim_rows.sort(
        key=lambda r: (
            float(r.get("fused_score") or 0.0),
            not bool(r.get("passage_only_support")),
            int(r.get("supporting_passage_count") or 0),
            str(r.get("doc_id") or ""),
            str(r.get("title") or ""),
        ),
        reverse=True,
    )
    prelim_rows, doc_rescue_rows = inject_doc_title_rescue_candidates(prelim_rows, documents, sections, passages, views, query_plan, opt)
    prelim_rows.sort(
        key=lambda r: (
            float(r.get("fused_score") or 0.0),
            not bool(r.get("passage_only_support")),
            int(r.get("supporting_passage_count") or 0),
            str(r.get("doc_id") or ""),
            str(r.get("title") or ""),
        ),
        reverse=True,
    )
    prelim_rows = annotate_subpoint_support(prelim_rows, sec_lookup, subpoint_specs)
    support_inventory = build_subpoint_support_inventory(prelim_rows, query_plan, subpoint_specs, opt)
    supported_subpoint_ids = list(support_inventory.get("supported_subpoint_ids") or [])
    unsupported_subpoint_ids = list(support_inventory.get("unsupported_subpoint_ids") or [])

    if bool(opt.use_supported_subpoint_selection):
        active_subpoint_ids = list(supported_subpoint_ids)
        if not active_subpoint_ids and not bool(opt.abstain_when_no_supported_subpoints):
            active_subpoint_ids = list(all_subpoint_ids)
    else:
        active_subpoint_ids = list(all_subpoint_ids)

    abstained = bool(all_subpoint_ids and not active_subpoint_ids and bool(opt.abstain_when_no_supported_subpoints))
    if abstained:
        fused_rows = []
    else:
        fused_rows = select_phase_e_candidates(prelim_rows, active_subpoint_ids, opt)
        fused_rows = list(fused_rows[: int(opt.fused_candidate_limit)])

    for row in fused_rows:
        row["selection_score"] = round(float(row.get("selection_score") or row.get("selection_base_score") or row.get("fused_score") or 0.0), 8)
        row["trusted_subpoints"] = ", ".join(list(row.get("trusted_subpoint_ids") or []))
        row["active_subpoint_overlap"] = len([subpoint_id for subpoint_id in list(row.get("trusted_subpoint_ids") or []) if subpoint_id in set(active_subpoint_ids)])
    for i, row in enumerate(fused_rows, 1):
        row["fused_rank"] = i

    write_jsonl_rows(fused_path, fused_rows)

    support_rows = []
    support_lookup = {str(row.get("subpoint_id") or ""): row for row in list(support_inventory.get("rows") or [])}
    for subpoint_id in all_subpoint_ids:
        raw = dict(support_lookup.get(subpoint_id) or {})
        raw["active_for_selection"] = subpoint_id in set(active_subpoint_ids)
        support_rows.append(raw)

    write_json(
        doc_rescue_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_e",
            "enabled": bool(opt.enable_doc_title_rescue),
            "rows": doc_rescue_rows,
        },
    )
    write_json(
        subpoint_support_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_e",
            "selection_strategy": opt.selection_strategy,
            "use_supported_subpoint_selection": bool(opt.use_supported_subpoint_selection),
            "abstain_when_no_supported_subpoints": bool(opt.abstain_when_no_supported_subpoints),
            "supported_subpoint_ids": supported_subpoint_ids,
            "unsupported_subpoint_ids": unsupported_subpoint_ids,
            "active_subpoint_ids": active_subpoint_ids,
            "abstained": abstained,
            "rows": support_rows,
        },
    )

    lane_summaries = [
        {
            "lane": lane,
            "candidate_count": len(rows),
            "unique_docs": len({str(r.get("doc_id") or "") for r in rows if str(r.get("doc_id") or "")}),
            "top1_score": (rows[0].get("lane_score") if rows else None),
            "top1_doc_id": (rows[0].get("doc_id") if rows else None),
            "top1_view": (rows[0].get("best_view_id") if rows else None),
            "top1_title": (rows[0].get("title") if rows else None),
        }
        for lane, rows in lane_rows.items()
    ]

    overlap = []
    for left, right in combinations(sorted(lane_rows.keys()), 2):
        a = {str(r.get("section_id") or "") for r in lane_rows[left][: min(40, int(opt.candidate_limit_per_lane))] if str(r.get("section_id") or "")}
        b = {str(r.get("section_id") or "") for r in lane_rows[right][: min(40, int(opt.candidate_limit_per_lane))] if str(r.get("section_id") or "")}
        union = a | b
        inter = a & b
        overlap.append({"lane_left": left, "lane_right": right, "top_k": min(40, int(opt.candidate_limit_per_lane)), "overlap_count": len(inter), "jaccard": round(len(inter) / max(1, len(union)), 4)})

    top20 = fused_rows[:20]
    top20_pen = sum(1 for r in top20 if str(r.get("section_type") or "") in set(query_plan.get("penalized_section_types") or []))
    top20_docs = len({str(r.get("doc_id") or "") for r in top20 if str(r.get("doc_id") or "")})
    passage_only_count = sum(1 for r in fused_rows if bool(r.get("passage_only_support")))
    passage_only_ratio = round(passage_only_count / max(1, len(fused_rows)), 4) if fused_rows else 0.0

    warnings, failures = [], []
    for lane in ["section_title_lexical", "section_body_lexical", "passage_lexical"]:
        if len(lane_rows.get(lane) or []) < 1:
            failures.append(f"{lane} produced no candidates")
    if not abstained and not fused_rows:
        failures.append("fused candidate pool is empty")
    elif not abstained and len(fused_rows) < 10:
        warnings.append(f"fused candidate pool is small ({len(fused_rows)})")
    if bool(opt.use_openai_dense) and not (lane_rows.get("section_dense") and lane_rows.get("passage_dense")):
        warnings.append("one or more dense lanes were unavailable; lexical-only evidence carried the phase")
    if top20_pen > 2:
        warnings.append(f"penalized sections in top20 is high ({top20_pen})")
    if top20_docs < 2 and len(top20) >= 2:
        warnings.append(f"top20 unique docs is low ({top20_docs})")
    if fused_rows and passage_only_ratio > 0.6:
        warnings.append(f"passage-only candidate ratio is high ({passage_only_ratio})")
    if unsupported_subpoint_ids:
        warnings.append(f"{len(unsupported_subpoint_ids)} chapter subpoints are unsupported by trusted corpus evidence")
    if abstained:
        warnings.append("phase abstained because no trusted supported subpoints were detected in the corpus")

    qc_rows = [
        qc_row(check="fused_candidates", status="OK" if (len(fused_rows) >= 1 or abstained) else "FAIL", value=len(fused_rows), expected=">= 1 or abstained", why="Phase F needs a non-empty section candidate set unless the phase explicitly abstains.", fix="inspect lane outputs, subpoint support, and query views"),
        qc_row(check="section_title_lexical", status="OK" if len(lane_rows["section_title_lexical"]) >= 1 else "FAIL", value=len(lane_rows["section_title_lexical"]), expected=">= 1", why="Title lexical recall is a required retrieval lane.", fix="inspect title queries and title index text"),
        qc_row(check="section_body_lexical", status="OK" if len(lane_rows["section_body_lexical"]) >= 1 else "FAIL", value=len(lane_rows["section_body_lexical"]), expected=">= 1", why="Body lexical recall is a required retrieval lane.", fix="inspect must_terms and section contextualized text"),
        qc_row(check="passage_lexical", status="OK" if len(lane_rows["passage_lexical"]) >= 1 else "FAIL", value=len(lane_rows["passage_lexical"]), expected=">= 1", why="Passage lexical recall is a required retrieval lane.", fix="inspect passage contextualized text and query views"),
        qc_row(check="dense_lanes", status="OK" if (lane_rows["section_dense"] and lane_rows["passage_dense"]) or not bool(opt.use_openai_dense) else "WARN", value="ready" if (lane_rows["section_dense"] and lane_rows["passage_dense"]) else dense_trace.get("dense_mode"), expected="ready when OpenAI dense retrieval is enabled", why="Dense lanes improve cross-lingual and semantic recall.", fix="check OPENAI_API_KEY, embedding model, and dense trace"),
        qc_row(check="supported_subpoints", status="OK" if supported_subpoint_ids else ("WARN" if all_subpoint_ids else "NA"), value=len(supported_subpoint_ids), expected=">= 1 when corpus covers at least part of the chapter", why="Supported subpoints are the facets trusted enough to drive diversified selection.", fix="inspect phase_e_subpoint_support.json and anchor support"),
        qc_row(check="top20_penalized", status="OK" if top20_pen <= 2 else "WARN", value=top20_pen, expected="<= 2", why="Penalized sections should not dominate the fused top set.", fix="inspect noisy query views or section typing"),
        qc_row(check="passage_only_ratio", status="OK" if passage_only_ratio <= 0.6 else "WARN", value=passage_only_ratio, expected="<= 0.6", why="Most fused candidates should have direct section-lane support.", fix="inspect section lanes and fusion weights"),
    ]

    status = "failed" if failures else ("success_with_warnings" if warnings else "success")
    quality = "insufficient" if failures else ("acceptable_with_issues" if warnings else "high")
    assessment = {
        "status": status,
        "quality_band": quality,
        "can_continue_to_next_phase": not failures,
        "failures": failures,
        "warnings": warnings,
        "selection_strategy": opt.selection_strategy,
        "supported_subpoint_ids": supported_subpoint_ids,
        "unsupported_subpoint_ids": unsupported_subpoint_ids,
        "active_subpoint_ids": active_subpoint_ids,
        "abstained": abstained,
        "counts": {
            **{lane: len(rows) for lane, rows in lane_rows.items()},
            "fused_candidate_count": len(fused_rows),
            "top20_unique_docs": top20_docs,
            "top20_penalized": top20_pen,
            "passage_only_candidate_count": passage_only_count,
            "supported_subpoint_count": len(supported_subpoint_ids),
            "unsupported_subpoint_count": len(unsupported_subpoint_ids),
        },
        "passage_only_candidate_ratio": passage_only_ratio,
        "top20_section_type_counts": dict(Counter(str(r.get("section_type") or "body_other") for r in top20)),
        "qc_rows": qc_rows,
    }

    preview = [
        {
            "fused_rank": r.get("fused_rank"),
            "doc_id": r.get("doc_id"),
            "title": r.get("title"),
            "section_type": r.get("section_type"),
            "pages": f"{r.get('page_start')}-{r.get('page_end')}",
            "fused_score": r.get("fused_score"),
            "selection_score": r.get("selection_score"),
            "trusted_subpoints": r.get("trusted_subpoints"),
            "lane_hits": ", ".join(sorted((r.get("component_lane_ranks") or {}).keys())),
            "supporting_passages": r.get("supporting_passage_count"),
            "passage_only_support": r.get("passage_only_support"),
        }
        for r in fused_rows[: int(opt.top_candidate_preview_count)]
    ]

    write_json(dense_trace_path, dense_trace)
    summary = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_e",
        "options": json_safe(asdict(opt)),
        "dense_trace": dense_trace,
        "selection_strategy": opt.selection_strategy,
        "doc_title_rescue_enabled": bool(opt.enable_doc_title_rescue),
        "doc_title_rescue_count": len(doc_rescue_rows),
        "supported_subpoint_ids": supported_subpoint_ids,
        "unsupported_subpoint_ids": unsupported_subpoint_ids,
        "active_subpoint_ids": active_subpoint_ids,
        "abstained": abstained,
        "subpoint_support_path": rel_to_run(Path(run_ctx.run_dir), subpoint_support_path),
        "doc_rescue_path": rel_to_run(Path(run_ctx.run_dir), doc_rescue_path),
        "lane_artifacts": {lane: rel_to_run(Path(run_ctx.run_dir), path) for lane, path in lane_paths.items()},
        "lane_summaries": lane_summaries,
        "lane_overlap": overlap,
        "fused_candidates_path": rel_to_run(Path(run_ctx.run_dir), fused_path),
        "fused_candidate_count": len(fused_rows),
        "fused_preview": preview,
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": qc_rows,
    }

    metrics_update = {
        "status": status,
        "quality_band": quality,
        "dense_mode": dense_trace.get("dense_mode"),
        "selection_strategy": opt.selection_strategy,
        "supported_subpoint_count": len(supported_subpoint_ids),
        "unsupported_subpoint_count": len(unsupported_subpoint_ids),
        "supported_subpoint_ids": supported_subpoint_ids,
        "unsupported_subpoint_ids": unsupported_subpoint_ids,
        "active_subpoint_ids": active_subpoint_ids,
        "abstained": abstained,
        "fused_candidate_count": len(fused_rows),
        "top20_unique_docs": top20_docs,
        "passage_only_candidate_ratio": passage_only_ratio,
        "openai_embedding_input_tokens": (dense_trace.get("usage") or {}).get("input_tokens"),
        "openai_embedding_total_tokens": (dense_trace.get("usage") or {}).get("total_tokens"),
        "openai_embedding_estimated_cost_usd": (dense_trace.get("cost") or {}).get("estimated_cost_usd"),
        "openai_embedding_model": dense_trace.get("model_used"),
        "phase_e_summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
        "phase_e_assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
        "phase_e_subpoint_support_path": rel_to_run(Path(run_ctx.run_dir), subpoint_support_path),
        "phase_e_doc_rescue_path": rel_to_run(Path(run_ctx.run_dir), doc_rescue_path),
    }
    for lane, rows in lane_rows.items():
        metrics_update[f"lane_{lane}_count"] = len(rows or [])

    write_json(summary_path, {**summary, "metrics_update": metrics_update})
    write_json(
        assessment_path,
        {
            "generated_at_utc": utc_now_iso(),
            "run_id": run_ctx.run_id,
            "phase": "phase_e",
            "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
            "qc_rows": qc_rows,
            "dense_trace": dense_trace,
            "fused_candidates_path": rel_to_run(Path(run_ctx.run_dir), fused_path),
            "subpoint_support_path": rel_to_run(Path(run_ctx.run_dir), subpoint_support_path),
        },
    )

    if log_event_fn is not None:
        log_event_fn(
            run_ctx,
            stage="phase_e",
            event="phase_finished",
            status=status,
            dense_mode=dense_trace.get("dense_mode"),
            fused_candidate_count=len(fused_rows),
            supported_subpoint_count=len(supported_subpoint_ids),
            unsupported_subpoint_count=len(unsupported_subpoint_ids),
            abstained=abstained,
            openai_embedding_input_tokens=(dense_trace.get("usage") or {}).get("input_tokens"),
            openai_embedding_estimated_cost_usd=(dense_trace.get("cost") or {}).get("estimated_cost_usd"),
        )
    if run_logger is not None:
        run_logger.info(
            "Phase E finished | status=%s | fused_candidates=%s | supported_subpoints=%s | unsupported_subpoints=%s | abstained=%s | dense_mode=%s | embedding_input_tokens=%s | embedding_cost_usd=%s",
            status,
            len(fused_rows),
            len(supported_subpoint_ids),
            len(unsupported_subpoint_ids),
            abstained,
            dense_trace.get("dense_mode"),
            (dense_trace.get("usage") or {}).get("input_tokens"),
            (dense_trace.get("cost") or {}).get("estimated_cost_usd"),
        )

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_e")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "dense_trace_path": dense_trace_path,
        "subpoint_support_path": subpoint_support_path,
        "doc_rescue_path": doc_rescue_path,
        "fused_candidates_path": fused_path,
        "lane_paths": lane_paths,
        "dense_trace": dense_trace,
        "lane_rows_by_name": lane_rows,
        "lane_summary_rows": lane_summaries,
        "lane_overlap_rows": overlap,
        "supported_subpoint_ids": supported_subpoint_ids,
        "unsupported_subpoint_ids": unsupported_subpoint_ids,
        "active_subpoint_ids": active_subpoint_ids,
        "abstained": abstained,
        "doc_rescue_rows": doc_rescue_rows,
        "subpoint_support_rows": support_rows,
        "fused_candidate_rows": fused_rows,
        "fused_preview_rows": preview,
        "assessment": assessment,
        "qc_rows": qc_rows,
        "metrics_update": metrics_update,
    }



def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase E lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_e_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
    parser.add_argument("--force-rebuild-phase-e", action="store_true")
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

    phase_c_logger = setup_run_logger(run_ctx)
    phase_c_options = PhaseCOptions(
        force_rebuild=bool(args.force_rebuild_phase_c),
        doc_limit=args.doc_limit,
        include_doc_ids=list(args.include_doc_id or []),
        exclude_doc_ids=list(args.exclude_doc_id or []),
        prefer_outline=True,
        use_docling=True,
        use_grobid=True,
        use_heuristic_headings=True,
        use_heuristic_recovery=True,
        repair_titles_from_anchor_blocks=True,
        heuristic_heading_min_words=1,
        heuristic_heading_max_words=18,
        heuristic_heading_max_chars=160,
        repeated_heading_page_threshold=3,
        min_section_chars=120,
        min_section_words=20,
        min_section_coverage_pct_warn=70.0,
        long_doc_page_threshold=40,
        passage_target_words=180,
        passage_max_words=260,
        passage_min_words=70,
        synthesize_front_matter=True,
        synthesize_document_body=True,
        metadata_filter_enabled=True,
        micro_section_max_words=20,
        micro_section_max_title_words=3,
    )
    with stage_timer(run_ctx, "phase_c"):
        phase_c_result = run_phase_c(run_ctx, phase_c_options, stable_hash_fn=stable_hash, log_event_fn=log_event, run_logger=phase_c_logger)
        metrics = load_metrics(run_ctx)
        metrics.setdefault("stages", {}).setdefault("phase_c", {}).update(phase_c_result["metrics_update"])
        save_metrics(run_ctx, metrics)

    phase_d_logger = setup_run_logger(run_ctx)
    phase_d_options = PhaseDOptions(
        force_rebuild=bool(args.force_rebuild_phase_d),
        use_openai_planner=not bool(args.no_openai_planner),
        allow_heuristic_fallback=True,
        openai_model=str(args.planner_model or "gpt-5-mini").strip() or "gpt-5-mini",
        reasoning_effort=str(args.planner_reasoning_effort or "low").strip() or "low",
        temperature=0.0,
        max_completion_tokens=1400,
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

    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))
    print_section("Phase E Lab - Retrieval Capabilities")
    print_kv({
        "numpy_available": phase_e_capabilities().get("numpy_available"),
        "openai_available": phase_e_capabilities().get("openai_available"),
        "openai_api_key_present": phase_e_capabilities().get("openai_api_key_present"),
        "embedding_model": phase_e_options.openai_embedding_model,
        "dense_mode": phase_e_result["dense_trace"].get("dense_mode"),
        "pricing_source_url": (phase_e_result["dense_trace"].get("cost") or {}).get("pricing_source_url"),
        "pricing_verified_date": (phase_e_result["dense_trace"].get("cost") or {}).get("pricing_verified_date"),
    })
    print_section("Phase E Lab - What Happened")
    print_kv({
        "run_id": run_ctx.run_id,
        "fused_candidates_jsonl": rel(phase_e_result["fused_candidates_path"]),
        "phase_e_config_json": rel(phase_e_result["config_path"]),
        "phase_e_runtime_json": rel(phase_e_result["runtime_path"]),
        "phase_e_summary_json": rel(phase_e_result["summary_path"]),
        "phase_e_assessment_json": rel(phase_e_result["assessment_path"]),
        "phase_e_dense_trace_json": rel(phase_e_result["dense_trace_path"]),
        "phase_e_subpoint_support_json": rel(phase_e_result["subpoint_support_path"]),
        "lane_files": len(phase_e_result["lane_paths"]),
        "fused_candidates": len(phase_e_result["fused_candidate_rows"]),
        "embedding_input_tokens": (phase_e_result["dense_trace"].get("usage") or {}).get("input_tokens"),
        "embedding_total_tokens": (phase_e_result["dense_trace"].get("usage") or {}).get("total_tokens"),
        "embedding_estimated_cost_usd": (phase_e_result["dense_trace"].get("cost") or {}).get("estimated_cost_usd"),
        "phase_status": phase_e_result["assessment"].get("status"),
    })
    print_section("Phase E Lab - Subpoint Support")
    print_kv({
        "selection_strategy": phase_e_options.selection_strategy,
        "supported_subpoints": ", ".join(phase_e_result["supported_subpoint_ids"]) or "none",
        "unsupported_subpoints": ", ".join(phase_e_result["unsupported_subpoint_ids"]) or "none",
        "abstained": phase_e_result["abstained"],
    })
    print_table(phase_e_result["subpoint_support_rows"], columns=["subpoint_id", "label", "supported", "trusted_candidate_count", "trusted_doc_count", "top_candidate_title", "top_candidate_score"], max_rows=20, max_col_width=52)
    print_section("Phase E Lab - Lane Summary")
    print_table(phase_e_result["lane_summary_rows"], columns=["lane", "candidate_count", "unique_docs", "top1_score", "top1_doc_id", "top1_view", "top1_title"], max_rows=20, max_col_width=54)
    print_section("Phase E Lab - Lane Overlap")
    print_table(phase_e_result["lane_overlap_rows"], columns=["lane_left", "lane_right", "top_k", "overlap_count", "jaccard"], max_rows=20, max_col_width=32)
    print_section("Phase E Lab - Fused Candidate Preview")
    print_table(phase_e_result["fused_preview_rows"], columns=["fused_rank", "doc_id", "title", "section_type", "pages", "fused_score", "selection_score", "trusted_subpoints", "lane_hits", "supporting_passages", "passage_only_support"], max_rows=20, max_col_width=52)
    print_section("Phase E Lab - QC")
    print_table(phase_e_result["qc_rows"], columns=["check", "status", "value", "expected", "why", "fix"], max_rows=20, max_col_width=46)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
