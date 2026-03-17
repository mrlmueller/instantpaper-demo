#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from argparse import Namespace
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence

from phase_a_lab import (
    load_metrics,
    log_event,
    print_kv,
    print_section,
    print_table,
    record_api_call,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
    run_phase_a,
)
from phase_b_lab import ensure_dir, json_safe, rel_to_run, utc_now_iso, write_json_atomic as write_json
from phase_c_lab import *  # noqa: F401,F403


PHASE_D_OPTIONAL_IMPORT_ERRORS: Dict[str, str] = {}

try:
    from openai import OpenAI
except Exception as e:  # pragma: no cover
    OpenAI = None
    PHASE_D_OPTIONAL_IMPORT_ERRORS["openai"] = f"{type(e).__name__}: {e}"

try:
    from pydantic import BaseModel, Field
except Exception as e:  # pragma: no cover
    BaseModel = None
    Field = None
    PHASE_D_OPTIONAL_IMPORT_ERRORS["pydantic"] = f"{type(e).__name__}: {e}"


OPENAI_API_KEY = (os.getenv("OPENAI_API_KEY") or "").strip()

PHASE_D_ALLOWED_SECTION_TYPES = [
    "front_matter",
    "abstract",
    "introduction",
    "background",
    "related_work",
    "methods",
    "results",
    "discussion",
    "conclusion",
    "body_other",
    "references",
    "appendix",
    "acknowledgements",
    "table_of_contents",
    "index",
]
PHASE_D_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "bei",
    "bzw",
    "das",
    "dem",
    "den",
    "der",
    "deren",
    "des",
    "die",
    "digitalen",
    "ein",
    "eine",
    "einer",
    "eines",
    "for",
    "from",
    "im",
    "in",
    "into",
    "is",
    "ist",
    "its",
    "kontext",
    "mit",
    "of",
    "on",
    "or",
    "online",
    "role",
    "shop",
    "speziell",
    "the",
    "their",
    "to",
    "und",
    "unsicherer",
    "unsicheren",
    "von",
    "webshop",
    "webshopkontext",
    "with",
    "zu",
}
PHASE_D_GENERIC_PHRASES = {
    "complex products",
    "consumer choice",
    "digital context",
    "factors",
    "factors that reduce uncertainty",
    "gestaltungsprinzipien",
    "grenzen",
    "limits",
    "mechanisms",
    "mechanismen",
    "online purchase",
    "online purchases",
    "online shopping",
    "perceived risk",
    "results",
    "the role",
    "trust",
    "uncertainty",
    "wahrgenommenes risiko",
}
LANGUAGE_HINT_MAP = {
    "de": "de",
    "deutsch": "de",
    "german": "de",
    "en": "en",
    "englisch": "en",
    "english": "en",
}
PHASE_D_RETRIEVAL_ALIAS_MAP = {
    "entscheidungspsychologie": ["decision psychology"],
    "webshop-kontext entscheidungspsychologie": ["webshop decision-making", "online purchase decision-making"],
    "entscheidungssicherheit": ["decision confidence"],
    "heuristiken": ["heuristics"],
    "dual-process-ansatze": ["dual-process models", "system 1 system 2"],
    "dual-process-ansaetze": ["dual-process models", "system 1 system 2"],
    "wahrgenommenes risiko": ["perceived risk"],
    "unsicherheit": ["uncertainty"],
    "wahrgenommenes risiko/unsicherheit": ["perceived risk", "uncertainty"],
    "unsicherheit im online-kauf perceived risk": ["online purchase uncertainty", "perceived risk"],
    "informationsdarstellung": ["information presentation", "information display"],
    "die unsicherheit reduzieren informationsdarstellung": ["information presentation", "quality signals", "comparability", "explainability"],
    "vergleichbarkeit": ["comparability"],
    "erklarbarkeit": ["explainability"],
    "erklärbarkeit": ["explainability"],
    "qualitatssignale": ["quality signals"],
    "qualitätssignale": ["quality signals"],
    "nutzerautonomie": ["user autonomy"],
    "transparenz": ["transparency"],
    "ethische leitplanken": ["ethical guardrails", "ethical boundaries"],
    "trust speziell": ["trustworthiness", "reviewer trustworthiness"],
}
PHASE_D_BRIDGE_GENERIC_TERMS = {
    "background",
    "behavioral",
    "decision making",
    "decision making process",
    "future directions",
    "implications",
    "introduction",
    "literature review",
    "methodology",
    "results",
    "taxonomy",
    "testing",
}
OPENAI_API_PRICING_SOURCE_URL = "https://platform.openai.com/docs/pricing"
OPENAI_API_PRICING_VERIFIED_DATE = "2026-03-15"
OPENAI_TEXT_MODEL_PRICING_USD_PER_1M = {
    "gpt-5": {"input": 1.25, "cached_input": 0.125, "output": 10.0},
    "gpt-5-mini": {"input": 0.25, "cached_input": 0.025, "output": 2.0},
    "gpt-5-nano": {"input": 0.05, "cached_input": 0.005, "output": 0.4},
}


@dataclass
class PhaseDOptions:
    force_rebuild: bool = False
    use_openai_planner: bool = True
    use_openai_bridge_terms: bool = True
    allow_heuristic_fallback: bool = True
    openai_model: str = "gpt-5-mini"
    reasoning_effort: str = "low"
    temperature: float = 0.0
    max_completion_tokens: int = 1400
    bridge_max_completion_tokens: int = 1800
    must_term_limit: int = 8
    should_term_limit: int = 14
    bridge_term_limit: int = 10
    bridge_section_titles_per_doc: int = 6
    bridge_sample_sections_per_doc: int = 2
    bridge_section_snippet_chars: int = 220
    exclusion_limit: int = 8
    subpoint_limit: int = 6
    drift_risk_limit: int = 8
    source_anchor_limit: int = 24
    subpoint_source_anchor_limit: int = 3
    max_summary_chars: int = 480
    max_subpoint_summary_chars: int = 320
    min_anchor_token_overlap: float = 0.67
    planner_prompt_mode: str = "baseline"
    include_should_terms_view: bool = True
    include_support_context_view: bool = True
    include_subpoint_lexical_views: bool = True

    def normalized(self) -> "PhaseDOptions":
        prompt_mode = str(self.planner_prompt_mode or "baseline").strip().lower() or "baseline"
        if prompt_mode not in {"baseline", "coverage"}:
            prompt_mode = "baseline"
        return PhaseDOptions(
            force_rebuild=bool(self.force_rebuild),
            use_openai_planner=bool(self.use_openai_planner),
            use_openai_bridge_terms=bool(self.use_openai_bridge_terms),
            allow_heuristic_fallback=bool(self.allow_heuristic_fallback),
            openai_model=str(self.openai_model or "gpt-5-mini").strip() or "gpt-5-mini",
            reasoning_effort=str(self.reasoning_effort or "low").strip().lower() or "low",
            temperature=float(self.temperature),
            max_completion_tokens=max(300, int(self.max_completion_tokens)),
            bridge_max_completion_tokens=max(300, int(self.bridge_max_completion_tokens)),
            must_term_limit=max(2, int(self.must_term_limit)),
            should_term_limit=max(4, int(self.should_term_limit)),
            bridge_term_limit=max(2, int(self.bridge_term_limit)),
            bridge_section_titles_per_doc=max(2, int(self.bridge_section_titles_per_doc)),
            bridge_sample_sections_per_doc=max(0, int(self.bridge_sample_sections_per_doc)),
            bridge_section_snippet_chars=max(120, int(self.bridge_section_snippet_chars)),
            exclusion_limit=max(1, int(self.exclusion_limit)),
            subpoint_limit=max(1, int(self.subpoint_limit)),
            drift_risk_limit=max(1, int(self.drift_risk_limit)),
            source_anchor_limit=max(6, int(self.source_anchor_limit)),
            subpoint_source_anchor_limit=max(1, int(self.subpoint_source_anchor_limit)),
            max_summary_chars=max(160, int(self.max_summary_chars)),
            max_subpoint_summary_chars=max(120, int(self.max_subpoint_summary_chars)),
            min_anchor_token_overlap=min(1.0, max(0.4, float(self.min_anchor_token_overlap))),
            planner_prompt_mode=prompt_mode,
            include_should_terms_view=bool(self.include_should_terms_view),
            include_support_context_view=bool(self.include_support_context_view),
            include_subpoint_lexical_views=bool(self.include_subpoint_lexical_views),
        )


if BaseModel is not None:

    class QuerySubpointModel(BaseModel):
        subpoint_id: str = Field(min_length=1)
        label: str = Field(min_length=1)
        summary: str = Field(min_length=1)
        source_anchors: List[str] = Field(default_factory=list)
        must_terms: List[str] = Field(default_factory=list)
        should_terms: List[str] = Field(default_factory=list)
        preferred_section_types: List[str] = Field(default_factory=list)


    class QueryPlanModel(BaseModel):
        chapter_summary: str = Field(min_length=1)
        source_anchors: List[str] = Field(default_factory=list)
        must_terms: List[str] = Field(default_factory=list)
        should_terms: List[str] = Field(default_factory=list)
        exclusions: List[str] = Field(default_factory=list)
        subpoints: List[QuerySubpointModel] = Field(default_factory=list)
        language_hints: List[str] = Field(default_factory=list)
        preferred_section_types: List[str] = Field(default_factory=list)
        penalized_section_types: List[str] = Field(default_factory=list)
        drift_risks: List[str] = Field(default_factory=list)


    class BridgeTermModel(BaseModel):
        term: str = Field(min_length=1)
        linked_source_anchors: List[str] = Field(default_factory=list, max_length=4)
        corpus_evidence: List[str] = Field(default_factory=list, max_length=4)
        source_link: str = Field(default="", max_length=160)


    class BridgeTermPlanModel(BaseModel):
        bridge_terms: List[BridgeTermModel] = Field(default_factory=list, max_length=16)

else:  # pragma: no cover
    QuerySubpointModel = None
    QueryPlanModel = None
    BridgeTermModel = None
    BridgeTermPlanModel = None


def phase_d_capabilities() -> Dict[str, Any]:
    return {
        "python_executable": sys.executable,
        "python_version": sys.version.split()[0],
        "openai_available": bool(OpenAI is not None),
        "pydantic_available": bool(BaseModel is not None),
        "openai_api_key_present": bool(OPENAI_API_KEY),
        "optional_import_errors": dict(PHASE_D_OPTIONAL_IMPORT_ERRORS),
    }


def resolve_openai_text_model_pricing(model_name: str) -> Dict[str, Any]:
    model_key = str(model_name or "").strip()
    for pricing_model in sorted(OPENAI_TEXT_MODEL_PRICING_USD_PER_1M.keys(), key=len, reverse=True):
        if model_key == pricing_model or model_key.startswith(pricing_model + "-"):
            return {
                "pricing_found": True,
                "pricing_model": pricing_model,
                "model_name": model_key,
                "pricing_source_url": OPENAI_API_PRICING_SOURCE_URL,
                "pricing_verified_date": OPENAI_API_PRICING_VERIFIED_DATE,
                "rates_usd_per_1m_tokens": dict(OPENAI_TEXT_MODEL_PRICING_USD_PER_1M[pricing_model]),
            }
    return {
        "pricing_found": False,
        "pricing_model": None,
        "model_name": model_key or None,
        "pricing_source_url": OPENAI_API_PRICING_SOURCE_URL,
        "pricing_verified_date": OPENAI_API_PRICING_VERIFIED_DATE,
        "rates_usd_per_1m_tokens": None,
    }


def extract_openai_usage_payload(usage: Any) -> Dict[str, Any]:
    input_details = getattr(usage, "input_tokens_details", None) or getattr(usage, "prompt_tokens_details", None)
    output_details = getattr(usage, "output_tokens_details", None) or getattr(usage, "completion_tokens_details", None)
    input_tokens = getattr(usage, "input_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "prompt_tokens", None)
    output_tokens = getattr(usage, "output_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "completion_tokens", None)
    total_tokens = getattr(usage, "total_tokens", None)
    cached_input_tokens = getattr(input_details, "cached_tokens", None) if input_details is not None else None
    reasoning_tokens = getattr(output_details, "reasoning_tokens", None) if output_details is not None else None
    accepted_prediction_tokens = getattr(output_details, "accepted_prediction_tokens", None) if output_details is not None else None
    rejected_prediction_tokens = getattr(output_details, "rejected_prediction_tokens", None) if output_details is not None else None
    audio_input_tokens = getattr(input_details, "audio_tokens", None) if input_details is not None else None
    audio_output_tokens = getattr(output_details, "audio_tokens", None) if output_details is not None else None
    non_cached_input_tokens = None
    if isinstance(input_tokens, int):
        non_cached_input_tokens = int(input_tokens)
        if isinstance(cached_input_tokens, int):
            non_cached_input_tokens = max(int(input_tokens) - int(cached_input_tokens), 0)
    return {
        "input_tokens": input_tokens,
        "cached_input_tokens": cached_input_tokens,
        "non_cached_input_tokens": non_cached_input_tokens,
        "output_tokens": output_tokens,
        "reasoning_tokens": reasoning_tokens,
        "accepted_prediction_tokens": accepted_prediction_tokens,
        "rejected_prediction_tokens": rejected_prediction_tokens,
        "audio_input_tokens": audio_input_tokens,
        "audio_output_tokens": audio_output_tokens,
        "total_tokens": total_tokens,
    }


def estimate_openai_text_cost_usd(model_name: str, usage_payload: Dict[str, Any]) -> Dict[str, Any]:
    pricing_info = resolve_openai_text_model_pricing(model_name)
    usage_payload = dict(usage_payload or {})
    result = {
        **pricing_info,
        "usage": usage_payload,
        "estimated_cost_usd": None,
        "cost_components_usd": {},
    }
    rates = pricing_info.get("rates_usd_per_1m_tokens") or {}
    if not pricing_info.get("pricing_found"):
        return result
    input_tokens = usage_payload.get("input_tokens")
    cached_input_tokens = usage_payload.get("cached_input_tokens")
    output_tokens = usage_payload.get("output_tokens")
    non_cached_input_tokens = usage_payload.get("non_cached_input_tokens")
    if non_cached_input_tokens is None and isinstance(input_tokens, int):
        non_cached_input_tokens = int(input_tokens)
        if isinstance(cached_input_tokens, int):
            non_cached_input_tokens = max(int(input_tokens) - int(cached_input_tokens), 0)
    total_cost = 0.0
    if isinstance(non_cached_input_tokens, int):
        input_cost = (non_cached_input_tokens / 1_000_000.0) * float(rates.get("input") or 0.0)
        result["cost_components_usd"]["input_cost_usd"] = round(input_cost, 8)
        total_cost += input_cost
    if isinstance(cached_input_tokens, int):
        cached_cost = (cached_input_tokens / 1_000_000.0) * float(rates.get("cached_input") or 0.0)
        result["cost_components_usd"]["cached_input_cost_usd"] = round(cached_cost, 8)
        total_cost += cached_cost
    if isinstance(output_tokens, int):
        output_cost = (output_tokens / 1_000_000.0) * float(rates.get("output") or 0.0)
        result["cost_components_usd"]["output_cost_usd"] = round(output_cost, 8)
        total_cost += output_cost
    result["estimated_cost_usd"] = round(total_cost, 8)
    return result


def normalize_match_tokens(text: Any) -> List[str]:
    return [tok for tok in re.findall(r"[a-z0-9]+", ascii_fold(clean_text(text)).lower()) if tok]


def normalize_match_key(text: Any) -> str:
    return " ".join(normalize_match_tokens(text))


def truncate_text(text: Any, max_len: int) -> str:
    s = clean_text(text)
    return s if len(s) <= int(max_len) else (s[: max(1, int(max_len) - 1)] + "…")


def truncate_words(text: Any, max_words: int) -> str:
    words = clean_text(text).split()
    if len(words) <= int(max_words):
        return " ".join(words)
    return " ".join(words[: max(1, int(max_words))]) + "…"


def strip_quotes(text: str) -> str:
    s = clean_text(text)
    s = s.strip("\"'“”„`´")
    return clean_text(s)


def unique_clean_terms(items: Iterable[Any], *, limit: int, max_words: int = 8, max_chars: int = 90) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in items or []:
        term = strip_quotes(clean_text(raw))
        term = re.sub(r"^\(?\d+\)?[.)-]?\s*", "", term)
        term = re.sub(r"^[,;:\-]+|[,;:\-]+$", "", term).strip()
        term = term.replace("*", "").strip()
        term = term.strip("()[]{}")
        term = clean_text(term)
        if not term or re.fullmatch(r"\d+", term):
            continue
        if len(term) < 2 or len(term) > max_chars:
            continue
        if count_words(term) > max_words:
            continue
        key = normalize_match_key(term)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(term)
        if len(out) >= int(limit):
            break
    return out


def normalized_source_text(chapter_title: str, chapter_spec_text: str) -> str:
    return normalize_match_key(f"{chapter_title}\n{chapter_spec_text}")


def text_contains_term(text: Any, term: Any) -> bool:
    haystack = normalize_match_key(text)
    needle = normalize_match_key(term)
    if not haystack or not needle:
        return False
    return f" {needle} " in f" {haystack} "


def detect_language_hints(chapter_title: str, chapter_spec_text: str) -> List[str]:
    source = normalized_source_text(chapter_title, chapter_spec_text)
    hints: List[str] = []
    if any(token in source for token in ["entscheidung", "kauf", "wahrgenommen", "unsicherheit", "leitplanken"]):
        hints.append("de")
    if any(token in source for token in ["decision", "trust", "perceived risk", "uncertainty", "consumer electronics", "choice architecture", "digital nudging"]):
        hints.append("en")
    if not hints:
        hints.append("en" if infer_language_guess(chapter_title + " " + chapter_spec_text) == "en" else "de")
    return list(dict.fromkeys(hints))


def normalize_language_hints(items: Iterable[Any]) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in items or []:
        norm = LANGUAGE_HINT_MAP.get(normalize_match_key(raw), "")
        if norm and norm not in seen:
            seen.add(norm)
            out.append(norm)
    return out


def retrieval_alias_terms(items: Iterable[Any], *, limit: int = 16) -> List[str]:
    out: List[str] = []
    seen = set()
    for raw in items or []:
        key = normalize_match_key(raw)
        if not key:
            continue
        for alias in PHASE_D_RETRIEVAL_ALIAS_MAP.get(key) or []:
            cleaned = clean_text(alias)
            alias_key = normalize_match_key(cleaned)
            if not cleaned or not alias_key or alias_key in seen:
                continue
            seen.add(alias_key)
            out.append(cleaned)
            if len(out) >= int(limit):
                return out
    return out


def infer_preferred_section_types(chapter_title: str, chapter_spec_text: str) -> List[str]:
    text = normalized_source_text(chapter_title, chapter_spec_text)
    preferred = ["introduction", "background", "related_work", "discussion", "conclusion", "body_other"]
    if any(token in text for token in ["risk", "trust", "uncertainty", "wahrgenommen", "consumer electronics"]):
        preferred.insert(3, "results")
    if any(token in text for token in ["measurement", "messung", "vergleichbarkeit", "erklarbarkeit", "erklärbarkeit", "quality signals", "qualitatssignale"]):
        preferred.append("methods")
    return list(dict.fromkeys([item for item in preferred if item in PHASE_D_ALLOWED_SECTION_TYPES]))


def infer_penalized_section_types() -> List[str]:
    return ["front_matter", "table_of_contents", "acknowledgements", "references", "index"]


def split_chapter_clauses(chapter_spec_text: str) -> List[str]:
    raw = clean_text(chapter_spec_text)
    if not raw:
        return []
    marked = re.sub(r"\(\s*(\d+)\s*\)", r" ||CLAUSE|| \1 ", raw)
    parts = re.split(r"\s*\|\|CLAUSE\|\|\s*\d+\s*|\s*;\s*|\s*\n+\s*", marked)
    clauses = [clean_text(part) for part in parts if clean_text(part)]
    return clauses or [raw]


def extract_parenthetical_terms(text: str) -> List[str]:
    out: List[str] = []
    for match in re.findall(r"\(([^)]+)\)", str(text or "")):
        for piece in re.split(r"[,/;]", match):
            term = strip_quotes(clean_text(piece))
            if term:
                out.append(term)
    return out


def extract_quoted_terms(text: str) -> List[str]:
    out: List[str] = []
    for match in re.findall(r"[\"“”„']([^\"“”„']+)[\"“”„']", str(text or "")):
        term = strip_quotes(clean_text(match))
        if term:
            out.append(term)
    return out


def expand_slash_terms(text: str) -> List[str]:
    out: List[str] = []
    for piece in re.split(r"[;,\n]", str(text or "")):
        if "/" not in piece:
            continue
        raw_parts = [clean_text(part) for part in piece.split("/") if clean_text(part)]
        if len(raw_parts) < 2:
            continue
        for part in raw_parts:
            out.append(part)
    return out


def strip_candidate_noise(text: str) -> str:
    s = clean_text(text)
    s = re.sub(
        r"^(also|sowie|speziell|speziell bei|insbesondere|deren rolle bei|deren rolle|faktoren,? die|faktoren zur|abgrenzung zu)\s+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\s+(also|sowie|speziell|insbesondere)$", "", s, flags=re.IGNORECASE)
    for marker in [r"\s+im\s+", r"\s+bei\s+", r"\s+sowie\s+", r"\s+also\s+", r"\s+speziell\s+bei\s+"]:
        if count_words(s) > 2:
            parts = re.split(marker, s, flags=re.IGNORECASE, maxsplit=1)
            if len(parts) > 1 and count_words(parts[0]) >= 2:
                s = clean_text(parts[0])
    s = re.sub(r"[()]+", "", s)
    s = re.sub(r"[.;:,]+$", "", s)
    return clean_text(s)


def score_anchor_term(text: str, origins: Sequence[str]) -> float:
    words = count_words(text)
    key = normalize_match_key(text)
    tokens = normalize_match_tokens(text)
    score = 0.0
    if 2 <= words <= 6:
        score += 3.0
    elif words == 1:
        score += 0.5
    elif words > 6:
        score -= 1.0
    if "title" in origins:
        score += 2.0
    if "quote" in origins:
        score += 1.8
    if "parenthetical" in origins:
        score += 1.5
    if "slash" in origins:
        score += 1.2
    if "clause_part" in origins and words > 4:
        score -= 1.5
    if any(tok in {"architecture", "nudging", "confidence", "electronics", "uncertainty", "transparency", "autonomie"} for tok in tokens):
        score += 0.8
    if key in PHASE_D_GENERIC_PHRASES:
        score -= 2.5
    if all(tok in PHASE_D_STOPWORDS for tok in tokens):
        score -= 4.0
    if not str(text or "").isascii():
        score -= 0.2
    return round(score, 4)


def extract_titlecase_phrases(text: str) -> List[str]:
    out: List[str] = []
    for match in re.findall(r"\b(?:[A-Z][A-Za-z-]+(?:\s+[A-Z][A-Za-z-]+)+)\b", str(text or "")):
        term = strip_candidate_noise(strip_quotes(match))
        if term:
            out.append(term)
    return out


def term_priority_score(term: str, source_inventory: Dict[str, Any]) -> float:
    key = normalize_match_key(term)
    words = count_words(term)
    row = next((item for item in (source_inventory.get("candidate_rows") or []) if item.get("key") == key), None)
    score = float((row or {}).get("score") or 0.0)
    if 1 <= words <= 4:
        score += 1.0
    elif words > 5:
        score -= 1.5
    if str(term or "").isascii():
        score += 0.7
    if any(tok in {"choice", "digital", "decision", "confidence", "risk", "uncertainty", "trust", "consumer", "electronics", "heuristics", "biases"} for tok in normalize_match_tokens(term)):
        score += 0.8
    if key in PHASE_D_GENERIC_PHRASES:
        score -= 1.0
    return round(score, 4)


def rank_terms(candidates: Iterable[Any], source_inventory: Dict[str, Any], *, limit: int, max_words: int, max_chars: int) -> List[str]:
    cleaned = unique_clean_terms(candidates or [], limit=max(limit * 4, 16), max_words=max_words, max_chars=max_chars)
    scored = [(term_priority_score(item, source_inventory), item) for item in cleaned]
    scored.sort(key=lambda item: (item[0], count_words(item[1]) <= 4, len(str(item[1] or ""))), reverse=True)
    return [item for _score, item in scored[: int(limit)]]


def build_source_anchor_inventory(chapter_title: str, chapter_spec_text: str, options: PhaseDOptions) -> Dict[str, Any]:
    clauses = split_chapter_clauses(chapter_spec_text)
    candidates: Dict[str, Dict[str, Any]] = {}

    def register(text: Any, origin: str) -> None:
        term = strip_candidate_noise(strip_quotes(clean_text(text)))
        if not term:
            return
        if origin in {"clause", "clause_part"} and (("(" in term) or (")" in term)):
            return
        if origin in {"clause", "clause_part"} and count_words(term) > 5:
            return
        key = normalize_match_key(term)
        if not key:
            return
        entry = candidates.setdefault(
            key,
            {
                "text": term,
                "key": key,
                "origins": [],
            },
        )
        entry["origins"].append(origin)

    register(chapter_title, "title")
    for clause in clauses:
        register(clause, "clause")
        for part in re.split(r"[;,]", clause):
            register(part, "clause_part")
    for term in extract_parenthetical_terms(chapter_spec_text):
        register(term, "parenthetical")
    for term in extract_quoted_terms(chapter_title + " " + chapter_spec_text):
        register(term, "quote")
    for term in expand_slash_terms(chapter_title + " ; " + chapter_spec_text):
        register(term, "slash")
    for term in extract_titlecase_phrases(chapter_title + " " + chapter_spec_text):
        register(term, "titlecase")

    candidate_rows: List[Dict[str, Any]] = []
    for row in candidates.values():
        cleaned = unique_clean_terms([row["text"]], limit=1, max_words=10, max_chars=120)
        row["text"] = cleaned[0] if cleaned else ""
        row["origins"] = sorted(set(row["origins"]))
        row["score"] = score_anchor_term(row["text"], row["origins"])
        row["word_count"] = count_words(row["text"])
        if row["text"]:
            candidate_rows.append(row)
    candidate_rows.sort(
        key=lambda item: (
            float(item.get("score") or 0.0),
            "title" in set(item.get("origins") or []),
            -abs(3 - int(item.get("word_count") or 0)),
            len(str(item.get("text") or "")),
        ),
        reverse=True,
    )
    selected = [row["text"] for row in candidate_rows[: int(options.source_anchor_limit)]]
    return {
        "chapter_title": clean_text(chapter_title),
        "chapter_spec_text": clean_text(chapter_spec_text),
        "clauses": clauses,
        "candidate_rows": candidate_rows,
        "selected_anchors": selected,
        "normalized_source_text": normalized_source_text(chapter_title, chapter_spec_text),
    }


def extract_term_candidates(text: str) -> List[str]:
    candidates: List[str] = []
    raw = clean_text(text)
    candidates.extend(extract_quoted_terms(raw))
    candidates.extend(extract_parenthetical_terms(raw))
    candidates.extend(expand_slash_terms(raw))
    candidates.extend(extract_titlecase_phrases(raw))
    candidates.extend([strip_candidate_noise(clean_text(part)) for part in re.split(r"[;,]", raw) if clean_text(part)])
    return unique_clean_terms(candidates, limit=32, max_words=8, max_chars=90)


def build_heuristic_query_plan(
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    options: PhaseDOptions,
    stable_hash_fn: Any,
) -> Dict[str, Any]:
    clauses = list(source_inventory.get("clauses") or split_chapter_clauses(chapter_spec_text))
    anchor_rows = list(source_inventory.get("candidate_rows") or [])
    selected_anchors = [str(x) for x in (source_inventory.get("selected_anchors") or []) if str(x).strip()]
    anchor_terms = [row.get("text") for row in anchor_rows if row.get("word_count") and 1 <= int(row.get("word_count")) <= 5]
    must_terms = rank_terms(anchor_terms + selected_anchors, source_inventory, limit=options.must_term_limit, max_words=6, max_chars=90)
    should_terms = rank_terms(selected_anchors + anchor_terms + extract_term_candidates(chapter_spec_text), source_inventory, limit=options.should_term_limit, max_words=8, max_chars=90)
    must_keys = set(normalize_match_key(item) for item in must_terms)
    should_terms = [item for item in should_terms if normalize_match_key(item) not in must_keys]
    preferred_section_types = infer_preferred_section_types(chapter_title, chapter_spec_text)
    language_hints = detect_language_hints(chapter_title, chapter_spec_text)
    subpoints: List[Dict[str, Any]] = []
    for idx, clause in enumerate(clauses[: int(options.subpoint_limit)], start=1):
        clause_terms = extract_term_candidates(clause)
        clause_anchor_terms = []
        for term in selected_anchors:
            if text_contains_term(clause, term):
                clause_anchor_terms.append(term)
        clause_anchor_terms = unique_clean_terms(clause_anchor_terms + clause_terms, limit=options.subpoint_source_anchor_limit + 2, max_words=8, max_chars=90)
        label = clean_text(clause)
        if len(label) > 110:
            label = truncate_text(label, max_len=110)
        subpoint_must = unique_clean_terms(clause_anchor_terms[:2], limit=2, max_words=6, max_chars=90)
        subpoint_should = unique_clean_terms(clause_terms[1:] + clause_anchor_terms[2:], limit=6, max_words=8, max_chars=90)
        subpoint_keys = set(normalize_match_key(item) for item in subpoint_must)
        subpoint_should = [item for item in subpoint_should if normalize_match_key(item) not in subpoint_keys]
        subpoints.append(
            {
                "subpoint_id": f"sp_{idx:02d}",
                "label": label or f"Subpoint {idx}",
                "summary": truncate_text(clause, max_len=options.max_subpoint_summary_chars),
                "source_anchors": clause_anchor_terms[: int(options.subpoint_source_anchor_limit)],
                "must_terms": subpoint_must,
                "should_terms": subpoint_should,
                "preferred_section_types": preferred_section_types[:],
            }
        )
    chapter_summary = truncate_text(clean_text(chapter_spec_text), max_len=options.max_summary_chars)
    drift_risks = [
        "Overemphasis on generic online shopping trust without the decision-psychology or nudging linkage.",
        "Overemphasis on dark patterns or ethics debates without evidence about uncertainty reduction or decision confidence.",
    ]
    return {
        "query_id": stable_hash_fn(chapter_title, chapter_spec_text, "phase_d_query_plan", length=16),
        "chapter_title": clean_text(chapter_title),
        "chapter_summary": chapter_summary,
        "source_anchors": selected_anchors[: min(len(selected_anchors), int(options.source_anchor_limit))],
        "must_terms": must_terms,
        "should_terms": should_terms,
        "exclusions": ["medizin", "agriculture", "climate", "geology", "interview transcript"],
        "subpoints": subpoints,
        "language_hints": language_hints,
        "preferred_section_types": preferred_section_types,
        "penalized_section_types": infer_penalized_section_types(),
        "drift_risks": unique_clean_terms(drift_risks, limit=options.drift_risk_limit, max_words=16, max_chars=140),
    }


def match_term_to_source(term: str, source_inventory: Dict[str, Any], options: PhaseDOptions) -> Dict[str, Any]:
    term_text = strip_quotes(clean_text(term))
    term_key = normalize_match_key(term_text)
    term_tokens = normalize_match_tokens(term_text)
    if not term_key or not term_tokens:
        return {"matched": False, "matched_anchor": None, "score": 0.0, "reason": "empty"}
    source_text = str(source_inventory.get("normalized_source_text") or "")
    if f" {term_key} " in f" {source_text} ":
        return {"matched": True, "matched_anchor": term_text, "score": 1.0, "reason": "exact_source_phrase"}
    best_match = {"matched": False, "matched_anchor": None, "score": 0.0, "reason": "no_match"}
    for anchor in source_inventory.get("selected_anchors") or []:
        anchor_key = normalize_match_key(anchor)
        anchor_tokens = normalize_match_tokens(anchor)
        if not anchor_key:
            continue
        if term_key == anchor_key:
            return {"matched": True, "matched_anchor": anchor, "score": 1.0, "reason": "exact_anchor"}
        if f" {term_key} " in f" {anchor_key} " or f" {anchor_key} " in f" {term_key} ":
            score = 0.92
            if score > float(best_match.get("score") or 0.0):
                best_match = {"matched": True, "matched_anchor": anchor, "score": score, "reason": "phrase_containment"}
            continue
        overlap = len(set(term_tokens) & set(anchor_tokens))
        overlap_ratio = overlap / max(1, len(set(term_tokens)))
        if overlap >= 2 and overlap_ratio >= float(options.min_anchor_token_overlap):
            score = round(0.6 + (0.3 * overlap_ratio), 4)
            if score > float(best_match.get("score") or 0.0):
                best_match = {"matched": True, "matched_anchor": anchor, "score": score, "reason": "token_overlap"}
    return best_match


def source_anchor_terms(
    items: Iterable[Any],
    source_inventory: Dict[str, Any],
    options: PhaseDOptions,
    *,
    limit: int,
    max_words: int,
    max_chars: int,
) -> Dict[str, Any]:
    cleaned = unique_clean_terms(items or [], limit=limit * 3, max_words=max_words, max_chars=max_chars)
    kept: List[str] = []
    dropped: List[str] = []
    kept_rows: List[Dict[str, Any]] = []
    for item in cleaned:
        matched = match_term_to_source(item, source_inventory, options)
        if matched.get("matched"):
            kept.append(item)
            kept_rows.append({"term": item, **matched})
        else:
            dropped.append(item)
    kept = unique_clean_terms(kept, limit=limit, max_words=max_words, max_chars=max_chars)
    kept_key_set = {normalize_match_key(item) for item in kept}
    kept_rows = [row for row in kept_rows if normalize_match_key(row.get("term")) in kept_key_set]
    return {"kept": kept, "dropped": dropped, "kept_rows": kept_rows}


def build_query_planner_messages(
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    options: PhaseDOptions,
) -> Dict[str, Any]:
    allowed_types = ", ".join(PHASE_D_ALLOWED_SECTION_TYPES)
    source_anchors = source_inventory.get("selected_anchors") or []
    clauses = source_inventory.get("clauses") or []
    if str(options.planner_prompt_mode or "baseline") == "coverage":
        system_prompt = (
            "You create high-recall, source-grounded query plans for retrieving useful sections from scientific PDFs.\n\n"
            "Your job is not only to find sections that restate the chapter wording. Your job is to find sections that could materially help write the chapter well. "
            "A section can be useful because it gives core theory, mechanisms, operational factors, design implications, quality or trust signals, failure modes, comparative framing, measurement constructs, or practical implications, as long as that usefulness is grounded in the source text.\n\n"
            "Hard constraints:\n"
            "- Use only the chapter title, chapter spec, numbered clauses, and source-anchor inventory.\n"
            "- Do not invent unrelated topics, datasets, products, methods, or jargon.\n"
            "- Keep must_terms short, discriminative, and likely to appear in section titles or section text.\n"
            "- Keep should_terms broader than must_terms, but still clearly grounded in the source anchors or obvious bilingual technical renderings.\n"
            "- When the source mixes German and English, prefer English technical surface forms when they are faithful translations of the source concepts and likely to appear in papers.\n"
            "- Return 3-6 subpoints, treating them as retrieval packs or information families rather than just sentence fragments.\n"
            "- At least one subpoint may cover supporting context if that context would clearly enrich scientific writing and is still source-grounded.\n"
            "- Every subpoint must cite 1-3 source_anchors.\n"
            "- Always include at least one drift_risk.\n\n"
            f"Allowed section types: {allowed_types}."
        )
        user_prompt = (
            f"## Chapter Title\n{chapter_title}\n\n"
            f"## Chapter Spec\n{chapter_spec_text}\n\n"
            "## Numbered Source Clauses\n"
            + "\n".join(f"- Clause {idx}: {clause}" for idx, clause in enumerate(clauses, start=1))
            + "\n\n## Source-Anchor Inventory\n"
            + "\n".join(f"- {anchor}" for anchor in source_anchors)
            + "\n\n## Task\n"
            "Build a retrieval plan that keeps recall high while staying auditable. "
            "Make the plan useful for heading-first plus section-text retrieval. "
            "Use must_terms for precise anchors, should_terms for broader but grounded retrieval, and subpoints for distinct useful evidence families. "
            "Favor terms that could surface theory, signals, review quality, practical implications, risk or trust mechanisms, design choices, or contextual evidence if those ideas are grounded in the source. "
            "Do not optimize only for the most literal wording overlap."
        )
    else:
        system_prompt = (
            "You create strict query plans for section retrieval over scientific PDFs. "
            "Use only the chapter title, chapter spec, and provided source-anchor inventory. "
            "Do not invent new topics, wildcards, regex fragments, or domain drift. "
            "Prefer selecting and grouping the supplied anchors over paraphrasing. "
            "When the source mixes German and English, prefer English technical terms for must_terms when the source already contains them. "
            "Every must_terms and should_terms item must be short, concrete, and source-grounded. "
            "Return 2-6 subpoints. Each subpoint must cite 1-3 source_anchors from the inventory. "
            "Always include at least one drift_risk. "
            f"Allowed section types: {allowed_types}."
        )
        user_prompt = (
            f"Chapter title:\n{chapter_title}\n\n"
            f"Chapter spec:\n{chapter_spec_text}\n\n"
            "Numbered source clauses:\n"
            + "\n".join(f"- Clause {idx}: {clause}" for idx, clause in enumerate(clauses, start=1))
            + "\n\n"
            + "Source-anchor inventory (choose from these whenever possible):\n"
            + "\n".join(f"- {anchor}" for anchor in source_anchors)
            + "\n\n"
            + "Build a retrieval query plan for finding useful PDF sections. "
            "Must terms should be discriminative lexical anchors likely to appear in paper titles, headings, or body text. "
            "Should terms may be broader but must stay grounded in the same source anchors. "
            "Keep chapter_summary concise."
        )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return {"system_prompt": system_prompt, "user_prompt": user_prompt, "messages": messages}


def normalize_section_type_list(items: Iterable[Any], fallback: List[str]) -> List[str]:
    out: List[str] = []
    for item in items or []:
        value = clean_text(item).lower().replace(" ", "_")
        if value in PHASE_D_ALLOWED_SECTION_TYPES and value not in out:
            out.append(value)
    return out or fallback[:]


def merge_terms(primary: Iterable[Any], fallback: Iterable[Any], *, limit: int, max_words: int, max_chars: int) -> List[str]:
    return unique_clean_terms(list(primary or []) + list(fallback or []), limit=limit, max_words=max_words, max_chars=max_chars)


def normalize_query_plan(
    plan_payload: Dict[str, Any],
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    options: PhaseDOptions,
    stable_hash_fn: Any,
) -> Dict[str, Any]:
    heuristic_plan = build_heuristic_query_plan(chapter_title, chapter_spec_text, source_inventory, options, stable_hash_fn)
    baseline_penalized = infer_penalized_section_types()
    normalized: Dict[str, Any] = {
        "query_id": stable_hash_fn(chapter_title, chapter_spec_text, "phase_d_query_plan", length=16),
        "chapter_title": clean_text(chapter_title),
        "chapter_summary": truncate_text(clean_text(plan_payload.get("chapter_summary") or heuristic_plan.get("chapter_summary") or chapter_spec_text), max_len=options.max_summary_chars),
        "source_anchors": [],
        "must_terms": [],
        "should_terms": [],
        "retrieval_should_terms": [],
        "exclusions": unique_clean_terms(plan_payload.get("exclusions") or heuristic_plan.get("exclusions") or [], limit=options.exclusion_limit, max_words=6, max_chars=80),
        "subpoints": [],
        "language_hints": normalize_language_hints(plan_payload.get("language_hints") or heuristic_plan.get("language_hints") or detect_language_hints(chapter_title, chapter_spec_text)),
        "preferred_section_types": normalize_section_type_list(
            list(plan_payload.get("preferred_section_types") or []) + list(heuristic_plan.get("preferred_section_types") or infer_preferred_section_types(chapter_title, chapter_spec_text)),
            heuristic_plan.get("preferred_section_types") or infer_preferred_section_types(chapter_title, chapter_spec_text),
        ),
        "penalized_section_types": normalize_section_type_list(list(baseline_penalized) + list(plan_payload.get("penalized_section_types") or []), baseline_penalized),
        "drift_risks": unique_clean_terms(plan_payload.get("drift_risks") or heuristic_plan.get("drift_risks") or [], limit=options.drift_risk_limit, max_words=16, max_chars=140),
        "source_pruned_terms": {"must_terms": [], "should_terms": [], "subpoints": []},
        "anchor_match_details": {"must_terms": [], "should_terms": [], "subpoints": []},
    }

    normalized["source_anchors"] = rank_terms(
        list(source_anchor_terms(plan_payload.get("source_anchors") or [], source_inventory, options, limit=options.source_anchor_limit, max_words=10, max_chars=120)["kept"])
        + list(heuristic_plan.get("source_anchors") or [])
        + list(source_inventory.get("selected_anchors") or []),
        source_inventory,
        limit=options.source_anchor_limit,
        max_words=10,
        max_chars=120,
    )

    must_term_support = source_anchor_terms(plan_payload.get("must_terms") or [], source_inventory, options, limit=options.must_term_limit, max_words=8, max_chars=90)
    should_term_support = source_anchor_terms(plan_payload.get("should_terms") or [], source_inventory, options, limit=options.should_term_limit, max_words=8, max_chars=90)
    normalized["anchor_match_details"]["must_terms"] = must_term_support["kept_rows"]
    normalized["anchor_match_details"]["should_terms"] = should_term_support["kept_rows"]
    normalized["source_pruned_terms"]["must_terms"] = must_term_support["dropped"]
    normalized["source_pruned_terms"]["should_terms"] = should_term_support["dropped"]

    normalized["must_terms"] = rank_terms(
        list(must_term_support["kept"]) + list(heuristic_plan.get("must_terms") or []) + list(normalized.get("source_anchors") or []),
        source_inventory,
        limit=options.must_term_limit,
        max_words=8,
        max_chars=90,
    )
    normalized["should_terms"] = rank_terms(
        [item for item in list(should_term_support["kept"]) + list(heuristic_plan.get("should_terms") or []) + list(normalized["source_anchors"]) if normalize_match_key(item) not in {normalize_match_key(x) for x in normalized["must_terms"]}],
        source_inventory,
        limit=options.should_term_limit,
        max_words=8,
        max_chars=90,
    )

    raw_subpoints = plan_payload.get("subpoints") or []
    for idx, raw in enumerate(raw_subpoints[: int(options.subpoint_limit)], start=1):
        if not isinstance(raw, dict):
            continue
        sub_anchor_support = source_anchor_terms(raw.get("source_anchors") or [], source_inventory, options, limit=options.subpoint_source_anchor_limit, max_words=10, max_chars=120)
        sub_must_support = source_anchor_terms(raw.get("must_terms") or [], source_inventory, options, limit=2, max_words=8, max_chars=90)
        sub_should_support = source_anchor_terms(raw.get("should_terms") or [], source_inventory, options, limit=6, max_words=8, max_chars=90)
        fallback_sub = heuristic_plan.get("subpoints", [])[idx - 1] if idx - 1 < len(heuristic_plan.get("subpoints") or []) else {}
        label = clean_text(raw.get("label") or fallback_sub.get("label") or f"Subpoint {idx}")
        summary = truncate_text(clean_text(raw.get("summary") or fallback_sub.get("summary") or ""), max_len=options.max_subpoint_summary_chars)
        source_anchors = merge_terms(
            sub_anchor_support["kept"],
            fallback_sub.get("source_anchors") or [],
            limit=options.subpoint_source_anchor_limit,
            max_words=10,
            max_chars=120,
        )
        must_terms = merge_terms(
            sub_must_support["kept"],
            fallback_sub.get("must_terms") or source_anchors,
            limit=2,
            max_words=8,
            max_chars=90,
        )
        should_terms = merge_terms(
            [item for item in sub_should_support["kept"] if normalize_match_key(item) not in {normalize_match_key(x) for x in must_terms}],
            [item for item in (fallback_sub.get("should_terms") or source_anchors) if normalize_match_key(item) not in {normalize_match_key(x) for x in must_terms}],
            limit=6,
            max_words=8,
            max_chars=90,
        )
        normalized["subpoints"].append(
            {
                "subpoint_id": clean_text(raw.get("subpoint_id") or fallback_sub.get("subpoint_id") or f"sp_{idx:02d}")[:32],
                "label": label[:110],
                "summary": summary,
                "source_anchors": source_anchors,
                "must_terms": must_terms,
                "should_terms": should_terms,
                "preferred_section_types": normalize_section_type_list(
                    list(raw.get("preferred_section_types") or []) + list(fallback_sub.get("preferred_section_types") or normalized["preferred_section_types"]),
                    fallback_sub.get("preferred_section_types") or normalized["preferred_section_types"],
                ),
            }
        )
        normalized["source_pruned_terms"]["subpoints"].append(
            {
                "subpoint_id": clean_text(raw.get("subpoint_id") or f"sp_{idx:02d}")[:32],
                "source_anchors": sub_anchor_support["dropped"],
                "must_terms": sub_must_support["dropped"],
                "should_terms": sub_should_support["dropped"],
            }
        )
        normalized["anchor_match_details"]["subpoints"].append(
            {
                "subpoint_id": clean_text(raw.get("subpoint_id") or f"sp_{idx:02d}")[:32],
                "source_anchors": sub_anchor_support["kept_rows"],
                "must_terms": sub_must_support["kept_rows"],
                "should_terms": sub_should_support["kept_rows"],
            }
        )

    if not normalized["subpoints"]:
        normalized["subpoints"] = list(heuristic_plan.get("subpoints") or [])
    if not normalized["must_terms"]:
        normalized["must_terms"] = list(heuristic_plan.get("must_terms") or [])
    if not normalized["should_terms"]:
        normalized["should_terms"] = list(heuristic_plan.get("should_terms") or [])
    if not normalized["source_anchors"]:
        normalized["source_anchors"] = list(heuristic_plan.get("source_anchors") or source_inventory.get("selected_anchors") or [])
    if not normalized["language_hints"]:
        normalized["language_hints"] = detect_language_hints(chapter_title, chapter_spec_text)
    if not normalized["preferred_section_types"]:
        normalized["preferred_section_types"] = infer_preferred_section_types(chapter_title, chapter_spec_text)
    if not normalized["penalized_section_types"]:
        normalized["penalized_section_types"] = baseline_penalized
    if not normalized["drift_risks"]:
        normalized["drift_risks"] = list(heuristic_plan.get("drift_risks") or [])
    normalized["normalization_notes"] = [
        "planner terms are source-anchored against a normalized chapter inventory",
        "heuristic anchors supplement the planner when the model under-specifies must terms or subpoints",
        "appendix is not globally penalized because some chapter specs legitimately seek scales or instruments",
    ]
    return normalized


def build_responses_input(messages: Sequence[Dict[str, str]]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for msg in messages:
        items.append({"role": msg.get("role") or "user", "content": [{"type": "input_text", "text": msg.get("content") or ""}]})
    return items


def parse_structured_response_payload(response: Any) -> Dict[str, Any]:
    parsed = getattr(response, "output_parsed", None)
    if parsed is None:
        raise RuntimeError("Structured query planner returned no parsed payload.")
    if hasattr(parsed, "model_dump"):
        return parsed.model_dump()
    if isinstance(parsed, dict):
        return dict(parsed)
    raise RuntimeError(f"Unsupported parsed payload type: {type(parsed).__name__}")


def call_openai_query_planner(
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    options: PhaseDOptions,
    stable_hash_fn: Any,
) -> Dict[str, Any]:
    if OpenAI is None or BaseModel is None:
        raise RuntimeError("OpenAI or pydantic is unavailable for the structured query planner.")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt_payload = build_query_planner_messages(chapter_title, chapter_spec_text, source_inventory, options)
    messages = prompt_payload["messages"]
    prompt_cache_key = f"phase_d::{stable_hash_fn(chapter_title, chapter_spec_text, 'planner_prompt', length=20)}"
    planner_attempts = [
        {
            "api_mode": "responses.parse",
            "model": options.openai_model,
            "reasoning_effort": options.reasoning_effort,
            "max_output_tokens": options.max_completion_tokens,
            "verbosity": "low",
        },
        {
            "api_mode": "responses.parse",
            "model": options.openai_model,
            "reasoning_effort": "low",
            "max_output_tokens": max(int(options.max_completion_tokens), 1800),
            "verbosity": "low",
        },
        {
            "api_mode": "chat.completions.parse",
            "model": options.openai_model,
            "reasoning_effort": "low",
            "max_completion_tokens": max(int(options.max_completion_tokens), 1800),
            "verbosity": "low",
        },
    ]
    if str(options.openai_model or "").strip() != "gpt-5-nano":
        planner_attempts.append(
            {
                "api_mode": "responses.parse",
                "model": "gpt-5-nano",
                "reasoning_effort": "low",
                "max_output_tokens": max(int(options.max_completion_tokens), 1500),
                "verbosity": "low",
            }
        )

    last_error = None
    attempt_traces: List[Dict[str, Any]] = []
    for attempt in planner_attempts:
        try:
            if attempt["api_mode"] == "responses.parse":
                request_kwargs = {
                    "model": attempt["model"],
                    "instructions": prompt_payload["system_prompt"],
                    "input": build_responses_input([messages[1]]),
                    "text_format": QueryPlanModel,
                    "reasoning": {"effort": attempt["reasoning_effort"]},
                    "max_output_tokens": attempt["max_output_tokens"],
                    "text": {"verbosity": attempt["verbosity"]},
                    "prompt_cache_key": prompt_cache_key,
                    "store": False,
                }
                if not str(attempt["model"] or "").startswith("gpt-5"):
                    request_kwargs["temperature"] = options.temperature
                response = client.responses.parse(**request_kwargs)
                plan_payload = parse_structured_response_payload(response)
            else:
                request_kwargs = {
                    "model": attempt["model"],
                    "messages": messages,
                    "response_format": QueryPlanModel,
                    "reasoning_effort": attempt["reasoning_effort"],
                    "max_completion_tokens": attempt["max_completion_tokens"],
                    "verbosity": attempt["verbosity"],
                    "prompt_cache_key": prompt_cache_key,
                    "store": False,
                }
                if not str(attempt["model"] or "").startswith("gpt-5"):
                    request_kwargs["temperature"] = options.temperature
                response = client.beta.chat.completions.parse(**request_kwargs)
                parsed = response.choices[0].message.parsed
                if parsed is None:
                    raise RuntimeError("Structured query planner returned no parsed payload.")
                plan_payload = parsed.model_dump()
            normalized_plan = normalize_query_plan(plan_payload, chapter_title, chapter_spec_text, source_inventory, options, stable_hash_fn)
            usage_payload = extract_openai_usage_payload(getattr(response, "usage", None))
            cost_payload = estimate_openai_text_cost_usd(str(getattr(response, "model", None) or attempt["model"]), usage_payload)
            raw_response = response.model_dump(mode="json") if hasattr(response, "model_dump") else {}
            return {
                "plan": normalized_plan,
                "planner_trace": {
                    "planner_mode": "openai",
                    "api_mode": attempt["api_mode"],
                    "model_requested": options.openai_model,
                    "model_used": str(getattr(response, "model", None) or attempt["model"]),
                    "message_count": len(messages),
                    "prompt_cache_key": prompt_cache_key,
                    "attempts": attempt_traces + [attempt],
                    "usage": usage_payload,
                    "cost": cost_payload,
                },
                "raw_response": raw_response,
                "prompt_payload": prompt_payload,
            }
        except Exception as e:
            last_error = e
            attempt_traces.append(
                {
                    **attempt,
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("Structured query planner failed without returning an error.")


def source_alignment_ratio(plan: Dict[str, Any], source_inventory: Dict[str, Any], options: PhaseDOptions) -> float:
    terms = [str(x) for x in (plan.get("must_terms") or []) + (plan.get("should_terms") or []) if str(x).strip()]
    if not terms:
        return 0.0
    hits = 0
    for term in terms:
        matched = match_term_to_source(term, source_inventory, options)
        if matched.get("matched"):
            hits += 1
    return round(hits / max(1, len(terms)), 3)


def build_compact_query_text(parts: Iterable[Any], *, separator: str = " | ", max_words: int = 64, max_chars: int = 360) -> str:
    joined = separator.join([clean_text(part) for part in parts if clean_text(part)]).strip()
    if not joined:
        return ""
    joined = truncate_words(joined, max_words=max_words)
    return truncate_text(joined, max_len=max_chars)


def is_bridge_section_title_candidate(title: Any) -> bool:
    cleaned = clean_text(title)
    lowered = cleaned.lower()
    if not cleaned:
        return False
    if lowered in {
        "front matter",
        "contents",
        "table of contents",
        "references",
        "acknowledgments",
        "acknowledgements",
        "preface",
        "title page",
        "copyright page",
        "index",
        "appendix",
    }:
        return False
    if lowered in {"abstract", "introduction", "background", "discussion", "conclusion", "results", "methods", "literature review"}:
        return False
    if re.fullmatch(r"\d+\.?\s+(introduction|discussion|conclusion|results|methods?)", lowered):
        return False
    words = count_words(cleaned)
    return 2 <= words <= 14 and len(cleaned) <= 120


def build_bridge_corpus_inventory(run_ctx: Any, options: PhaseDOptions) -> Dict[str, Any]:
    documents_path = Path(run_ctx.artifacts.normalized_dir) / "documents.jsonl"
    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    documents = read_jsonl_rows(documents_path)
    sections = read_jsonl_rows(sections_path)
    sections_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for row in sections:
        doc_id = str(row.get("doc_id") or "")
        if not doc_id:
            continue
        sections_by_doc.setdefault(doc_id, []).append(row)
    for rows in sections_by_doc.values():
        rows.sort(key=lambda item: (int(item.get("page_start") or 0), int(item.get("level") or 0), str(item.get("title") or "")))

    doc_rows: List[Dict[str, Any]] = []
    unique_titles: List[str] = []
    seen_titles = set()
    for doc in documents:
        doc_id = str(doc.get("doc_id") or "")
        doc_title = clean_text(doc.get("title") or "")
        section_titles: List[str] = []
        section_snippets: List[str] = []
        seen_doc_titles = set()
        for section in sections_by_doc.get(doc_id, []):
            title = clean_text(section.get("title") or "")
            if not is_bridge_section_title_candidate(title):
                continue
            if title in seen_doc_titles:
                continue
            seen_doc_titles.add(title)
            section_titles.append(title)
            if title not in seen_titles:
                seen_titles.add(title)
                unique_titles.append(title)
            if len(section_titles) >= int(options.bridge_section_titles_per_doc):
                break
        if int(options.bridge_sample_sections_per_doc) > 0:
            for section in sections_by_doc.get(doc_id, []):
                if not bool(section.get("retrieval_eligible", True)):
                    continue
                section_type = str(section.get("section_type") or "body_other")
                if section_type not in {"abstract", "introduction", "discussion", "conclusion", "results", "body_other"}:
                    continue
                text = clean_text(section.get("text") or section.get("contextualized_text") or "")
                if count_words(text) < 18:
                    continue
                snippet = truncate_text(truncate_words(text, max_words=28), max_len=int(options.bridge_section_snippet_chars))
                if not snippet or snippet in section_snippets:
                    continue
                section_snippets.append(snippet)
                if len(section_snippets) >= int(options.bridge_sample_sections_per_doc):
                    break
        doc_rows.append(
            {
                "doc_id": doc_id,
                "doc_title": doc_title,
                "section_titles": section_titles,
                "section_snippets": section_snippets,
            }
        )
    return {
        "doc_count": len(doc_rows),
        "unique_section_title_count": len(unique_titles),
        "doc_rows": doc_rows,
        "unique_section_titles": unique_titles,
    }


def build_bridge_generation_messages(
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    plan: Dict[str, Any],
    corpus_inventory: Dict[str, Any],
    options: PhaseDOptions,
) -> Dict[str, Any]:
    source_anchor_lines = "\n".join(f"- {item}" for item in (plan.get("source_anchors") or source_inventory.get("selected_anchors") or [])[:24])
    must_term_lines = "\n".join(f"- {item}" for item in (plan.get("must_terms") or [])[:12])
    corpus_lines = []
    for row in corpus_inventory.get("doc_rows") or []:
        section_titles = " | ".join([clean_text(item) for item in (row.get("section_titles") or []) if clean_text(item)])
        section_snippets = " || ".join([clean_text(item) for item in (row.get("section_snippets") or []) if clean_text(item)])
        if section_titles:
            line = f"- {clean_text(row.get('doc_title'))} :: headings: {section_titles}"
        else:
            line = f"- {clean_text(row.get('doc_title'))}"
        if section_snippets:
            line += f" :: snippets: {section_snippets}"
        corpus_lines.append(line)
    corpus_block = truncate_text("\n".join(corpus_lines), max_len=12000)
    system_prompt = (
        "You create bridge retrieval terms that connect a chapter request to an existing PDF corpus. "
        "Bridge terms may go beyond the literal chapter wording, but they must be justified by both the chapter source anchors and the provided corpus titles/headings/snippets. "
        "Prefer terms copied or lightly normalized from the corpus wording. "
        "Prioritize intermediary corpus vocabulary over repeating the chapter's direct must terms. "
        "Good bridge terms often name a topical object, source/actor, quality signal, trust cue, overload/friction concept, manipulation/problem type, or intervention mechanism found in the corpus. "
        "Each term must be short (1-5 words), reusable across papers, and likely to help retrieve relevant sections. "
        "Avoid vague words like study, paper, results, methods, introduction, discussion, framework, approach, model, analysis. "
        "Avoid broad academic filler like background, taxonomy, testing, future directions, or generic decision making. "
        "Do not invent unsupported domain drift. "
        "Return 4-12 bridge terms."
    )
    user_prompt = (
        f"Chapter title:\n{chapter_title}\n\n"
        f"Chapter spec:\n{chapter_spec_text}\n\n"
        "Source anchors already accepted from the chapter:\n"
        f"{source_anchor_lines or '-'}\n\n"
        "Current source-grounded must terms:\n"
        f"{must_term_lines or '-'}\n\n"
        "Corpus document titles, section headings, and sampled section snippets:\n"
        f"{corpus_block}\n\n"
        "Do not simply repeat the direct source anchors or must terms unless there is no better corpus-side bridge. "
        "Prefer terms taken from corpus wording that would help retrieve relevant sections even when the chapter wording is more abstract. "
        "Return bridge_terms as JSON. "
        "Each bridge term must include linked_source_anchors chosen from the source anchors above, a short source_link explanation, and 1-4 corpus_evidence strings copied from the corpus block. "
        "Prefer terms that are likely to appear verbatim in titles, headings, or body text."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
    return {"system_prompt": system_prompt, "user_prompt": user_prompt, "messages": messages}


def call_openai_bridge_term_generator(
    chapter_title: str,
    chapter_spec_text: str,
    source_inventory: Dict[str, Any],
    plan: Dict[str, Any],
    corpus_inventory: Dict[str, Any],
    options: PhaseDOptions,
    stable_hash_fn: Any,
) -> Dict[str, Any]:
    if OpenAI is None or BaseModel is None or BridgeTermPlanModel is None:
        raise RuntimeError("OpenAI or pydantic is unavailable for bridge-term generation.")
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is missing.")
    client = OpenAI(api_key=OPENAI_API_KEY)
    prompt_payload = build_bridge_generation_messages(chapter_title, chapter_spec_text, source_inventory, plan, corpus_inventory, options)
    messages = prompt_payload["messages"]
    prompt_cache_key = f"phase_d::{stable_hash_fn(chapter_title, chapter_spec_text, 'bridge_prompt', length=20)}"
    attempts = [
        {
            "api_mode": "responses.parse",
            "model": options.openai_model,
            "reasoning_effort": options.reasoning_effort,
            "max_output_tokens": options.bridge_max_completion_tokens,
        },
        {
            "api_mode": "chat.completions.parse",
            "model": options.openai_model,
            "reasoning_effort": options.reasoning_effort,
            "max_output_tokens": max(int(options.bridge_max_completion_tokens), 1200),
        },
    ]
    last_error: Optional[Exception] = None
    trace_attempts: List[Dict[str, Any]] = []
    for attempt in attempts:
        try:
            if attempt["api_mode"] == "responses.parse":
                response = client.responses.parse(
                    model=attempt["model"],
                    reasoning={"effort": attempt["reasoning_effort"]},
                    input=build_responses_input(messages),
                    max_output_tokens=int(attempt["max_output_tokens"]),
                    text_format=BridgeTermPlanModel,
                )
                plan_payload = parse_structured_response_payload(response)
                usage_payload = extract_openai_usage_payload(getattr(response, "usage", None))
                raw_response = response.model_dump() if hasattr(response, "model_dump") else {"id": getattr(response, "id", None)}
            else:
                response = client.beta.chat.completions.parse(
                    model=attempt["model"],
                    reasoning_effort=attempt["reasoning_effort"],
                    max_completion_tokens=int(attempt["max_output_tokens"]),
                    response_format=BridgeTermPlanModel,
                    messages=messages,
                )
                message = ((response.choices or [None])[0]).message
                parsed = getattr(message, "parsed", None)
                if parsed is None:
                    raise RuntimeError("Bridge-term generator returned no parsed payload.")
                plan_payload = parsed.model_dump() if hasattr(parsed, "model_dump") else dict(parsed)
                usage_payload = extract_openai_usage_payload(getattr(response, "usage", None))
                raw_response = response.model_dump() if hasattr(response, "model_dump") else {"id": getattr(response, "id", None)}
            cost_payload = estimate_openai_text_cost_usd(attempt["model"], usage_payload)
            planner_trace = {
                "planner_mode": "openai",
                "api_mode": attempt["api_mode"],
                "model_requested": options.openai_model,
                "model_used": attempt["model"],
                "reasoning_effort": attempt["reasoning_effort"],
                "message_count": len(messages),
                "prompt_cache_key": prompt_cache_key,
                "usage": usage_payload,
                "cost": cost_payload,
                "attempts": trace_attempts + [{**attempt, "status": "success"}],
            }
            return {
                "bridge_payload": plan_payload,
                "planner_trace": planner_trace,
                "raw_response": raw_response,
                "prompt_payload": prompt_payload,
            }
        except Exception as e:
            last_error = e
            trace_attempts.append(
                {
                    **attempt,
                    "status": "error",
                    "error_type": type(e).__name__,
                    "error_message": str(e),
                }
            )
    if last_error is not None:
        raise last_error
    raise RuntimeError("Structured bridge-term generator failed without returning an error.")


def derive_heuristic_bridge_terms(plan: Dict[str, Any], source_inventory: Dict[str, Any], run_ctx: Any, options: PhaseDOptions) -> List[Dict[str, Any]]:
    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    sections = [row for row in read_jsonl_rows(sections_path) if bool(row.get("retrieval_eligible", True))]
    existing_keys = {
        normalize_match_key(item)
        for item in list(plan.get("source_anchors") or []) + list(plan.get("must_terms") or []) + list(plan.get("should_terms") or [])
        if clean_text(item)
    }
    alias_seed_terms = (
        list(plan.get("source_anchors") or [])
        + list(plan.get("must_terms") or [])
        + list(plan.get("should_terms") or [])
        + [term for subpoint in (plan.get("subpoints") or []) for term in (subpoint.get("source_anchors") or []) + (subpoint.get("must_terms") or []) + (subpoint.get("should_terms") or [])]
    )
    alias_candidates = retrieval_alias_terms(alias_seed_terms, limit=max(int(options.bridge_term_limit) * 3, 18))
    rows = []
    for support in collect_term_support_rows(alias_candidates, sections, "bridge_heuristic"):
        term = clean_text(support.get("term") or "")
        if not term or normalize_match_key(term) in existing_keys:
            continue
        if not bridge_term_is_valid(term, allow_single_word=True):
            continue
        if int(support.get("section_hits") or 0) < 1:
            continue
        rows.append(
            {
                "term": term,
                "linked_source_anchors": [],
                "corpus_evidence": list(support.get("example_titles") or [])[:3],
                "source_link": "heuristic alias fallback",
                "candidate_origin": "heuristic_alias",
                "doc_hits": int(support.get("doc_hits") or 0),
                "section_hits": int(support.get("section_hits") or 0),
                "title_hits": int(support.get("title_hits") or 0),
                "text_hits": int(support.get("text_hits") or 0),
                "rank_score": round(
                    (int(support.get("doc_hits") or 0) * 4.0)
                    + (int(support.get("title_hits") or 0) * 3.0)
                    + (min(int(support.get("text_hits") or 0), 20) * 0.2)
                    + (1.0 if 2 <= count_words(term) <= 4 else 0.0),
                    6,
                ),
            }
        )
    rows.sort(key=lambda item: (int(item.get("doc_hits") or 0), int(item.get("title_hits") or 0), int(item.get("text_hits") or 0), -len(str(item.get("term") or ""))), reverse=True)
    return rows[: int(options.bridge_term_limit)]


def extract_bridge_phrase_candidates(text: Any, *, max_phrases: int = 20) -> List[str]:
    tokens = [token for token in normalize_match_tokens(clean_text(text)) if token and token not in PHASE_D_STOPWORDS]
    candidates: List[str] = []
    for n in (4, 3, 2):
        if len(tokens) < n:
            continue
        for start in range(len(tokens) - n + 1):
            phrase = " ".join(tokens[start : start + n])
            if count_words(phrase) < 2:
                continue
            if normalize_match_key(phrase) in PHASE_D_GENERIC_PHRASES:
                continue
            candidates.append(phrase)
    return unique_clean_terms(candidates, limit=max_phrases, max_words=5, max_chars=80)


def bridge_term_is_valid(term: Any, *, allow_single_word: bool = False) -> bool:
    normalized = clean_text(term)
    tokens = [token for token in normalize_match_tokens(normalized) if token]
    if not tokens:
        return False
    if not allow_single_word and len(tokens) < 2:
        return False
    if len(tokens) > 5:
        return False
    if normalize_match_key(normalized) in PHASE_D_GENERIC_PHRASES or normalize_match_key(normalized) in PHASE_D_BRIDGE_GENERIC_TERMS:
        return False
    if tokens[0] in PHASE_D_STOPWORDS or tokens[-1] in PHASE_D_STOPWORDS:
        return False
    content_tokens = [token for token in tokens if token not in PHASE_D_STOPWORDS]
    if len(set(content_tokens)) < (1 if allow_single_word else 2):
        return False
    return True


def attach_bridge_terms_to_plan(
    plan: Dict[str, Any],
    bridge_payload: Dict[str, Any],
    source_inventory: Dict[str, Any],
    run_ctx: Any,
    options: PhaseDOptions,
) -> Dict[str, Any]:
    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    sections = [row for row in read_jsonl_rows(sections_path) if bool(row.get("retrieval_eligible", True))]
    existing_keys = {
        normalize_match_key(item)
        for item in list(plan.get("source_anchors") or []) + list(plan.get("must_terms") or []) + list(plan.get("should_terms") or []) + list(plan.get("retrieval_should_terms") or [])
        if clean_text(item)
    }
    raw_candidates: List[Dict[str, Any]] = []
    for raw in bridge_payload.get("bridge_terms") or []:
        linked = source_anchor_terms(raw.get("linked_source_anchors") or [], source_inventory, options, limit=3, max_words=10, max_chars=120)
        if not linked.get("kept"):
            continue
        raw_evidence = [truncate_text(clean_text(item), max_len=160) for item in (raw.get("corpus_evidence") or []) if clean_text(item)][:4]
        term_candidates = unique_clean_terms([raw.get("term")], limit=1, max_words=5, max_chars=80)
        for term in term_candidates:
            raw_candidates.append(
                {
                    "term": term,
                    "linked_source_anchors": list(linked.get("kept") or []),
                    "source_link": truncate_text(clean_text(raw.get("source_link") or ""), max_len=160),
                    "corpus_evidence": raw_evidence,
                    "candidate_origin": "model_term",
                }
            )
        for evidence_text in raw_evidence:
            for phrase in extract_bridge_phrase_candidates(evidence_text, max_phrases=16):
                raw_candidates.append(
                    {
                        "term": phrase,
                        "linked_source_anchors": list(linked.get("kept") or []),
                        "source_link": truncate_text(clean_text(raw.get("source_link") or ""), max_len=160),
                        "corpus_evidence": raw_evidence,
                        "candidate_origin": "evidence_phrase",
                    }
                )

    bridge_rows: List[Dict[str, Any]] = []
    for raw in raw_candidates:
        term = clean_text(raw.get("term") or "")
        term_key = normalize_match_key(term)
        if not term_key or term_key in existing_keys:
            continue
        if not bridge_term_is_valid(term):
            continue
        support_rows = collect_term_support_rows([term], sections, "bridge")
        support = support_rows[0] if support_rows else {}
        if int(support.get("section_hits") or 0) < 1:
            continue
        rank_score = (
            (int(support.get("doc_hits") or 0) * 4.0)
            + (int(support.get("title_hits") or 0) * 3.0)
            + (min(int(support.get("text_hits") or 0), 20) * 0.2)
            + (1.5 if 2 <= count_words(term) <= 4 else 0.0)
        )
        bridge_rows.append(
            {
                "term": term,
                "linked_source_anchors": list(raw.get("linked_source_anchors") or []),
                "source_link": raw.get("source_link"),
                "corpus_evidence": list(raw.get("corpus_evidence") or [])[:4],
                "candidate_origin": raw.get("candidate_origin"),
                "doc_hits": int(support.get("doc_hits") or 0),
                "section_hits": int(support.get("section_hits") or 0),
                "title_hits": int(support.get("title_hits") or 0),
                "text_hits": int(support.get("text_hits") or 0),
                "example_titles": list(support.get("example_titles") or [])[:4],
                "rank_score": round(rank_score, 6),
            }
        )
        existing_keys.add(term_key)
    bridge_rows.sort(
        key=lambda item: (
            float(item.get("rank_score") or 0.0),
            int(item.get("doc_hits") or 0),
            int(item.get("title_hits") or 0),
            int(item.get("text_hits") or 0),
            len(item.get("linked_source_anchors") or []),
            -len(str(item.get("term") or "")),
        ),
        reverse=True,
    )
    bridge_rows = bridge_rows[: int(options.bridge_term_limit)]
    plan["bridge_term_rows"] = bridge_rows
    plan["bridge_terms"] = [row.get("term") for row in bridge_rows if row.get("term")]
    plan["bridge_generation"] = {
        "performed": bool(bridge_rows),
        "bridge_term_count": len(bridge_rows),
    }
    return plan


def build_retrieval_views(plan: Dict[str, Any], options: PhaseDOptions) -> Dict[str, Any]:
    def join_terms(items: List[str], limit: int = 12) -> str:
        return " | ".join([clean_text(x) for x in (items or []) if clean_text(x)][: int(limit)])

    supported_should_terms = list(plan.get("retrieval_should_terms") or plan.get("corpus_supported_should_terms") or [])
    bridge_rows = list(plan.get("bridge_term_rows") or [])
    bridge_terms = [clean_text(row.get("term") or "") for row in bridge_rows if clean_text(row.get("term") or "")]
    bridge_lexical_text = join_terms(bridge_terms, limit=10)
    broad_text = build_compact_query_text(
        [
            clean_text(plan.get("chapter_title")),
            truncate_words(plan.get("chapter_summary"), max_words=28),
            join_terms(plan.get("must_terms") or [], limit=5),
            join_terms(supported_should_terms, limit=4),
            join_terms(bridge_terms, limit=3),
        ],
        separator=" | ",
        max_words=64,
        max_chars=340,
    )
    retrieval_views = {
        "title_lexical": {
            "view_id": "title_lexical",
            "kind": "title_lexical",
            "query_text": build_compact_query_text(
                [clean_text(plan.get("chapter_title")), join_terms(plan.get("must_terms") or [], limit=5)],
                separator=" | ",
                max_words=22,
                max_chars=220,
            ),
            "anchor_terms": list(plan.get("must_terms") or [])[:5],
            "target_units": ["section_title"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "summary_semantic": {
            "view_id": "summary_semantic",
            "kind": "summary_semantic",
            "query_text": build_compact_query_text(
                [clean_text(plan.get("chapter_summary"))],
                separator=" ",
                max_words=54,
                max_chars=320,
            ),
            "anchor_terms": list(plan.get("source_anchors") or [])[:6],
            "target_units": ["section_contextualized", "passage_contextualized"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "must_terms_lexical": {
            "view_id": "must_terms_lexical",
            "kind": "must_terms_lexical",
            "query_text": join_terms(plan.get("must_terms") or [], limit=12),
            "anchor_terms": list(plan.get("must_terms") or [])[:12],
            "target_units": ["section_text", "passage_text"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "should_terms_lexical": {
            "view_id": "should_terms_lexical",
            "kind": "should_terms_lexical",
            "query_text": join_terms(supported_should_terms or plan.get("should_terms") or [], limit=12),
            "anchor_terms": list((supported_should_terms or plan.get("should_terms") or []))[:12],
            "target_units": ["section_title", "section_text", "passage_text"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "bridge_lexical": {
            "view_id": "bridge_lexical",
            "kind": "bridge_lexical",
            "query_text": bridge_lexical_text,
            "anchor_terms": bridge_terms[:8],
            "target_units": ["section_text", "passage_text"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "bridge_semantic": {
            "view_id": "bridge_semantic",
            "kind": "bridge_semantic",
            "query_text": build_compact_query_text(
                [clean_text(plan.get("chapter_summary")), join_terms(bridge_terms, limit=6)],
                separator=" | ",
                max_words=64,
                max_chars=340,
            ),
            "anchor_terms": bridge_terms[:6],
            "target_units": ["section_contextualized", "passage_contextualized"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "subpoint_views": [],
        "subpoint_lexical_views": [],
        "broad_fallback": {
            "view_id": "broad_fallback",
            "kind": "broad_fallback",
            "query_text": broad_text,
            "anchor_terms": list(plan.get("source_anchors") or [])[:8],
            "target_units": ["section_contextualized", "passage_contextualized"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
        "support_context_semantic": {
            "view_id": "support_context_semantic",
            "kind": "support_context_semantic",
            "query_text": build_compact_query_text(
                [
                    clean_text(plan.get("chapter_summary")),
                    join_terms(supported_should_terms or plan.get("should_terms") or [], limit=6),
                    join_terms([clean_text(item.get("label") or "") for item in (plan.get("subpoints") or [])], limit=3),
                ],
                separator=" | ",
                max_words=72,
                max_chars=360,
            ),
            "anchor_terms": list((supported_should_terms or plan.get("should_terms") or []))[:8],
            "target_units": ["section_contextualized", "passage_contextualized"],
            "preferred_section_types": plan.get("preferred_section_types") or [],
        },
    }
    if not bool(options.include_should_terms_view) or not clean_text((retrieval_views.get("should_terms_lexical") or {}).get("query_text")):
        retrieval_views.pop("should_terms_lexical", None)
    if not bool(options.include_support_context_view) or not clean_text((retrieval_views.get("support_context_semantic") or {}).get("query_text")):
        retrieval_views.pop("support_context_semantic", None)
    for subpoint in plan.get("subpoints") or []:
        subpoint_keys = {
            normalize_match_key(item)
            for item in list(subpoint.get("source_anchors") or []) + list(subpoint.get("must_terms") or []) + list(subpoint.get("should_terms") or [])
            if clean_text(item)
        }
        linked_bridge_terms = unique_clean_terms(
            [
                row.get("term")
                for row in bridge_rows
                if row.get("term")
                and (
                    not (row.get("linked_source_anchors") or [])
                    or subpoint_keys & {normalize_match_key(item) for item in (row.get("linked_source_anchors") or []) if clean_text(item)}
                )
            ],
            limit=2,
            max_words=5,
            max_chars=80,
        )
        retrieval_views["subpoint_views"].append(
            {
                "view_id": f"subpoint::{subpoint.get('subpoint_id')}",
                "kind": "subpoint",
                "label": subpoint.get("label"),
                "query_text": build_compact_query_text(
                    [
                        clean_text(subpoint.get("label")),
                        truncate_words(subpoint.get("summary"), max_words=24),
                        join_terms(subpoint.get("source_anchors") or [], limit=3),
                        join_terms(subpoint.get("must_terms") or [], limit=3),
                        join_terms(linked_bridge_terms, limit=2),
                    ],
                    separator=" | ",
                    max_words=42,
                    max_chars=280,
                ),
                "anchor_terms": list(subpoint.get("source_anchors") or [])[:3] + list(subpoint.get("must_terms") or [])[:3] + linked_bridge_terms[:2],
                "bridge_terms": linked_bridge_terms,
                "target_units": ["section_contextualized", "passage_contextualized"],
                "preferred_section_types": subpoint.get("preferred_section_types") or plan.get("preferred_section_types") or [],
            }
        )
        if bool(options.include_subpoint_lexical_views):
            retrieval_views["subpoint_lexical_views"].append(
                {
                    "view_id": f"subpoint_lexical::{subpoint.get('subpoint_id')}",
                    "kind": "subpoint_lexical",
                    "label": subpoint.get("label"),
                    "query_text": build_compact_query_text(
                        [
                            clean_text(subpoint.get("label")),
                            join_terms(subpoint.get("source_anchors") or [], limit=3),
                            join_terms(subpoint.get("must_terms") or [], limit=3),
                            join_terms(linked_bridge_terms, limit=2),
                        ],
                        separator=" | ",
                        max_words=26,
                        max_chars=220,
                    ),
                    "anchor_terms": list(subpoint.get("source_anchors") or [])[:3] + list(subpoint.get("must_terms") or [])[:3] + linked_bridge_terms[:2],
                    "bridge_terms": linked_bridge_terms,
                    "target_units": ["section_title", "section_text", "passage_text"],
                    "preferred_section_types": subpoint.get("preferred_section_types") or plan.get("preferred_section_types") or [],
                }
            )
    return retrieval_views


def flatten_retrieval_views(retrieval_views: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for key in ["title_lexical", "summary_semantic", "must_terms_lexical", "should_terms_lexical", "bridge_lexical", "bridge_semantic", "support_context_semantic", "broad_fallback"]:
        view = retrieval_views.get(key) or {}
        if not clean_text(view.get("query_text")):
            continue
        rows.append(
            {
                "view_id": view.get("view_id"),
                "kind": view.get("kind"),
                "target_units": ", ".join(view.get("target_units") or []),
                "preferred_section_types": ", ".join(view.get("preferred_section_types") or []),
                "anchor_terms": ", ".join(view.get("anchor_terms") or []),
                "query_word_count": count_words(clean_text(view.get("query_text"))),
                "query_text": truncate_text(clean_text(view.get("query_text")), max_len=220),
            }
        )
    for view in retrieval_views.get("subpoint_views") or []:
        rows.append(
            {
                "view_id": view.get("view_id"),
                "kind": view.get("kind"),
                "target_units": ", ".join(view.get("target_units") or []),
                "preferred_section_types": ", ".join(view.get("preferred_section_types") or []),
                "anchor_terms": ", ".join(view.get("anchor_terms") or []),
                "query_word_count": count_words(clean_text(view.get("query_text"))),
                "query_text": truncate_text(clean_text(view.get("query_text")), max_len=220),
            }
        )
    for view in retrieval_views.get("subpoint_lexical_views") or []:
        rows.append(
            {
                "view_id": view.get("view_id"),
                "kind": view.get("kind"),
                "target_units": ", ".join(view.get("target_units") or []),
                "preferred_section_types": ", ".join(view.get("preferred_section_types") or []),
                "anchor_terms": ", ".join(view.get("anchor_terms") or []),
                "query_word_count": count_words(clean_text(view.get("query_text"))),
                "query_text": truncate_text(clean_text(view.get("query_text")), max_len=220),
            }
        )
    return rows


def collect_term_support_rows(terms: Iterable[Any], sections: List[Dict[str, Any]], kind: str) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for term in terms or []:
        section_hits = []
        title_hits = 0
        text_hits = 0
        doc_ids = set()
        titles = []
        for row in sections:
            section_id = str(row.get("section_id") or "")
            title = clean_text(row.get("title") or "")
            body = clean_text(row.get("contextualized_text") or row.get("text") or "")
            matched_title = text_contains_term(title, term)
            matched_body = text_contains_term(body, term)
            if matched_title:
                title_hits += 1
            if matched_body:
                text_hits += 1
            if matched_title or matched_body:
                section_hits.append(section_id)
                doc_ids.add(str(row.get("doc_id") or ""))
                titles.append(title)
        rows.append(
            {
                "kind": kind,
                "term": term,
                "title_hits": title_hits,
                "text_hits": text_hits,
                "section_hits": len(section_hits),
                "doc_hits": len([doc for doc in doc_ids if doc]),
                "example_titles": list(dict.fromkeys([title for title in titles if title]))[:3],
            }
        )
    return rows


def recalibrate_plan_with_corpus_support(plan: Dict[str, Any], run_ctx: Any, source_inventory: Dict[str, Any], options: PhaseDOptions) -> Dict[str, Any]:
    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    if not sections_path.exists():
        return plan
    sections = [row for row in read_jsonl_rows(sections_path) if bool(row.get("retrieval_eligible", True))]
    if not sections:
        return plan
    candidate_terms = unique_clean_terms(
        list(plan.get("must_terms") or [])
        + list(plan.get("should_terms") or [])
        + list(plan.get("source_anchors") or [])
        + [term for subpoint in (plan.get("subpoints") or []) for term in (subpoint.get("must_terms") or []) + (subpoint.get("should_terms") or []) + (subpoint.get("source_anchors") or [])],
        limit=64,
        max_words=8,
        max_chars=120,
    )
    support_rows = collect_term_support_rows(candidate_terms, sections, "candidate")
    for row in support_rows:
        support_score = (int(row.get("doc_hits") or 0) * 4.0) + (int(row.get("title_hits") or 0) * 2.0) + min(int(row.get("text_hits") or 0), 20) * 0.2
        row["rank_score"] = round(term_priority_score(str(row.get("term") or ""), source_inventory) + support_score, 4)
    support_rows.sort(key=lambda item: (float(item.get("rank_score") or 0.0), int(item.get("doc_hits") or 0), int(item.get("title_hits") or 0), int(item.get("text_hits") or 0)), reverse=True)
    supported_rows = [row for row in support_rows if int(row.get("section_hits") or 0) > 0]
    if len(supported_rows) < 2:
        return plan
    must_candidate_rows = [row for row in supported_rows if int(row.get("doc_hits") or 0) >= 3 or int(row.get("section_hits") or 0) >= 5]
    if len(must_candidate_rows) < 2:
        must_candidate_rows = supported_rows
    original_must_terms = list(plan.get("must_terms") or [])
    original_should_terms = list(plan.get("should_terms") or [])
    new_must_terms = [row.get("term") for row in must_candidate_rows[: int(options.must_term_limit)] if row.get("term")]
    remaining_terms = [row.get("term") for row in support_rows if row.get("term") and row.get("term") not in new_must_terms]
    remaining_supported_terms = [
        row.get("term")
        for row in supported_rows
        if row.get("term") and row.get("term") not in new_must_terms and (int(row.get("doc_hits") or 0) >= 2 or int(row.get("section_hits") or 0) >= 4)
    ]
    alias_seed_terms = (
        list(plan.get("source_anchors") or [])
        + original_must_terms
        + original_should_terms
        + [term for subpoint in (plan.get("subpoints") or []) for term in (subpoint.get("source_anchors") or []) + (subpoint.get("must_terms") or []) + (subpoint.get("should_terms") or [])]
    )
    alias_candidates = [
        alias
        for alias in retrieval_alias_terms(alias_seed_terms, limit=max(int(options.should_term_limit) * 3, 18))
        if normalize_match_key(alias) not in {normalize_match_key(item) for item in new_must_terms}
    ]
    alias_rows = [row for row in collect_term_support_rows(alias_candidates, sections, "alias") if int(row.get("section_hits") or 0) > 0]
    alias_rows.sort(key=lambda item: (int(item.get("doc_hits") or 0), int(item.get("title_hits") or 0), int(item.get("text_hits") or 0), len(str(item.get("term") or ""))), reverse=True)
    retrieval_should_terms = unique_clean_terms(
        remaining_supported_terms + [row.get("term") for row in alias_rows if row.get("term")] + alias_candidates,
        limit=options.should_term_limit,
        max_words=8,
        max_chars=120,
    )
    plan["pre_corpus_rebalance_must_terms"] = original_must_terms
    plan["pre_corpus_rebalance_should_terms"] = original_should_terms
    plan["must_terms"] = new_must_terms
    plan["should_terms"] = unique_clean_terms(remaining_terms + original_should_terms, limit=options.should_term_limit, max_words=8, max_chars=120)
    plan["retrieval_should_terms"] = retrieval_should_terms
    supported_term_keys = {normalize_match_key(item) for item in retrieval_should_terms if item}
    plan["corpus_supported_should_terms"] = retrieval_should_terms[: int(options.should_term_limit)]
    plan["corpus_unsupported_should_terms"] = [
        item for item in (plan.get("should_terms") or []) if normalize_match_key(item) not in supported_term_keys
    ][: int(options.should_term_limit)]
    plan["corpus_rebalance"] = {
        "performed": True,
        "supported_candidate_count": len(supported_rows),
        "selected_must_terms": list(new_must_terms),
        "selected_retrieval_should_terms": list(retrieval_should_terms),
        "alias_support_count": len(alias_rows),
    }
    return plan


def suppress_unsupported_subpoints(plan: Dict[str, Any], corpus_support: Dict[str, Any]) -> Dict[str, Any]:
    rows = list(corpus_support.get("subpoint_rows") or [])
    if not rows:
        return plan
    support_by_id = {str(row.get("subpoint_id") or ""): row for row in rows if str(row.get("subpoint_id") or "")}
    subpoints = list(plan.get("subpoints") or [])
    if not subpoints:
        return plan
    supported = []
    suppressed = []
    for subpoint in subpoints:
        row = support_by_id.get(str(subpoint.get("subpoint_id") or "")) or {}
        if int(row.get("matched_sections") or 0) > 0:
            supported.append(subpoint)
            continue
        suppressed.append(
            {
                "subpoint_id": subpoint.get("subpoint_id"),
                "label": subpoint.get("label"),
                "reason": "zero_lexical_support_in_current_corpus",
                "anchor_terms": list(row.get("anchor_terms") or []),
            }
        )
    if not suppressed or len(supported) < 2:
        plan["suppressed_subpoints"] = suppressed
        plan["subpoint_suppression"] = {
            "performed": False,
            "kept_count": len(subpoints),
            "suppressed_count": len(suppressed),
        }
        return plan
    plan["subpoints"] = supported
    plan["suppressed_subpoints"] = suppressed
    plan["subpoint_suppression"] = {
        "performed": True,
        "kept_count": len(supported),
        "suppressed_count": len(suppressed),
    }
    return plan


def analyze_corpus_support(plan: Dict[str, Any], run_ctx: Any) -> Dict[str, Any]:
    sections_path = Path(run_ctx.artifacts.normalized_dir) / "sections.jsonl"
    if not sections_path.exists():
        return {"status": "missing_sections", "term_rows": [], "subpoint_rows": [], "summary": {}}
    sections = [row for row in read_jsonl_rows(sections_path) if bool(row.get("retrieval_eligible", True))]
    term_rows = collect_term_support_rows(plan.get("must_terms") or [], sections, "must") + collect_term_support_rows(plan.get("should_terms") or [], sections, "should")
    subpoint_rows: List[Dict[str, Any]] = []
    for subpoint in plan.get("subpoints") or []:
        terms = unique_clean_terms(
            list(subpoint.get("source_anchors") or []) + list(subpoint.get("must_terms") or []) + list(subpoint.get("should_terms") or []),
            limit=8,
            max_words=10,
            max_chars=120,
        )
        matched_sections = set()
        matched_docs = set()
        titles = []
        for row in sections:
            section_id = str(row.get("section_id") or "")
            title = clean_text(row.get("title") or "")
            body = clean_text(row.get("contextualized_text") or row.get("text") or "")
            hit_count = sum(1 for term in terms if text_contains_term(title, term) or text_contains_term(body, term))
            if hit_count > 0:
                matched_sections.add(section_id)
                matched_docs.add(str(row.get("doc_id") or ""))
                titles.append(title)
        subpoint_rows.append(
            {
                "subpoint_id": subpoint.get("subpoint_id"),
                "label": subpoint.get("label"),
                "anchor_terms": terms,
                "matched_sections": len(matched_sections),
                "matched_docs": len([doc for doc in matched_docs if doc]),
                "example_titles": list(dict.fromkeys([title for title in titles if title]))[:4],
            }
        )
    must_rows = [row for row in term_rows if row.get("kind") == "must"]
    summary = {
        "section_count": len(sections),
        "must_term_unsupported_count": sum(1 for row in must_rows if int(row.get("section_hits") or 0) == 0),
        "must_term_supported_count": sum(1 for row in must_rows if int(row.get("section_hits") or 0) > 0),
        "should_term_unsupported_count": sum(1 for row in term_rows if row.get("kind") == "should" and int(row.get("section_hits") or 0) == 0),
        "subpoints_without_support": sum(1 for row in subpoint_rows if int(row.get("matched_sections") or 0) == 0),
    }
    return {
        "status": "ok",
        "term_rows": term_rows,
        "subpoint_rows": subpoint_rows,
        "summary": summary,
    }


def assess_phase_d(
    plan: Dict[str, Any],
    retrieval_views: Dict[str, Any],
    *,
    options: PhaseDOptions,
    planner_trace: Dict[str, Any],
    source_inventory: Dict[str, Any],
    corpus_support: Dict[str, Any],
) -> Dict[str, Any]:
    failures: List[str] = []
    warnings: List[str] = []
    if not clean_text(plan.get("chapter_summary")):
        failures.append("chapter_summary is empty")
    if not (plan.get("must_terms") or []):
        failures.append("must_terms is empty")
    if not (plan.get("source_anchors") or []):
        failures.append("source_anchors is empty")
    subpoints = plan.get("subpoints") or []
    if len(subpoints) < 1:
        failures.append("subpoints is empty")
    if len(subpoints) > 8:
        warnings.append(f"subpoint count is high ({len(subpoints)})")
    if len(plan.get("drift_risks") or []) < 1:
        warnings.append("drift_risks is empty")
    pruned_terms = plan.get("source_pruned_terms") or {}
    pruned_count = len(pruned_terms.get("must_terms") or []) + len(pruned_terms.get("should_terms") or [])
    pruned_subpoint_count = 0
    for row in pruned_terms.get("subpoints") or []:
        pruned_subpoint_count += len(row.get("source_anchors") or []) + len(row.get("must_terms") or []) + len(row.get("should_terms") or [])
    if pruned_count > 4:
        warnings.append(f"planner produced {pruned_count} source-unanchored global terms that were pruned")
    if pruned_subpoint_count > 0:
        warnings.append(f"planner produced {pruned_subpoint_count} source-unanchored subpoint terms that were pruned")
    if planner_trace.get("planner_mode") != "openai":
        warnings.append("heuristic fallback planner was used")
    alignment = source_alignment_ratio(plan, source_inventory, options)
    if alignment < 0.9:
        warnings.append(f"source alignment is lower than expected ({alignment})")
    view_rows = flatten_retrieval_views(retrieval_views)
    if len(view_rows) < 4:
        failures.append("derived retrieval view count is too low")
    if corpus_support.get("status") == "ok":
        unsupported_must = int((corpus_support.get("summary") or {}).get("must_term_unsupported_count") or 0)
        if unsupported_must >= max(2, int(len(plan.get("must_terms") or []) * 0.5)):
            warnings.append(f"{unsupported_must} must terms have zero lexical support in the current corpus")
        unsupported_subpoints = int((corpus_support.get("summary") or {}).get("subpoints_without_support") or 0)
        if unsupported_subpoints > 0:
            warnings.append(f"{unsupported_subpoints} subpoints have zero lexical support in the current corpus")

    status = "success"
    quality_band = "high"
    if failures:
        status = "failed"
        quality_band = "insufficient"
    elif warnings:
        status = "success_with_warnings"
        quality_band = "acceptable_with_issues"

    qc_rows = [
        qc_row(check="chapter_summary", status="OK" if clean_text(plan.get("chapter_summary")) else "FAIL", value=bool(clean_text(plan.get("chapter_summary"))), expected="non-empty", why="Retrieval needs a normalized chapter summary.", fix="inspect query_plan.json and planner trace"),
        qc_row(check="source_anchors", status="OK" if len(plan.get("source_anchors") or []) >= 4 else "WARN", value=len(plan.get("source_anchors") or []), expected=">= 4", why="Source anchors make the planner auditable and reduce drift.", fix="inspect source_anchor_inventory.json and planner prompt"),
        qc_row(check="must_terms", status="OK" if len(plan.get("must_terms") or []) >= 2 else "FAIL", value=len(plan.get("must_terms") or []), expected=">= 2", why="Must terms anchor lexical retrieval.", fix="inspect planner output or heuristic fallback"),
        qc_row(check="subpoints", status="OK" if 1 <= len(subpoints) <= 8 else "WARN", value=len(subpoints), expected="1-8", why="Subpoints support diversified retrieval views.", fix="tighten planner prompt or subpoint limit"),
        qc_row(check="retrieval_views", status="OK" if len(view_rows) >= 4 else "FAIL", value=len(view_rows), expected=">= 4", why="Phase E should consume multiple derived views.", fix="inspect retrieval view derivation"),
        qc_row(check="source_alignment", status="OK" if alignment >= 0.9 else "WARN", value=alignment, expected=">= 0.9", why="Low alignment means the planner is drifting beyond the chapter source.", fix="inspect must_terms / should_terms against source_anchor_inventory.json"),
        qc_row(check="source_pruned_terms", status="OK" if pruned_count <= 4 else "WARN", value=pruned_count, expected="<= 4 preferred", why="Pruned terms indicate planner drift away from the chapter wording.", fix="inspect source_pruned_terms in query_plan.json and planner prompt"),
    ]
    if corpus_support.get("status") == "ok":
        qc_rows.append(
            qc_row(
                check="must_term_corpus_support",
                status="OK" if int((corpus_support.get("summary") or {}).get("must_term_unsupported_count") or 0) == 0 else "WARN",
                value=int((corpus_support.get("summary") or {}).get("must_term_unsupported_count") or 0),
                expected="0 preferred",
                why="Unsupported must terms are weak lexical anchors for the current run corpus.",
                fix="inspect phase_d_corpus_support.json and consider tightening must term selection",
            )
        )

    return {
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": not failures,
        "failures": failures,
        "warnings": warnings,
        "counts": {
            "source_anchor_count": len(plan.get("source_anchors") or []),
            "must_term_count": len(plan.get("must_terms") or []),
            "should_term_count": len(plan.get("should_terms") or []),
            "subpoint_count": len(subpoints),
            "retrieval_view_count": len(view_rows),
            "source_pruned_term_count": pruned_count,
        },
        "source_alignment_ratio": alignment,
        "qc_rows": qc_rows,
    }


def run_phase_d(
    run_ctx: Any,
    *,
    chapter_title: str,
    chapter_spec_text: str,
    options: PhaseDOptions,
    stable_hash_fn=None,
    log_event_fn=None,
    run_logger=None,
) -> Dict[str, Any]:
    options = options.normalized()
    stable_hash_local = stable_hash_fn or stable_hash
    retrieval_dir = ensure_dir(Path(run_ctx.artifacts.retrieval_dir))
    query_plan_path = Path(run_ctx.artifacts.query_plan_json)
    config_path = retrieval_dir / "phase_d_config.json"
    runtime_path = retrieval_dir / "phase_d_runtime.json"
    query_views_path = retrieval_dir / "query_views.json"
    summary_path = retrieval_dir / "phase_d_summary.json"
    assessment_path = retrieval_dir / "phase_d_assessment.json"
    planner_trace_path = retrieval_dir / "planner_trace.json"
    planner_prompt_path = retrieval_dir / "planner_prompt.json"
    planner_response_path = retrieval_dir / "planner_response.json"
    bridge_trace_path = retrieval_dir / "bridge_trace.json"
    bridge_prompt_path = retrieval_dir / "bridge_prompt.json"
    bridge_response_path = retrieval_dir / "bridge_response.json"
    bridge_corpus_inventory_path = retrieval_dir / "bridge_corpus_inventory.json"
    source_inventory_path = retrieval_dir / "source_anchor_inventory.json"
    corpus_support_path = retrieval_dir / "phase_d_corpus_support.json"

    runtime_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_d",
        "options": json_safe(asdict(options)),
        "capabilities": phase_d_capabilities(),
    }
    write_json(runtime_path, runtime_payload)
    write_json(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_d", "options": json_safe(asdict(options))})

    source_inventory = build_source_anchor_inventory(chapter_title, chapter_spec_text, options)
    write_json(source_inventory_path, source_inventory)

    if run_logger is not None:
        run_logger.info(
            "Phase D start | openai=%s | api_key=%s | model=%s | allow_heuristic_fallback=%s",
            bool(OpenAI is not None),
            bool(OPENAI_API_KEY),
            options.openai_model,
            options.allow_heuristic_fallback,
        )

    planner_trace: Dict[str, Any]
    bridge_trace: Dict[str, Any] = {"planner_mode": "disabled"}
    raw_response: Dict[str, Any] = {}
    prompt_payload: Dict[str, Any] = {}
    bridge_raw_response: Dict[str, Any] = {}
    bridge_prompt_payload: Dict[str, Any] = {}
    if options.use_openai_planner:
        try:
            planner_result = call_openai_query_planner(chapter_title, chapter_spec_text, source_inventory, options, stable_hash_local)
            plan = planner_result["plan"]
            planner_trace = planner_result["planner_trace"]
            raw_response = planner_result.get("raw_response") or {}
            prompt_payload = planner_result.get("prompt_payload") or {}
        except Exception as e:
            if not options.allow_heuristic_fallback:
                raise
            plan = build_heuristic_query_plan(chapter_title, chapter_spec_text, source_inventory, options, stable_hash_local)
            prompt_payload = build_query_planner_messages(chapter_title, chapter_spec_text, source_inventory, options)
            planner_trace = {
                "planner_mode": "heuristic_fallback",
                "planner_error": {"type": type(e).__name__, "message": str(e)},
                "model_requested": options.openai_model,
            }
    else:
        plan = build_heuristic_query_plan(chapter_title, chapter_spec_text, source_inventory, options, stable_hash_local)
        prompt_payload = build_query_planner_messages(chapter_title, chapter_spec_text, source_inventory, options)
        planner_trace = {"planner_mode": "heuristic_only", "model_requested": None}

    plan = recalibrate_plan_with_corpus_support(plan, run_ctx, source_inventory, options)
    bridge_corpus_inventory = build_bridge_corpus_inventory(run_ctx, options)
    write_json(bridge_corpus_inventory_path, bridge_corpus_inventory)
    if options.use_openai_bridge_terms:
        try:
            bridge_result = call_openai_bridge_term_generator(
                chapter_title,
                chapter_spec_text,
                source_inventory,
                plan,
                bridge_corpus_inventory,
                options,
                stable_hash_local,
            )
            bridge_trace = bridge_result["planner_trace"]
            bridge_raw_response = bridge_result.get("raw_response") or {}
            bridge_prompt_payload = bridge_result.get("prompt_payload") or {}
            plan = attach_bridge_terms_to_plan(plan, bridge_result.get("bridge_payload") or {}, source_inventory, run_ctx, options)
            heuristic_bridge_rows = derive_heuristic_bridge_terms(plan, source_inventory, run_ctx, options)
            existing_bridge_keys = {normalize_match_key(item) for item in (plan.get("bridge_terms") or []) if clean_text(item)}
            merged_bridge_rows = list(plan.get("bridge_term_rows") or [])
            for row in heuristic_bridge_rows:
                term = clean_text(row.get("term") or "")
                term_key = normalize_match_key(term)
                if not term or not term_key or term_key in existing_bridge_keys or term_key in PHASE_D_BRIDGE_GENERIC_TERMS:
                    continue
                merged_bridge_rows.append(dict(row))
                existing_bridge_keys.add(term_key)
            merged_bridge_rows.sort(
                key=lambda item: (
                    float(item.get("rank_score") or 0.0),
                    int(item.get("doc_hits") or 0),
                    int(item.get("title_hits") or 0),
                    int(item.get("text_hits") or 0),
                    len(item.get("linked_source_anchors") or []),
                ),
                reverse=True,
            )
            merged_bridge_rows = merged_bridge_rows[: int(options.bridge_term_limit)]
            plan["bridge_term_rows"] = merged_bridge_rows
            plan["bridge_terms"] = [row.get("term") for row in merged_bridge_rows if row.get("term")]
            plan["bridge_generation"] = {
                **(plan.get("bridge_generation") or {}),
                "performed": bool(merged_bridge_rows),
                "bridge_term_count": len(merged_bridge_rows),
                "heuristic_merge_count": max(len(merged_bridge_rows) - len(list(bridge_result.get("bridge_payload", {}).get("bridge_terms") or [])), 0),
            }
        except Exception as e:
            heuristic_bridge_rows = derive_heuristic_bridge_terms(plan, source_inventory, run_ctx, options)
            plan["bridge_term_rows"] = heuristic_bridge_rows
            plan["bridge_terms"] = [row.get("term") for row in heuristic_bridge_rows if row.get("term")]
            plan["bridge_generation"] = {
                "performed": bool(heuristic_bridge_rows),
                "bridge_term_count": len(heuristic_bridge_rows),
                "fallback": "heuristic_alias_support",
            }
            bridge_trace = {
                "planner_mode": "heuristic_fallback",
                "planner_error": {"type": type(e).__name__, "message": str(e)},
                "model_requested": options.openai_model,
            }
    else:
        heuristic_bridge_rows = derive_heuristic_bridge_terms(plan, source_inventory, run_ctx, options)
        plan["bridge_term_rows"] = heuristic_bridge_rows
        plan["bridge_terms"] = [row.get("term") for row in heuristic_bridge_rows if row.get("term")]
        plan["bridge_generation"] = {
            "performed": bool(heuristic_bridge_rows),
            "bridge_term_count": len(heuristic_bridge_rows),
            "fallback": "heuristic_only",
        }
        bridge_trace = {"planner_mode": "heuristic_only", "model_requested": None}

    corpus_support = analyze_corpus_support(plan, run_ctx)
    plan = suppress_unsupported_subpoints(plan, corpus_support)
    retrieval_views = build_retrieval_views(plan, options)
    write_json(planner_prompt_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_d", **prompt_payload})
    write_json(planner_response_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_d", "response": raw_response})
    write_json(bridge_prompt_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_d", **bridge_prompt_payload})
    write_json(bridge_response_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_d", "response": bridge_raw_response})
    write_json(bridge_trace_path, bridge_trace)

    if planner_trace.get("planner_mode") == "openai":
        usage = planner_trace.get("usage") or {}
        cost = planner_trace.get("cost") or {}
        record_api_call(
            run_ctx,
            stage="phase_d",
            provider="openai",
            model=str(planner_trace.get("model_used") or planner_trace.get("model_requested") or options.openai_model),
            input_tokens=int(usage.get("input_tokens") or 0),
            cached_input_tokens=int(usage.get("cached_input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(cost.get("estimated_cost_usd") or 0.0),
            meta={
                "api_mode": planner_trace.get("api_mode"),
                "message_count": planner_trace.get("message_count"),
                "prompt_cache_key": planner_trace.get("prompt_cache_key"),
                "pricing_model": cost.get("pricing_model"),
            },
        )

    if bridge_trace.get("planner_mode") == "openai":
        usage = bridge_trace.get("usage") or {}
        cost = bridge_trace.get("cost") or {}
        record_api_call(
            run_ctx,
            stage="phase_d",
            provider="openai",
            model=str(bridge_trace.get("model_used") or bridge_trace.get("model_requested") or options.openai_model),
            input_tokens=int(usage.get("input_tokens") or 0),
            cached_input_tokens=int(usage.get("cached_input_tokens") or 0),
            output_tokens=int(usage.get("output_tokens") or 0),
            cost_usd=float(cost.get("estimated_cost_usd") or 0.0),
            meta={
                "api_mode": bridge_trace.get("api_mode"),
                "message_count": bridge_trace.get("message_count"),
                "prompt_cache_key": bridge_trace.get("prompt_cache_key"),
                "pricing_model": cost.get("pricing_model"),
                "call_purpose": "bridge_terms",
            },
        )

    corpus_support = analyze_corpus_support(plan, run_ctx)
    write_json(corpus_support_path, {"generated_at_utc": utc_now_iso(), "run_id": run_ctx.run_id, "phase": "phase_d", **corpus_support})
    assessment = assess_phase_d(plan, retrieval_views, options=options, planner_trace=planner_trace, source_inventory=source_inventory, corpus_support=corpus_support)

    query_plan_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_d",
        "query_plan": plan,
        "retrieval_views": retrieval_views,
        "planner_trace": planner_trace,
    }
    write_json(query_plan_path, query_plan_payload)
    write_json(query_views_path, retrieval_views)
    write_json(planner_trace_path, planner_trace)

    view_rows = flatten_retrieval_views(retrieval_views)
    subpoint_rows = [
        {
            "subpoint_id": row.get("subpoint_id"),
            "label": row.get("label"),
            "summary": truncate_text(clean_text(row.get("summary")), max_len=180),
            "source_anchors": ", ".join(row.get("source_anchors") or []),
            "must_terms": ", ".join(row.get("must_terms") or []),
            "preferred_section_types": ", ".join(row.get("preferred_section_types") or []),
        }
        for row in (plan.get("subpoints") or [])
    ]
    term_support_rows = []
    for row in corpus_support.get("term_rows") or []:
        term_support_rows.append(
            {
                "kind": row.get("kind"),
                "term": row.get("term"),
                "doc_hits": row.get("doc_hits"),
                "section_hits": row.get("section_hits"),
                "title_hits": row.get("title_hits"),
                "text_hits": row.get("text_hits"),
                "example_titles": ", ".join(row.get("example_titles") or []),
            }
        )

    summary_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_d",
        "options": json_safe(asdict(options)),
        "planner_trace": planner_trace,
        "openai_usage": planner_trace.get("usage"),
        "openai_cost": planner_trace.get("cost"),
        "query_plan_path": rel_to_run(Path(run_ctx.run_dir), query_plan_path),
        "query_views_path": rel_to_run(Path(run_ctx.run_dir), query_views_path),
        "planner_prompt_path": rel_to_run(Path(run_ctx.run_dir), planner_prompt_path),
        "planner_response_path": rel_to_run(Path(run_ctx.run_dir), planner_response_path),
        "bridge_prompt_path": rel_to_run(Path(run_ctx.run_dir), bridge_prompt_path),
        "bridge_response_path": rel_to_run(Path(run_ctx.run_dir), bridge_response_path),
        "bridge_trace_path": rel_to_run(Path(run_ctx.run_dir), bridge_trace_path),
        "bridge_corpus_inventory_path": rel_to_run(Path(run_ctx.run_dir), bridge_corpus_inventory_path),
        "source_inventory_path": rel_to_run(Path(run_ctx.run_dir), source_inventory_path),
        "corpus_support_path": rel_to_run(Path(run_ctx.run_dir), corpus_support_path),
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": assessment["qc_rows"],
        "source_anchors": plan.get("source_anchors") or [],
        "bridge_terms": plan.get("bridge_terms") or [],
        "bridge_term_rows": plan.get("bridge_term_rows") or [],
        "bridge_trace": bridge_trace,
        "subpoint_suppression": plan.get("subpoint_suppression") or {},
        "suppressed_subpoints": plan.get("suppressed_subpoints") or [],
        "subpoints": subpoint_rows,
        "retrieval_views": view_rows,
        "term_support_rows": term_support_rows,
    }
    assessment_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_d",
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": assessment["qc_rows"],
        "openai_usage": planner_trace.get("usage"),
        "openai_cost": planner_trace.get("cost"),
        "bridge_openai_usage": bridge_trace.get("usage"),
        "bridge_openai_cost": bridge_trace.get("cost"),
        "query_plan_path": rel_to_run(Path(run_ctx.run_dir), query_plan_path),
        "query_views_path": rel_to_run(Path(run_ctx.run_dir), query_views_path),
        "corpus_support_path": rel_to_run(Path(run_ctx.run_dir), corpus_support_path),
    }
    write_json(summary_path, summary_payload)
    write_json(assessment_path, assessment_payload)

    if log_event_fn is not None:
        log_event_fn(
            run_ctx,
            stage="phase_d",
            event="phase_finished",
            planner_mode=planner_trace.get("planner_mode"),
            status=assessment["status"],
            source_anchor_count=len(plan.get("source_anchors") or []),
            subpoint_count=len(subpoint_rows),
            retrieval_view_count=len(view_rows),
            openai_input_tokens=(planner_trace.get("usage") or {}).get("input_tokens"),
            openai_output_tokens=(planner_trace.get("usage") or {}).get("output_tokens"),
            openai_estimated_cost_usd=(planner_trace.get("cost") or {}).get("estimated_cost_usd"),
        )
    if run_logger is not None:
        run_logger.info(
            "Phase D finished | planner_mode=%s | status=%s | anchors=%s | subpoints=%s | views=%s | input_tokens=%s | output_tokens=%s | estimated_cost_usd=%s",
            planner_trace.get("planner_mode"),
            assessment["status"],
            len(plan.get("source_anchors") or []),
            len(subpoint_rows),
            len(view_rows),
            (planner_trace.get("usage") or {}).get("input_tokens"),
            (planner_trace.get("usage") or {}).get("output_tokens"),
            (planner_trace.get("cost") or {}).get("estimated_cost_usd"),
        )

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_d")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "query_plan_path": query_plan_path,
        "query_views_path": query_views_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "planner_trace_path": planner_trace_path,
        "planner_prompt_path": planner_prompt_path,
        "planner_response_path": planner_response_path,
        "source_inventory_path": source_inventory_path,
        "corpus_support_path": corpus_support_path,
        "planner_trace": planner_trace,
        "query_plan": plan,
        "source_anchor_rows": [{"source_anchor": item} for item in (plan.get("source_anchors") or [])],
        "subpoint_rows": subpoint_rows,
        "retrieval_view_rows": view_rows,
        "term_support_rows": term_support_rows,
        "assessment": assessment,
        "qc_rows": assessment["qc_rows"],
        "metrics_update": {
            "status": assessment["status"],
            "quality_band": assessment["quality_band"],
            "planner_mode": planner_trace.get("planner_mode"),
            "source_anchor_count": assessment["counts"].get("source_anchor_count"),
            "must_term_count": assessment["counts"].get("must_term_count"),
            "subpoint_count": assessment["counts"].get("subpoint_count"),
            "retrieval_view_count": assessment["counts"].get("retrieval_view_count"),
            "source_alignment_ratio": assessment.get("source_alignment_ratio"),
            "openai_input_tokens": (planner_trace.get("usage") or {}).get("input_tokens"),
            "openai_cached_input_tokens": (planner_trace.get("usage") or {}).get("cached_input_tokens"),
            "openai_output_tokens": (planner_trace.get("usage") or {}).get("output_tokens"),
            "openai_total_tokens": (planner_trace.get("usage") or {}).get("total_tokens"),
            "openai_estimated_cost_usd": (planner_trace.get("cost") or {}).get("estimated_cost_usd"),
            "openai_pricing_model": (planner_trace.get("cost") or {}).get("pricing_model"),
            "openai_pricing_verified_date": (planner_trace.get("cost") or {}).get("pricing_verified_date"),
            "phase_d_summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
            "phase_d_assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
        },
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase D lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_d_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--force-rebuild-phase-d", action="store_true")
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
        phase_b_result = run_phase_b(
            run_ctx,
            pdf_manifest,
            phase_b_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=phase_b_logger,
        )
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
        phase_c_result = run_phase_c(
            run_ctx,
            phase_c_options,
            stable_hash_fn=stable_hash,
            log_event_fn=log_event,
            run_logger=phase_c_logger,
        )
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

    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))
    plan = phase_d_result["query_plan"]
    print_section("Phase D Lab - Planner Capabilities")
    print_kv(
        {
            "openai_available": phase_d_capabilities().get("openai_available"),
            "pydantic_available": phase_d_capabilities().get("pydantic_available"),
            "openai_api_key_present": phase_d_capabilities().get("openai_api_key_present"),
            "planner_model": phase_d_options.openai_model,
            "planner_mode": phase_d_result["planner_trace"].get("planner_mode"),
            "api_mode": phase_d_result["planner_trace"].get("api_mode"),
            "pricing_source_url": (phase_d_result["planner_trace"].get("cost") or {}).get("pricing_source_url"),
        }
    )
    print_section("Phase D Lab - What Happened")
    print_kv(
        {
            "run_id": run_ctx.run_id,
            "query_plan_json": rel(phase_d_result["query_plan_path"]),
            "query_views_json": rel(phase_d_result["query_views_path"]),
            "planner_prompt_json": rel(phase_d_result["planner_prompt_path"]),
            "planner_response_json": rel(phase_d_result["planner_response_path"]),
            "source_inventory_json": rel(phase_d_result["source_inventory_path"]),
            "corpus_support_json": rel(phase_d_result["corpus_support_path"]),
            "openai_input_tokens": (phase_d_result["planner_trace"].get("usage") or {}).get("input_tokens"),
            "openai_output_tokens": (phase_d_result["planner_trace"].get("usage") or {}).get("output_tokens"),
            "openai_estimated_cost_usd": (phase_d_result["planner_trace"].get("cost") or {}).get("estimated_cost_usd"),
            "phase_status": phase_d_result["assessment"].get("status"),
        }
    )
    print_section("Phase D Lab - Query Plan Summary")
    print_kv(
        {
            "chapter_title": truncate_text(plan.get("chapter_title"), max_len=110),
            "chapter_summary": truncate_text(plan.get("chapter_summary"), max_len=220),
            "source_anchors": ", ".join((plan.get("source_anchors") or [])[:10]),
            "must_terms": ", ".join(plan.get("must_terms") or []),
            "should_terms": ", ".join((plan.get("should_terms") or [])[:10]),
            "drift_risks": ", ".join(plan.get("drift_risks") or []),
        }
    )
    print_section("Phase D Lab - Subpoints")
    print_table(
        phase_d_result["subpoint_rows"],
        columns=["subpoint_id", "label", "summary", "source_anchors", "must_terms", "preferred_section_types"],
        max_rows=20,
        max_col_width=48,
    )
    print_section("Phase D Lab - Retrieval Views")
    print_table(
        phase_d_result["retrieval_view_rows"],
        columns=["view_id", "kind", "target_units", "anchor_terms", "query_word_count", "query_text"],
        max_rows=30,
        max_col_width=52,
    )
    print_section("Phase D Lab - Corpus Support")
    print_table(
        phase_d_result["term_support_rows"],
        columns=["kind", "term", "doc_hits", "section_hits", "title_hits", "text_hits", "example_titles"],
        max_rows=24,
        max_col_width=42,
    )
    print_section("Phase D Lab - QC")
    print_table(
        phase_d_result["qc_rows"],
        columns=["check", "status", "value", "expected", "why", "fix"],
        max_rows=20,
        max_col_width=46,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
