from __future__ import annotations

"""
Two-lane sources retrieval pipeline.

This module is a backend-safe port of `sources-v2/sources_two_lane.ipynb`:
- no notebook/UI dependencies
- callable from FastAPI background jobs
- optional local artifacts (dev-only) with retention

Important: scoring/query logic should match the notebook as closely as possible.
"""

import csv
import asyncio
import hashlib
import json
import logging
import math
import os
import random
import re
import shutil
import statistics
import subprocess
import tempfile
import time
import traceback
import unicodedata
from array import array
from bisect import bisect_right
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Literal, Optional, Tuple
from urllib.parse import urlparse

import numpy as np
import requests
from fastapi import HTTPException
from google.cloud.firestore_v1 import SERVER_TIMESTAMP
from openai import APIConnectionError, APIStatusError, APITimeoutError, InternalServerError, RateLimitError
from pydantic import BaseModel, Field
from pydantic.config import ConfigDict

from services.cost_service import TokenUsage, get_cost_service
from services.credits_service import get_credits_service
from services.firebase_service import firebase_service
from services.openai_budget_service import get_openai_budget_service
from services.openai_service import OpenAIService
from services.user_key_service import user_key_service
from utils.config import config as app_config
from utils.token_estimation import count_tokens

logger = logging.getLogger(__name__)


# -----------------------------
# Small utils (from notebook)
# -----------------------------


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def stable_hash(*parts: str, length: int = 24) -> str:
    payload = "\n".join([(p or "").strip().replace("\r\n", "\n") for p in parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:length]


def compute_seed_id(chapter_title: str, chapter_spec_text: str, pipeline_version: str) -> str:
    # Notebook run_id is computed from chapter inputs; we keep this as a stable seed for determinism.
    return stable_hash(pipeline_version, chapter_title, chapter_spec_text, length=24)


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def _json_default(o: Any):
    if isinstance(o, Path):
        return str(o)
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


def write_json(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, obj: Any) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False, default=_json_default) + "\n")


def _render_template(template: str, **vars: str) -> str:
    out = str(template or "")
    for k, v in (vars or {}).items():
        out = out.replace("{{" + str(k) + "}}", str(v))
    return out


def _json_for_prompt(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2, default=_json_default)


def _fmt_int(x) -> str:
    try:
        return f"{int(x):,}"
    except Exception:
        return str(x)


def _truncate(text: Any, max_len: int = 120) -> str:
    s = str(text or "")
    return s if len(s) <= max_len else (s[: max_len - 1] + "…")


def pctile(xs: Iterable[Any], p: float) -> float:
    arr: List[float] = []
    for x in xs or []:
        try:
            arr.append(float(x))
        except Exception:
            continue
    if not arr:
        return 0.0
    arr.sort()
    if len(arr) == 1:
        return float(arr[0])

    pp = float(p)
    if pp <= 0:
        return float(arr[0])
    if pp >= 100:
        return float(arr[-1])

    k = (len(arr) - 1) * (pp / 100.0)
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return float(arr[f])
    d = k - f
    return float(arr[f] + (arr[c] - arr[f]) * d)


def any_term_in_text(text: Any, terms: Iterable[Any]) -> bool:
    s = str(text or "").casefold()
    if not s:
        return False
    for t in terms or []:
        tt = str(t or "").strip()
        if not tt:
            continue
        if tt.casefold() in s:
            return True
    return False


# -----------------------------
# OpenAI response helpers
# -----------------------------


def _get(obj: Any, key: str, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _extract_text_from_response(resp: Any) -> str:
    """
    Extract the assistant text from an OpenAI Responses API response.

    Prefer `output_text` when present, but fall back to traversing `output[].content[]`.
    """

    t = _get(resp, "output_text", None)
    if isinstance(t, str) and t.strip():
        return t

    chunks: list[str] = []
    for item in _get(resp, "output", []) or []:
        if _get(item, "type") != "message":
            continue
        for part in _get(item, "content", []) or []:
            part_type = _get(part, "type")
            if part_type in ("output_text", "text"):
                txt = _get(part, "text", "")
                if txt:
                    chunks.append(txt)
    return "".join(chunks)


# -----------------------------
# Global constants (notebook)
# -----------------------------

FACETS_MIN = 8
FACETS_MAX = 20
ANCHORS_MIN = 3

QUERY_DUP_WARN = 0.10
QUERY_DUP_FAIL = 0.25

ZERO_Q_WARN = 0.20
ZERO_Q_FAIL = 0.50

DOMINANCE_WARN = 0.30
DOMINANCE_FAIL = 0.50

WITH_ABS_WARN = 0.70
WITH_ABS_FAIL = 0.50

YEAR_MISSING_WARN = 0.20
YEAR_MISSING_FAIL = 0.40

TOPK_ANCHOR_WARN = 0.70
TOPK_ANCHOR_FAIL = 0.40

REQUIRED_FACET_WEIGHT_MIN = 4


# -----------------------------
# Artifacts + metrics (ported)
# -----------------------------


class RunArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query_plan_json: Path
    openalex_queries_json: Path
    semanticscholar_queries_json: Path

    openalex_raw_jsonl: Path
    semanticscholar_raw_jsonl: Path
    semanticscholar_recommendations_jsonl: Path

    candidates_normalized_jsonl: Path
    candidates_normalized_csv: Path

    embeddings_manifest_jsonl: Path
    embeddings_manifest_csv: Path
    embeddings_vectors_dir: Path

    rerank_results_jsonl: Path
    output_json: Path

    logs_jsonl: Path
    run_log: Path
    metrics_json: Path


class RunContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_root: Path
    run_id: str
    run_dir: Path
    artifacts: RunArtifacts

    def create_artifact_skeleton(self, *, overwrite: bool = False) -> None:
        ensure_dir(self.run_dir)

        jsonl_files = [
            self.artifacts.openalex_raw_jsonl,
            self.artifacts.semanticscholar_raw_jsonl,
            self.artifacts.semanticscholar_recommendations_jsonl,
            self.artifacts.candidates_normalized_jsonl,
            self.artifacts.embeddings_manifest_jsonl,
            self.artifacts.rerank_results_jsonl,
            self.artifacts.logs_jsonl,
        ]
        for p in jsonl_files:
            ensure_dir(p.parent)
            p.touch(exist_ok=True)

        ensure_dir(self.artifacts.run_log.parent)
        self.artifacts.run_log.touch(exist_ok=True)

        csv_files = [
            self.artifacts.candidates_normalized_csv,
            self.artifacts.embeddings_manifest_csv,
        ]
        for p in csv_files:
            ensure_dir(p.parent)
            if overwrite or not p.exists():
                p.write_text("", encoding="utf-8")

        if overwrite or not self.artifacts.metrics_json.exists():
            write_json(
                self.artifacts.metrics_json,
                {
                    "run_id": self.run_id,
                    "created_at_utc": utc_now_iso(),
                    "stages": {},
                },
            )


def log_event(run_ctx: RunContext, *, stage: str, event: str, **fields: Any) -> None:
    rec = {"ts": utc_now_iso(), "stage": stage, "event": event, **fields}
    append_jsonl(run_ctx.artifacts.logs_jsonl, rec)

    # Keep server logs readable; the detailed record is in logs.jsonl.
    level = logging.INFO
    if event in {"http_request", "cache_hit", "cache_write", "aggregate_rebuilt"}:
        level = logging.DEBUG
    if "error" in fields or event.endswith("_error") or event.endswith("_failed"):
        level = logging.ERROR
    logger.log(level, json.dumps({k: v for k, v in rec.items() if k != "ts"}, ensure_ascii=False, default=_json_default))


def load_metrics(run_ctx: RunContext) -> Dict[str, Any]:
    try:
        return read_json(run_ctx.artifacts.metrics_json)
    except Exception:
        return {"run_id": run_ctx.run_id, "created_at_utc": utc_now_iso(), "stages": {}}


def save_metrics(run_ctx: RunContext, metrics: Dict[str, Any]) -> None:
    metrics = dict(metrics)
    metrics["updated_at_utc"] = utc_now_iso()
    write_json(run_ctx.artifacts.metrics_json, metrics)


@contextmanager
def stage_timer(run_ctx: RunContext, stage: str):
    t0 = time.time()
    yield
    dt = time.time() - t0
    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["last_duration_s"] = round(dt, 3)
    save_metrics(run_ctx, metrics)


# -----------------------------
# Pipeline config + inputs
# -----------------------------


class ChapterInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chapter_title: str
    chapter_spec_text: str
    pipeline_version: str

    def compute_seed_id(self) -> str:
        return compute_seed_id(self.chapter_title, self.chapter_spec_text, self.pipeline_version)


class BilingualTerms(BaseModel):
    model_config = ConfigDict(extra="forbid")

    en: List[str] = Field(default_factory=list)
    de: List[str] = Field(default_factory=list)


QUERY_FAMILY_ENUM = [
    "object_core",
    "object_plus_construct",
    "object_plus_data_proxy",
    "object_plus_method",
    "object_plus_limitation",
    "object_plus_context",
]

LANGUAGE_STRATEGY_ENUM = [
    "en_core_only",
    "en_plus_bilingual_fallback",
    "en_plus_selective_de",
    "en_de_parallel",
]

AUTHORITY_ROLE_ENUM = [
    "none",
    "core",
    "booster",
]

AUTHORITY_KIND_ENUM = [
    "core",
    "booster",
]

AUTHORITY_SEARCH_BREADTH_ENUM = [
    "tight",
    "broad_ok",
]


class AuthorityBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    authority_kind: str
    label_en: str
    label_de: str
    target_facet_ids: List[str] = Field(default_factory=list)
    language_strategy: str
    search_breadth: str
    notes_en: str


class Facet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    facet_id: str
    facet_label_en: str
    facet_label_de: str
    facet_type: str
    facet_group: str
    query_family_preference: str
    language_strategy: str
    authority_role: str
    importance_weight: int = Field(ge=1, le=5)
    text_en: str
    text_de: str
    canonical_terms: BilingualTerms
    neighbor_terms: BilingualTerms
    exclusion_terms: BilingualTerms


class QueryPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    topic_summary_en: str
    topic_summary_de: str
    primary_context_anchors: BilingualTerms
    core_object_terms: BilingualTerms
    must_keep_constraints: List[str] = Field(default_factory=list)
    drift_risks: List[str] = Field(default_factory=list)
    authority_blueprints: List[AuthorityBlueprint] = Field(default_factory=list)
    facets: List[Facet]
    global_canonical_terms: BilingualTerms
    global_exclusions: BilingualTerms


# -----------------------------
# Phase B — LLM Query Planner (ported)
# -----------------------------


FACET_GROUP_ENUM = [
    "object",
    "construct",
    "data_proxy",
    "method",
    "context",
    "limitation",
]

FACET_GROUP_TO_QUERY_FAMILY = {
    "object": {"object_core", "object_plus_context"},
    "construct": {"object_plus_construct"},
    "data_proxy": {"object_plus_data_proxy", "object_plus_method"},
    "method": {"object_plus_method"},
    "context": {"object_plus_context", "object_core"},
    "limitation": {"object_plus_limitation", "object_plus_context"},
}

DEFAULT_QUERY_FAMILY_BY_GROUP = {
    "object": "object_core",
    "construct": "object_plus_construct",
    "data_proxy": "object_plus_data_proxy",
    "method": "object_plus_method",
    "context": "object_plus_context",
    "limitation": "object_plus_limitation",
}


QUERY_PLAN_JSON_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "topic_summary_en",
        "topic_summary_de",
        "primary_context_anchors",
        "core_object_terms",
        "must_keep_constraints",
        "drift_risks",
        "authority_blueprints",
        "facets",
        "global_canonical_terms",
        "global_exclusions",
    ],
    "properties": {
        "topic_summary_en": {"type": "string"},
        "topic_summary_de": {"type": "string"},
        "primary_context_anchors": {
            "type": "object",
            "additionalProperties": False,
            "required": ["en", "de"],
            "properties": {
                "en": {"type": "array", "items": {"type": "string"}},
                "de": {"type": "array", "items": {"type": "string"}},
            },
        },
        "core_object_terms": {
            "type": "object",
            "additionalProperties": False,
            "required": ["en", "de"],
            "properties": {
                "en": {"type": "array", "items": {"type": "string"}},
                "de": {"type": "array", "items": {"type": "string"}},
            },
        },
        "must_keep_constraints": {
            "type": "array",
            "items": {"type": "string"},
        },
        "drift_risks": {
            "type": "array",
            "items": {"type": "string"},
        },
        "authority_blueprints": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "authority_kind",
                    "label_en",
                    "label_de",
                    "target_facet_ids",
                    "language_strategy",
                    "search_breadth",
                    "notes_en",
                ],
                "properties": {
                    "authority_kind": {"type": "string", "enum": AUTHORITY_KIND_ENUM},
                    "label_en": {"type": "string"},
                    "label_de": {"type": "string"},
                    "target_facet_ids": {"type": "array", "items": {"type": "string"}},
                    "language_strategy": {"type": "string", "enum": LANGUAGE_STRATEGY_ENUM},
                    "search_breadth": {"type": "string", "enum": AUTHORITY_SEARCH_BREADTH_ENUM},
                    "notes_en": {"type": "string"},
                },
            },
        },
        "global_canonical_terms": {
            "type": "object",
            "additionalProperties": False,
            "required": ["en", "de"],
            "properties": {
                "en": {"type": "array", "items": {"type": "string"}},
                "de": {"type": "array", "items": {"type": "string"}},
            },
        },
        "global_exclusions": {
            "type": "object",
            "additionalProperties": False,
            "required": ["en", "de"],
            "properties": {
                "en": {"type": "array", "items": {"type": "string"}},
                "de": {"type": "array", "items": {"type": "string"}},
            },
        },
        "facets": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "facet_id",
                    "facet_label_en",
                    "facet_label_de",
                    "facet_type",
                    "facet_group",
                    "query_family_preference",
                    "language_strategy",
                    "authority_role",
                    "importance_weight",
                    "text_en",
                    "text_de",
                    "canonical_terms",
                    "neighbor_terms",
                    "exclusion_terms",
                ],
                "properties": {
                    "facet_id": {"type": "string"},
                    "facet_label_en": {"type": "string"},
                    "facet_label_de": {"type": "string"},
                    "facet_type": {
                        "type": "string",
                        "enum": [
                            "background",
                            "theory",
                            "mechanism",
                            "methods",
                            "data",
                            "measurement",
                            "evaluation",
                            "case_context",
                            "debate",
                            "limitations",
                            "applications",
                        ],
                    },
                    "facet_group": {"type": "string", "enum": FACET_GROUP_ENUM},
                    "query_family_preference": {"type": "string", "enum": QUERY_FAMILY_ENUM},
                    "language_strategy": {"type": "string", "enum": LANGUAGE_STRATEGY_ENUM},
                    "authority_role": {"type": "string", "enum": AUTHORITY_ROLE_ENUM},
                    "importance_weight": {"type": "integer", "minimum": 1, "maximum": 5},
                    "text_en": {"type": "string"},
                    "text_de": {"type": "string"},
                    "canonical_terms": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["en", "de"],
                        "properties": {
                            "en": {"type": "array", "items": {"type": "string"}},
                            "de": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "neighbor_terms": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["en", "de"],
                        "properties": {
                            "en": {"type": "array", "items": {"type": "string"}},
                            "de": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                    "exclusion_terms": {
                        "type": "object",
                        "additionalProperties": False,
                        "required": ["en", "de"],
                        "properties": {
                            "en": {"type": "array", "items": {"type": "string"}},
                            "de": {"type": "array", "items": {"type": "string"}},
                        },
                    },
                },
            },
        },
    },
}


PLANNER_SYSTEM_PROMPT = """
You are a scientific literature search planner for a multi-stage academic retrieval pipeline.
Your job is not to describe a topic in generic academic language. Your job is to preserve the chapter's exact retrieval target and to define how downstream query builders should search for it.

Priority order:
1) Preserve the chapter's core object, corpus, domain, or context exactly.
2) Preserve the main constructs, questions, outcomes, or debates.
3) Preserve data-source, proxy, measurement, and validity constraints.
4) Control query-family shape so generic method drift is hard downstream.
5) Split authority into tight core authority vs optional broader boosters.
6) Add useful neighboring facets without diluting the core object.
7) Add exclusions only for true wrong-sense confounders.

Rules:
- If a phrase is central to the chapter object, keep it even if one token inside the phrase is generic.
- Do not replace concrete chapter nouns with broader abstractions.
- Method terms are supporting context unless the chapter is explicitly about methods.
- Do not leave Phase C to guess whether a facet should become object+data, object+method, or a broader authority booster.
- Do not name specific papers, authors, or venues. Do not invent citations.
- Be deterministic and return only valid JSON.
"""


PLANNER_USER_PROMPT_TEMPLATE = """CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC (retrieval contract):
{{chapter_spec_text}}

TASK:
Return a QueryPlan JSON object with the schema required by this pipeline.

HOW TO INTERPRET THE CHAPTER:
Preserve these distinctions in the plan:
- chapter object / corpus / domain context
- target construct / question / outcome
- data source / proxy / measurement constraints
- analytical methods
- exclusions / wrong-sense confounders

PRIORITY ORDER:
1) preserve the chapter's core object/corpus/domain exactly
2) preserve the main constructs/questions/outcomes
3) preserve data/proxy/measurement constraints
4) control query-family shape so downstream query builders do not invent generic method-heavy families
5) split authority into tight core authority and optional broader boosters
6) add useful neighboring facets without diluting the object
7) add exclusions only for true wrong-sense confounders

Return a QueryPlan JSON object with these keys:

1) topic_summary_en: 2-3 sentences
2) topic_summary_de: 2-3 sentences (natural German)

Summary rules:
- The first sentence must name the chapter object/corpus/domain before any methods framing.
- State the chapter object, the main construct/question, and the role of data/proxies/methods.
- Do not generalize away the named corpus/object.

3) primary_context_anchors:
   - en: 4-10 short anchors
   - de: 4-10 short anchors
   RULES:
   - Each anchor must be 1-6 words.
   - At least 2 anchors per language should name the core object/corpus/domain when available.
   - Pure method anchors are allowed only if genuinely central; they must never be the majority.
   - Avoid vague standalone research words such as analysis, study, effects, framework, model, system, approach, dynamics, development, overview.
   - A full phrase may be kept if the phrase itself is chapter-critical, even if one word inside it is generic.
   - Avoid long narrative phrases. Avoid parentheses and commas inside anchors.

4) core_object_terms:
   - en: 3-12 short terms/phrases naming the core object/corpus/domain
   - de: 3-12 short terms/phrases naming the core object/corpus/domain
   RULES:
   - These should be the best retrieval phrases for the chapter's object, not methods or broad abstractions.
   - Reuse exact chapter wording where helpful.
   - Each term must be <= 4 words and follow TERM HYGIENE.

5) must_keep_constraints:
   - 3-10 short English strings
   RULES:
   - Each item should capture a non-negotiable retrieval constraint that downstream stages must preserve.
   - Focus on object, construct, proxy/data, measurement, or scope constraints.
   - Keep each item short and concrete.

6) drift_risks:
   - 2-8 short English strings
   RULES:
   - List the most likely ways retrieval could drift off-topic.
   - Include generic method drift when relevant.
   - Keep each item short and concrete.

7) authority_blueprints:
   - 1-4 items total
   - MUST include at least 1 core blueprint
   Each item has:
   - authority_kind: "core" | "booster"
   - label_en: <= 8 words
   - label_de: <= 8 words
   - target_facet_ids: 1-4 existing facet_ids
   - language_strategy: one of ["en_core_only","en_plus_bilingual_fallback","en_plus_selective_de","en_de_parallel"]
   - search_breadth: "tight" | "broad_ok"
   - notes_en: <= 18 words
   RULES:
   - core authority is the chapter's non-negotiable authoritative literature family; it should stay tight and object-led.
   - booster authority is broader, but must still remain chapter-anchored.
   - search_breadth="broad_ok" is allowed only for boosters.
   - core blueprints should usually target object / construct / data_proxy facets, not generic methods facets.
   - booster blueprints may add context or limitation angles, but must still preserve the chapter object.

8) global_canonical_terms:
   - en: 12-30 terms/phrases
   - de: 12-30 terms/phrases
   TERM HYGIENE:
   - Each term must be <= 4 words.
   - No explanatory text, no "e.g." / "z. B.".
   - No parentheses, no commas, no semicolons.
   - Preserve important chapter wording if it is likely to appear in titles/abstracts.
   - Ensure the list includes object terms first, then construct/data/proxy terms, then method terms.

9) global_exclusions:
   - en: 0-12 atomic confounder terms
   - de: 0-12 atomic confounder terms
   EXCLUSION RULES:
   - Only include exclusions that are likely to appear in unrelated literature and cause wrong-sense retrieval.
   - <= 3 words each
   - No punctuation except hyphen
   - If unsure, omit the exclusion

10) facets: 8-18 ATOMIC facets.
For each facet:
- facet_id: lower_snake_case, 3-6 words, stable
- facet_type: one of ["background","theory","mechanism","methods","data","measurement","evaluation","case_context","debate","limitations","applications"]
- facet_group: one of ["object","construct","data_proxy","method","context","limitation"]
- query_family_preference: one of ["object_core","object_plus_construct","object_plus_data_proxy","object_plus_method","object_plus_limitation","object_plus_context"]
- language_strategy: one of ["en_core_only","en_plus_bilingual_fallback","en_plus_selective_de","en_de_parallel"]
- authority_role: one of ["none","core","booster"]
- importance_weight: integer 1..5
- facet_label_en: <= 8 words
- facet_label_de: <= 8 words
- text_en: 1-2 sentences
- text_de: 1-2 sentences
- canonical_terms.en/de: 6-18 terms each
- neighbor_terms.en/de: 4-12 terms each
- exclusion_terms.en/de: 0-6 terms each

FACET RULES:
- Cover every explicit instruction in the chapter spec.
- Add 2-4 useful neighboring facets that support retrieval, but keep the plan centered on the named chapter object.
- If the chapter is not primarily a methods chapter, generic methods facets must not dominate the weight>=4 set.
- For any methods/data/measurement facet, write it as methods/data/measurement FOR this chapter object, not as a generic field overview.
- Use facet_group to mark the facet's coarse retrieval role.
- Use query_family_preference to tell Phase C what shape the query should have, not just what words to use.
- Use the smallest query family that preserves meaning:
  - object -> usually object_core
  - construct -> usually object_plus_construct
  - data/proxy/measurement -> usually object_plus_data_proxy
  - methods -> usually object_plus_method
  - limitation/bias/validity -> usually object_plus_limitation
  - domain/platform/context -> usually object_plus_context
- Use language_strategy to say whether the facet should stay EN-core, use bilingual fallback, or support selective DE.
- Do not mark a facet as en_de_parallel unless the object phrase and facet phrase are both likely to exist in real literature in both languages.
- authority_role="core" means this facet deserves tight authority coverage.
- authority_role="booster" means this facet can support a broader authority booster if budget remains.
- authority_role="none" means the facet is match-oriented only.
- Generic methods facets should rarely be authority_role="core".
- If the chapter mentions proxies, secondary data, validity, bias, or representativeness, add the relevant facets when supported by the spec.
- Keep facets non-overlapping as much as possible.

QUALITY CHECKS:
- If your top anchors would retrieve generic method papers but not the chapter object, revise them.
- If core_object_terms are weak, generic, or method-heavy, revise them.
- If Phase C could build a generic workflow/evaluation query from this facet with weak object conditioning, change query_family_preference or lower its priority.
- If authority is still a single flat concept rather than core vs booster, revise the authority_blueprints.
- If the plan drops the concrete object/corpus in favor of abstractions, revise it.
- If an exclusion is not a clear wrong-sense confounder, omit it.

OUTPUT:
Return ONLY valid JSON. No extra text.
"""


def planner_user_prompt(chapter_input: ChapterInput) -> str:
    s = PLANNER_USER_PROMPT_TEMPLATE
    s = s.replace("{{chapter_title}}", chapter_input.chapter_title.strip())
    s = s.replace("{{chapter_spec_text}}", chapter_input.chapter_spec_text.strip())
    return s


_PLANNER_BAD_EXCL_PAT = re.compile(r"(e\.g\.|z\.\s*b\.|,|\(|\)|;|:)", re.IGNORECASE)
_PLANNER_BAD_TERM_PAT = re.compile(r"(e\.g\.|z\.\s*b\.|\(|\)|,|;)", re.IGNORECASE)

_GENERIC_RESEARCH_WORDS = [
    "analysis",
    "study",
    "effects",
    "mechanism",
    "framework",
    "model",
    "system",
    "approach",
    "dynamics",
    "development",
    "review",
    "overview",
    "analyse",
    "studie",
    "effekte",
    "mechanismus",
    "rahmen",
    "modell",
    "system",
    "ansatz",
    "dynamik",
    "entwicklung",
    "überblick",
]
_GENERIC_RESEARCH_WORD_PAT = re.compile(
    r"\b(" + "|".join(re.escape(w) for w in _GENERIC_RESEARCH_WORDS) + r")\b", re.IGNORECASE
)


def _planner_word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", str(text or "").strip()) if w])


def _planner_is_atomic_exclusion(term: str) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _PLANNER_BAD_EXCL_PAT.search(t):
        return False
    if len(t) > 40:
        return False
    if _planner_word_count(t) > 3:
        return False
    if re.search(r"[^\w\s-]", t, flags=re.UNICODE):
        return False
    return True


def _planner_is_hygienic_term(term: str, *, max_words: int) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _PLANNER_BAD_TERM_PAT.search(t):
        return False
    if _planner_word_count(t) > int(max_words):
        return False
    return True


def diagnose_query_plan(plan: QueryPlan) -> Dict[str, Any]:
    issues: List[str] = []

    n_facets = len(plan.facets)
    if n_facets < 8 or n_facets > 20:
        issues.append(f"CRITICAL: facet count is {n_facets} (expected 8–20).")

    ids = [f.facet_id for f in plan.facets]
    dup_ids = sorted({x for x in ids if ids.count(x) > 1})
    if dup_ids:
        issues.append(f"CRITICAL: duplicate facet_id(s): {dup_ids}")

    bad_weights = [f.facet_id for f in plan.facets if not (1 <= f.importance_weight <= 5)]
    if bad_weights:
        issues.append(f"CRITICAL: facets with invalid importance_weight: {bad_weights}")

    # Primary context anchors
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        if len(anchors) < 3 or len(anchors) > 8:
            issues.append(f"CRITICAL: primary_context_anchors.{lang} has {len(anchors)} items (expected 3–8).")

        bad = []
        for a in anchors:
            aa = str(a or "").strip()
            if not aa:
                bad.append(a)
                continue
            if not _planner_is_hygienic_term(aa, max_words=6):
                bad.append(aa)
                continue
            if _GENERIC_RESEARCH_WORD_PAT.search(aa):
                bad.append(aa)
                continue
        if bad:
            issues.append(f"CRITICAL: primary_context_anchors.{lang} contains invalid/generic anchors: {bad[:6]}")

    # Term hygiene checks
    def check_term_list(name: str, terms: List[str], *, max_words: int) -> None:
        bad_terms = [t for t in (terms or []) if not _planner_is_hygienic_term(t, max_words=max_words)]
        if bad_terms:
            issues.append(f"CRITICAL: {name} contains non-hygienic terms: {bad_terms[:8]}")

    check_term_list("global_canonical_terms.en", plan.global_canonical_terms.en, max_words=4)
    check_term_list("global_canonical_terms.de", plan.global_canonical_terms.de, max_words=4)

    # Exclusion atomicity checks
    def check_exclusions(name: str, terms: List[str]) -> None:
        bad_terms = [t for t in (terms or []) if not _planner_is_atomic_exclusion(t)]
        if bad_terms:
            issues.append(f"CRITICAL: {name} contains non-atomic exclusions: {bad_terms[:8]}")

    check_exclusions("global_exclusions.en", plan.global_exclusions.en)
    check_exclusions("global_exclusions.de", plan.global_exclusions.de)

    for f in plan.facets:
        check_term_list(f"facet[{f.facet_id}].canonical_terms.en", f.canonical_terms.en, max_words=4)
        check_term_list(f"facet[{f.facet_id}].canonical_terms.de", f.canonical_terms.de, max_words=4)
        check_term_list(f"facet[{f.facet_id}].neighbor_terms.en", f.neighbor_terms.en, max_words=4)
        check_term_list(f"facet[{f.facet_id}].neighbor_terms.de", f.neighbor_terms.de, max_words=4)
        check_exclusions(f"facet[{f.facet_id}].exclusion_terms.en", f.exclusion_terms.en)
        check_exclusions(f"facet[{f.facet_id}].exclusion_terms.de", f.exclusion_terms.de)

    # Very rough overlap heuristic: identical canonical term sets.
    canon_sets: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], str] = {}
    overlaps: List[Tuple[str, str]] = []
    for f in plan.facets:
        key = (
            tuple(sorted({t.strip().lower() for t in f.canonical_terms.en if str(t or "").strip()})),
            tuple(sorted({t.strip().lower() for t in f.canonical_terms.de if str(t or "").strip()})),
        )
        if key in canon_sets and key != ((), ()):
            overlaps.append((canon_sets[key], f.facet_id))
        else:
            canon_sets[key] = f.facet_id

    if overlaps:
        issues.append(f"Potential duplicate facets (identical canonical_terms): {overlaps[:5]}")

    critical = [x for x in issues if str(x).startswith("CRITICAL:")]
    return {"facet_count": n_facets, "issues": issues, "critical_issues": critical}


_BAD_EXCL_PAT = re.compile(r"(e\.g\.|z\.\s*b\.|,|\(|\)|;|:)", re.IGNORECASE)
_BAD_TERM_PAT = re.compile(r"(e\.g\.|z\.\s*b\.|\(|\)|,|;)", re.IGNORECASE)
_GENERIC_RESEARCH_WORD_SET = {w.casefold() for w in _GENERIC_RESEARCH_WORDS}
_ANCHOR_JOINER_WORDS = {
    "and",
    "or",
    "of",
    "for",
    "the",
    "a",
    "an",
    "und",
    "oder",
    "von",
    "für",
    "der",
    "die",
    "das",
}


def _word_count(text: str) -> int:
    return len([w for w in re.split(r"\s+", str(text or "").strip()) if w])


def _phrase_tokens(text: str) -> List[str]:
    return [t.casefold() for t in re.findall(r"[\w-]+", str(text or ""), flags=re.UNICODE) if t]


def _normalized_phrase(text: str) -> str:
    return " ".join(_phrase_tokens(text))


def _is_vague_anchor(term: str) -> bool:
    toks = _phrase_tokens(term)
    if not toks:
        return True
    content = [t for t in toks if t not in _ANCHOR_JOINER_WORDS]
    if not content:
        return True
    if len(content) == 1 and content[0] in _GENERIC_RESEARCH_WORD_SET:
        return True
    return all(t in _GENERIC_RESEARCH_WORD_SET for t in content)


def _is_short_plain_text(text: str, *, min_words: int = 1, max_words: int = 12, max_chars: int = 120) -> bool:
    s = str(text or "").strip()
    if not s:
        return False
    if len(s) > int(max_chars):
        return False
    n_words = _word_count(s)
    if n_words < int(min_words) or n_words > int(max_words):
        return False
    return True


def _is_atomic_exclusion(term: str) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _BAD_EXCL_PAT.search(t):
        return False
    if len(t) > 40:
        return False
    if _word_count(t) > 3:
        return False
    if re.search(r"[^\w\s-]", t, flags=re.UNICODE):
        return False
    return True


def _is_hygienic_term(term: str, *, max_words: int) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _BAD_TERM_PAT.search(t):
        return False
    if _word_count(t) > int(max_words):
        return False
    return True


def _dedupe_keep_order(items: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items or []:
        s = str(item or "").strip()
        if not s or s in seen:
            continue
        seen.add(s)
        out.append(s)
    return out


def _clean_short_text(text: str, *, fallback: str, max_words: int, max_chars: int) -> str:
    s = re.sub(r"\s+", " ", str(text or "").strip())
    if not s:
        s = fallback
    words = s.split()
    if len(words) > int(max_words):
        s = " ".join(words[: int(max_words)]).strip()
    if len(s) > int(max_chars):
        s = s[: int(max_chars)].rstrip()
    return s or fallback


def _choose_blueprint_language_strategy(kind: str, target_ids: List[str], facet_by_id: Dict[str, Facet]) -> str:
    strategies = [
        str(getattr(facet_by_id.get(fid), "language_strategy", "") or "")
        for fid in (target_ids or [])
        if facet_by_id.get(fid) is not None
    ]
    strategies = [x for x in strategies if x in LANGUAGE_STRATEGY_ENUM]
    if kind == "core":
        for pref in ["en_de_parallel", "en_plus_bilingual_fallback", "en_plus_selective_de", "en_core_only"]:
            if pref in strategies:
                return pref
        return "en_plus_bilingual_fallback"
    for pref in ["en_plus_selective_de", "en_plus_bilingual_fallback", "en_core_only", "en_de_parallel"]:
        if pref in strategies:
            return pref
    return "en_plus_selective_de"


def _authority_target_sort_key(fid: str, *, kind: str, facet_by_id: Dict[str, Facet]) -> Tuple[int, int, str]:
    facet = facet_by_id.get(fid)
    if facet is None:
        return (99, 99, fid)
    group = str(getattr(facet, "facet_group", "") or "")
    if kind == "core":
        group_rank = {"object": 0, "construct": 1, "data_proxy": 2, "context": 3, "limitation": 4, "method": 5}
    else:
        group_rank = {"context": 0, "limitation": 1, "data_proxy": 2, "method": 3, "construct": 4, "object": 5}
    return (group_rank.get(group, 9), -int(getattr(facet, "importance_weight", 0) or 0), fid)


def _make_authority_blueprint(
    *,
    kind: str,
    ordinal: int,
    target_ids: List[str],
    facet_by_id: Dict[str, Facet],
) -> AuthorityBlueprint:
    target_ids = _dedupe_keep_order(target_ids)[:4]
    label_seed = None
    if target_ids:
        facet0 = facet_by_id.get(target_ids[0])
        if facet0 is not None:
            label_seed = str(getattr(facet0, "facet_label_en", "") or "").strip()
    label_seed = label_seed or ("core authority" if kind == "core" else "booster authority")
    label_en = _clean_short_text(
        f"{'Core' if kind == 'core' else 'Booster'} {label_seed}",
        fallback=f"{'Core' if kind == 'core' else 'Booster'} authority {ordinal}",
        max_words=8,
        max_chars=80,
    )
    label_de = _clean_short_text(
        f"{'Kern' if kind == 'core' else 'Booster'} {label_seed}",
        fallback=f"{'Kern' if kind == 'core' else 'Booster'} Literatur {ordinal}",
        max_words=8,
        max_chars=80,
    )
    notes_en = _clean_short_text(
        (
            "Tight authority coverage for the chapter object."
            if kind == "core"
            else "Broader authority coverage that remains chapter-anchored."
        ),
        fallback="Authority blueprint",
        max_words=18,
        max_chars=120,
    )
    return AuthorityBlueprint(
        authority_kind=kind,
        label_en=label_en,
        label_de=label_de,
        target_facet_ids=target_ids,
        language_strategy=_choose_blueprint_language_strategy(kind, target_ids, facet_by_id),
        search_breadth="tight" if kind == "core" else "broad_ok",
        notes_en=notes_en,
    )


def _repair_query_plan(plan: QueryPlan) -> Tuple[QueryPlan, List[str]]:
    repair_notes: List[str] = []

    repaired_facets: List[Facet] = []
    for facet in list(plan.facets or []):
        fg = str(getattr(facet, "facet_group", "") or "")
        qfp = str(getattr(facet, "query_family_preference", "") or "")
        allowed = FACET_GROUP_TO_QUERY_FAMILY.get(fg) or set()
        if allowed and qfp not in allowed:
            new_qfp = DEFAULT_QUERY_FAMILY_BY_GROUP.get(fg) or sorted(allowed)[0]
            if new_qfp != qfp:
                repair_notes.append(
                    f"facet[{facet.facet_id}] query_family_preference repaired from {qfp!r} to {new_qfp!r}"
                )
                facet = facet.model_copy(update={"query_family_preference": new_qfp})
        repaired_facets.append(facet)

    if not any(str(getattr(f, "authority_role", "") or "") == "core" for f in repaired_facets):
        candidates = sorted(
            repaired_facets,
            key=lambda f: (
                {"object": 0, "construct": 1, "data_proxy": 2, "context": 3, "limitation": 4, "method": 5}.get(
                    str(getattr(f, "facet_group", "") or ""),
                    9,
                ),
                -int(getattr(f, "importance_weight", 0) or 0),
                str(getattr(f, "facet_id", "") or ""),
            ),
        )
        if candidates:
            chosen = candidates[0]
            repair_notes.append(f"facet[{chosen.facet_id}] authority_role promoted to 'core' to guarantee core authority coverage")
            repaired_facets = [
                (f.model_copy(update={"authority_role": "core"}) if f.facet_id == chosen.facet_id else f)
                for f in repaired_facets
            ]

    facet_by_id: Dict[str, Facet] = {
        str(f.facet_id or "").strip(): f
        for f in repaired_facets
        if str(getattr(f, "facet_id", "") or "").strip()
    }
    role_to_ids = {
        "core": [
            f.facet_id
            for f in repaired_facets
            if str(getattr(f, "authority_role", "") or "") == "core" and str(getattr(f, "facet_id", "") or "").strip()
        ],
        "booster": [
            f.facet_id
            for f in repaired_facets
            if str(getattr(f, "authority_role", "") or "") == "booster" and str(getattr(f, "facet_id", "") or "").strip()
        ],
    }

    repaired_blueprints: List[AuthorityBlueprint] = []
    kind_counter = {"core": 0, "booster": 0}
    for bp in list(plan.authority_blueprints or []):
        kind = str(getattr(bp, "authority_kind", "") or "")
        if kind not in AUTHORITY_KIND_ENUM:
            kind = "core" if kind_counter["core"] == 0 else "booster"
            repair_notes.append(
                f"authority_blueprint[{getattr(bp, 'label_en', '?')}] authority_kind repaired to {kind!r}"
            )
        raw_target_ids = _dedupe_keep_order(
            [str(x or "").strip() for x in (getattr(bp, "target_facet_ids", None) or []) if str(x or "").strip()]
        )
        filtered_target_ids = [fid for fid in raw_target_ids if fid in facet_by_id and fid in role_to_ids.get(kind, [])]
        filtered_target_ids = sorted(
            filtered_target_ids,
            key=lambda fid: _authority_target_sort_key(fid, kind=kind, facet_by_id=facet_by_id),
        )[:4]
        if raw_target_ids != filtered_target_ids:
            repair_notes.append(
                f"authority_blueprint[{getattr(bp, 'label_en', '?')}] target_facet_ids normalized to {filtered_target_ids}"
            )

        if not filtered_target_ids and role_to_ids.get(kind):
            continue

        kind_counter[kind] += 1
        fallback_bp = _make_authority_blueprint(
            kind=kind,
            ordinal=kind_counter[kind],
            target_ids=filtered_target_ids,
            facet_by_id=facet_by_id,
        )
        repaired_blueprints.append(
            AuthorityBlueprint(
                authority_kind=kind,
                label_en=_clean_short_text(
                    getattr(bp, "label_en", ""),
                    fallback=fallback_bp.label_en,
                    max_words=8,
                    max_chars=80,
                ),
                label_de=_clean_short_text(
                    getattr(bp, "label_de", ""),
                    fallback=fallback_bp.label_de,
                    max_words=8,
                    max_chars=80,
                ),
                target_facet_ids=filtered_target_ids,
                language_strategy=(
                    str(getattr(bp, "language_strategy", "") or "")
                    if str(getattr(bp, "language_strategy", "") or "") in LANGUAGE_STRATEGY_ENUM
                    else fallback_bp.language_strategy
                ),
                search_breadth=(
                    "tight"
                    if kind == "core"
                    else (
                        str(getattr(bp, "search_breadth", "") or "")
                        if str(getattr(bp, "search_breadth", "") or "") in AUTHORITY_SEARCH_BREADTH_ENUM
                        else fallback_bp.search_breadth
                    )
                ),
                notes_en=_clean_short_text(
                    getattr(bp, "notes_en", ""),
                    fallback=fallback_bp.notes_en,
                    max_words=18,
                    max_chars=120,
                ),
            )
        )

    if role_to_ids["core"] and not any(bp.authority_kind == "core" for bp in repaired_blueprints):
        kind_counter["core"] += 1
        repaired_blueprints.append(
            _make_authority_blueprint(
                kind="core",
                ordinal=kind_counter["core"],
                target_ids=sorted(
                    role_to_ids["core"],
                    key=lambda fid: _authority_target_sort_key(fid, kind="core", facet_by_id=facet_by_id),
                )[:4],
                facet_by_id=facet_by_id,
            )
        )
        repair_notes.append("created core authority blueprint to cover core authority facets")

    assigned_by_kind = {"core": set(), "booster": set()}
    for bp in repaired_blueprints:
        assigned_by_kind.setdefault(bp.authority_kind, set()).update(bp.target_facet_ids or [])

    for kind in ("core", "booster"):
        unassigned = [fid for fid in role_to_ids.get(kind, []) if fid not in assigned_by_kind.get(kind, set())]
        if not unassigned:
            continue

        for idx, bp in enumerate(list(repaired_blueprints)):
            if not unassigned or bp.authority_kind != kind:
                continue
            current = list(bp.target_facet_ids or [])
            capacity = 4 - len(current)
            if capacity <= 0:
                continue
            additions = unassigned[:capacity]
            repaired_blueprints[idx] = bp.model_copy(update={"target_facet_ids": current + additions})
            assigned_by_kind.setdefault(kind, set()).update(additions)
            unassigned = unassigned[capacity:]
            repair_notes.append(
                f"authority_blueprint[{bp.label_en}] extended with {additions} to cover {kind} authority facets"
            )

        while unassigned and len(repaired_blueprints) < 4:
            kind_counter[kind] += 1
            chunk = sorted(
                unassigned[:4],
                key=lambda fid: _authority_target_sort_key(fid, kind=kind, facet_by_id=facet_by_id),
            )
            repaired_blueprints.append(
                _make_authority_blueprint(
                    kind=kind,
                    ordinal=kind_counter[kind],
                    target_ids=chunk,
                    facet_by_id=facet_by_id,
                )
            )
            assigned_by_kind.setdefault(kind, set()).update(chunk)
            repair_notes.append(f"created {kind} authority blueprint for facets {chunk}")
            unassigned = [fid for fid in unassigned if fid not in set(chunk)]

    repaired_plan = plan.model_copy(update={"facets": repaired_facets, "authority_blueprints": repaired_blueprints})
    return repaired_plan, repair_notes


def diagnose_query_plan(plan: QueryPlan) -> Dict[str, Any]:
    issues: List[str] = []

    n_facets = len(plan.facets)
    if n_facets < 8 or n_facets > 20:
        issues.append(f"CRITICAL: facet count is {n_facets} (expected 8–20).")

    ids = [f.facet_id for f in plan.facets]
    dup_ids = sorted({x for x in ids if ids.count(x) > 1})
    if dup_ids:
        issues.append(f"CRITICAL: duplicate facet_id(s): {dup_ids}")

    bad_weights = [f.facet_id for f in plan.facets if not (1 <= f.importance_weight <= 5)]
    if bad_weights:
        issues.append(f"CRITICAL: facets with invalid importance_weight: {bad_weights}")

    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        if len(anchors) < 4 or len(anchors) > 10:
            issues.append(f"CRITICAL: primary_context_anchors.{lang} has {len(anchors)} items (expected 4–10).")

        bad = []
        for a in anchors:
            aa = str(a or "").strip()
            if not aa:
                bad.append(a)
                continue
            if not _is_hygienic_term(aa, max_words=6):
                bad.append(aa)
                continue
            if _is_vague_anchor(aa):
                bad.append(aa)
                continue
        if bad:
            issues.append(f"CRITICAL: primary_context_anchors.{lang} contains invalid/generic anchors: {bad[:6]}")

    for lang in ("en", "de"):
        obj_terms = getattr(plan.core_object_terms, lang, []) or []
        if len(obj_terms) < 3 or len(obj_terms) > 12:
            issues.append(f"CRITICAL: core_object_terms.{lang} has {len(obj_terms)} items (expected 3–12).")
        bad = []
        for t in obj_terms:
            tt = str(t or "").strip()
            if not _is_hygienic_term(tt, max_words=4):
                bad.append(tt)
                continue
            if _is_vague_anchor(tt):
                bad.append(tt)
                continue
        if bad:
            issues.append(f"CRITICAL: core_object_terms.{lang} contains invalid/generic terms: {bad[:6]}")

    anchors_norm = {
        lang: {_normalized_phrase(x) for x in (getattr(plan.primary_context_anchors, lang, []) or []) if _normalized_phrase(x)}
        for lang in ("en", "de")
    }
    obj_norm = {
        lang: {_normalized_phrase(x) for x in (getattr(plan.core_object_terms, lang, []) or []) if _normalized_phrase(x)}
        for lang in ("en", "de")
    }
    for lang in ("en", "de"):
        overlap = any((a == c) or (a in c) or (c in a) for a in anchors_norm[lang] for c in obj_norm[lang])
        if not overlap:
            issues.append(f"CRITICAL: primary_context_anchors.{lang} does not preserve any core_object_terms.{lang} phrase.")

    mkc = list(plan.must_keep_constraints or [])
    if len(mkc) < 3 or len(mkc) > 10:
        issues.append(f"CRITICAL: must_keep_constraints has {len(mkc)} items (expected 3–10).")
    bad_mkc = [x for x in mkc if not _is_short_plain_text(x, min_words=2, max_words=12, max_chars=120)]
    if bad_mkc:
        issues.append(f"CRITICAL: must_keep_constraints contains invalid items: {bad_mkc[:6]}")

    drift = list(plan.drift_risks or [])
    if len(drift) < 2 or len(drift) > 8:
        issues.append(f"CRITICAL: drift_risks has {len(drift)} items (expected 2–8).")
    bad_drift = [x for x in drift if not _is_short_plain_text(x, min_words=2, max_words=12, max_chars=120)]
    if bad_drift:
        issues.append(f"CRITICAL: drift_risks contains invalid items: {bad_drift[:6]}")

    authority_blueprints = list(plan.authority_blueprints or [])
    if len(authority_blueprints) < 1 or len(authority_blueprints) > 4:
        issues.append(f"CRITICAL: authority_blueprints has {len(authority_blueprints)} items (expected 1–4).")

    facet_id_set = {str(f.facet_id or "").strip() for f in plan.facets if str(f.facet_id or "").strip()}
    core_bp_n = 0
    for bp in authority_blueprints:
        if str(getattr(bp, "authority_kind", "") or "") not in AUTHORITY_KIND_ENUM:
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] has invalid authority_kind.")
        if str(getattr(bp, "language_strategy", "") or "") not in LANGUAGE_STRATEGY_ENUM:
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] has invalid language_strategy.")
        if str(getattr(bp, "search_breadth", "") or "") not in AUTHORITY_SEARCH_BREADTH_ENUM:
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] has invalid search_breadth.")
        if not _is_short_plain_text(getattr(bp, "label_en", ""), min_words=1, max_words=8, max_chars=80):
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] label_en is invalid.")
        if not _is_short_plain_text(getattr(bp, "label_de", ""), min_words=1, max_words=8, max_chars=80):
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] label_de is invalid.")
        if not _is_short_plain_text(getattr(bp, "notes_en", ""), min_words=2, max_words=18, max_chars=120):
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] notes_en is invalid.")

        target_ids = [str(x or "").strip() for x in (getattr(bp, "target_facet_ids", None) or []) if str(x or "").strip()]
        if len(target_ids) < 1 or len(target_ids) > 4:
            issues.append(f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] target_facet_ids has {len(target_ids)} items (expected 1–4).")
        missing_target_ids = [x for x in target_ids if x not in facet_id_set]
        if missing_target_ids:
            issues.append(
                f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] references unknown facet_ids: {missing_target_ids[:6]}"
            )

        if str(getattr(bp, "authority_kind", "") or "") == "core":
            core_bp_n += 1
            if str(getattr(bp, "search_breadth", "") or "") != "tight":
                issues.append(
                    f"CRITICAL: authority_blueprint[{getattr(bp, 'label_en', '?')}] core authority must use search_breadth='tight'."
                )

    if core_bp_n < 1:
        issues.append("CRITICAL: authority_blueprints must include at least one core blueprint.")

    def check_term_list(name: str, terms: List[str], *, max_words: int) -> None:
        bad_terms = [t for t in (terms or []) if not _is_hygienic_term(t, max_words=max_words)]
        if bad_terms:
            issues.append(f"CRITICAL: {name} contains non-hygienic terms: {bad_terms[:8]}")

    check_term_list("global_canonical_terms.en", plan.global_canonical_terms.en, max_words=4)
    check_term_list("global_canonical_terms.de", plan.global_canonical_terms.de, max_words=4)

    def check_exclusions(name: str, terms: List[str]) -> None:
        bad_terms = [t for t in (terms or []) if not _is_atomic_exclusion(t)]
        if bad_terms:
            issues.append(f"CRITICAL: {name} contains non-atomic exclusions: {bad_terms[:8]}")

    check_exclusions("global_exclusions.en", plan.global_exclusions.en)
    check_exclusions("global_exclusions.de", plan.global_exclusions.de)

    for f in plan.facets:
        fg = str(getattr(f, "facet_group", "") or "")
        qfp = str(getattr(f, "query_family_preference", "") or "")
        ls = str(getattr(f, "language_strategy", "") or "")
        ar = str(getattr(f, "authority_role", "") or "")
        if fg not in FACET_GROUP_ENUM:
            issues.append(f"CRITICAL: facet[{f.facet_id}] has invalid facet_group: {getattr(f, 'facet_group', None)!r}")
        if qfp not in QUERY_FAMILY_ENUM:
            issues.append(f"CRITICAL: facet[{f.facet_id}] has invalid query_family_preference: {qfp!r}")
        if ls not in LANGUAGE_STRATEGY_ENUM:
            issues.append(f"CRITICAL: facet[{f.facet_id}] has invalid language_strategy: {ls!r}")
        if ar not in AUTHORITY_ROLE_ENUM:
            issues.append(f"CRITICAL: facet[{f.facet_id}] has invalid authority_role: {ar!r}")
        if fg in FACET_GROUP_TO_QUERY_FAMILY and qfp and qfp not in FACET_GROUP_TO_QUERY_FAMILY[fg]:
            issues.append(
                f"CRITICAL: facet[{f.facet_id}] query_family_preference={qfp!r} is inconsistent with facet_group={fg!r}."
            )
        check_term_list(f"facet[{f.facet_id}].canonical_terms.en", f.canonical_terms.en, max_words=4)
        check_term_list(f"facet[{f.facet_id}].canonical_terms.de", f.canonical_terms.de, max_words=4)
        check_term_list(f"facet[{f.facet_id}].neighbor_terms.en", f.neighbor_terms.en, max_words=4)
        check_term_list(f"facet[{f.facet_id}].neighbor_terms.de", f.neighbor_terms.de, max_words=4)
        check_exclusions(f"facet[{f.facet_id}].exclusion_terms.en", f.exclusion_terms.en)
        check_exclusions(f"facet[{f.facet_id}].exclusion_terms.de", f.exclusion_terms.de)

    facet_groups_all = [str(getattr(f, "facet_group", "") or "") for f in plan.facets]
    if "object" not in facet_groups_all:
        issues.append("CRITICAL: QueryPlan has no object facet_group facet.")

    high_value_groups = [
        str(getattr(f, "facet_group", "") or "")
        for f in plan.facets
        if int(getattr(f, "importance_weight", 0) or 0) >= 4
    ]
    if not any(g in {"object", "construct", "data_proxy"} for g in high_value_groups):
        issues.append("CRITICAL: weight>=4 facets do not include any object/construct/data_proxy facet_group.")

    method_heavy = sum(1 for g in high_value_groups if g == "method")
    objectish = sum(1 for g in high_value_groups if g in {"object", "construct", "data_proxy"})
    if high_value_groups and method_heavy > objectish:
        issues.append("Method-heavy weighting detected: weight>=4 method facets outnumber object/construct/data_proxy facets.")

    core_authority_facets = [f for f in plan.facets if str(getattr(f, "authority_role", "") or "") == "core"]
    booster_authority_facets = [f for f in plan.facets if str(getattr(f, "authority_role", "") or "") == "booster"]
    if not core_authority_facets:
        issues.append("CRITICAL: no facets are marked authority_role='core'.")
    core_authority_groups = {str(getattr(f, "facet_group", "") or "") for f in core_authority_facets}
    if core_authority_groups and not any(g in {"object", "construct", "data_proxy", "context"} for g in core_authority_groups):
        issues.append("CRITICAL: authority_role='core' facets are not object/construct/data_proxy/context-led.")
    if core_authority_facets and all(str(getattr(f, "facet_group", "") or "") == "method" for f in core_authority_facets):
        issues.append("CRITICAL: all authority_role='core' facets are method facets.")

    bp_targets_by_kind = {"core": set(), "booster": set()}
    for bp in authority_blueprints:
        kind = str(getattr(bp, "authority_kind", "") or "")
        target_ids = {str(x or "").strip() for x in (getattr(bp, "target_facet_ids", None) or []) if str(x or "").strip()}
        bp_targets_by_kind.setdefault(kind, set()).update(target_ids)
    for f in core_authority_facets:
        if f.facet_id not in bp_targets_by_kind.get("core", set()):
            issues.append(f"CRITICAL: facet[{f.facet_id}] authority_role='core' is not referenced by any core authority blueprint.")
    for f in booster_authority_facets:
        if f.facet_id not in bp_targets_by_kind.get("booster", set()):
            issues.append(
                f"CRITICAL: facet[{f.facet_id}] authority_role='booster' is not referenced by any booster authority blueprint."
            )

    canon_sets: Dict[Tuple[Tuple[str, ...], Tuple[str, ...]], str] = {}
    overlaps: List[Tuple[str, str]] = []
    for f in plan.facets:
        key = (
            tuple(sorted({t.strip().lower() for t in f.canonical_terms.en if str(t or "").strip()})),
            tuple(sorted({t.strip().lower() for t in f.canonical_terms.de if str(t or "").strip()})),
        )
        if key in canon_sets and key != ((), ()):
            overlaps.append((canon_sets[key], f.facet_id))
        else:
            canon_sets[key] = f.facet_id

    if overlaps:
        issues.append(f"Potential duplicate facets (identical canonical_terms): {overlaps[:5]}")

    critical = [x for x in issues if str(x).startswith("CRITICAL:")]
    return {"facet_count": n_facets, "issues": issues, "critical_issues": critical}


def _is_placeholder_cache(obj: Any) -> bool:
    if not isinstance(obj, dict):
        return False
    meta = obj.get("_meta")
    return isinstance(meta, dict) and meta.get("placeholder") is True


async def plan_queries_llm(
    chapter_input: ChapterInput,
    *,
    config: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    force_rebuild: bool = False,
) -> Tuple[QueryPlan, Dict[str, Any]]:
    stage = "phase_b_query_planner"
    cache_path = run_ctx.artifacts.query_plan_json

    if cache_path.exists() and not force_rebuild:
        try:
            cached_obj = read_json(cache_path)
            if _is_placeholder_cache(cached_obj):
                log_event(run_ctx, stage=stage, event="cache_placeholder_ignored", path=str(cache_path))
            else:
                plan = QueryPlan.model_validate(cached_obj)
                plan, repair_notes = _repair_query_plan(plan)
                meta = {
                    "cache_hit": True,
                    "usage": {
                        "input_tokens": 0,
                        "cached_input_tokens": 0,
                        "output_tokens": 0,
                        "reasoning_tokens": 0,
                    },
                    "cost_usd": 0.0,
                    "diagnostics": diagnose_query_plan(plan),
                    "repair_notes": repair_notes,
                }
                if repair_notes:
                    write_json(cache_path, plan.model_dump(mode="json"))
                    log_event(run_ctx, stage=stage, event="cache_repaired", path=str(cache_path), repairs=repair_notes[:8])
                log_event(run_ctx, stage=stage, event="cache_hit", path=str(cache_path))
                return plan, meta
        except Exception as e:
            err = str(e)
            err_short = err if len(err) <= 800 else (err[:800] + "…")
            write_json(run_ctx.run_dir / "query_plan.cache_invalid.json", {"ts": utc_now_iso(), "path": str(cache_path), "error": err})
            log_event(run_ctx, stage=stage, event="cache_invalid", path=str(cache_path), error=err_short)

    user_prompt = planner_user_prompt(chapter_input)

    max_attempts = 3
    last_err: Optional[Exception] = None
    obj: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    plan: Optional[QueryPlan] = None
    repair_notes: List[str] = []

    with stage_timer(run_ctx, stage):
        for attempt in range(1, max_attempts + 1):
            debug_prefix = f"query_plan_attempt{attempt}"
            attempt_prompt = user_prompt
            if last_err is not None:
                attempt_prompt = (
                    user_prompt
                    + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                    + f"- Error: {str(last_err)[:600]}\n"
                )

            try:
                obj, meta = await llm.json_schema_call(
                    stage=stage,
                    operation_type="quellen_finder_two_lane_query_planner",
                    model=config.openai_model_planner,
                    system_prompt=PLANNER_SYSTEM_PROMPT,
                    user_prompt=attempt_prompt,
                    schema_name="query_plan",
                    schema=QUERY_PLAN_JSON_SCHEMA,
                    reasoning_effort=config.openai_reasoning_effort,
                    max_output_tokens=getattr(config, "openai_max_output_tokens_planner", 6000),
                    timeout_s=config.openai_timeout_s,
                    operation_details={"attempt": int(attempt)},
                )
            except Exception as e:
                last_err = e
                dbg = {
                    "ts": utc_now_iso(),
                    "stage": stage,
                    "attempt": attempt,
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                    "chapter_title": chapter_input.chapter_title,
                    "pipeline_version": chapter_input.pipeline_version,
                }
                write_json(run_ctx.run_dir / f"{debug_prefix}.error.json", dbg)
                log_event(run_ctx, stage=stage, event="openai_error", attempt=attempt, error=str(e)[:800])
                if attempt >= max_attempts:
                    raise
                continue

            attempt_raw_path = run_ctx.run_dir / f"{debug_prefix}.raw_output.json"
            attempt_meta_path = run_ctx.run_dir / f"{debug_prefix}.openai_meta.json"
            write_json(attempt_raw_path, obj)
            write_json(attempt_meta_path, meta)

            try:
                plan = QueryPlan.model_validate(obj)
                plan, repair_notes = _repair_query_plan(plan)
                diag = diagnose_query_plan(plan)
                critical = diag.get("critical_issues") or []
                if critical:
                    raise ValueError("QueryPlan failed hygiene checks: " + "; ".join([str(x) for x in critical[:6]]))

                if repair_notes:
                    log_event(run_ctx, stage=stage, event="plan_repaired", attempt=attempt, repairs=repair_notes[:8])

                write_json(run_ctx.run_dir / "query_plan.raw_output.json", obj)
                write_json(run_ctx.run_dir / "query_plan.openai_meta.json", meta)
                break
            except Exception as e:
                last_err = e
                log_event(run_ctx, stage=stage, event="lint_failed", attempt=attempt, error=str(e)[:800], raw_path=str(attempt_raw_path))
                if attempt >= max_attempts:
                    raise
                continue

    if plan is None:
        raise RuntimeError("QueryPlan generation failed unexpectedly (no plan).")

    write_json(cache_path, plan.model_dump(mode="json"))
    log_event(run_ctx, stage=stage, event="cache_write", path=str(cache_path), model_used=meta.get("model_used"), usage=meta.get("usage"), cost=meta.get("cost_usd"))

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["openai"] = meta
    save_metrics(run_ctx, metrics)

    meta = dict(meta)
    meta["cache_hit"] = False
    meta["diagnostics"] = diagnose_query_plan(plan)
    meta["repair_notes"] = repair_notes
    return plan, meta


# -----------------------------
# Phase C — Provider-specific query generators (ported)
# -----------------------------


class OpenAlexQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["authority", "match"]
    language: Literal["en", "de"]
    search_field: Literal["search", "default.search", "title_and_abstract.search"] = "title_and_abstract.search"
    query_string: str
    filters: str
    sort: Optional[Literal["cited_by_count:desc", "relevance_score:desc"]] = None
    per_page: int = Field(default=200)
    notes: str


class S2BulkQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: Literal["authority", "match"]
    language: Literal["en", "de"]
    query_string: str
    notes: str


OPENALEX_QUERY_BUILDER_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["openalex_queries"],
    "properties": {
        "openalex_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["intent", "language", "search_field", "query_string", "filters", "sort", "per_page", "notes"],
                "properties": {
                    "intent": {"type": "string", "enum": ["authority", "match"]},
                    "language": {"type": "string", "enum": ["en", "de"]},
                    "search_field": {"type": "string", "enum": ["search", "title_and_abstract.search"]},
                    "query_string": {"type": "string"},
                    "filters": {"type": "string"},
                    "sort": {
                        "anyOf": [
                            {"type": "string", "enum": ["cited_by_count:desc", "relevance_score:desc"]},
                            {"type": "null"},
                        ]
                    },
                    "per_page": {"type": "integer", "enum": [200]},
                    "notes": {"type": "string"},
                },
            },
        }
    },
}


S2_BULK_QUERY_BUILDER_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["s2_bulk_queries"],
    "properties": {
        "s2_bulk_queries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["intent", "language", "query_string", "notes"],
                "properties": {
                    "intent": {"type": "string", "enum": ["authority", "match"]},
                    "language": {"type": "string", "enum": ["en", "de"]},
                    "query_string": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        }
    },
}


OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT = """You generate OpenAlex /works query objects for a multi-stage scientific retrieval pipeline.
Your job is to maximize useful recall without losing the chapter's true object.

Priority order:
1) Keep every query inside the chapter object, corpus, or domain.
2) Cover the main constructs, data/proxy constraints, and required facets.
3) Add breadth through controlled synonym and facet variation.
4) Add authority boosters only when they remain chapter-anchored.
5) Prefer simpler provider-safe syntax over clever but brittle syntax.

Do not output prose. Output only valid JSON.
Be deterministic.
"""


OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE = """PIPELINE CONTEXT:
You generate provider-safe OpenAlex /works query objects for a two-lane retrieval pipeline.
These queries only collect candidates, but you must still prevent generic-method drift now.

CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}
languages = ["en","de"]

GOAL HIERARCHY:
- authority: canonical/high-impact literature that is still clearly about the chapter object
- match: strongest topical fit for the chapter, including strong partial matches on required facets
- do not spend budget on queries that are mainly about a generic method with weak chapter-object anchoring

PLANNER-CONTROLLED INPUT FIELDS:
- Each facet includes:
  - query_family_preference: the dominant query shape Phase C should use
  - language_strategy: whether the facet should stay EN-core, use bilingual fallback, or support selective DE
  - authority_role: none | core | booster
- authority_blueprints is the canonical upstream authority split.
- authority_blueprints_expanded repeats each blueprint with its target facet controls for easier use.
- Generate authority queries from authority_blueprints first. Do not invent flat authority families that ignore this split.

OUTPUT JSON SCHEMA:
{
  "openalex_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "search_field": "search" | "title_and_abstract.search",
      "query_string": "BOOLEAN QUERY STRING",
      "filters": "comma,separated,filters",
      "sort": "cited_by_count:desc" | "relevance_score:desc" | null,
      "per_page": 200,
      "notes": "<= 18 words"
    }
  ]
}

IMPORTANT IMPLEMENTATION NOTE:
The live API probe showed:
- top-level OpenAlex `search` is much broader than `title_and_abstract.search`
- wildcard and `~` syntax can work on top-level `search`
- exact phrase AND can collapse quickly if the phrase pair is too rare

So for THIS task:
- authority queries should generally use `search`
- match queries should generally use `title_and_abstract.search`
- use readable quoted phrases first
- use `*` or `~` only on `search` and only when they clearly solve a recall problem
- do NOT use `?`
- AND/OR/NOT must be uppercase
- avoid slash tokens X/Y; rewrite as (X OR Y)

MANDATORY RETRIEVAL RULES:
1) Every query MUST include at least one term from primary_context_anchors[language].
2) Every MATCH query must include:
   - one core object/corpus/domain anchor
   - and one construct/data/method group that is meaningful only inside that object
3) Pure method-only queries are NOT allowed.
4) Authority queries may be broader, but they must still remain about the chapter object.
5) Use exclusions only for true wrong-sense confounders. If exclusions are weak or messy, omit them.

FILTER POLICY:
- filters MUST include: is_paratext:false, is_retracted:false, language:<en|de>
- use only comma-separated filters
- use only safe keys already supported by the implementation:
  language,is_paratext,is_retracted,type,from_publication_date,to_publication_date,
  primary_location.source.is_core,locations.source.is_core

search_field policy:
- authority -> "search"
- match -> "title_and_abstract.search"
- authority blueprint with authority_kind="core" and search_breadth="tight":
  use object-led phrasing, avoid speculative broadening, and avoid wildcard/fuzzy unless recall would otherwise collapse
- authority blueprint with authority_kind="booster" and search_breadth="broad_ok":
  broader `search` is allowed, but the chapter object must still remain explicit

QUERY FAMILIES TO COVER:
- emit all core authority blueprints first
- emit booster authority blueprints only after core authority coverage is satisfied
- global object+construct match EN + at least one DE or bilingual core query
- object+facet queries for weight>=4 facets, using each facet's query_family_preference
- if budget remains, prefer object+data/proxy or object+limitations expansions before object+method expansions

LANGUAGE POLICY:
- obey the planner's language_strategy for each facet or authority blueprint
- en_core_only -> emit EN only
- en_plus_bilingual_fallback -> emit EN and use one bilingual rescue query instead of fragile DE clones when needed
- en_plus_selective_de -> emit EN plus DE only when the phrasing is likely to survive title/abstract search
- en_de_parallel -> emit both EN and DE
- do not mirror every English query into German mechanically
- if the German rendering becomes too literal, niche, or implementation-like, prefer one strongly object-anchored DE core query over multiple dead DE clones
- keep DE coverage for queries whose object phrase and facet phrase are both likely to appear in German titles/abstracts

LEXICALITY POLICY:
- prefer literature-native phrases that are likely to appear verbatim in titles/abstracts
- prefer direct object phrases over implementation jargon or abstract substitutes
- prefer full forms before acronyms or project-local shorthand

QUERY SHAPES:
- object_core -> ("core object" OR variants) AND ("construct" OR close object-defining context)
- object_plus_construct -> ("core object" OR variants) AND ("construct" OR variants)
- object_plus_data_proxy -> ("core object" OR variants) AND ("data" OR "proxy" OR "measurement" variants)
- object_plus_method -> ("core object" OR variants) AND ("specific method" OR close variants)
- object_plus_limitation -> ("core object" OR variants) AND ("bias" OR "validity" OR "limitation" variants)
- object_plus_context -> ("core object" OR variants) AND ("domain" OR "platform" OR "setting" variants)
- authority core -> object-led, tight, field-defining construct/data/context phrasing
- authority booster -> broader but still chapter-anchored authority expansion

BUDGETING:
- authority: 1 query per core authority blueprint first
- authority: then up to 1 query per booster authority blueprint if budget remains and lexicality is plausible
- match: global match EN + at least one DE or bilingual core query
- match: for each facet with weight>=4 -> 1 EN query, plus DE only when the facet language_strategy supports it
- if budget remains -> extra object-anchored expansions only

EMPTY-QUERY TARGET:
- some narrow zero-yield probes are acceptable
- core authority and core object+construct families should usually have a plausible hit path
- avoid stacking rare exact phrases, brittle exclusions, and literal DE mirroring in the same query

SELF-CHECK (must enforce silently):
- Would this query still retrieve many generic method surveys if the object phrase were removed? If yes, strengthen it.
- Does every query include an object anchor, not only a method term? If not, fix it.
- Did this authority query come from a core or booster authority blueprint? If not, fix it.
- Does the query shape match the facet's query_family_preference? If not, fix it.
- Are exclusions atomic and provider-safe? If not, omit them.
- Are boolean operators uppercase and filters safe? If not, fix them.
- Are `*` or `~` used only on `search` and only when clearly justified? If not, simplify.

Return ONLY JSON.
"""


S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT = """You generate Semantic Scholar Academic Graph bulk search queries for scientific literature retrieval.
Reliability and chapter anchoring are more important than clever syntax.

Priority order:
1) Keep every query inside the chapter object, corpus, or domain.
2) Cover the main constructs, data/proxy constraints, and required facets.
3) Use title/abstract-plausible wording and simple, provider-safe syntax first.
4) Use advanced syntax only when it clearly solves a recall problem.

Never mix context anchors and facet terms in the same OR-group.
Keep every query interpretable by a human reviewer.
Output ONLY valid JSON. No prose.
Be deterministic."""


S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE = """CHAPTER_TITLE:
{{chapter_title}}

CHAPTER_SPEC_TEXT:
{{chapter_spec_text}}

INPUT_QUERY_PLAN_JSON:
{{query_plan_json}}

BUDGET:
max_queries = {{max_queries}}
languages = ["en","de"]

OUTPUT JSON:
{
  "s2_bulk_queries": [
    {
      "intent": "authority" | "match",
      "language": "en" | "de",
      "query_string": "QUERY STRING",
      "notes": "<= 18 words"
    }
  ]
}

GOAL HIERARCHY:
- authority: tight core authority first, optional broader boosters second
- match: strongest chapter fit with good recall
- do not spend budget on generic method queries that are weakly tied to the chapter object

PLANNER-CONTROLLED INPUT FIELDS:
- Each facet includes:
  - query_family_preference
  - language_strategy
  - authority_role
- authority_blueprints is the canonical upstream authority split.
- authority_blueprints_expanded repeats each blueprint with its target facet controls for easier use.
- Generate authority queries from authority_blueprints first. Do not collapse them into one flat authority notion.

PROVIDER REALITY:
- Semantic Scholar bulk keyword search matches titles and abstracts, so use phrases likely to appear in titles/abstracts.
- Prefer full lexical forms over acronym-only shorthand.
- Do not mirror every English query into German mechanically.

LANGUAGE STRATEGY:
- obey the planner's language_strategy for each facet or authority blueprint
- en_core_only -> emit EN only
- en_plus_bilingual_fallback -> emit EN and use bilingual rescue only when it improves recall
- en_plus_selective_de -> emit EN plus selective DE only when the phrasing is plausible
- en_de_parallel -> emit both EN and DE
- English should carry the recall backbone.
- Use German selectively, only where the object phrase and facet phrase are both likely to appear in German titles/abstracts.
- If the German rendering is literal, brittle, or niche, use a bilingual or English fallback instead of forcing DE parity.

LEXICALITY POLICY:
- prefer direct object phrases and standard literature wording
- prefer full forms before acronyms or shorthand
- avoid implementation-jargon translations that are unlikely to appear in titles/abstracts

ALLOWED OPERATORS (ONLY THESE):
- Required: +term or +("a" | "b")
- Exclude: -term or -"phrase"
- OR: ("a" | "b" | "c")  # ALL | MUST be inside parentheses
- Quotes: "two words"
- Wildcard: suffix only, e.g. gene*  (GUARDRAIL: stem length >=4)
- Fuzzy/edit distance: term~1 or term~2 (GUARDRAIL: N<=2 unless term length>=8; then N<=3)
- Phrase proximity: "two word phrase" ~2..4 (GUARDRAIL: N<=4)

ABSOLUTE SEPARATION RULE (CRITICAL; DO NOT VIOLATE):
A) PRIMARY_CONTEXT terms and FACET terms MUST NEVER be mixed in the same OR-group.
B) PRIMARY_CONTEXT_OR_GROUP MUST be built ONLY from primary_context_anchors for that language.
C) FACET_OR_GROUP MUST be built ONLY from facet canonical_terms + neighbor_terms (plus safe bilingual variants).
D) If a term is not explicitly in primary_context_anchors, it is NOT allowed in PRIMARY_CONTEXT_OR_GROUP.

MANDATORY STRUCTURE:

MATCH queries MUST have:
  +(PRIMARY_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional NEGATIVE]

DEFAULT STRONG MATCH FORM:
  +(PRIMARY_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional NEGATIVE]

OPTIONAL DRIFT-REDUCING FORM:
  +(PRIMARY_CONTEXT_OR_GROUP) +(SECOND_CONTEXT_OR_GROUP) +(FACET_OR_GROUP) [optional NEGATIVE]

PRIMARY_CONTEXT_OR_GROUP:
- 2-5 terms
- use terms that name the chapter object/corpus/domain, not only methods
- when available, include at least 2 distinct object/context anchors
- prefer direct object phrases such as `online reviews`, `user reviews`, `customer reviews`, `review platforms`
- avoid abstract substitutes such as `user generated content` unless paired with a direct object phrase

SECOND_CONTEXT_OR_GROUP:
- optional but recommended only when it clearly reduces drift
- may use anchors or global canonical terms that are still true context anchors
- do NOT place generic facet/method terms here

FACET_OR_GROUP:
- 5-10 terms
- only target-facet canonical_terms + neighbor_terms
- bilingual variants are allowed inside this group when they improve recall
- front-load standard literature wording before niche or implementation-like wording
- avoid filling the whole group with rare translated compounds that are unlikely to appear in titles/abstracts

QUERY-FAMILY SHAPE CONTROL:
- object_core -> PRIMARY_CONTEXT + object-defining construct/context facet group
- object_plus_construct -> PRIMARY_CONTEXT + construct facet group
- object_plus_data_proxy -> PRIMARY_CONTEXT + data/proxy facet group
- object_plus_method -> PRIMARY_CONTEXT + specific method facet group; add SECOND_CONTEXT only when it clearly reduces drift
- object_plus_limitation -> PRIMARY_CONTEXT + limitation/validity facet group
- object_plus_context -> PRIMARY_CONTEXT + context/domain/platform facet group
- The query's dominant structure must match the facet's query_family_preference.

AUTHORITY SPLIT:
- Emit all core authority blueprints first.
- Core authority queries should usually use 2 required groups: +(PRIMARY_CONTEXT_OR_GROUP) +(field-defining authority facet group)
- Booster authority queries may broaden OR-groups, but must remain object-led and interpretable.
- Do not create authority queries for facets with authority_role="none".

ANTI-DRIFT RULES:
- Pure method-only queries are NOT allowed.
- If a query could retrieve broad NLP/LLM/economics/method papers with no chapter object, strengthen it.
- Ambiguous standalone tokens must be rewritten as more specific phrases or paired with disambiguating terms.

NEGATIVE RULES:
- default to 0 or 1 negatives
- use at most 2 negatives unless there is a very clear wrong-sense problem
- negatives must be atomic and provider-safe
- if a negative is messy, omit it

EMPTY-QUERY TARGET:
- some narrow zero-yield probes are acceptable
- most core authority, global-match, and weight>=4 facet families should keep a plausible title/abstract hit path
- avoid combining literal DE phrasing, 3 required groups, and multiple negatives unless the payoff is clear

AUTHORITY POLICY:
Authority queries are broader but MUST remain chapter-anchored:
  +(PRIMARY_CONTEXT_OR_GROUP) +(HIGH_LEVEL_OR_GROUP) [optional NEGATIVE]

HIGH_LEVEL_OR_GROUP:
- use topic-specific construct/data/proxy terms
- avoid generic standalone method or field terms
- keep authority queries interpretable and obviously on-topic
- avoid acronym-only terms unless the full phrase is also present

ALWAYS INCLUDE:
- authority EN
- authority bilingual fallback
- at least 1 DE query that uses clearly standard German academic phrasing when such phrasing exists
- global match EN
- match EN for each weight>=4 facet while budget permits
- spend remaining budget first on object+data/proxy and object+limitations families before DE clones or extra method families

SELF-CHECK (MUST DO, FIX SILENTLY):
- PRIMARY_CONTEXT_OR_GROUP contains only true anchors
- FACET_OR_GROUP contains only facet terms
- every '|' is inside parentheses
- MATCH has at least two required groups and at most three
- negatives are atomic and <=2
- wildcard only suffix and stem>=4
- ~ only within allowed N
- if the German version is a literal translation that is unlikely to appear in titles/abstracts, replace it with a bilingual or English fallback
- if the query depends on acronym-only shorthand, rewrite it with full terms
- if advanced syntax is unnecessary, simplify it
- Did this authority query come from a core or booster blueprint? If not, fix it.
- Does the query shape match the facet's query_family_preference? If not, fix it.

Return ONLY JSON: { "s2_bulk_queries": [ ... ] }
"""


OPENALEX_ALLOWED_FILTER_KEYS = {
    "language",
    "is_paratext",
    "is_retracted",
    "type",
    "from_publication_date",
    "to_publication_date",
    "primary_location.source.is_core",
    "locations.source.is_core",
}


def _sanitize_plan_for_query_builders(plan: QueryPlan) -> Dict[str, Any]:
    obj = plan.model_dump(mode="json")
    try:
        ge = obj.get("global_exclusions") or {}
        for lang in ("en", "de"):
            terms = list(ge.get(lang) or [])
            ge[lang] = [t for t in terms if _is_atomic_exclusion(t)]
        obj["global_exclusions"] = ge

        facets = obj.get("facets") or []
        for f in facets:
            ex = f.get("exclusion_terms") or {}
            for lang in ("en", "de"):
                terms = list(ex.get(lang) or [])
                ex[lang] = [t for t in terms if _is_atomic_exclusion(t)]
            f["exclusion_terms"] = ex

        facet_lookup = {
            str(f.get("facet_id") or ""): f
            for f in facets
            if isinstance(f, dict) and str(f.get("facet_id") or "").strip()
        }
        obj["phase_c_guidance"] = {
            "facet_query_controls": [
                {
                    "facet_id": str(f.get("facet_id") or ""),
                    "facet_label_en": str(f.get("facet_label_en") or ""),
                    "importance_weight": int(f.get("importance_weight") or 0),
                    "facet_group": str(f.get("facet_group") or ""),
                    "query_family_preference": str(f.get("query_family_preference") or ""),
                    "language_strategy": str(f.get("language_strategy") or ""),
                    "authority_role": str(f.get("authority_role") or ""),
                }
                for f in facets
            ],
            "authority_blueprints_expanded": [
                {
                    "authority_kind": str(bp.get("authority_kind") or ""),
                    "label_en": str(bp.get("label_en") or ""),
                    "label_de": str(bp.get("label_de") or ""),
                    "language_strategy": str(bp.get("language_strategy") or ""),
                    "search_breadth": str(bp.get("search_breadth") or ""),
                    "notes_en": str(bp.get("notes_en") or ""),
                    "target_facets": [
                        {
                            "facet_id": facet_id,
                            "facet_label_en": str((facet_lookup.get(facet_id) or {}).get("facet_label_en") or ""),
                            "facet_group": str((facet_lookup.get(facet_id) or {}).get("facet_group") or ""),
                            "query_family_preference": str((facet_lookup.get(facet_id) or {}).get("query_family_preference") or ""),
                            "language_strategy": str((facet_lookup.get(facet_id) or {}).get("language_strategy") or ""),
                            "authority_role": str((facet_lookup.get(facet_id) or {}).get("authority_role") or ""),
                        }
                        for facet_id in [
                            str(fid or "").strip()
                            for fid in (bp.get("target_facet_ids") or [])
                            if str(fid or "").strip()
                        ]
                    ],
                }
                for bp in (obj.get("authority_blueprints") or [])
                if isinstance(bp, dict)
            ],
        }
    except Exception:
        return obj
    return obj


def _limit_words(text: str, max_words: int) -> str:
    s = str(text or "").strip()
    if not s:
        return ""
    words = re.split(r"\s+", s)
    if len(words) <= int(max_words):
        return s
    return " ".join(words[: int(max_words)]).strip()


def _truncate_chars(text: str, max_chars: int) -> str:
    s = str(text or "").strip()
    if len(s) <= int(max_chars):
        return s
    head = s[: int(max_chars)].rstrip()
    return head + "\n...[TRUNCATED]..."

_BAD_EXCL_PAT = re.compile(r"(e\.g\.|z\.\s*b\.|,|\(|\)|;|:)", re.IGNORECASE)


def _is_atomic_exclusion(term: str) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _BAD_EXCL_PAT.search(t):
        return False
    if len(t) > 40:
        return False
    if len(t.split()) > 3:
        return False
    # No punctuation except hyphen (Unicode word chars are allowed; '_' is treated as punctuation here).
    if "_" in t:
        return False
    if re.search(r"[^\w\s-]", t, flags=re.UNICODE):
        return False
    return True


def _lint_openalex_not_clauses_atomic(qs: str) -> None:
    s = str(qs or "")
    if "NOT" not in s:
        return

    # Identify NOT clauses outside quotes and validate all term candidates inside them.
    in_quote = False
    i = 0
    clauses: List[str] = []

    def _is_word_boundary(pos: int) -> bool:
        if pos < 0 or pos >= len(s):
            return True
        return not (s[pos].isalnum() or s[pos] == "_")

    while i < len(s):
        ch = s[i]
        if ch == '"':
            in_quote = not in_quote
            i += 1
            continue
        if not in_quote and s.startswith("NOT", i) and _is_word_boundary(i - 1) and _is_word_boundary(i + 3):
            j = i + 3
            while j < len(s) and s[j].isspace():
                j += 1
            if j >= len(s):
                break
            if s[j] == "(":
                depth = 1
                k = j + 1
                in_q2 = False
                while k < len(s) and depth > 0:
                    if s[k] == '"':
                        in_q2 = not in_q2
                        k += 1
                        continue
                    if not in_q2:
                        if s[k] == "(":
                            depth += 1
                        elif s[k] == ")":
                            depth -= 1
                    k += 1
                clauses.append(s[j:k])
                i = k
                continue
            if s[j] == '"':
                k = j + 1
                while k < len(s) and s[k] != '"':
                    k += 1
                clauses.append(s[j : min(k + 1, len(s))])
                i = min(k + 1, len(s))
                continue
            k = j
            while k < len(s) and not s[k].isspace():
                k += 1
            clauses.append(s[j:k])
            i = k
            continue
        i += 1

    if not clauses:
        return

    bad: List[str] = []
    for clause in clauses:
        # Quoted phrases
        for m in re.finditer(r'"([^"]+)"', clause):
            term = m.group(1).strip()
            if not _is_atomic_exclusion(term):
                bad.append(term)
        # Bare tokens (ignore boolean ops)
        for tok in re.findall(r"[\w-]+", clause, flags=re.UNICODE):
            if tok.upper() in {"AND", "OR", "NOT"}:
                continue
            if not _is_atomic_exclusion(tok):
                bad.append(tok)

    if bad:
        raise ValueError(f"OpenAlex: non-atomic exclusions in NOT clause: {bad[:6]}")


def _lint_s2_negative_terms_atomic(qs: str) -> None:
    s = str(qs or "")
    bad: List[str] = []
    for m in re.finditer(r'(?:^|[\s(])-\s*(\"[^\"]+\"|[^\s()|]+)', s):
        raw = m.group(1).strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            raw = raw[1:-1].strip()
        if not _is_atomic_exclusion(raw):
            bad.append(raw)
    if bad:
        raise ValueError(f"S2: non-atomic negative terms: {bad[:6]}")


def _validate_s2_advanced_ops(qs: str) -> None:
    s = str(qs or "")

    # wildcard: allow only suffix token like abc*
    for m in re.finditer(r"(\S+)\*", s):
        stem = m.group(1)
        stem = stem.strip().strip('"()')
        stem = re.sub(r"^[+\-]+", "", stem)
        if len(stem) < 4:
            raise ValueError(f"S2: wildcard stem too short: {m.group(0)!r}")
        # suffix only: reject if immediately followed by a word char (e.g. gene*foo)
        if m.end() < len(s) and re.match(r"\w", s[m.end() : m.end() + 1]):
            raise ValueError(f"S2: wildcard must be suffix: {m.group(0)!r}")

    # fuzzy: term~N
    for m in re.finditer(r"(\w+)~(\d+)", s):
        term, n = m.group(1), int(m.group(2))
        if n > 3:
            raise ValueError(f"S2: fuzzy too large: {m.group(0)!r}")
        if n == 3 and len(term) < 8:
            raise ValueError(f"S2: ~3 only for long terms: {m.group(0)!r}")

    # phrase proximity: "a b" ~N
    for m in re.finditer(r'"[^"]+"\s*~\s*(\d+)', s):
        n = int(m.group(1))
        if n > 4:
            raise ValueError(f"S2: proximity too large: {m.group(0)!r}")


_UNICODE_INVISIBLE_CHARS = [
    "\u200b",  # zero width space
    "\u200c",  # zero width non-joiner
    "\u200d",  # zero width joiner
    "\u2060",  # word joiner
    "\ufeff",  # zero width no-break space / BOM
]

_UNICODE_HYPHEN_CHARS = [
    "\u2010",  # hyphen
    "\u2011",  # non-breaking hyphen
    "\u2012",  # figure dash
    "\u2013",  # en dash
    "\u2014",  # em dash
    "\u2212",  # minus sign
    "\ufe58",  # small em dash
    "\ufe63",  # small hyphen-minus
    "\uff0d",  # fullwidth hyphen-minus
]


def _normalize_unicode_query_text(text: str) -> str:
    s = str(text or "")
    s = unicodedata.normalize("NFKC", s)
    s = s.replace("\u00a0", " ")  # NBSP -> space
    s = s.replace("\u00ad", "")  # soft hyphen -> remove
    for ch in _UNICODE_INVISIBLE_CHARS:
        s = s.replace(ch, "")
    for ch in _UNICODE_HYPHEN_CHARS:
        s = s.replace(ch, "-")
    return s


def _quote_term(term: str) -> str:
    t = str(term or "").strip()
    if t.startswith('"') and t.endswith('"') and len(t) >= 2:
        t = t[1:-1].strip()
    t = t.replace('"', "")
    return f"\"{t}\""


def _expand_slash_tokens(text: str, *, or_operator: str) -> str:
    s = str(text or "")
    if "/" not in s:
        return s

    def _make_or_group(value: str) -> Optional[str]:
        if "://" in value:
            return None
        if re.search(r"\b10\.\d{4,9}/\S+\b", value):
            return None

        parts = [p.strip() for p in str(value or "").split("/") if p.strip()]
        if len(parts) < 2:
            return None
        if all(p.lower() in {"and", "or", "not"} for p in parts):
            return None

        return "(" + f" {or_operator} ".join(_quote_term(p) for p in parts) + ")"

    # Rewrite inside quotes first:  "roads/bridges" -> ("roads" OR "bridges")
    def _repl_quoted(m: re.Match[str]) -> str:
        inner = m.group(1)
        group = _make_or_group(inner)
        return group if group is not None else m.group(0)

    s = re.sub(r"\"([^\"]*?/[^\"\n]*)\"", _repl_quoted, s)

    # Then rewrite bare tokens outside quotes.
    token_re = re.compile(r"(?P<tok>[\w][\w\.-]*/[\w][\w\.-]*(?:/[\w][\w\.-]*)*)", flags=re.UNICODE)

    def _rewrite_segment(seg: str) -> str:
        def _repl_tok(m: re.Match[str]) -> str:
            tok = m.group("tok")
            group = _make_or_group(tok)
            return group if group is not None else tok

        return token_re.sub(_repl_tok, seg)

    out: List[str] = []
    buf: List[str] = []
    in_quote = False

    for ch in s:
        if ch == '"':
            seg = "".join(buf)
            out.append(seg if in_quote else _rewrite_segment(seg))
            buf.clear()
            out.append('"')
            in_quote = not in_quote
            continue
        buf.append(ch)

    seg = "".join(buf)
    out.append(seg if in_quote else _rewrite_segment(seg))
    return "".join(out)


def _uppercase_boolean_ops_outside_quotes(text: str) -> str:
    s = str(text or "")
    out: List[str] = []
    buf: List[str] = []
    in_quote = False

    def flush_buf():
        seg = "".join(buf)
        if not in_quote:
            seg = re.sub(r"\b(and|or|not)\b", lambda m: m.group(1).upper(), seg, flags=re.IGNORECASE)
        out.append(seg)
        buf.clear()

    for ch in s:
        if ch == '"':
            flush_buf()
            out.append('"')
            in_quote = not in_quote
            continue
        buf.append(ch)

    flush_buf()
    return "".join(out)


def _parse_filters(filters: str) -> List[str]:
    parts = [p.strip() for p in str(filters or "").split(",")]
    return [p for p in parts if p]


def _canonicalize_openalex_filters(filters: str, *, language: str) -> str:
    parts = _parse_filters(filters)
    seen = set()
    cleaned: List[str] = []

    for p in parts:
        if ":" not in p:
            raise ValueError(f"OpenAlex filter missing ':': {p!r}")
        key = p.split(":", 1)[0].strip()
        if key not in OPENALEX_ALLOWED_FILTER_KEYS:
            raise ValueError(f"OpenAlex filter key not allowed: {key!r} (filter={p!r})")
        if key == "language":
            p = f"language:{language}"
        if p not in seen:
            cleaned.append(p)
            seen.add(p)

    required = ["is_paratext:false", "is_retracted:false", f"language:{language}"]
    tail = [p for p in cleaned if p not in required and not p.startswith("language:")]
    return ",".join(required + tail)


def _normalize_openalex_query(q: OpenAlexQuery) -> OpenAlexQuery:
    qs = _normalize_unicode_query_text(str(q.query_string or "")).strip()
    if any(ch in qs for ch in ("*", "?", "~")):
        raise ValueError(f"OpenAlex forbidden character in query_string: {qs!r}")
    qs = _expand_slash_tokens(qs, or_operator="OR")
    qs = _uppercase_boolean_ops_outside_quotes(qs)
    qs = re.sub(r"\s+", " ", qs).strip()
    _lint_openalex_not_clauses_atomic(qs)

    filters = _canonicalize_openalex_filters(q.filters, language=q.language)

    search_field = getattr(q, "search_field", None) or "title_and_abstract.search"
    if q.intent == "match":
        search_field = "title_and_abstract.search"
    elif search_field not in ("default.search", "title_and_abstract.search"):
        search_field = "title_and_abstract.search"

    sort = q.sort
    if q.intent == "authority":
        sort = "cited_by_count:desc"
    elif q.intent == "match":
        if sort not in (None, "relevance_score:desc"):
            sort = "relevance_score:desc"

    notes = _limit_words(q.notes, 18)

    return q.model_copy(
        update={
            "search_field": search_field,
            "query_string": qs,
            "filters": filters,
            "sort": sort,
            "per_page": 200,
            "notes": notes,
        }
    )


def _normalize_s2_query(q: S2BulkQuery) -> S2BulkQuery:
    qs = _normalize_unicode_query_text(str(q.query_string or ""))
    qs = _expand_slash_tokens(qs.strip(), or_operator="|")
    qs = re.sub(r"\s+", " ", qs)
    if "?" in qs:
        raise ValueError(f"S2 forbidden character in query_string: {qs!r}")
    _validate_s2_advanced_ops(qs)
    _lint_s2_negative_terms_atomic(qs)
    if not re.search(r"\+\s*(?:\(|\")", qs):
        raise ValueError(f"S2 query_string must contain at least one +anchor: {qs!r}")

    plus_count = len(re.findall(r"(?:^|\s)\+", qs))
    if q.intent == "match" and plus_count < 2:
        raise ValueError(f"S2 match query_string must contain >=2 required components (+): {qs!r}")

    depth = 0
    in_quote = False
    for ch in qs:
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == "|" and depth <= 0:
            raise ValueError(f"S2 operator sanity: '|' must be inside parentheses: {qs!r}")

    notes = _limit_words(q.notes, 18)
    return q.model_copy(update={"query_string": qs.strip(), "notes": notes})


def _validate_language_coverage(queries: List[Any], *, provider: str) -> None:
    langs = sorted({getattr(q, "language", None) for q in queries})
    if "en" not in langs or "de" not in langs:
        raise ValueError(f"{provider}: expected both languages en+de, got {langs}")


def _validate_intent_coverage(queries: List[Any], *, provider: str) -> None:
    intents = sorted({getattr(q, "intent", None) for q in queries})
    if "authority" not in intents or "match" not in intents:
        raise ValueError(f"{provider}: expected both intents authority+match, got {intents}")


def _find_anchor_terms_in_text(text: str, terms: List[str]) -> List[str]:
    s = str(text or "").casefold()
    hits: List[str] = []
    for t in terms or []:
        tt = str(t or "").strip()
        if not tt:
            continue
        if tt.casefold() in s:
            hits.append(tt)
    return hits


def _validate_openalex_anchor_presence(queries: List[OpenAlexQuery], *, plan: QueryPlan) -> None:
    for q in queries:
        anchors = getattr(plan.primary_context_anchors, q.language, []) or []
        if not anchors:
            continue
        hits = _find_anchor_terms_in_text(q.query_string, list(anchors))
        if not hits:
            raise ValueError(
                f"OpenAlex: query missing required anchor (lang={q.language}, intent={q.intent}): {q.query_string!r}"
            )


def _validate_s2_anchor_presence(queries: List[S2BulkQuery], *, plan: QueryPlan) -> None:
    for q in queries:
        anchors = getattr(plan.primary_context_anchors, q.language, []) or []
        if not anchors:
            continue
        hits = _find_anchor_terms_in_text(q.query_string, list(anchors))
        if not hits:
            raise ValueError(
                f"S2: query missing required primary anchor (lang={q.language}, intent={q.intent}): {q.query_string!r}"
            )


def _openalex_quote_term(term: str) -> str:
    # NOTE: OpenAlex boolean syntax supports quotes; we avoid escaping rules by replacing embedded quotes.
    t = str(term or "").strip().replace('"', "'")
    return f"\"{t}\""


def _build_openalex_anchor_clause(terms: List[str]) -> str:
    clean = [str(t or "").strip() for t in (terms or []) if str(t or "").strip()]
    clean = [t.replace('"', "'") for t in clean]
    if not clean:
        return ""
    inner = " OR ".join(_openalex_quote_term(t) for t in clean)
    return f"({inner})"


def _maybe_inject_missing_openalex_anchor(q: OpenAlexQuery, *, plan: QueryPlan) -> Tuple[OpenAlexQuery, bool]:
    anchors = getattr(plan.primary_context_anchors, q.language, []) or []
    anchors = [str(a or "").strip() for a in anchors if str(a or "").strip()]
    if not anchors:
        return q, False

    hits = _find_anchor_terms_in_text(q.query_string, anchors)
    if hits:
        return q, False

    inject_terms: List[str] = []
    if q.intent == "match":
        # Match queries are meant to be context-anchored but not ultra-narrow; injecting the two strongest
        # primary anchors is a safe default.
        if len(anchors) >= 2:
            inject_terms = [anchors[0], anchors[1]]
        else:
            inject_terms = [anchors[0]]
    else:
        inject_terms = [anchors[0]]

    clause = _build_openalex_anchor_clause(inject_terms)
    if not clause:
        return q, False

    base = str(q.query_string or "").strip()
    new_qs = f"{clause} AND ({base})" if base else clause
    return q.model_copy(update={"query_string": new_qs}), True


def _maybe_inject_missing_s2_anchor(q: S2BulkQuery, *, plan: QueryPlan) -> Tuple[S2BulkQuery, bool]:
    anchors = getattr(plan.primary_context_anchors, q.language, []) or []
    anchors = [str(a or "").strip() for a in anchors if str(a or "").strip()]
    if not anchors:
        return q, False

    s = str(q.query_string or "").strip()
    hits = _find_anchor_terms_in_text(s, anchors)

    plus_count = len(re.findall(r"(?:^|\s)\+", s))
    has_plus_anchor = bool(re.search(r"\+\s*(?:\(|\")", s))
    required_plus_total = 2 if q.intent == "match" else 1

    needs_primary_anchor = not hits
    needs_plus_components = (plus_count < required_plus_total) or (not has_plus_anchor)
    if not (needs_primary_anchor or needs_plus_components):
        return q, False

    # S2 advanced queries require +("...") required components; for match we also need >= 2.
    # We inject at the front and keep the existing query in parentheses to preserve semantics.
    needed = max(0, required_plus_total - plus_count)
    if not has_plus_anchor:
        needed = max(needed, 1)
    if needs_primary_anchor and q.intent == "match":
        needed = max(needed, 2 if len(anchors) >= 2 else 1)

    preferred_terms: List[str] = []
    if hits:
        preferred_terms.extend(hits[:2])
    else:
        preferred_terms.append(anchors[0])
        if len(anchors) >= 2:
            preferred_terms.append(anchors[1])

    inject_terms: List[str] = []
    for t in preferred_terms + anchors:
        if len(inject_terms) >= needed:
            break
        tt = str(t or "").strip()
        if not tt:
            continue
        if tt.casefold() in s.casefold():
            # If term already exists but plus_count is low, we can still add it as a required component.
            pass
        if tt not in inject_terms:
            inject_terms.append(tt)

    parts: List[str] = []
    for t in inject_terms:
        tt = t.replace('"', "'").replace(",", " ").replace(";", " ").strip()
        if not tt:
            continue
        parts.append(f'+("{tt}")')

    if not parts:
        return q, False

    prefix = " ".join(parts)
    new_qs = f"{prefix} AND ({s})" if s else prefix
    return q.model_copy(update={"query_string": new_qs}), True


def _validate_openalex_match_anchor_fingerprint_diversity(
    queries: List[OpenAlexQuery],
    *,
    plan: QueryPlan,
    max_share: float = 0.60,
) -> None:
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [t for t in anchors if str(t or "").strip()]
        if not anchors:
            continue

        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        if len(match_qs) < 4:
            continue

        # Some plans include 1–2 very generic, chapter-wide anchors that will naturally show up in nearly every
        # query (e.g. time period + geography). We exclude those "always-on" anchors from the diversity heuristic
        # to avoid false positives that would otherwise abort the run.
        presence_counts: Dict[str, int] = {str(a): 0 for a in anchors}
        for q in match_qs:
            qs = str(q.query_string or "")
            for a in anchors:
                if str(a).casefold() in qs.casefold():
                    presence_counts[str(a)] += 1

        n_total = max(len(match_qs), 1)
        variable_anchors = [a for a in anchors if (presence_counts.get(str(a), 0) / n_total) < 0.90]
        if len(variable_anchors) < 2:
            continue

        counts: Dict[Tuple[str, str], int] = {}
        eligible = 0
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, variable_anchors)
            top2 = [h.lower() for h in hits[:2]]
            if len(top2) < 2:
                continue
            fp = (top2[0], top2[1])
            counts[fp] = counts.get(fp, 0) + 1
            eligible += 1

        if eligible < 4:
            continue

        most_fp, most_n = max(counts.items(), key=lambda kv: kv[1])
        share = most_n / max(eligible, 1)
        if share > float(max_share):
            raise ValueError(
                f"OpenAlex: anchor fingerprint concentration too high (lang={lang}, share={share:.2f}, fp={most_fp}): regenerate"
            )


def _count_s2_required_components(qs: str) -> int:
    return len(re.findall(r"(?:^|\s)\+(?=(?:\(|\"|[\w]))", str(qs or ""), flags=re.UNICODE))


def _count_s2_negative_components(qs: str) -> int:
    return len(re.findall(r"(?:^|[\s(])-\s*(?:(?:\"[^\"]+\")|[^\s()|]+)", str(qs or ""), flags=re.UNICODE))


def _has_s2_advanced_syntax(qs: str) -> bool:
    s = str(qs or "")
    if "*" in s or "?" in s:
        return True
    if re.search(r"\w+~\d+", s):
        return True
    if re.search(r'"[^"]+"\s*~\s*\d+', s):
        return True
    return False


def _plan_language_terms(plan: QueryPlan, attr_name: str, language: str) -> List[str]:
    obj = getattr(plan, attr_name, None)
    if obj is None:
        return []
    terms = getattr(obj, language, None) or []
    return [str(t).strip() for t in terms if str(t or "").strip()]


def _is_atomic_exclusion(term: str) -> bool:
    t = str(term or "").strip()
    if not t:
        return False
    if _BAD_EXCL_PAT.search(t):
        return False
    if len(t) > 40:
        return False
    if _word_count(t) > 3:
        return False
    if re.search(r"[^\w\s-]", t, flags=re.UNICODE):
        return False
    return True


def _normalize_openalex_query(q: OpenAlexQuery) -> OpenAlexQuery:
    raw_search_field = getattr(q, "search_field", None) or ("search" if q.intent == "authority" else "title_and_abstract.search")
    if raw_search_field == "default.search":
        raw_search_field = "search"
    search_field = raw_search_field

    qs = _normalize_unicode_query_text(str(q.query_string or "")).strip()
    qs = _expand_slash_tokens(qs, or_operator="OR")
    qs = _uppercase_boolean_ops_outside_quotes(qs)
    qs = re.sub(r"\s+", " ", qs).strip()
    if "?" in qs:
        raise ValueError(f"OpenAlex unsupported character in query_string: {qs!r}")
    if search_field != "search" and any(ch in qs for ch in ("*", "~")):
        raise ValueError(f"OpenAlex advanced syntax allowed only on search field: {qs!r}")
    _lint_openalex_not_clauses_atomic(qs)

    filters = _canonicalize_openalex_filters(q.filters, language=q.language)

    sort = q.sort
    if q.intent == "authority":
        sort = "cited_by_count:desc"
    elif q.intent == "match" and sort not in (None, "relevance_score:desc"):
        sort = "relevance_score:desc"

    notes = _limit_words(q.notes, 18)

    return q.model_copy(
        update={
            "search_field": search_field,
            "query_string": qs,
            "filters": filters,
            "sort": sort,
            "per_page": 200,
            "notes": notes,
        }
    )


def _normalize_s2_query(q: S2BulkQuery) -> S2BulkQuery:
    qs = _normalize_unicode_query_text(str(q.query_string or ""))
    qs = _expand_slash_tokens(qs.strip(), or_operator="|")
    qs = re.sub(r"\s+", " ", qs)
    if "?" in qs:
        raise ValueError(f"S2 forbidden character in query_string: {qs!r}")
    _validate_s2_advanced_ops(qs)
    _lint_s2_negative_terms_atomic(qs)
    if not re.search(r"\+\s*(?:\(|\")", qs):
        raise ValueError(f"S2 query_string must contain at least one +anchor: {qs!r}")

    plus_count = _count_s2_required_components(qs)
    neg_count = _count_s2_negative_components(qs)
    if neg_count > 2:
        raise ValueError(f"S2 negative budget exceeded (>2): {qs!r}")
    if plus_count > 3:
        raise ValueError(f"S2 query_string has too many required components (>3): {qs!r}")
    if q.intent == "match" and plus_count < 2:
        raise ValueError(f"S2 match query_string must contain >=2 required components (+): {qs!r}")

    depth = 0
    in_quote = False
    for ch in qs:
        if ch == '"':
            in_quote = not in_quote
            continue
        if in_quote:
            continue
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif ch == "|" and depth <= 0:
            raise ValueError(f"S2 operator sanity: '|' must be inside parentheses: {qs!r}")

    notes = _limit_words(q.notes, 18)
    return q.model_copy(update={"query_string": qs.strip(), "notes": notes})


def _find_anchor_terms_in_text(text: str, terms: List[str]) -> List[str]:
    hay = _normalize_unicode_query_text(str(text or "")).lower()
    matches: List[str] = []
    for t in terms:
        tt = _normalize_unicode_query_text(str(t or "")).strip()
        if not tt:
            continue
        if tt.lower() in hay:
            matches.append(tt)
    matches.sort(key=lambda x: len(x), reverse=True)

    seen = set()
    uniq: List[str] = []
    for match in matches:
        key = match.lower()
        if key in seen:
            continue
        uniq.append(match)
        seen.add(key)
    return uniq


def _validate_openalex_anchor_presence(queries: List[OpenAlexQuery], *, plan: QueryPlan) -> None:
    for q in queries:
        anchors = getattr(plan.primary_context_anchors, q.language, []) or []
        if not anchors:
            continue
        hits = _find_anchor_terms_in_text(q.query_string, list(anchors))
        if not hits:
            raise ValueError(f"OpenAlex: query missing required anchor (lang={q.language}, intent={q.intent}): {q.query_string!r}")


def _validate_s2_anchor_presence(queries: List[S2BulkQuery], *, plan: QueryPlan) -> None:
    for q in queries:
        anchors = getattr(plan.primary_context_anchors, q.language, []) or []
        if not anchors:
            continue
        hits = _find_anchor_terms_in_text(q.query_string, list(anchors))
        if not hits:
            raise ValueError(f"S2: query missing required primary anchor (lang={q.language}, intent={q.intent}): {q.query_string!r}")


def _validate_match_core_object_presence(queries: List[Any], *, plan: QueryPlan, provider: str) -> None:
    for q in queries:
        if getattr(q, "intent", None) != "match":
            continue
        core_terms = _plan_language_terms(plan, "core_object_terms", getattr(q, "language", ""))
        if not core_terms:
            continue
        hits = _find_anchor_terms_in_text(getattr(q, "query_string", ""), core_terms)
        if not hits:
            raise ValueError(
                f"{provider}: match query missing core object term (lang={getattr(q, 'language', '')}): {getattr(q, 'query_string', '')!r}"
            )


def _validate_openalex_match_anchor_fingerprint_diversity(
    queries: List[OpenAlexQuery],
    *,
    plan: QueryPlan,
    max_share: float = 0.60,
) -> None:
    for lang in ("en", "de"):
        anchors = getattr(plan.primary_context_anchors, lang, []) or []
        anchors = [t for t in anchors if str(t or "").strip()]
        if not anchors:
            continue

        match_qs = [q for q in queries if q.intent == "match" and q.language == lang]
        if len(match_qs) < 4:
            continue

        counts: Dict[Tuple[str, str], int] = {}
        eligible = 0
        for q in match_qs:
            hits = _find_anchor_terms_in_text(q.query_string, anchors)
            top2 = [h.lower() for h in hits[:2]]
            if len(top2) < 2:
                continue
            fp = (top2[0], top2[1])
            counts[fp] = counts.get(fp, 0) + 1
            eligible += 1

        if eligible < 4:
            continue

        most_fp, most_n = max(counts.items(), key=lambda kv: kv[1])
        share = most_n / max(eligible, 1)
        if share > float(max_share):
            raise ValueError(
                f"OpenAlex: anchor fingerprint concentration too high (lang={lang}, share={share:.2f}, fp={most_fp}): regenerate"
            )


def _validate_openalex_search_field_budget(
    queries: List[OpenAlexQuery],
    *,
    max_match_search_queries: int = 2,
    max_match_search_share: float = 0.20,
) -> None:
    match_queries = [q for q in queries if q.intent == "match"]
    if not match_queries:
        return
    match_search = [q for q in match_queries if q.search_field == "search"]
    share = float(len(match_search)) / float(max(1, len(match_queries)))
    if len(match_search) > int(max_match_search_queries) or share > float(max_match_search_share):
        raise ValueError(
            f"OpenAlex: too many broad match queries on search field (count={len(match_search)}/{len(match_queries)}, share={share:.2f}): regenerate"
        )


def _validate_s2_match_required_group_budget(
    queries: List[S2BulkQuery],
    *,
    max_three_group_share: float = 0.35,
) -> None:
    match_queries = [q for q in queries if q.intent == "match"]
    if len(match_queries) < 4:
        return
    three_group = [q for q in match_queries if _count_s2_required_components(q.query_string) == 3]
    share = float(len(three_group)) / float(max(1, len(match_queries)))
    if share > float(max_three_group_share):
        raise ValueError(
            f"S2: too many 3-group match queries (share={share:.2f}, count={len(three_group)}/{len(match_queries)}): regenerate"
        )


def _validate_s2_advanced_syntax_budget(
    queries: List[S2BulkQuery],
    *,
    max_queries_with_advanced: int = 2,
    max_share: float = 0.20,
) -> None:
    advanced = [q for q in queries if _has_s2_advanced_syntax(q.query_string)]
    if not advanced:
        return
    share = float(len(advanced)) / float(max(1, len(queries)))
    if len(advanced) > int(max_queries_with_advanced) or share > float(max_share):
        raise ValueError(
            f"S2: advanced syntax overused (count={len(advanced)}/{len(queries)}, share={share:.2f}): regenerate"
        )

async def build_openalex_queries_llm(
    plan: QueryPlan,
    *,
    chapter_title: str = "",
    chapter_spec_text: str = "",
    config: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    force_rebuild: bool = False,
) -> Tuple[List[OpenAlexQuery], Dict[str, Any]]:
    stage = "phase_c_openalex_query_builder"
    cache_path = run_ctx.artifacts.openalex_queries_json

    def _load_cache() -> Optional[List[OpenAlexQuery]]:
        if not cache_path.exists():
            return None
        try:
            cached_obj = read_json(cache_path)
            if _is_placeholder_cache(cached_obj):
                log_event(run_ctx, stage=stage, event="cache_placeholder_ignored", path=str(cache_path))
                return None

            items = cached_obj.get("openalex_queries")
            if not isinstance(items, list):
                raise ValueError("cache missing openalex_queries list")

            queries = [_normalize_openalex_query(OpenAlexQuery.model_validate(x)) for x in items]

            max_q = int(config.max_queries_per_provider or 0) or 50
            if len(queries) > max_q:
                queries = queries[:max_q]

            _validate_language_coverage(queries, provider="OpenAlex")
            _validate_intent_coverage(queries, provider="OpenAlex")
            _validate_openalex_anchor_presence(queries, plan=plan)
            _validate_match_core_object_presence(queries, plan=plan, provider="OpenAlex")
            _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)
            _validate_openalex_search_field_budget(queries)

            write_json(cache_path, {"openalex_queries": [q.model_dump(mode="json") for q in queries]})
            log_event(run_ctx, stage=stage, event="cache_hit", path=str(cache_path), query_count=len(queries))
            return queries
        except Exception as e:
            err = str(e)
            write_json(run_ctx.run_dir / "openalex_queries.cache_invalid.json", {"ts": utc_now_iso(), "path": str(cache_path), "error": err})
            log_event(run_ctx, stage=stage, event="cache_invalid", path=str(cache_path), error=err[:800])
            return None

    if not force_rebuild:
        cached = _load_cache()
        if cached is not None:
            meta = {
                "cache_hit": True,
                "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
                "cost_usd": 0.0,
                "query_count": len(cached),
            }
            return cached, meta

    query_plan_json = _json_for_prompt(_sanitize_plan_for_query_builders(plan))
    max_q = int(config.max_queries_per_provider or 0) or 50

    user_prompt = _render_template(
        OPENALEX_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter_spec_text, 12000),
        query_plan_json=query_plan_json,
        max_queries=str(max_q),
    )

    max_attempts = 3
    last_err: Optional[Exception] = None
    obj: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    queries: List[OpenAlexQuery] = []

    with stage_timer(run_ctx, stage):
        for attempt in range(1, max_attempts + 1):
            debug_prefix = f"openalex_queries_attempt{attempt}"
            attempt_prompt = user_prompt
            if last_err is not None:
                attempt_prompt = (
                    user_prompt
                    + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                    + f"- Error: {str(last_err)[:400]}\n"
                )
            try:
                obj, meta = await llm.json_schema_call(
                    stage=stage,
                    operation_type="quellen_finder_two_lane_openalex_query_builder",
                    model=config.openai_model_openalex_query_builder,
                    system_prompt=OPENALEX_QUERY_BUILDER_SYSTEM_PROMPT,
                    user_prompt=attempt_prompt,
                    schema_name="openalex_queries",
                    schema=OPENALEX_QUERY_BUILDER_JSON_SCHEMA,
                    reasoning_effort=config.openai_reasoning_effort,
                    max_output_tokens=50000,
                    timeout_s=config.openai_timeout_s,
                    operation_details={"attempt": int(attempt)},
                )
            except Exception as e:
                last_err = e
                log_event(run_ctx, stage=stage, event="openai_call_failed", attempt=attempt, error=str(e)[:800])
                if attempt >= max_attempts:
                    raise
                continue

            attempt_raw_path = run_ctx.run_dir / f"{debug_prefix}.raw_output.json"
            attempt_meta_path = run_ctx.run_dir / f"{debug_prefix}.openai_meta.json"
            write_json(attempt_raw_path, obj)
            write_json(attempt_meta_path, meta)

            try:
                items = obj.get("openalex_queries")
                if not isinstance(items, list):
                    raise ValueError("OpenAI output missing openalex_queries list")
                queries = [_normalize_openalex_query(OpenAlexQuery.model_validate(x)) for x in items]

                if len(queries) > max_q:
                    log_event(run_ctx, stage=stage, event="budget_trim", from_count=len(queries), to_count=max_q)
                    queries = queries[:max_q]

                _validate_language_coverage(queries, provider="OpenAlex")
                _validate_intent_coverage(queries, provider="OpenAlex")
                _validate_openalex_anchor_presence(queries, plan=plan)
                _validate_match_core_object_presence(queries, plan=plan, provider="OpenAlex")
                _validate_openalex_match_anchor_fingerprint_diversity(queries, plan=plan)
                _validate_openalex_search_field_budget(queries)

                write_json(run_ctx.run_dir / "openalex_queries.raw_output.json", obj)
                write_json(run_ctx.run_dir / "openalex_queries.openai_meta.json", meta)
                break
            except Exception as e:
                last_err = e
                log_event(run_ctx, stage=stage, event="lint_failed", attempt=attempt, error=str(e)[:800], raw_path=str(attempt_raw_path))
                if attempt >= max_attempts:
                    raise
                continue

    write_json(cache_path, {"openalex_queries": [q.model_dump(mode="json") for q in queries]})
    log_event(run_ctx, stage=stage, event="cache_write", path=str(cache_path), model_used=meta.get("model_used"), usage=meta.get("usage"), cost=meta.get("cost_usd"), query_count=len(queries))

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["openai"] = meta
    metrics["stages"][stage]["query_count"] = len(queries)
    save_metrics(run_ctx, metrics)

    meta = dict(meta)
    meta["cache_hit"] = False
    meta["query_count"] = len(queries)
    return queries, meta


async def build_s2_bulk_queries_llm(
    plan: QueryPlan,
    *,
    chapter_title: str = "",
    chapter_spec_text: str = "",
    config: PipelineConfig,
    run_ctx: RunContext,
    llm: TwoLaneOpenAI,
    force_rebuild: bool = False,
) -> Tuple[List[S2BulkQuery], Dict[str, Any]]:
    stage = "phase_c_s2_query_builder"
    cache_path = run_ctx.artifacts.semanticscholar_queries_json

    def _load_cache() -> Optional[List[S2BulkQuery]]:
        if not cache_path.exists():
            return None
        try:
            cached_obj = read_json(cache_path)
            if _is_placeholder_cache(cached_obj):
                log_event(run_ctx, stage=stage, event="cache_placeholder_ignored", path=str(cache_path))
                return None

            items = cached_obj.get("s2_bulk_queries")
            if not isinstance(items, list):
                raise ValueError("cache missing s2_bulk_queries list")

            queries = [_normalize_s2_query(S2BulkQuery.model_validate(x)) for x in items]

            max_q = int(config.max_queries_per_provider or 0) or 50
            if len(queries) > max_q:
                queries = queries[:max_q]

            _validate_language_coverage(queries, provider="S2")
            _validate_intent_coverage(queries, provider="S2")
            _validate_s2_anchor_presence(queries, plan=plan)
            _validate_match_core_object_presence(queries, plan=plan, provider="S2")
            _validate_s2_match_required_group_budget(queries)
            _validate_s2_advanced_syntax_budget(queries)

            write_json(cache_path, {"s2_bulk_queries": [q.model_dump(mode="json") for q in queries]})
            log_event(run_ctx, stage=stage, event="cache_hit", path=str(cache_path), query_count=len(queries))
            return queries
        except Exception as e:
            err = str(e)
            write_json(run_ctx.run_dir / "s2_bulk_queries.cache_invalid.json", {"ts": utc_now_iso(), "path": str(cache_path), "error": err})
            log_event(run_ctx, stage=stage, event="cache_invalid", path=str(cache_path), error=err[:800])
            return None

    if not force_rebuild:
        cached = _load_cache()
        if cached is not None:
            meta = {
                "cache_hit": True,
                "usage": {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "reasoning_tokens": 0},
                "cost_usd": 0.0,
                "query_count": len(cached),
            }
            return cached, meta

    query_plan_json = _json_for_prompt(_sanitize_plan_for_query_builders(plan))
    max_q = int(config.max_queries_per_provider or 0) or 50

    user_prompt = _render_template(
        S2_BULK_QUERY_BUILDER_USER_PROMPT_TEMPLATE,
        chapter_title=str(chapter_title or "").strip(),
        chapter_spec_text=_truncate_chars(chapter_spec_text, 12000),
        query_plan_json=query_plan_json,
        max_queries=str(max_q),
    )

    max_attempts = 3
    last_err: Optional[Exception] = None
    obj: Dict[str, Any] = {}
    meta: Dict[str, Any] = {}
    queries: List[S2BulkQuery] = []

    with stage_timer(run_ctx, stage):
        for attempt in range(1, max_attempts + 1):
            debug_prefix = f"s2_bulk_queries_attempt{attempt}"
            attempt_prompt = user_prompt
            if last_err is not None:
                attempt_prompt = (
                    user_prompt
                    + "\n\nLINT_FEEDBACK:\n- Previous attempt failed deterministic validation. Fix and regenerate.\n"
                    + f"- Error: {str(last_err)[:400]}\n"
                )
            try:
                obj, meta = await llm.json_schema_call(
                    stage=stage,
                    operation_type="quellen_finder_two_lane_s2_query_builder",
                    model=config.openai_model_s2_query_builder,
                    system_prompt=S2_BULK_QUERY_BUILDER_SYSTEM_PROMPT,
                    user_prompt=attempt_prompt,
                    schema_name="s2_bulk_queries",
                    schema=S2_BULK_QUERY_BUILDER_JSON_SCHEMA,
                    reasoning_effort=config.openai_reasoning_effort,
                    max_output_tokens=50000,
                    timeout_s=config.openai_timeout_s,
                    operation_details={"attempt": int(attempt)},
                )
            except Exception as e:
                last_err = e
                log_event(run_ctx, stage=stage, event="openai_call_failed", attempt=attempt, error=str(e)[:800])
                if attempt >= max_attempts:
                    raise
                continue

            attempt_raw_path = run_ctx.run_dir / f"{debug_prefix}.raw_output.json"
            attempt_meta_path = run_ctx.run_dir / f"{debug_prefix}.openai_meta.json"
            write_json(attempt_raw_path, obj)
            write_json(attempt_meta_path, meta)

            try:
                items = obj.get("s2_bulk_queries")
                if not isinstance(items, list):
                    raise ValueError("OpenAI output missing s2_bulk_queries list")
                queries = [_normalize_s2_query(S2BulkQuery.model_validate(x)) for x in items]

                if len(queries) > max_q:
                    log_event(run_ctx, stage=stage, event="budget_trim", from_count=len(queries), to_count=max_q)
                    queries = queries[:max_q]

                _validate_language_coverage(queries, provider="S2")
                _validate_intent_coverage(queries, provider="S2")
                _validate_s2_anchor_presence(queries, plan=plan)
                _validate_match_core_object_presence(queries, plan=plan, provider="S2")
                _validate_s2_match_required_group_budget(queries)
                _validate_s2_advanced_syntax_budget(queries)

                write_json(run_ctx.run_dir / "s2_bulk_queries.raw_output.json", obj)
                write_json(run_ctx.run_dir / "s2_bulk_queries.openai_meta.json", meta)
                break
            except Exception as e:
                last_err = e
                log_event(run_ctx, stage=stage, event="lint_failed", attempt=attempt, error=str(e)[:800], raw_path=str(attempt_raw_path))
                if attempt >= max_attempts:
                    raise
                continue

    write_json(cache_path, {"s2_bulk_queries": [q.model_dump(mode="json") for q in queries]})
    log_event(run_ctx, stage=stage, event="cache_write", path=str(cache_path), model_used=meta.get("model_used"), usage=meta.get("usage"), cost=meta.get("cost_usd"), query_count=len(queries))

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["openai"] = meta
    metrics["stages"][stage]["query_count"] = len(queries)
    save_metrics(run_ctx, metrics)

    meta = dict(meta)
    meta["cache_hit"] = False
    meta["query_count"] = len(queries)
    return queries, meta


# -----------------------------
# Phase D — Retrieval orchestrator (ported)
# -----------------------------


def _chunked(xs: List[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(xs), n):
        yield xs[i : i + n]


def _trim_cache_dir(run_ctx: RunContext) -> Path:
    p = run_ctx.run_dir / "cache"
    ensure_dir(p)
    return p


class RateLimiter:
    def __init__(self, rps: float):
        self.rps = float(rps or 0.0)
        self.min_interval = (1.0 / self.rps) if self.rps > 0 else 0.0
        self._next_ts = 0.0

    def acquire(self) -> None:
        if self.min_interval <= 0:
            return
        now = time.monotonic()
        if now < self._next_ts:
            time.sleep(self._next_ts - now)
        now2 = time.monotonic()
        self._next_ts = max(self._next_ts, now2) + self.min_interval


def _truncate_for_log(x: Any, max_str_len: int = 400) -> Any:
    if isinstance(x, str):
        return _truncate(x, max_str_len)
    if isinstance(x, dict):
        return {k: _truncate_for_log(v, max_str_len=max_str_len) for k, v in x.items()}
    if isinstance(x, list):
        # keep logs bounded
        return [_truncate_for_log(v, max_str_len=max_str_len) for v in x[:50]]
    return x


def _parse_retry_after(resp: requests.Response) -> Optional[float]:
    try:
        ra = (resp.headers or {}).get("Retry-After")
        if not ra:
            return None
        return float(ra)
    except Exception:
        return None


def request_json(
    *,
    run_ctx: RunContext,
    stage: str,
    provider: str,
    session: requests.Session,
    method: str,
    url: str,
    params: Optional[Dict[str, Any]],
    body: Optional[Dict[str, Any]],
    timeout_s: float,
    rate_limiter: Optional[RateLimiter],
    max_attempts: int = 8,
    backoff_initial_s: float = 1.0,
    backoff_max_s: float = 60.0,
) -> Any:
    method_u = method.upper()
    params_fp = dict(params or {})
    if "api_key" in params_fp:
        params_fp["api_key"] = "<redacted>"
    pjson = json.dumps(params_fp, ensure_ascii=False, sort_keys=True)
    bjson = json.dumps(body or {}, ensure_ascii=False, sort_keys=True)
    fingerprint = stable_hash(provider, method_u, url, pjson, bjson, length=24)
    endpoint = urlparse(url).path

    last_status: Any = None
    last_err: Optional[str] = None

    for attempt in range(1, max_attempts + 1):
        if rate_limiter is not None:
            rate_limiter.acquire()

        t0 = time.time()
        resp: Optional[requests.Response] = None
        try:
            resp = session.request(method_u, url, params=params, json=body, timeout=timeout_s)
            last_status = int(resp.status_code)
        except Exception as e:
            last_status = "exception"
            last_err = repr(e)

        retries = attempt - 1
        log_event(
            run_ctx,
            stage=stage,
            event="http_request",
            provider=provider,
            fingerprint=fingerprint,
            endpoint=endpoint,
            method=method_u,
            status=last_status,
            retries=retries,
            cache_hit=False,
            params=_truncate_for_log(params_fp),
            elapsed_s=round(time.time() - t0, 3),
        )

        retry_after_s: Optional[float] = None
        retryable = False
        if resp is None:
            retryable = True
        elif resp.status_code in (429, 500, 502, 503, 504):
            retryable = True
            retry_after_s = _parse_retry_after(resp)
        elif resp.status_code >= 400:
            raise RuntimeError(f"{provider} HTTP {resp.status_code} | URL: {resp.url} | Body: {resp.text[:600]}")

        if not retryable:
            try:
                return resp.json() if resp is not None else None
            except Exception as e:
                last_err = f"json_error: {e!r}"
                if attempt >= max_attempts:
                    raise RuntimeError(f"{provider} JSON decode error | URL: {url} | err={last_err}")
                retryable = True

        if attempt >= max_attempts:
            detail = f"last_status={last_status}"
            if last_err:
                detail += f" last_err={last_err}"
            raise RuntimeError(f"{provider} retry budget exhausted: {method_u} {url} ({detail})")

        wait = min(backoff_max_s, backoff_initial_s * (2 ** max(0, retries)))
        if retry_after_s is not None:
            wait = max(wait, float(retry_after_s))
        # jitter (avoid thundering herd)
        wait = wait * (1.0 + random.uniform(-0.15, 0.15))
        wait = max(0.5, float(wait))
        time.sleep(wait)


def _query_hash(provider: str, q: BaseModel) -> str:
    payload = json.dumps(q.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
    return stable_hash(provider, payload, length=24)


def count_jsonl_records(paths: List[Path]) -> int:
    total = 0
    seen: set[str] = set()
    for p in paths:
        sp = str(p)
        if sp in seen:
            continue
        seen.add(sp)
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        total += 1
        except Exception:
            continue
    return total


OPENALEX_SELECT = (
    "id,doi,display_name,publication_year,type,ids,cited_by_count,"
    "primary_location,authorships,abstract_inverted_index"
)


def _openalex_params(cfg: PipelineConfig, q: OpenAlexQuery, *, cursor: str) -> Dict[str, Any]:
    params: Dict[str, Any] = {
        "per-page": int(getattr(q, "per_page", 200) or 200),
        "cursor": cursor,
        "select": OPENALEX_SELECT,
    }
    if getattr(q, "sort", None):
        params["sort"] = q.sort
    if cfg.openalex_email:
        params["mailto"] = cfg.openalex_email
    if cfg.openalex_api_key:
        params["api_key"] = cfg.openalex_api_key

    base_filters = str(getattr(q, "filters", "") or "").strip().strip(",")
    if q.search_field in {"default.search", "search"}:
        params["search"] = q.query_string
        if base_filters:
            params["filter"] = base_filters
        return params

    # OpenAlex field-specific search via filter key (e.g. title_and_abstract.search:...)
    search_filter = f"{q.search_field}:{q.query_string}"
    params["filter"] = f"{base_filters},{search_filter}" if base_filters else search_filter
    return params


def fetch_openalex_to_cache(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    queries: List[OpenAlexQuery],
    force_rebuild: bool,
) -> Dict[str, Any]:
    stage = "phase_d_openalex_retrieval"
    base_url = cfg.openalex_base_url.rstrip("/") + "/works"
    cache_root = _trim_cache_dir(run_ctx) / "openalex"
    ensure_dir(cache_root)

    limiter = RateLimiter(cfg.openalex_rps)
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})

    cache_hits = 0
    cache_writes = 0
    query_failed = 0
    records_fetched = 0
    used_cache_paths: List[Path] = []

    for qi, q in enumerate(queries, start=1):
        qh = _query_hash("openalex", q)
        cache_path = cache_root / f"{qh}.jsonl"

        if cache_path.exists() and not force_rebuild:
            cache_hits += 1
            used_cache_paths.append(cache_path)
            log_event(
                run_ctx,
                stage=stage,
                event="cache_hit",
                provider="openalex",
                query_hash=qh,
                query_i=qi,
                path=str(cache_path),
                intent=q.intent,
                language=q.language,
            )
            continue

        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        ensure_dir(tmp.parent)
        tmp.touch(exist_ok=True)

        pages = 0
        cursor = "*"
        rank = 0

        try:
            while cursor:
                params = _openalex_params(cfg, q, cursor=cursor)
                data = request_json(
                    run_ctx=run_ctx,
                    stage=stage,
                    provider="openalex",
                    session=session,
                    method="GET",
                    url=base_url,
                    params=params,
                    body=None,
                    timeout_s=float(cfg.openalex_timeout_s),
                    rate_limiter=limiter,
                    max_attempts=8,
                    backoff_initial_s=1.0,
                    backoff_max_s=60.0,
                )
                pages += 1

                results = (data or {}).get("results") or []
                for w in results:
                    rank += 1
                    append_jsonl(
                        tmp,
                        {
                            "run_id": run_ctx.run_id,
                            "provider": "openalex",
                            "query_hash": qh,
                            "query_i": qi,
                            "intent": q.intent,
                            "language": q.language,
                            "rank": rank,
                            "work": w,
                        },
                    )

                cursor = ((data or {}).get("meta") or {}).get("next_cursor")
                if not cursor:
                    break

            tmp.replace(cache_path)
            cache_writes += 1
            used_cache_paths.append(cache_path)
            records_fetched += rank
            log_event(
                run_ctx,
                stage=stage,
                event="cache_write",
                provider="openalex",
                query_hash=qh,
                query_i=qi,
                path=str(cache_path),
                pages=pages,
                records=rank,
                intent=q.intent,
                language=q.language,
            )
        except Exception as e:
            query_failed += 1
            log_event(
                run_ctx,
                stage=stage,
                event="query_failed",
                provider="openalex",
                query_hash=qh,
                query_i=qi,
                intent=q.intent,
                language=q.language,
                error=repr(e),
            )
            # Keep existing cache_path if it exists (FORCE rebuild fallback).
            if cache_path.exists():
                used_cache_paths.append(cache_path)
            # preserve tmp for debugging
            if tmp.exists():
                failed = cache_path.with_suffix(cache_path.suffix + f".failed.{utc_now_iso().replace(':','_')}")
                try:
                    tmp.replace(failed)
                except Exception:
                    pass

    return {
        "cache_root": cache_root,
        "cache_hits": cache_hits,
        "cache_writes": cache_writes,
        "query_failed": query_failed,
        "records": count_jsonl_records(used_cache_paths),
        "records_fetched": records_fetched,
        "used_cache_paths": used_cache_paths,
    }


S2_BULK_FIELDS = "paperId"
S2_BATCH_FIELDS = "paperId,title,year,authors,venue,url,externalIds,citationCount,influentialCitationCount,abstract"


def _s2_iter_batch_items(batch: Any) -> List[Dict[str, Any]]:
    if isinstance(batch, list):
        return [b for b in batch if isinstance(b, dict)]
    if isinstance(batch, dict):
        it = batch.get("data", []) or []
        return [b for b in it if isinstance(b, dict)]
    return []


def fetch_s2_to_cache(
    *,
    cfg: PipelineConfig,
    run_ctx: RunContext,
    queries: List[S2BulkQuery],
    force_rebuild: bool,
    bulk_limit: int = 100,
) -> Dict[str, Any]:
    stage = "phase_d_semanticscholar_retrieval"
    base = cfg.semanticscholar_base_url.rstrip("/")
    bulk_url = base + "/paper/search/bulk"
    batch_url = base + "/paper/batch"

    cache_root = _trim_cache_dir(run_ctx) / "semanticscholar"
    ensure_dir(cache_root)

    limiter = RateLimiter(cfg.semanticscholar_rps)
    session = requests.Session()
    session.headers.update({"User-Agent": "instantpaper-two-lane/1.0"})
    if cfg.semanticscholar_api_key:
        session.headers.update({"x-api-key": cfg.semanticscholar_api_key})

    cache_hits = 0
    cache_writes = 0
    query_failed = 0
    records_fetched = 0
    used_cache_paths: List[Path] = []

    for qi, q in enumerate(queries, start=1):
        qh = _query_hash("semanticscholar", q)
        cache_path = cache_root / f"{qh}.jsonl"

        if cache_path.exists() and not force_rebuild:
            cache_hits += 1
            used_cache_paths.append(cache_path)
            log_event(
                run_ctx,
                stage=stage,
                event="cache_hit",
                provider="semanticscholar",
                query_hash=qh,
                query_i=qi,
                path=str(cache_path),
                intent=q.intent,
                language=q.language,
            )
            continue

        tmp = cache_path.with_suffix(cache_path.suffix + ".tmp")
        if tmp.exists():
            try:
                tmp.unlink()
            except Exception:
                pass

        ensure_dir(tmp.parent)
        tmp.touch(exist_ok=True)

        token: Optional[str] = None
        rank = 0
        written = 0

        try:
            while True:
                params: Dict[str, Any] = {"query": q.query_string, "fields": S2_BULK_FIELDS, "limit": int(bulk_limit)}
                if token:
                    params["token"] = token

                page = request_json(
                    run_ctx=run_ctx,
                    stage=stage,
                    provider="semanticscholar",
                    session=session,
                    method="GET",
                    url=bulk_url,
                    params=params,
                    body=None,
                    timeout_s=float(cfg.semanticscholar_timeout_s),
                    rate_limiter=limiter,
                    max_attempts=10,
                    backoff_initial_s=2.0,
                    backoff_max_s=120.0,
                )

                items = (page or {}).get("data") or []
                ids: List[str] = []
                ranks: Dict[str, int] = {}
                for it in items:
                    if not isinstance(it, dict):
                        continue
                    pid = it.get("paperId")
                    if not pid:
                        continue
                    pid_s = str(pid)
                    rank += 1
                    ids.append(pid_s)
                    ranks[pid_s] = rank

                if ids:
                    for chunk in _chunked(ids, 500):
                        batch = request_json(
                            run_ctx=run_ctx,
                            stage=stage,
                            provider="semanticscholar",
                            session=session,
                            method="POST",
                            url=batch_url,
                            params={"fields": S2_BATCH_FIELDS},
                            body={"ids": chunk},
                            timeout_s=float(cfg.semanticscholar_timeout_s),
                            rate_limiter=limiter,
                            max_attempts=10,
                            backoff_initial_s=2.0,
                            backoff_max_s=120.0,
                        )
                        for paper in _s2_iter_batch_items(batch):
                            pid = paper.get("paperId")
                            if not pid:
                                continue
                            pid_s = str(pid)
                            append_jsonl(
                                tmp,
                                {
                                    "run_id": run_ctx.run_id,
                                    "provider": "semanticscholar",
                                    "query_hash": qh,
                                    "query_i": qi,
                                    "intent": q.intent,
                                    "language": q.language,
                                    "rank": int(ranks.get(pid_s) or 0),
                                    "paper": paper,
                                },
                            )
                            written += 1

                token = (page or {}).get("token") or (page or {}).get("next")
                if not token:
                    break

            tmp.replace(cache_path)
            cache_writes += 1
            used_cache_paths.append(cache_path)
            records_fetched += written
            log_event(
                run_ctx,
                stage=stage,
                event="cache_write",
                provider="semanticscholar",
                query_hash=qh,
                query_i=qi,
                path=str(cache_path),
                ids_seen=rank,
                records=written,
                intent=q.intent,
                language=q.language,
            )
        except Exception as e:
            query_failed += 1
            log_event(
                run_ctx,
                stage=stage,
                event="query_failed",
                provider="semanticscholar",
                query_hash=qh,
                query_i=qi,
                intent=q.intent,
                language=q.language,
                error=repr(e),
            )
            if cache_path.exists():
                used_cache_paths.append(cache_path)
            if tmp.exists():
                failed = cache_path.with_suffix(cache_path.suffix + f".failed.{utc_now_iso().replace(':','_')}")
                try:
                    tmp.replace(failed)
                except Exception:
                    pass

    return {
        "cache_root": cache_root,
        "cache_hits": cache_hits,
        "cache_writes": cache_writes,
        "query_failed": query_failed,
        "records": count_jsonl_records(used_cache_paths),
        "records_fetched": records_fetched,
        "used_cache_paths": used_cache_paths,
    }


def rebuild_aggregate_jsonl(dest: Path, sources: List[Path]) -> None:
    ensure_dir(dest.parent)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    if tmp.exists():
        try:
            tmp.unlink()
        except Exception:
            pass

    with tmp.open("w", encoding="utf-8") as out:
        for src in sources:
            if not src.exists():
                continue
            with src.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        out.write(line)

    tmp.replace(dest)


# -----------------------------
# Phase E — Normalize + deduplicate candidates (ported)
# -----------------------------


_PARATEXT_RE = re.compile(
    r"^(books received|book[s]?\s+received|erratum|correction|editorial|preface|introduction|obituary)\b",
    re.IGNORECASE,
)


def is_paratext_title(title: str) -> bool:
    t = (title or "").strip()
    if not t:
        return True
    return bool(_PARATEXT_RE.search(t))


class CandidateSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: str
    query_hash: str
    query_i: int
    intent: str
    language: str
    rank: Optional[int] = None


class Candidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Canonical identity
    id: str
    doi: Optional[str] = None
    external_ids: Dict[str, str] = Field(default_factory=dict)

    # Metadata
    title: str
    authors: List[str] = Field(default_factory=list)
    year: Optional[int] = None
    venue: Optional[str] = None
    venue_is_core: Optional[bool] = None
    url: Optional[str] = None
    language: Optional[str] = None
    languages: List[str] = Field(default_factory=list)
    abstract: Optional[str] = None

    # Provenance
    provider_ids: Dict[str, List[str]] = Field(default_factory=dict)
    sources: List[CandidateSource] = Field(default_factory=list)
    intents: List[str] = Field(default_factory=list)

    # Signals
    citations: int = 0
    influential_citations: int = 0

    # Pool split
    pool: str


def _iter_jsonl_dicts(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.exists():
        return
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                yield obj


def _count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    try:
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    n += 1
    except Exception:
        return 0
    return n


def reconstruct_abstract_from_inverted_index(inv: Any) -> Optional[str]:
    """Reconstruct OpenAlex abstract text from `abstract_inverted_index`."""

    if not isinstance(inv, dict) or not inv:
        return None

    max_pos = -1
    for positions in inv.values():
        if not isinstance(positions, list):
            continue
        for p in positions:
            if isinstance(p, int) and p > max_pos:
                max_pos = p

    if max_pos < 0:
        return None

    words = [""] * (max_pos + 1)
    for token, positions in inv.items():
        if not isinstance(token, str) or not isinstance(positions, list):
            continue
        for p in positions:
            if isinstance(p, int) and 0 <= p <= max_pos:
                words[p] = token

    text = " ".join(w for w in words if w)
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


_DOI_PREFIX_RE = re.compile(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)", re.IGNORECASE)


def normalize_doi(x: Any) -> Optional[str]:
    if not x:
        return None
    s = str(x).strip()
    s = _DOI_PREFIX_RE.sub("", s)
    s = s.strip().strip("/")
    s = s.lower()
    if not s:
        return None
    if s.startswith("10."):
        return s
    m = re.search(r"10\.[0-9]{4,9}/[^\s]+", s)
    if m:
        return m.group(0).lower().rstrip(".")
    return None


def normalize_arxiv(x: Any) -> Optional[str]:
    if not x:
        return None
    s = str(x).strip()
    s = re.sub(r"^https?://arxiv\.org/(abs|pdf)/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^arxiv:\s*", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("/")
    s = s.lower()
    return s or None


def normalize_pmid(x: Any) -> Optional[str]:
    if not x:
        return None
    s = str(x).strip()
    s = re.sub(r"^https?://pubmed\.ncbi\.nlm\.nih\.gov/", "", s, flags=re.IGNORECASE)
    s = re.sub(r"\D+", "", s)
    return s or None


def normalize_pmcid(x: Any) -> Optional[str]:
    if not x:
        return None
    s = str(x).strip()
    s = re.sub(r"^https?://www\.ncbi\.nlm\.nih\.gov/pmc/articles/", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("/")
    s = s.upper()
    if s and not s.startswith("PMC"):
        s = "PMC" + s
    return s or None


_PUNCT_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def normalize_title(x: Any) -> str:
    s = str(x or "").casefold()
    s = _PUNCT_RE.sub(" ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def first_author_lastname(authors: List[str]) -> str:
    if not authors:
        return ""
    a = str(authors[0] or "").strip()
    if not a:
        return ""
    parts = re.split(r"\s+", a)
    last = parts[-1] if parts else ""
    last = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ\-']+", "", last)
    return last.casefold()


def _merge_str(a: Optional[str], b: Optional[str]) -> Optional[str]:
    a = (a or "").strip() or None
    b = (b or "").strip() or None
    if a and b:
        return a if len(a) >= len(b) else b
    return a or b


def _merge_list_pref_longer(a: List[str], b: List[str]) -> List[str]:
    a = list(a or [])
    b = list(b or [])
    if len(b) > len(a):
        return b
    return a


def _merge_int_max(a: Any, b: Any) -> int:
    try:
        ia = int(a or 0)
    except Exception:
        ia = 0
    try:
        ib = int(b or 0)
    except Exception:
        ib = 0
    return max(ia, ib)


def _merge_bool_tristate(a: Any, b: Any) -> Optional[bool]:
    va = a if isinstance(a, bool) else None
    vb = b if isinstance(b, bool) else None
    if va is True or vb is True:
        return True
    if va is False or vb is False:
        return False
    return None


def _merge_year(a: Optional[int], b: Optional[int]) -> Optional[int]:
    ya = int(a) if isinstance(a, int) else None
    yb = int(b) if isinstance(b, int) else None
    if ya and yb:
        return ya if ya == yb else min(ya, yb)
    return ya or yb


def _uniq_preserve(xs: List[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for x in xs or []:
        x = str(x or "").strip()
        if not x:
            continue
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _merge_sources(a: List[CandidateSource], b: List[CandidateSource]) -> List[CandidateSource]:
    out = list(a or [])
    seen = {stable_hash(s.provider, s.query_hash, str(s.query_i), str(s.rank or ""), s.intent, s.language, length=24) for s in out}
    for s in b or []:
        h = stable_hash(s.provider, s.query_hash, str(s.query_i), str(s.rank or ""), s.intent, s.language, length=24)
        if h in seen:
            continue
        seen.add(h)
        out.append(s)
    return out


def _merge_provider_ids(a: Dict[str, List[str]], b: Dict[str, List[str]]) -> Dict[str, List[str]]:
    out: Dict[str, List[str]] = {k: list(v) for k, v in (a or {}).items()}
    for k, vs in (b or {}).items():
        out.setdefault(k, [])
        out[k].extend(list(vs or []))
        out[k] = _uniq_preserve(out[k])
    return out


def _merge_external_ids(a: Dict[str, str], b: Dict[str, str]) -> Dict[str, str]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if not v:
            continue
        if k not in out or not out.get(k):
            out[k] = str(v)
            continue
        if len(str(v)) > len(str(out[k])):
            out[k] = str(v)
    return out


def _key_candidates(partial: Dict[str, Any]) -> List[str]:
    doi = normalize_doi(partial.get("doi"))
    ext = partial.get("external_ids") or {}
    arxiv = normalize_arxiv(ext.get("arxiv"))
    pmid = normalize_pmid(ext.get("pmid"))
    pmcid = normalize_pmcid(ext.get("pmcid"))

    title = partial.get("title") or ""
    year = partial.get("year")
    authors = partial.get("authors") or []

    keys: List[str] = []
    if doi:
        keys.append(f"doi:{doi}")
    if arxiv:
        keys.append(f"arxiv:{arxiv}")
    if pmid:
        keys.append(f"pmid:{pmid}")
    if pmcid:
        keys.append(f"pmcid:{pmcid}")

    tnorm = normalize_title(title)
    ln = first_author_lastname(authors)
    if tnorm and year and ln:
        keys.append(f"fallback:{tnorm}|{int(year)}|{ln}")

    pri = {"doi": 0, "arxiv": 1, "pmid": 2, "pmcid": 3, "fallback": 4}
    keys = sorted(set(keys), key=lambda k: (pri.get(k.split(":", 1)[0], 99), k))
    return keys


def _final_candidate_id(c: Dict[str, Any]) -> str:
    doi = normalize_doi(c.get("doi"))
    if doi:
        return doi
    ext = c.get("external_ids") or {}
    arxiv = normalize_arxiv(ext.get("arxiv"))
    if arxiv:
        return f"arxiv:{arxiv}"
    pmid = normalize_pmid(ext.get("pmid"))
    if pmid:
        return f"pmid:{pmid}"
    pmcid = normalize_pmcid(ext.get("pmcid"))
    if pmcid:
        return f"pmcid:{pmcid}"

    title = c.get("title") or ""
    year = c.get("year")
    authors = c.get("authors") or []
    tnorm = normalize_title(title)
    ln = first_author_lastname(authors)
    if tnorm and year and ln:
        payload = f"{tnorm}|{year}|{ln}"
        return "cand_" + stable_hash(payload, length=24)

    pid = json.dumps(c.get("provider_ids") or {}, ensure_ascii=False, sort_keys=True)
    url = str(c.get("url") or "").strip()
    payload = f"{tnorm}|{year or ''}|{ln}|{url}|{pid}"
    return "cand_" + stable_hash(payload, length=24)


def normalize_openalex_record(rec: Dict[str, Any], *, stats: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
    w = (rec or {}).get("work") or {}
    if not isinstance(w, dict):
        return None

    title = (w.get("display_name") or "").strip()
    if not title:
        return None

    if is_paratext_title(title):
        if stats is not None:
            stats["filtered_paratext_titles"] = int(stats.get("filtered_paratext_titles", 0) or 0) + 1
        return None

    wtype = str(w.get("type") or "").casefold()
    if wtype in {"editorial", "erratum", "correction", "letter"}:
        if stats is not None:
            stats["filtered_openalex_types"] = int(stats.get("filtered_openalex_types", 0) or 0) + 1
        return None

    cited_by = int(w.get("cited_by_count") or 0)
    year = w.get("publication_year")
    year = int(year) if isinstance(year, int) else None

    ids = w.get("ids") or {}
    doi = normalize_doi(w.get("doi") or ids.get("doi"))
    arxiv = normalize_arxiv(ids.get("arxiv"))
    pmid = normalize_pmid(ids.get("pmid"))
    pmcid = normalize_pmcid(ids.get("pmcid"))

    external_ids: Dict[str, str] = {}
    if arxiv:
        external_ids["arxiv"] = arxiv
    if pmid:
        external_ids["pmid"] = pmid
    if pmcid:
        external_ids["pmcid"] = pmcid

    pl = w.get("primary_location") or {}
    src = (pl.get("source") or {}) if isinstance(pl, dict) else {}
    venue = None
    if isinstance(src, dict):
        venue = (src.get("display_name") or "").strip() or None

    venue_is_core: Optional[bool] = None
    if isinstance(src, dict) and isinstance(src.get("is_core"), bool):
        venue_is_core = src.get("is_core")

    url = None
    if isinstance(pl, dict):
        url = (pl.get("landing_page_url") or "").strip() or None
    if not url and doi:
        url = "https://doi.org/" + doi

    authors: List[str] = []
    auths = w.get("authorships") or []
    if isinstance(auths, list):
        for a in auths[:50]:
            if not isinstance(a, dict):
                continue
            nm = ((a.get("author") or {}).get("display_name") or "").strip()
            if nm:
                authors.append(nm)
    authors = _uniq_preserve(authors)

    abstract = reconstruct_abstract_from_inverted_index(w.get("abstract_inverted_index"))

    openalex_id = (w.get("id") or ids.get("openalex") or "").strip() or None

    intent = str(rec.get("intent") or "unknown")
    if intent == "unknown":
        if stats is not None:
            stats["unknown_intent_count"] = int(stats.get("unknown_intent_count", 0) or 0) + 1

    src_obj = CandidateSource(
        provider="openalex",
        query_hash=str(rec.get("query_hash") or ""),
        query_i=int(rec.get("query_i") or 0),
        intent=intent,
        language=str(rec.get("language") or ""),
        rank=int(rec.get("rank") or 0) if rec.get("rank") is not None else None,
    )

    return {
        "doi": doi,
        "external_ids": external_ids,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "venue_is_core": venue_is_core,
        "url": url,
        "language": str(rec.get("language") or "") or None,
        "languages": [str(rec.get("language") or "") or ""],
        "abstract": abstract,
        "provider_ids": {"openalex": [openalex_id] if openalex_id else []},
        "sources": [src_obj],
        "intents": [intent],
        "citations": cited_by,
        "influential_citations": 0,
    }


def normalize_s2_record(rec: Dict[str, Any], *, stats: Optional[Dict[str, int]] = None) -> Optional[Dict[str, Any]]:
    p = (rec or {}).get("paper") or {}
    if not isinstance(p, dict):
        return None

    title = (p.get("title") or "").strip()
    if not title:
        return None

    if is_paratext_title(title):
        if stats is not None:
            stats["filtered_paratext_titles"] = int(stats.get("filtered_paratext_titles", 0) or 0) + 1
        return None

    year = p.get("year")
    year = int(year) if isinstance(year, int) else None

    doi = normalize_doi(((p.get("externalIds") or {}).get("DOI")) or p.get("doi"))
    ext = p.get("externalIds") or {}

    arxiv = normalize_arxiv(ext.get("ArXiv"))
    pmid = normalize_pmid(ext.get("PubMed"))
    pmcid = normalize_pmcid(ext.get("PubMedCentral"))

    external_ids: Dict[str, str] = {}
    if arxiv:
        external_ids["arxiv"] = arxiv
    if pmid:
        external_ids["pmid"] = pmid
    if pmcid:
        external_ids["pmcid"] = pmcid

    citations = int(p.get("citationCount") or 0)
    influential = int(p.get("influentialCitationCount") or 0)

    venue = (p.get("venue") or "").strip() or None
    url = (p.get("url") or "").strip() or None

    authors: List[str] = []
    auths = p.get("authors") or []
    if isinstance(auths, list):
        for a in auths[:80]:
            if not isinstance(a, dict):
                continue
            nm = (a.get("name") or "").strip()
            if nm:
                authors.append(nm)
    authors = _uniq_preserve(authors)

    abstract = (p.get("abstract") or "").strip() or None

    paper_id = (p.get("paperId") or "").strip() or None

    intent = str(rec.get("intent") or "unknown")
    if intent == "unknown":
        if stats is not None:
            stats["unknown_intent_count"] = int(stats.get("unknown_intent_count", 0) or 0) + 1

    src_obj = CandidateSource(
        provider="semanticscholar",
        query_hash=str(rec.get("query_hash") or ""),
        query_i=int(rec.get("query_i") or 0),
        intent=intent,
        language=str(rec.get("language") or ""),
        rank=int(rec.get("rank") or 0) if rec.get("rank") is not None else None,
    )

    return {
        "doi": doi,
        "external_ids": external_ids,
        "title": title,
        "authors": authors,
        "year": year,
        "venue": venue,
        "venue_is_core": None,
        "url": url,
        "language": str(rec.get("language") or "") or None,
        "languages": [str(rec.get("language") or "") or ""],
        "abstract": abstract,
        "provider_ids": {"semanticscholar": [paper_id] if paper_id else []},
        "sources": [src_obj],
        "intents": [intent],
        "citations": citations,
        "influential_citations": influential,
    }


def merge_partials(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a)

    out["doi"] = normalize_doi(_merge_str(out.get("doi"), b.get("doi")))
    out["external_ids"] = _merge_external_ids(out.get("external_ids") or {}, b.get("external_ids") or {})
    out["title"] = _merge_str(out.get("title"), b.get("title")) or (out.get("title") or "")
    out["authors"] = _merge_list_pref_longer(out.get("authors") or [], b.get("authors") or [])
    out["year"] = _merge_year(out.get("year"), b.get("year"))
    out["venue"] = _merge_str(out.get("venue"), b.get("venue"))
    out["venue_is_core"] = _merge_bool_tristate(out.get("venue_is_core"), b.get("venue_is_core"))
    out["url"] = _merge_str(out.get("url"), b.get("url"))

    abs_a = (out.get("abstract") or "").strip()
    abs_b = (b.get("abstract") or "").strip()
    if abs_a and abs_b:
        out["abstract"] = abs_a if len(abs_a) >= len(abs_b) else abs_b
    else:
        out["abstract"] = abs_a or abs_b or None

    out["provider_ids"] = _merge_provider_ids(out.get("provider_ids") or {}, b.get("provider_ids") or {})
    out["sources"] = _merge_sources(out.get("sources") or [], b.get("sources") or [])
    out["intents"] = sorted(set([*(out.get("intents") or []), *(b.get("intents") or [])]))
    out["languages"] = sorted(set([*(out.get("languages") or []), *(b.get("languages") or [])]))

    out["citations"] = _merge_int_max(out.get("citations"), b.get("citations"))
    out["influential_citations"] = _merge_int_max(out.get("influential_citations"), b.get("influential_citations"))

    langs = [x for x in out.get("languages") or [] if x]
    out["language"] = langs[0] if len(set(langs)) == 1 else None

    return out


def build_candidates_from_raw(
    *,
    run_ctx: RunContext,
    force_rebuild: bool,
) -> Tuple[List[Candidate], Dict[str, Any]]:
    stage = "phase_e_candidates"

    raw_oa = run_ctx.artifacts.openalex_raw_jsonl
    raw_s2 = run_ctx.artifacts.semanticscholar_raw_jsonl
    out_jsonl = run_ctx.artifacts.candidates_normalized_jsonl
    out_csv = run_ctx.artifacts.candidates_normalized_csv

    def _has_data(p: Path) -> bool:
        try:
            with p.open("r", encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        return True
        except Exception:
            return False
        return False

    if (not force_rebuild) and _has_data(out_jsonl):
        rows = [Candidate(**obj) for obj in _iter_jsonl_dicts(out_jsonl)]

        ids = [c.id for c in rows]
        if len(set(ids)) == len(ids):
            meta: Dict[str, Any] = {}
            try:
                metrics = load_metrics(run_ctx)
                cached = ((metrics.get("stages") or {}).get(stage) or {}).get("counts")
                if isinstance(cached, dict):
                    meta = dict(cached)
            except Exception:
                meta = {}

            pool_counts = {"with_abstract": 0, "without_abstract": 0}
            for c in rows:
                pool_counts[c.pool] = pool_counts.get(c.pool, 0) + 1

            meta.update(
                {
                    "cache_hit": True,
                    "raw_openalex_records": _count_lines(raw_oa),
                    "raw_s2_records": _count_lines(raw_s2),
                    "deduped_candidates": len(rows),
                    "final_id_collisions": 0,
                    "pool_counts": pool_counts,
                    "candidates_jsonl": str(out_jsonl),
                    "candidates_csv": str(out_csv),
                }
            )
            return rows, meta

    normalized = 0
    normalized_by_provider = {"openalex": 0, "semanticscholar": 0}
    stats: Dict[str, int] = {
        "filtered_paratext_titles": 0,
        "filtered_openalex_types": 0,
        "unknown_intent_count": 0,
    }

    index: Dict[str, str] = {}
    by_cid: Dict[str, Dict[str, Any]] = {}

    merges = 0

    def _get_or_create(part: Dict[str, Any]) -> str:
        nonlocal merges
        keys = _key_candidates(part)
        cid = None
        for k in keys:
            if k in index:
                cid = index[k]
                break
        if cid is None:
            if keys:
                seed = keys[0]
            else:
                pid = json.dumps(part.get("provider_ids") or {}, ensure_ascii=False, sort_keys=True)
                seed = (part.get("title") or "") + "\n" + pid + "\n" + str(part.get("url") or "")
            cid = stable_hash("candidate", seed, length=24)
            by_cid[cid] = part
        else:
            by_cid[cid] = merge_partials(by_cid[cid], part)
            merges += 1

        merged = by_cid[cid]
        for k in _key_candidates(merged):
            index[k] = cid
        return cid

    for rec in _iter_jsonl_dicts(raw_oa):
        part = normalize_openalex_record(rec, stats=stats)
        if not part:
            continue
        normalized += 1
        normalized_by_provider["openalex"] += 1
        _get_or_create(part)

    for rec in _iter_jsonl_dicts(raw_s2):
        part = normalize_s2_record(rec, stats=stats)
        if not part:
            continue
        normalized += 1
        normalized_by_provider["semanticscholar"] += 1
        _get_or_create(part)

    candidates: List[Candidate] = []
    pool_counts = {"with_abstract": 0, "without_abstract": 0}
    final_ids_seen = set()
    final_id_collisions = 0

    for cid, part in by_cid.items():
        abstract = (part.get("abstract") or "").strip() or None
        pool = "with_abstract" if abstract else "without_abstract"
        pool_counts[pool] += 1

        part_final = dict(part)
        part_final["abstract"] = abstract
        part_final["pool"] = pool
        final_id = _final_candidate_id(part_final)
        if final_id in final_ids_seen:
            final_id_collisions += 1
            final_id = "cand_" + str(cid)
        final_ids_seen.add(final_id)
        part_final["id"] = final_id
        part_final["doi"] = normalize_doi(part_final.get("doi"))

        part_final["authors"] = _uniq_preserve(part_final.get("authors") or [])
        part_final["intents"] = sorted(set([x for x in part_final.get("intents") or [] if x]))
        part_final["languages"] = sorted(set([x for x in part_final.get("languages") or [] if x]))

        candidates.append(Candidate(**part_final))

    candidates.sort(key=lambda c: (-int(c.citations or 0), (c.title or "").casefold(), c.id))

    ensure_dir(out_jsonl.parent)
    tmp = out_jsonl.with_suffix(out_jsonl.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as f:
        for c in candidates:
            f.write(json.dumps(c.model_dump(mode="json"), ensure_ascii=False, default=_json_default) + "\n")
    tmp.replace(out_jsonl)

    ensure_dir(out_csv.parent)
    tmpc = out_csv.with_suffix(out_csv.suffix + ".tmp")
    fieldnames = [
        "id",
        "doi",
        "pool",
        "citations",
        "influential_citations",
        "year",
        "title",
        "venue",
        "venue_is_core",
        "url",
        "authors_first",
        "langs",
        "intents",
        "openalex_id",
        "s2_paperId",
        "sources_n",
        "abstract_len",
    ]
    with tmpc.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for c in candidates:
            openalex_ids = (c.provider_ids or {}).get("openalex") or []
            s2_ids = (c.provider_ids or {}).get("semanticscholar") or []
            w.writerow(
                {
                    "id": c.id,
                    "doi": c.doi or "",
                    "pool": c.pool,
                    "citations": int(c.citations or 0),
                    "influential_citations": int(c.influential_citations or 0),
                    "year": c.year or "",
                    "title": c.title,
                    "venue": c.venue or "",
                    "venue_is_core": ("" if c.venue_is_core is None else str(bool(c.venue_is_core)).lower()),
                    "url": c.url or "",
                    "authors_first": (c.authors[0] if c.authors else ""),
                    "langs": ",".join(c.languages or []),
                    "intents": ",".join(c.intents or []),
                    "openalex_id": (openalex_ids[0] if openalex_ids else ""),
                    "s2_paperId": (s2_ids[0] if s2_ids else ""),
                    "sources_n": len(c.sources or []),
                    "abstract_len": (len(c.abstract or "") if c.abstract else 0),
                }
            )
    tmpc.replace(out_csv)

    meta = {
        "cache_hit": False,
        "raw_openalex_records": _count_lines(raw_oa),
        "raw_s2_records": _count_lines(raw_s2),
        "normalized_total": normalized,
        "normalized_by_provider": normalized_by_provider,
        "deduped_candidates": len(candidates),
        "merges": merges,
        "final_id_collisions": int(final_id_collisions or 0),
        "filtered_paratext_titles": int(stats.get("filtered_paratext_titles", 0) or 0),
        "filtered_openalex_types": int(stats.get("filtered_openalex_types", 0) or 0),
        "unknown_intent_count": int(stats.get("unknown_intent_count", 0) or 0),
        "pool_counts": pool_counts,
        "candidates_jsonl": str(out_jsonl),
        "candidates_csv": str(out_csv),
    }

    log_event(
        run_ctx,
        stage=stage,
        event="cache_write",
        provider="candidates",
        path=str(out_jsonl),
        records=len(candidates),
        csv=str(out_csv),
        merges=merges,
        with_abstract=pool_counts.get("with_abstract"),
        without_abstract=pool_counts.get("without_abstract"),
    )

    metrics = load_metrics(run_ctx)
    metrics.setdefault("stages", {}).setdefault(stage, {})["counts"] = meta
    save_metrics(run_ctx, metrics)

    return candidates, meta


class PipelineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_version: str = "two_lane_v1"
    runs_root: Path

    # OpenAI (LLM)
    openai_api_key: Optional[str] = Field(default=None, repr=False)
    openai_model_planner: str = "gpt-5-mini"
    openai_model_openalex_query_builder: str = "gpt-5-mini"
    openai_model_s2_query_builder: str = "gpt-5-mini"
    openai_model_rerank: str = "gpt-5-nano"
    openai_reasoning_effort: str = "high"
    openai_timeout_s: float = 43200.0
    openai_max_output_tokens_planner: int = 100000

    # Providers
    openalex_base_url: str = "https://api.openalex.org"
    openalex_api_key: Optional[str] = Field(default=None, repr=False)
    openalex_email: Optional[str] = None
    openalex_timeout_s: float = 60.0
    openalex_rps: float = 10.0

    semanticscholar_base_url: str = "https://api.semanticscholar.org/graph/v1"
    semanticscholar_api_key: Optional[str] = Field(default=None, repr=False)
    semanticscholar_timeout_s: float = 60.0
    semanticscholar_rps: float = 1.0

    # Hard caps
    max_queries_per_provider: int = 50

    # Debug / dev
    # When True, ignore any cached stage artifacts in the run directory.
    # When False, stages will attempt to resume from existing artifacts (best-effort).
    force_rebuild: bool = True

    # Embeddings
    embedding_model: str = "text-embedding-3-small"
    embedding_batch_size: int = 256
    embedding_candidate_abstract_chars_main: int = 800
    embedding_candidate_include_venue: bool = True
    embedding_candidate_include_year: bool = True
    embedding_candidate_include_authors: bool = False
    embedding_shortlist_stage2: int = 400
    embedding_chunk_target_min: int = 260
    embedding_chunk_target_max: int = 420
    embedding_stage2_weight: float = 0.45
    embedding_stage1_weight: float = 0.55
    embedding_apply_mmr: bool = True
    embedding_mmr_lambda: float = 0.82
    embedding_mmr_top_k: int = 40
    embedding_max_no_abstract_share: float = 0.15
    embedding_apply_hygiene: bool = True
    embedding_temp_precap_total: int = 100000
    embedding_temp_precap_noabs_share: float = 0.15

    # Pruning
    prune_n1: int = 600
    prune_n1_without_abstract: int = 300

    # S2 neighbor booster
    s2_neighbor_seed_count: int = 5
    s2_recs_limit_per_seed: int = 300

    # Rerank
    rerank_top_k_pre: int = 40
    rerank_concurrency: int = 20
    rerank_pairwise_top_k: int = 6
    rerank_pointwise_max_output_tokens: int = 2500
    rerank_pointwise_timeout_s: float = 300.0
    rerank_pairwise_max_output_tokens: int = 1500
    rerank_pairwise_timeout_s: float = 240.0

    # Match aggregation weights
    match_weight_best: float = 0.55
    match_weight_top_m: float = 0.25
    match_weight_cov: float = 0.20
    match_m: int = 3

    # Scoring constants
    scoring_t: float = 0.30
    scoring_t_noabs: float = 0.35

    # Authority time stratification
    authority_classic_year_max: int = 2004
    authority_recent_year_window: int = 8
    authority_bucket_quotas: Dict[str, int] = Field(default_factory=lambda: {"classic": 8, "mid": 6, "recent": 6})

    @classmethod
    def from_env(cls, *, runs_root: Path, pipeline_version: str) -> "PipelineConfig":
        return cls(
            pipeline_version=pipeline_version,
            runs_root=Path(runs_root),
            openai_api_key=(os.getenv("OPENAI_API_KEY") or "").strip() or None,
            openalex_api_key=(os.getenv("OPENALEX_API_KEY") or "").strip() or None,
            openalex_email=((os.getenv("OPENALEX_EMAIL") or "").strip() or (os.getenv("OPENALEX_MAILTO") or "").strip() or None),
            semanticscholar_api_key=(os.getenv("SEMANTICSCHOLAR_API_KEY") or "").strip() or None,
        )


# -----------------------------
# OpenAI runtime wrapper (budget + cost cap)
# -----------------------------


class TwoLaneBudgetExceeded(RuntimeError):
    pass


@dataclass
class TwoLaneStageCost:
    cost_usd: float = 0.0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    requests: int = 0


class TwoLaneOpenAI:
    def __init__(
        self,
        *,
        user_id: str,
        projekt_id: str,
        kapitel_id: str,
        run_id: str,
        api_key: str,
        key_source: str,
        max_total_cost_usd: float = 2.0,
    ):
        self.user_id = str(user_id)
        self.projekt_id = str(projekt_id)
        self.kapitel_id = str(kapitel_id)
        self.run_id = str(run_id)
        self.api_key = api_key
        self.key_source = key_source
        self.max_total_cost_usd = float(max_total_cost_usd)

        self.openai_service = OpenAIService()
        self.cost_service = get_cost_service(firebase_service)
        self.budget_service = get_openai_budget_service(firebase_service)
        self.credits_service = get_credits_service(firebase_service)

        self.total_cost_usd: float = 0.0
        self.stage_costs: Dict[str, TwoLaneStageCost] = {}

        # Unique workflow id scopes all budget/cost operations to one pipeline run.
        self.workflow_id = stable_hash("two_lane", self.user_id, self.run_id, length=16)
        self._operation_seq = 0
        self.budget_exceeded = False

        # Live cost reporting to Firestore (for UI updates while running).
        # Throttled to avoid write hot-spots during high-concurrency phases (e.g. rerank).
        self._live_cost_emit_interval_s = 1.0
        self._live_cost_emit_last_s = 0.0
        self._live_cost_emit_pending_stage: str | None = None
        self._live_cost_emit_task: asyncio.Task | None = None
        self._live_cost_emit_lock = asyncio.Lock()

    def _ensure_budget_before_call(self) -> None:
        if self.budget_exceeded or float(self.total_cost_usd) > float(self.max_total_cost_usd):
            self.budget_exceeded = True
            raise TwoLaneBudgetExceeded(
                f"Two-lane pipeline budget exceeded: ${self.total_cost_usd:.2f} > ${self.max_total_cost_usd:.2f}"
            )

    def _stage(self, stage: str) -> TwoLaneStageCost:
        st = self.stage_costs.get(stage)
        if st is None:
            st = TwoLaneStageCost()
            self.stage_costs[stage] = st
        return st

    def _next_operation_id(self, *, stage: str, operation_type: str, model: str, operation_details: dict | None = None) -> str:
        self._operation_seq += 1
        try:
            details_key = json.dumps(operation_details or {}, ensure_ascii=False, sort_keys=True, default=_json_default)
        except Exception:
            details_key = str(operation_details or "")
        suffix = stable_hash(
            stage,
            operation_type,
            model,
            details_key,
            f"seq:{self._operation_seq}",
            length=12,
        )
        return f"{self.workflow_id}_{suffix}"

    @staticmethod
    def _openai_retry_after_seconds(exc: Exception) -> float | None:
        response = getattr(exc, "response", None)
        headers = getattr(response, "headers", None)
        if not headers:
            return None
        value = headers.get("retry-after") or headers.get("Retry-After")
        if value is None:
            return None
        try:
            return max(0.0, float(value))
        except Exception:
            return None

    @classmethod
    def _should_retry_embedding_error(cls, exc: Exception) -> tuple[bool, float | None]:
        retry_after_s = cls._openai_retry_after_seconds(exc)

        if isinstance(exc, (APIConnectionError, APITimeoutError, InternalServerError, RateLimitError)):
            return True, retry_after_s

        if isinstance(exc, APIStatusError):
            status_code = int(getattr(exc, "status_code", 0) or getattr(getattr(exc, "response", None), "status_code", 0) or 0)
            return status_code in {408, 409, 429, 500, 502, 503, 504}, retry_after_s

        status_code = getattr(exc, "status_code", None)
        if status_code is not None:
            try:
                return int(status_code) in {408, 409, 429, 500, 502, 503, 504}, retry_after_s
            except Exception:
                pass

        message = str(exc).lower()
        if any(
            token in message
            for token in (
                "server_error",
                "internalservererror",
                "rate limit",
                "timeout",
                "timed out",
                "connection error",
                "temporarily unavailable",
            )
        ):
            return True, retry_after_s

        return False, None

    def _costs_snapshot(self) -> Dict[str, Any]:
        stage_costs = {
            str(stage): {
                "cost_usd": float(st.cost_usd),
                "input_tokens": int(st.input_tokens),
                "cached_input_tokens": int(st.cached_input_tokens),
                "output_tokens": int(st.output_tokens),
                "requests": int(st.requests),
            }
            for stage, st in (self.stage_costs or {}).items()
        }
        return {
            "total_cost_usd": float(self.total_cost_usd),
            "budget_cap_usd": float(self.max_total_cost_usd),
            "key_source": str(self.key_source),
            "stage_costs": stage_costs,
        }

    def _write_live_costs_sync(self, *, stage: str) -> None:
        try:
            ref = (
                firebase_service.db.collection("users")
                .document(str(self.user_id))
                .collection("projects")
                .document(str(self.projekt_id))
                .collection("researchRuns")
                .document(str(self.run_id))
            )
            ref.set(
                {
                    "updatedAt": SERVER_TIMESTAMP,
                    "summary": {
                        **self._costs_snapshot(),
                        "lastCostUpdatedAt": SERVER_TIMESTAMP,
                        "lastCostStage": str(stage),
                    },
                },
                merge=True,
            )
        except Exception as exc:
            logger.warning("Two-lane live cost update failed (ignored): %s", exc)

    async def _emit_live_costs_worker(self) -> None:
        while True:
            async with self._live_cost_emit_lock:
                stage = self._live_cost_emit_pending_stage
                self._live_cost_emit_pending_stage = None
                if not stage:
                    self._live_cost_emit_task = None
                    return

                now = time.perf_counter()
                delay = max(0.0, float(self._live_cost_emit_interval_s) - float(now - self._live_cost_emit_last_s))

            if delay > 0:
                await asyncio.sleep(delay)

            await asyncio.to_thread(self._write_live_costs_sync, stage=str(stage))

            async with self._live_cost_emit_lock:
                self._live_cost_emit_last_s = time.perf_counter()

    async def _request_live_cost_emit(self, *, stage: str) -> None:
        try:
            async with self._live_cost_emit_lock:
                self._live_cost_emit_pending_stage = str(stage)
                if self._live_cost_emit_task is None or self._live_cost_emit_task.done():
                    self._live_cost_emit_task = asyncio.create_task(self._emit_live_costs_worker())
        except Exception:
            # Best-effort only; never fail the pipeline due to live UI telemetry.
            return

    async def json_schema_call(
        self,
        *,
        stage: str,
        operation_type: str,
        model: str,
        system_prompt: str,
        user_prompt: str,
        schema_name: str,
        schema: dict,
        reasoning_effort: str,
        max_output_tokens: int | None,
        timeout_s: float,
        operation_details: dict | None = None,
    ) -> tuple[dict, dict]:
        self._ensure_budget_before_call()

        spend_rate = float(await self.credits_service.get_spend_rate_for_user(self.user_id))
        pricing_model, pricing, _match_type = await self.cost_service.resolve_model_pricing(model)
        input_price, _cached_input_price, output_price = pricing

        input_tokens_est = int(count_tokens(system_prompt) + count_tokens(user_prompt))
        output_tokens_est = int(max_output_tokens or 0) if max_output_tokens else 6000
        cost_est_usd = float((input_tokens_est / 1_000_000) * float(input_price) + (output_tokens_est / 1_000_000) * float(output_price))
        credits_est = float(cost_est_usd * spend_rate)
        if credits_est <= 0:
            credits_est = 0.0001

        op_id = self._next_operation_id(
            stage=stage,
            operation_type=operation_type,
            model=model,
            operation_details=operation_details,
        )
        estimate = {
            "operationType": str(operation_type),
            "model": str(model),
            "pricingModel": str(pricing_model),
            "inputTokens": int(input_tokens_est),
            "outputTokens": int(output_tokens_est),
            "totalTokens": int(input_tokens_est + output_tokens_est),
            "costUsd": float(cost_est_usd),
            "spendRate": float(spend_rate),
            "credits": float(credits_est),
        }

        reservation = await self.budget_service.reserve_operation(
            user_id=self.user_id,
            operation_id=op_id,
            operation_type=operation_type,
            user_action_id=self.run_id,
            estimate=estimate,
            projekt_id=self.projekt_id,
            kapitel_id=self.kapitel_id,
            operation_details=operation_details,
        )
        if reservation.result == "blocked":
            raise HTTPException(
                status_code=402,
                detail="Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
            )
        if reservation.result in {"already_reserved", "finalized"}:
            raise HTTPException(status_code=409, detail="Operation already exists. Please retry later.")

        await self.budget_service.mark_running(user_id=self.user_id, operation_id=op_id)

        client = self.openai_service._get_client(self.api_key)  # pylint: disable=protected-access
        overall_timeout_s = float(timeout_s or 120.0)
        http_timeout_create_s = float(min(max(30.0, overall_timeout_s), 600.0))
        http_timeout_poll_s = float(min(60.0, http_timeout_create_s))
        if max_output_tokens is not None:
            max_output_tokens = max(256, int(max_output_tokens or 0))

        t0 = time.perf_counter()
        try:
            resp = await client.responses.create(
                model=model,
                service_tier="default",
                input=[
                    {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
                    {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
                ],
                text={
                    "format": {
                        "type": "json_schema",
                        "name": schema_name,
                        "schema": schema,
                        "strict": True,
                    }
                },
                reasoning={"effort": reasoning_effort},
                max_output_tokens=max_output_tokens,
                store=False,
                background=True,
                timeout=http_timeout_create_s,
            )

            response_id = getattr(resp, "id", None)
            terminal_statuses = {"completed", "incomplete", "failed", "cancelled", "canceled"}

            poll_sleep_s = 1.0
            while getattr(resp, "status", None) not in terminal_statuses:
                if (time.perf_counter() - t0) > overall_timeout_s:
                    raise TimeoutError(
                        f"OpenAI background response timed out after {int(overall_timeout_s)}s "
                        f"(last_status={getattr(resp, 'status', None)!r}, response_id={response_id!r})."
                    )
                await asyncio.sleep(poll_sleep_s)
                poll_sleep_s = min(poll_sleep_s * 1.5, 10.0)
                if not response_id:
                    break
                resp = await client.responses.retrieve(response_id, timeout=http_timeout_poll_s)
        except Exception as exc:
            await self.budget_service.mark_status(user_id=self.user_id, operation_id=op_id, status="error", error_message=str(exc))
            await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="error")
            raise

        raw_text = _extract_text_from_response(resp)
        if not isinstance(raw_text, str) or not raw_text.strip():
            await self.budget_service.mark_status(user_id=self.user_id, operation_id=op_id, status="error", error_message="empty_output")
            await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="error")
            raise RuntimeError("OpenAI returned empty output_text.")

        try:
            obj = json.loads(raw_text)
        except Exception as exc:
            await self.budget_service.mark_status(user_id=self.user_id, operation_id=op_id, status="error", error_message="invalid_json")
            await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="error")
            raise RuntimeError("Failed to parse JSON output.") from exc

        usage = self.cost_service.extract_usage_from_response(resp)
        cost_breakdown, matched_model, pricing, _match_type = await self.cost_service.calculate_cost(
            model=str(getattr(resp, "model", None) or model),
            usage=usage,
        )

        await self.cost_service.log_operation(
            operation_id=op_id,
            operation_type=operation_type,
            user_id=self.user_id,
            user_action_id=self.run_id,
            operation_details=operation_details,
            model=str(getattr(resp, "model", None) or model),
            usage=usage,
            cost_breakdown=cost_breakdown,
            matched_model_key=matched_model,
            pricing=pricing,
            key_source=self.key_source,
            projekt_id=self.projekt_id,
            kapitel_id=self.kapitel_id,
        )

        await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="success")

        dt = float(time.perf_counter() - t0)
        cost_usd = float(cost_breakdown.total_cost_usd)

        incomplete_details = getattr(resp, "incomplete_details", None)
        incomplete_reason = (
            incomplete_details.get("reason")
            if isinstance(incomplete_details, dict)
            else getattr(incomplete_details, "reason", None)
        )

        st = self._stage(stage)
        st.requests += 1
        st.input_tokens += int(usage.input_tokens)
        st.cached_input_tokens += int(usage.cached_input_tokens)
        st.output_tokens += int(usage.output_tokens)
        st.cost_usd += float(cost_usd)
        self.total_cost_usd += float(cost_usd)

        # Post-call budget tracking (user requirement: block the *next* OpenAI call).
        if float(self.total_cost_usd) > float(self.max_total_cost_usd):
            self.budget_exceeded = True

        await self._request_live_cost_emit(stage=stage)

        meta = {
            "model_requested": model,
            "model_used": str(getattr(resp, "model", None) or model),
            "response_id": str(getattr(resp, "id", None) or ""),
            "latency_s": round(dt, 3),
            "usage": {
                "input_tokens": int(usage.input_tokens),
                "cached_input_tokens": int(usage.cached_input_tokens),
                "output_tokens": int(usage.output_tokens),
                "reasoning_tokens": 0,
            },
            "cost_usd": float(cost_usd),
            "status": str(getattr(resp, "status", None) or "completed"),
            "incomplete_reason": str(incomplete_reason) if incomplete_reason else None,
        }

        return obj, meta

    async def embed_texts(
        self,
        *,
        stage: str,
        operation_type: str,
        model: str,
        texts: list[str],
        batch_size: int,
        operation_details: dict | None = None,
    ) -> tuple[list[array], dict]:
        self._ensure_budget_before_call()

        spend_rate = float(await self.credits_service.get_spend_rate_for_user(self.user_id))
        pricing_model, pricing, _match_type = await self.cost_service.resolve_model_pricing(model)
        input_price, _cached_input_price, _output_price = pricing

        client = self.openai_service._get_client(self.api_key)  # pylint: disable=protected-access

        all_vecs: list[array] = []
        reqs = 0
        prompt_tokens_total = 0
        cost_usd_total = 0.0

        for bi in range(0, len(texts), int(batch_size)):
            self._ensure_budget_before_call()
            batch = texts[bi : bi + int(batch_size)]
            if not batch:
                continue

            batch_operation_details = {"batchIndex": int(bi), "batchSize": int(len(batch)), **(operation_details or {})}
            op_id = self._next_operation_id(
                stage=stage,
                operation_type=operation_type,
                model=model,
                operation_details=batch_operation_details,
            )

            input_tokens_est = int(sum(count_tokens(t) for t in batch))
            cost_est_usd = float((input_tokens_est / 1_000_000) * float(input_price))
            credits_est = float(cost_est_usd * spend_rate)
            if credits_est <= 0:
                credits_est = 0.0001

            estimate = {
                "operationType": str(operation_type),
                "model": str(model),
                "pricingModel": str(pricing_model),
                "inputTokens": int(input_tokens_est),
                "outputTokens": 0,
                "totalTokens": int(input_tokens_est),
                "costUsd": float(cost_est_usd),
                "spendRate": float(spend_rate),
                "credits": float(credits_est),
            }

            reservation = await self.budget_service.reserve_operation(
                user_id=self.user_id,
                operation_id=op_id,
                operation_type=operation_type,
                user_action_id=self.run_id,
                estimate=estimate,
                projekt_id=self.projekt_id,
                kapitel_id=self.kapitel_id,
                operation_details=batch_operation_details,
            )
            if reservation.result == "blocked":
                raise HTTPException(
                    status_code=402,
                    detail="Nicht genügend Credits verfügbar. Bitte lade Credits im Profil unter Billing auf.",
                )
            if reservation.result in {"already_reserved", "finalized"}:
                raise HTTPException(status_code=409, detail="Operation already exists. Please retry later.")

            await self.budget_service.mark_running(user_id=self.user_id, operation_id=op_id)

            t0 = time.perf_counter()
            resp = None
            backoff_s = 1.0
            for attempt in range(1, 9):
                try:
                    resp = await client.embeddings.create(model=model, input=batch)
                    break
                except Exception as exc:
                    retryable, retry_after_s = self._should_retry_embedding_error(exc)
                    if (not retryable) or attempt >= 8:
                        await self.budget_service.mark_status(
                            user_id=self.user_id,
                            operation_id=op_id,
                            status="error",
                            error_message=str(exc),
                        )
                        await self.budget_service.release_reservation(
                            user_id=self.user_id,
                            operation_id=op_id,
                            reason="error",
                        )
                        raise

                    wait_s = min(60.0, float(backoff_s))
                    if retry_after_s is not None:
                        wait_s = max(wait_s, float(retry_after_s))
                    wait_s = max(0.5, float(wait_s) * (1.0 + random.uniform(-0.15, 0.15)))
                    logger.warning(
                        "Two-lane embeddings transient failure | stage=%s run_id=%s operation_id=%s batch_index=%s "
                        "attempt=%s/8 wait_s=%.2f error=%s",
                        stage,
                        self.run_id,
                        op_id,
                        int(bi),
                        attempt,
                        wait_s,
                        _truncate(repr(exc), max_len=240),
                    )
                    await asyncio.sleep(wait_s)
                    backoff_s *= 2.0

            data = list(getattr(resp, "data", None) or [])
            if len(data) != len(batch) or any(getattr(item, "embedding", None) is None for item in data):
                err = RuntimeError(f"Embedding response shape mismatch (got {len(data)} for {len(batch)}).")
                await self.budget_service.mark_status(user_id=self.user_id, operation_id=op_id, status="error", error_message=str(err))
                await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="error")
                raise err

            vecs = [array("f", [float(x) for x in item.embedding]) for item in data]
            all_vecs.extend(vecs)
            reqs += 1

            usage_obj = getattr(resp, "usage", None)
            prompt_tokens = int(getattr(usage_obj, "total_tokens", 0) or getattr(usage_obj, "prompt_tokens", 0) or 0)
            prompt_tokens_total += int(prompt_tokens)

            usage = TokenUsage.from_any(prompt_tokens, 0, 0)
            cost_breakdown, matched_model, pricing, _match_type = await self.cost_service.calculate_cost(model=model, usage=usage)
            cost_usd = float(cost_breakdown.total_cost_usd)
            cost_usd_total += float(cost_usd)

            await self.cost_service.log_operation(
                operation_id=op_id,
                operation_type=operation_type,
                user_id=self.user_id,
                user_action_id=self.run_id,
                operation_details=batch_operation_details,
                model=model,
                usage=usage,
                cost_breakdown=cost_breakdown,
                matched_model_key=matched_model,
                pricing=pricing,
                key_source=self.key_source,
                projekt_id=self.projekt_id,
                kapitel_id=self.kapitel_id,
            )

            await self.budget_service.release_reservation(user_id=self.user_id, operation_id=op_id, reason="success")

            st = self._stage(stage)
            st.requests += 1
            st.input_tokens += int(prompt_tokens)
            st.cost_usd += float(cost_usd)
            self.total_cost_usd += float(cost_usd)

            if float(self.total_cost_usd) > float(self.max_total_cost_usd):
                self.budget_exceeded = True

            await self._request_live_cost_emit(stage=stage)

        meta = {
            "texts": int(len(texts)),
            "batches": int(math.ceil(len(texts) / max(1, int(batch_size)))),
            "api_calls": int(reqs),
            "prompt_tokens": int(prompt_tokens_total),
            "cost_usd": float(cost_usd_total),
            "model": str(model),
        }
        return all_vecs, meta


# TODO(two-lane): remaining phases F–K and orchestrator
