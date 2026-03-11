from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import statistics
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import numpy as np
import tiktoken
from openai import OpenAI

from phase_c_query_replay_probe import OUTPUT_DIR, REPO_ROOT, _load_env


RUNS_DIR = REPO_ROOT / "sources-v2" / "runs"
CACHE_DIR = REPO_ROOT / "sources-v2" / "prompt_research" / "embedding_probe_cache"
USAGE_LOG_PATH = OUTPUT_DIR / "phase_f_embedding_probe_usage.jsonl"

SMALL_MODEL = "text-embedding-3-small"
LARGE_MODEL = "text-embedding-3-large"
MODEL_PRICES_USD_PER_1M = {
    SMALL_MODEL: 0.02,
    LARGE_MODEL: 0.13,
}
DEFAULT_BUDGET_USD = 1.0
DOC_ABSTRACT_CHARS = 800
CHUNK_ABSTRACT_CHARS = 1800
CHUNK_TARGET_MIN = 260
CHUNK_TARGET_MAX = 420
STAGED_SHORTLIST = 400
MMR_LAMBDA = 0.82


@dataclass
class Candidate:
    id: str
    title: str
    abstract: Optional[str]
    year: Optional[int]
    venue: Optional[str]
    authors: List[str]
    doi: Optional[str]
    citations: int
    influential_citations: int
    providers: List[str]
    intents: List[str]
    languages: List[str]
    source_count: int


@dataclass
class RunData:
    run_id: str
    run_dir: Path
    chapter_title: str
    chapter_spec: str
    topic_summary_en: str
    topic_summary_de: str
    core_object_terms_en: List[str]
    core_object_terms_de: List[str]
    anchors_en: List[str]
    anchors_de: List[str]
    facets: List[Dict[str, Any]]
    candidates: List[Candidate]


def _now_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _sanitize(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _sanitize(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_sanitize(v) for v in value]
    return value


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(_sanitize(obj), ensure_ascii=False) + "\n")


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if isinstance(obj, dict):
                yield obj


def _clean_space(text: Any) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _normalize_title(text: Any) -> str:
    s = _clean_space(text).casefold()
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _normalize_doi(value: Any) -> Optional[str]:
    if not value:
        return None
    s = str(value).strip()
    s = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:)\s*", "", s, flags=re.IGNORECASE)
    s = s.strip().strip("/").lower()
    if not s:
        return None
    m = re.search(r"10\.[0-9]{4,9}/[^\s]+", s)
    if m:
        return m.group(0).rstrip(".")
    return s if s.startswith("10.") else None


def _first_author_lastname(authors: List[str]) -> str:
    if not authors:
        return ""
    a = _clean_space(authors[0])
    if not a:
        return ""
    parts = re.split(r"\s+", a)
    last = parts[-1] if parts else ""
    last = re.sub(r"[^A-Za-zÀ-ÖØ-öø-ÿ'-]+", "", last)
    return last.casefold()


def _reconstruct_openalex_abstract(inv: Any) -> Optional[str]:
    if not isinstance(inv, dict):
        return None
    pairs: List[Tuple[int, str]] = []
    for term, positions in inv.items():
        if not isinstance(positions, list):
            continue
        for pos in positions:
            try:
                pairs.append((int(pos), str(term)))
            except Exception:
                continue
    if not pairs:
        return None
    pairs.sort(key=lambda item: item[0])
    words: List[str] = []
    seen_positions = set()
    for pos, term in pairs:
        if pos in seen_positions:
            continue
        words.append(term)
        seen_positions.add(pos)
    return _clean_space(" ".join(words)) or None


def _safe_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:
        return None


def _candidate_key(title: str, year: Optional[int], authors: List[str], doi: Optional[str]) -> str:
    if doi:
        return f"doi:{doi}"
    return f"title:{_normalize_title(title)}|year:{year or ''}|author:{_first_author_lastname(authors)}"


def _stable_hash(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:24]


def _text_hash(text: str) -> str:
    return _stable_hash(_clean_space(text))


def _parse_chapter_prompt(path: Path) -> Tuple[str, str]:
    text = path.read_text(encoding="utf-8")
    title_match = re.search(r"CHAPTER_TITLE:\s*(.*?)\n\s*CHAPTER_SPEC", text, flags=re.DOTALL)
    spec_match = re.search(r"CHAPTER_SPEC \(retrieval contract\):\s*(.*?)\n\s*TASK:", text, flags=re.DOTALL)
    title = _clean_space(title_match.group(1) if title_match else "")
    spec = _clean_space(spec_match.group(1) if spec_match else "")
    if not title or not spec:
        raise ValueError(f"Could not parse chapter prompt from {path}")
    return title, spec


def _load_env_fallback() -> None:
    _load_env()
    if os.environ.get("OPENAI_API_KEY"):
        return
    for env_path in [REPO_ROOT / ".env", REPO_ROOT / "fastapi" / ".env"]:
        if not env_path.exists():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


def _extract_openalex_candidate(obj: Dict[str, Any]) -> Tuple[Candidate, str]:
    work = obj.get("work") or {}
    authors = [
        _clean_space((auth.get("author") or {}).get("display_name"))
        for auth in (work.get("authorships") or [])
        if isinstance(auth, dict)
    ]
    authors = [a for a in authors if a]
    title = _clean_space(work.get("display_name"))
    doi = _normalize_doi(work.get("doi") or ((work.get("ids") or {}).get("doi")))
    year = _safe_int(work.get("publication_year"))
    abstract = _reconstruct_openalex_abstract(work.get("abstract_inverted_index"))
    venue = _clean_space((((work.get("primary_location") or {}).get("source") or {}).get("display_name")))
    candidate = Candidate(
        id=f"openalex:{_clean_space(work.get('id') or title or doi or obj.get('query_hash') or '')}",
        title=title,
        abstract=abstract,
        year=year,
        venue=venue or None,
        authors=authors[:12],
        doi=doi,
        citations=int(work.get("cited_by_count") or 0),
        influential_citations=0,
        providers=["openalex"],
        intents=[str(obj.get("intent") or "").strip()] if obj.get("intent") else [],
        languages=[str(obj.get("language") or "").strip()] if obj.get("language") else [],
        source_count=1,
    )
    return candidate, _candidate_key(title, year, authors, doi)


def _extract_s2_candidate(obj: Dict[str, Any]) -> Tuple[Candidate, str]:
    paper = obj.get("paper") or {}
    authors = [
        _clean_space(auth.get("name"))
        for auth in (paper.get("authors") or [])
        if isinstance(auth, dict)
    ]
    authors = [a for a in authors if a]
    external_ids = paper.get("externalIds") or {}
    doi = _normalize_doi(external_ids.get("DOI"))
    title = _clean_space(paper.get("title"))
    year = _safe_int(paper.get("year"))
    abstract = _clean_space(paper.get("abstract")) or None
    candidate = Candidate(
        id=f"s2:{_clean_space(paper.get('paperId') or title or doi or obj.get('query_hash') or '')}",
        title=title,
        abstract=abstract,
        year=year,
        venue=_clean_space(paper.get("venue")) or None,
        authors=authors[:12],
        doi=doi,
        citations=int(paper.get("citationCount") or 0),
        influential_citations=int(paper.get("influentialCitationCount") or 0),
        providers=["semanticscholar"],
        intents=[str(obj.get("intent") or "").strip()] if obj.get("intent") else [],
        languages=[str(obj.get("language") or "").strip()] if obj.get("language") else [],
        source_count=1,
    )
    return candidate, _candidate_key(title, year, authors, doi)


def _pick_better_candidate(existing: Candidate, new: Candidate) -> Candidate:
    existing_score = (
        1 if existing.abstract else 0,
        len(existing.abstract or ""),
        existing.influential_citations,
        existing.citations,
        1 if "semanticscholar" in existing.providers else 0,
    )
    new_score = (
        1 if new.abstract else 0,
        len(new.abstract or ""),
        new.influential_citations,
        new.citations,
        1 if "semanticscholar" in new.providers else 0,
    )
    if new_score > existing_score:
        keep = new
        other = existing
    else:
        keep = existing
        other = new

    merged_providers = sorted(set(keep.providers + other.providers))
    merged_intents = sorted(set([x for x in keep.intents + other.intents if x]))
    merged_languages = sorted(set([x for x in keep.languages + other.languages if x]))
    keep.providers = merged_providers
    keep.intents = merged_intents
    keep.languages = merged_languages
    keep.source_count = int(existing.source_count or 0) + int(new.source_count or 0)
    keep.citations = max(int(existing.citations or 0), int(new.citations or 0))
    keep.influential_citations = max(int(existing.influential_citations or 0), int(new.influential_citations or 0))
    if not keep.venue:
        keep.venue = other.venue
    if not keep.doi:
        keep.doi = other.doi
    if len(keep.authors) < len(other.authors):
        keep.authors = other.authors
    return keep


def _build_topic_doc(run: RunData) -> str:
    return "\n".join(
        [
            f"Chapter title: {run.chapter_title}",
            f"Chapter spec: {run.chapter_spec}",
            f"Topic summary (EN): {run.topic_summary_en}",
            f"Topic summary (DE): {run.topic_summary_de}",
        ]
    )


def _build_summary_doc(run: RunData) -> str:
    parts = [
        run.chapter_title,
        run.topic_summary_en,
        run.topic_summary_de,
        "Core object terms EN: " + ", ".join(run.core_object_terms_en[:10]),
        "Core object terms DE: " + ", ".join(run.core_object_terms_de[:10]),
        "Primary anchors EN: " + ", ".join(run.anchors_en[:8]),
        "Primary anchors DE: " + ", ".join(run.anchors_de[:8]),
    ]
    return "\n".join([p for p in parts if _clean_space(p)])


def _build_facet_texts(run: RunData) -> Tuple[List[str], List[int], List[str]]:
    texts: List[str] = []
    weights: List[int] = []
    facet_ids: List[str] = []
    for facet in run.facets:
        fid = str(facet.get("facet_id") or "")
        text_en = _clean_space(facet.get("text_en"))
        text_de = _clean_space(facet.get("text_de"))
        terms = facet.get("canonical_terms") or {}
        terms_en = ", ".join([_clean_space(x) for x in (terms.get("en") or []) if _clean_space(x)])
        terms_de = ", ".join([_clean_space(x) for x in (terms.get("de") or []) if _clean_space(x)])
        body = "\n".join(
            [
                f"Facet label EN: {_clean_space(facet.get('facet_label_en'))}",
                f"Facet label DE: {_clean_space(facet.get('facet_label_de'))}",
                f"Facet text EN: {text_en}",
                f"Facet text DE: {text_de}",
                f"Canonical EN: {terms_en}",
                f"Canonical DE: {terms_de}",
            ]
        )
        texts.append(body)
        weights.append(int(facet.get("importance_weight") or 1))
        facet_ids.append(fid)
    return texts, weights, facet_ids


def load_run_data(run_id: str) -> RunData:
    run_dir = RUNS_DIR / run_id
    plan = _read_json(run_dir / "query_plan.json")
    chapter_title, chapter_spec = _parse_chapter_prompt(run_dir / "query_plan_attempt1.user_prompt.txt")

    dedup: Dict[str, Candidate] = {}
    for row in _iter_jsonl(run_dir / "openalex_raw.jsonl"):
        cand, key = _extract_openalex_candidate(row)
        if not cand.title:
            continue
        dedup[key] = _pick_better_candidate(dedup[key], cand) if key in dedup else cand
    for row in _iter_jsonl(run_dir / "semanticscholar_raw.jsonl"):
        cand, key = _extract_s2_candidate(row)
        if not cand.title:
            continue
        dedup[key] = _pick_better_candidate(dedup[key], cand) if key in dedup else cand

    candidates = sorted(
        dedup.values(),
        key=lambda c: (
            -(1 if c.abstract else 0),
            -(int(c.influential_citations or 0)),
            -(int(c.citations or 0)),
            _normalize_title(c.title),
        ),
    )

    return RunData(
        run_id=run_id,
        run_dir=run_dir,
        chapter_title=chapter_title,
        chapter_spec=chapter_spec,
        topic_summary_en=_clean_space(plan.get("topic_summary_en")),
        topic_summary_de=_clean_space(plan.get("topic_summary_de")),
        core_object_terms_en=[_clean_space(x) for x in ((plan.get("core_object_terms") or {}).get("en") or []) if _clean_space(x)],
        core_object_terms_de=[_clean_space(x) for x in ((plan.get("core_object_terms") or {}).get("de") or []) if _clean_space(x)],
        anchors_en=[_clean_space(x) for x in ((plan.get("primary_context_anchors") or {}).get("en") or []) if _clean_space(x)],
        anchors_de=[_clean_space(x) for x in ((plan.get("primary_context_anchors") or {}).get("de") or []) if _clean_space(x)],
        facets=list(plan.get("facets") or []),
        candidates=candidates,
    )


def candidate_meta_text(c: Candidate) -> str:
    parts = [
        f"Title: {c.title}",
        f"Year: {c.year or ''}",
        f"Venue: {c.venue or ''}",
        f"Authors: {', '.join(c.authors[:8])}",
    ]
    return "\n".join([p for p in parts if _clean_space(p)])


def candidate_doc_text(c: Candidate, *, abstract_chars: int = DOC_ABSTRACT_CHARS) -> str:
    parts = [candidate_meta_text(c)]
    if c.abstract:
        parts.append(f"Abstract: {_clean_space(c.abstract)[:abstract_chars]}")
    return "\n".join([p for p in parts if _clean_space(p)])


def chunk_abstract(text: str, *, target_min: int = CHUNK_TARGET_MIN, target_max: int = CHUNK_TARGET_MAX) -> List[str]:
    body = _clean_space(text)[:CHUNK_ABSTRACT_CHARS]
    if not body:
        return []
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body) if s.strip()]
    if not sentences:
        return [body[:target_max]]
    chunks: List[str] = []
    idx = 0
    while idx < len(sentences):
        cur = sentences[idx]
        j = idx + 1
        while j < len(sentences) and len(cur) + 1 + len(sentences[j]) <= target_max:
            cur = f"{cur} {sentences[j]}".strip()
            j += 1
        if len(cur) < target_min and j < len(sentences):
            nxt = sentences[j]
            if len(cur) + 1 + len(nxt) <= target_max:
                cur = f"{cur} {nxt}".strip()
                j += 1
        chunks.append(cur[:target_max])
        idx = max(j - 1, idx + 1)
    deduped: List[str] = []
    for chunk in chunks:
        if not deduped or chunk != deduped[-1]:
            deduped.append(chunk)
    return deduped


class EmbeddingCache:
    def __init__(
        self,
        *,
        client: OpenAI,
        encoder: Any,
        cache_dir: Path,
        usage_log_path: Path,
        session_id: str,
    ) -> None:
        self.client = client
        self.encoder = encoder
        self.cache_dir = cache_dir
        self.usage_log_path = usage_log_path
        self.session_id = session_id
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.usage: Dict[str, Dict[str, float]] = {}

    def _path(self, model: str, text_hash: str) -> Path:
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", model)
        return self.cache_dir / safe_model / f"{text_hash}.npy"

    def estimate_tokens(self, texts: Iterable[str]) -> int:
        return sum(len(self.encoder.encode(_clean_space(text))) for text in texts)

    def embed_texts(
        self,
        *,
        model: str,
        texts: List[str],
        kind: str,
        batch_size: Optional[int] = None,
    ) -> np.ndarray:
        out: List[Optional[np.ndarray]] = [None] * len(texts)
        to_fetch: List[Tuple[int, str, str]] = []
        for idx, text in enumerate(texts):
            text_hash = _text_hash(text)
            path = self._path(model, text_hash)
            if path.exists():
                out[idx] = np.load(path)
                continue
            to_fetch.append((idx, text_hash, text))

        if batch_size is None:
            batch_size = 32 if model == LARGE_MODEL else 128

        total_batches = int(math.ceil(len(to_fetch) / float(max(batch_size, 1)))) if to_fetch else 0
        for start in range(0, len(to_fetch), batch_size):
            batch = to_fetch[start : start + batch_size]
            inputs = [_clean_space(item[2]) for item in batch]
            batch_no = (start // batch_size) + 1
            print(f"[embed] {kind} | {model} | batch {batch_no}/{total_batches} | items={len(batch)}")
            resp = None
            backoff = 2.0
            last_exc: Optional[Exception] = None
            for attempt in range(1, 7):
                try:
                    resp = self.client.embeddings.create(model=model, input=inputs)
                    break
                except Exception as exc:
                    last_exc = exc
                    if attempt >= 6:
                        raise
                    print(f"[embed] retry {attempt} failed for {kind} / {model}: {exc!r}")
                    time.sleep(min(backoff, 45.0))
                    backoff *= 2.0
            if resp is None:
                raise RuntimeError(f"Embedding request failed for {kind} / {model}: {last_exc!r}")
            prompt_tokens = int(getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0)
            stats = self.usage.setdefault(model, {"prompt_tokens": 0.0, "cost_usd": 0.0, "api_calls": 0.0})
            stats["prompt_tokens"] += prompt_tokens
            stats["api_calls"] += 1
            price = MODEL_PRICES_USD_PER_1M.get(model)
            if price is not None:
                stats["cost_usd"] += (prompt_tokens / 1_000_000.0) * price
            _append_jsonl(
                self.usage_log_path,
                {
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                    "session_id": self.session_id,
                    "model": model,
                    "kind": kind,
                    "items": len(batch),
                    "prompt_tokens": prompt_tokens,
                    "cost_usd": None if price is None else round((prompt_tokens / 1_000_000.0) * price, 8),
                },
            )
            for item, row in zip(batch, getattr(resp, "data", []) or []):
                idx, text_hash, _ = item
                vec = np.array(getattr(row, "embedding"), dtype=np.float32)
                path = self._path(model, text_hash)
                path.parent.mkdir(parents=True, exist_ok=True)
                np.save(path, vec)
                out[idx] = vec

        missing = [i for i, vec in enumerate(out) if vec is None]
        if missing:
            raise RuntimeError(f"Missing embeddings for {len(missing)} items ({kind}, {model})")
        matrix = np.vstack([vec for vec in out if vec is not None]).astype(np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        return matrix / norms


def _cosine_scores(query_vec: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    q = query_vec / (np.linalg.norm(query_vec) or 1.0)
    return matrix @ q


def _weighted_facet_scores(facet_matrix: np.ndarray, candidate_matrix: np.ndarray, weights: List[int]) -> np.ndarray:
    sims = candidate_matrix @ facet_matrix.T
    w = np.asarray(weights, dtype=np.float32)
    weighted = sims * w[None, :]
    top = weighted.max(axis=1) / max(float(w.max()), 1.0)
    top_m = np.mean(np.sort(weighted, axis=1)[:, -min(3, len(weights)) :], axis=1) / max(float(np.mean(w)), 1.0)
    coverage = np.sum(np.clip(sims - 0.30, a_min=0.0, a_max=None) * w[None, :], axis=1) / max(float(np.sum(w)), 1.0)
    return (0.45 * top) + (0.35 * top_m) + (0.20 * coverage)


def _mean_pairwise_similarity(matrix: np.ndarray, idxs: List[int]) -> Optional[float]:
    if len(idxs) < 2:
        return None
    sub = matrix[idxs]
    sim = sub @ sub.T
    tri = sim[np.triu_indices_from(sim, k=1)]
    if tri.size == 0:
        return None
    return float(np.mean(tri))


def _any_term_in_text(text: str, terms: Iterable[str]) -> bool:
    hay = _normalize_title(text)
    if not hay:
        return False
    for term in terms:
        needle = _normalize_title(term)
        if needle and needle in hay:
            return True
    return False


def _sort_scores(scores: np.ndarray) -> List[int]:
    return list(np.argsort(-scores))


def _mmr_select(
    *,
    scores: np.ndarray,
    vectors: np.ndarray,
    candidate_order: List[int],
    top_k: int,
    lambda_mult: float = MMR_LAMBDA,
) -> List[int]:
    selected: List[int] = []
    pool = candidate_order[: max(top_k * 6, top_k)]
    while pool and len(selected) < top_k:
        best_idx = None
        best_val = None
        for idx in pool:
            rel = float(scores[idx])
            div = 0.0
            if selected:
                div = float(np.max(vectors[idx] @ vectors[selected].T))
            mmr = lambda_mult * rel - (1.0 - lambda_mult) * div
            if best_val is None or mmr > best_val:
                best_val = mmr
                best_idx = idx
        assert best_idx is not None
        selected.append(best_idx)
        pool = [idx for idx in pool if idx != best_idx]
    return selected


def _unique_text_cost_stats(
    *,
    texts: List[str],
    cache_hashes: set[str],
    encoder: Any,
    price_per_1m: float,
) -> Dict[str, Any]:
    seen: set[str] = set()
    cached = 0
    missing = 0
    cached_tokens = 0
    missing_tokens = 0
    for text in texts:
        text_hash = _text_hash(text)
        if text_hash in seen:
            continue
        seen.add(text_hash)
        tok = len(encoder.encode(_clean_space(text)))
        if text_hash in cache_hashes:
            cached += 1
            cached_tokens += tok
        else:
            missing += 1
            missing_tokens += tok
    return {
        "unique_texts": len(seen),
        "cached_items": cached,
        "missing_items": missing,
        "cached_tokens": cached_tokens,
        "missing_tokens": missing_tokens,
        "cached_cost_usd": (cached_tokens / 1_000_000.0) * price_per_1m,
        "missing_cost_usd": (missing_tokens / 1_000_000.0) * price_per_1m,
    }


def _top_rows(run: RunData, indices: List[int], scores: np.ndarray, limit: int = 20) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rank, idx in enumerate(indices[:limit], start=1):
        cand = run.candidates[idx]
        rows.append(
            {
                "rank": rank,
                "id": cand.id,
                "title": cand.title,
                "year": cand.year,
                "venue": cand.venue,
                "providers": cand.providers,
                "intents": cand.intents,
                "languages": cand.languages,
                "citations": cand.citations,
                "influential_citations": cand.influential_citations,
                "score": round(float(scores[idx]), 6),
                "abstract": _clean_space(cand.abstract or "")[:1200],
            }
        )
    return rows


def _variant_metrics(
    *,
    run: RunData,
    top_indices: List[int],
    scores: np.ndarray,
    doc_vectors: np.ndarray,
) -> Dict[str, Any]:
    top20 = top_indices[:20]
    top10 = top_indices[:10]
    title_hits = sum(1 for idx in top20 if _any_term_in_text(run.candidates[idx].title, run.core_object_terms_en + run.core_object_terms_de))
    abstract_hits = sum(
        1
        for idx in top20
        if _any_term_in_text((run.candidates[idx].abstract or ""), run.core_object_terms_en + run.core_object_terms_de)
    )
    with_abstract = sum(1 for idx in top20 if run.candidates[idx].abstract)
    provider_mix = sorted({provider for idx in top20 for provider in run.candidates[idx].providers})
    years = [run.candidates[idx].year for idx in top20 if run.candidates[idx].year]
    mean_score = float(np.mean([scores[idx] for idx in top20])) if top20 else None
    return {
        "top20_count": len(top20),
        "top20_score_mean": None if mean_score is None else round(mean_score, 6),
        "top20_with_abstract": with_abstract,
        "top20_title_core_hit_rate": round(title_hits / max(1, len(top20)), 4),
        "top20_abstract_core_hit_rate": round(abstract_hits / max(1, len(top20)), 4),
        "top20_provider_mix": provider_mix,
        "top20_year_min": min(years) if years else None,
        "top20_year_max": max(years) if years else None,
        "top20_year_median": statistics.median(years) if years else None,
        "top20_mean_pairwise_similarity": _mean_pairwise_similarity(doc_vectors, top20),
        "top10_mean_pairwise_similarity": _mean_pairwise_similarity(doc_vectors, top10),
    }


def _write_top_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "rank",
        "id",
        "score",
        "year",
        "citations",
        "influential_citations",
        "providers",
        "intents",
        "languages",
        "title",
        "venue",
        "abstract",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["providers"] = ", ".join(out.get("providers") or [])
            out["intents"] = ", ".join(out.get("intents") or [])
            out["languages"] = ", ".join(out.get("languages") or [])
            writer.writerow(out)


def _write_summary_md(
    *,
    path: Path,
    run_summaries: Dict[str, Dict[str, Any]],
    usage: Dict[str, Dict[str, float]],
    estimated_cost: Dict[str, Any],
) -> None:
    lines: List[str] = []
    lines.append("# Phase F Embedding Probe Summary")
    lines.append("")
    lines.append("## Cost")
    lines.append("")
    lines.append(f"- Estimated cached cost: `${estimated_cost['estimated_cached_cost_usd']:.4f}`")
    lines.append(f"- Estimated missing cost before this run: `${estimated_cost['estimated_missing_cost_usd']:.4f}`")
    lines.append(f"- Estimated total cost: `${estimated_cost['estimated_total_cost_usd']:.4f}`")
    lines.append(f"- Actual total cost: `${estimated_cost['actual_total_cost_usd']:.4f}`")
    for model, stats in usage.items():
        lines.append(
            f"- `{model}`: prompt_tokens={int(stats.get('prompt_tokens', 0))}, api_calls={int(stats.get('api_calls', 0))}, cost=`${stats.get('cost_usd', 0.0):.4f}`"
        )
    for run_id, payload in run_summaries.items():
        lines.append("")
        lines.append(f"## Run `{run_id}`")
        lines.append("")
        lines.append(f"- Chapter: {payload['chapter_title']}")
        lines.append(f"- Candidates: {payload['candidate_count']}")
        lines.append("")
        for variant_name, variant in payload["variants"].items():
            lines.append(f"### {variant_name}")
            lines.append("")
            metrics = variant["metrics"]
            lines.append(
                f"- mean_score={metrics.get('top20_score_mean')} | title_core_hit_rate={metrics.get('top20_title_core_hit_rate')} | abstract_core_hit_rate={metrics.get('top20_abstract_core_hit_rate')} | top20_pairwise={metrics.get('top20_mean_pairwise_similarity')}"
            )
            for row in variant["top20"]:
                title = row["title"]
                abstract = _clean_space(row["abstract"])[:260]
                lines.append(f"- {row['rank']:02d}. {title} ({row.get('year') or 'n.d.'}) :: {abstract}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_probe(
    *,
    runs: List[RunData],
    budget_usd: float,
    dry_run: bool,
) -> Dict[str, Any]:
    _load_env_fallback()
    api_key = (
        os.environ.get("OPENAI_API_KEY")
    )
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing.")

    encoder = tiktoken.get_encoding("cl100k_base")
    client = OpenAI(api_key=api_key, timeout=180.0, max_retries=5)
    session_id = _now_slug()
    cache = EmbeddingCache(
        client=client,
        encoder=encoder,
        cache_dir=CACHE_DIR,
        usage_log_path=USAGE_LOG_PATH,
        session_id=session_id,
    )

    small_cache_hashes = {p.stem for p in (CACHE_DIR / SMALL_MODEL).glob("*.npy")}
    large_cache_hashes = {p.stem for p in (CACHE_DIR / LARGE_MODEL).glob("*.npy")}

    prepared: Dict[str, Dict[str, Any]] = {}
    estimated_costs: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        facet_texts, facet_weights, facet_ids = _build_facet_texts(run)
        topic_doc = _build_topic_doc(run)
        summary_doc = _build_summary_doc(run)
        meta_texts = [candidate_meta_text(c) for c in run.candidates]
        doc_texts = [candidate_doc_text(c) for c in run.candidates]
        prepared[run.run_id] = {
            "facet_texts": facet_texts,
            "facet_weights": facet_weights,
            "facet_ids": facet_ids,
            "topic_doc": topic_doc,
            "summary_doc": summary_doc,
            "meta_texts": meta_texts,
            "doc_texts": doc_texts,
        }
    estimated_costs[SMALL_MODEL] = _unique_text_cost_stats(
        texts=[
            text
            for run_id in prepared
            for text in (
                prepared[run_id]["meta_texts"]
                + prepared[run_id]["doc_texts"]
                + [prepared[run_id]["topic_doc"], prepared[run_id]["summary_doc"]]
                + prepared[run_id]["facet_texts"]
            )
        ],
        cache_hashes=small_cache_hashes,
        encoder=encoder,
        price_per_1m=MODEL_PRICES_USD_PER_1M[SMALL_MODEL],
    )
    estimated_costs[LARGE_MODEL] = _unique_text_cost_stats(
        texts=[
            text
            for run_id in prepared
            for text in (
                prepared[run_id]["doc_texts"]
                + [prepared[run_id]["topic_doc"]]
                + prepared[run_id]["facet_texts"]
            )
        ],
        cache_hashes=large_cache_hashes,
        encoder=encoder,
        price_per_1m=MODEL_PRICES_USD_PER_1M[LARGE_MODEL],
    )
    estimated_missing_cost = sum(v["missing_cost_usd"] for v in estimated_costs.values())
    estimated_cached_cost = sum(v["cached_cost_usd"] for v in estimated_costs.values())
    estimated_total_cost = estimated_cached_cost + estimated_missing_cost
    if estimated_total_cost > budget_usd:
        raise RuntimeError(
            f"Estimated embedding cost ${estimated_total_cost:.4f} exceeds budget ${budget_usd:.2f}. Lower DOC_ABSTRACT_CHARS first."
        )
    if dry_run:
        return {
            "dry_run": True,
            "session_id": session_id,
            "estimated_costs": estimated_costs,
            "estimated_cached_cost_usd": round(estimated_cached_cost, 6),
            "estimated_missing_cost_usd": round(estimated_missing_cost, 6),
            "estimated_total_cost_usd": round(estimated_total_cost, 6),
        }

    run_summaries: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        info = prepared[run.run_id]
        doc_small = cache.embed_texts(model=SMALL_MODEL, texts=info["doc_texts"], kind=f"{run.run_id}:doc_small")
        doc_large = cache.embed_texts(model=LARGE_MODEL, texts=info["doc_texts"], kind=f"{run.run_id}:doc_large")
        meta_small = cache.embed_texts(model=SMALL_MODEL, texts=info["meta_texts"], kind=f"{run.run_id}:meta_small")
        topic_small = cache.embed_texts(model=SMALL_MODEL, texts=[info["topic_doc"]], kind=f"{run.run_id}:topic_small")[0]
        topic_large = cache.embed_texts(model=LARGE_MODEL, texts=[info["topic_doc"]], kind=f"{run.run_id}:topic_large")[0]
        summary_small = cache.embed_texts(model=SMALL_MODEL, texts=[info["summary_doc"]], kind=f"{run.run_id}:summary_small")[0]
        facet_small = cache.embed_texts(model=SMALL_MODEL, texts=info["facet_texts"], kind=f"{run.run_id}:facet_small")
        facet_large = cache.embed_texts(model=LARGE_MODEL, texts=info["facet_texts"], kind=f"{run.run_id}:facet_large")

        facet_doc_small = _weighted_facet_scores(facet_small, doc_small, info["facet_weights"])
        facet_doc_large = _weighted_facet_scores(facet_large, doc_large, info["facet_weights"])
        facet_meta_small = _weighted_facet_scores(facet_small, meta_small, info["facet_weights"])
        topic_doc_small = _cosine_scores(topic_small, doc_small)
        topic_doc_large = _cosine_scores(topic_large, doc_large)
        summary_doc_small = _cosine_scores(summary_small, doc_small)
        hybrid_small = (0.60 * facet_doc_small) + (0.40 * topic_doc_small)
        hybrid_large = (0.60 * facet_doc_large) + (0.40 * topic_doc_large)

        chunk_base_scores = hybrid_small.copy()
        shortlist = _sort_scores(hybrid_small)[:STAGED_SHORTLIST]
        chunk_texts: List[str] = []
        chunk_owner: List[int] = []
        for idx in shortlist:
            cand = run.candidates[idx]
            if not cand.abstract:
                continue
            for chunk in chunk_abstract(cand.abstract):
                chunk_texts.append(f"Title: {cand.title}\nAbstract chunk: {chunk}")
                chunk_owner.append(idx)
        staged_small = hybrid_small.copy()
        if chunk_texts:
            chunk_small = cache.embed_texts(model=SMALL_MODEL, texts=chunk_texts, kind=f"{run.run_id}:chunk_small")
            chunk_scores = _cosine_scores(topic_small, chunk_small)
            best_chunk_by_idx: Dict[int, float] = {}
            for idx, score in zip(chunk_owner, chunk_scores):
                best_chunk_by_idx[idx] = max(best_chunk_by_idx.get(idx, -1.0), float(score))
            for idx, best_chunk in best_chunk_by_idx.items():
                staged_small[idx] = (0.55 * hybrid_small[idx]) + (0.45 * best_chunk)

        variants = {
            "topic_doc_small": topic_doc_small,
            "topic_doc_large": topic_doc_large,
            "summary_doc_small": summary_doc_small,
            "facet_meta_small": facet_meta_small,
            "facet_doc_small": facet_doc_small,
            "facet_doc_large": facet_doc_large,
            "hybrid_small": hybrid_small,
            "hybrid_large": hybrid_large,
            "staged_small": staged_small,
        }

        variant_payload: Dict[str, Any] = {}
        for name, scores in variants.items():
            order = _sort_scores(scores)
            if name == "staged_small":
                order = _mmr_select(scores=scores, vectors=doc_small, candidate_order=order, top_k=20) + order[20:]
            top20 = _top_rows(run, order, scores, limit=20)
            variant_payload[name] = {
                "metrics": _variant_metrics(run=run, top_indices=order, scores=scores, doc_vectors=doc_small if "large" not in name else doc_large),
                "top20": top20,
            }
            csv_path = OUTPUT_DIR / f"phase_f_top20_{run.run_id}_{name}.csv"
            _write_top_csv(csv_path, top20)

        run_summaries[run.run_id] = {
            "chapter_title": run.chapter_title,
            "candidate_count": len(run.candidates),
            "variants": variant_payload,
        }

    actual_total_cost = sum(float(stats.get("cost_usd") or 0.0) for stats in cache.usage.values())
    return {
        "dry_run": False,
        "session_id": session_id,
        "estimated_costs": estimated_costs,
        "estimated_cached_cost_usd": round(estimated_cached_cost, 6),
        "estimated_missing_cost_usd": round(estimated_missing_cost, 6),
        "estimated_total_cost_usd": round(estimated_total_cost, 6),
        "actual_total_cost_usd": round(actual_total_cost, 6),
        "usage": cache.usage,
        "runs": run_summaries,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Phase F embedding probe across cached runs.")
    parser.add_argument(
        "--runs",
        nargs="+",
        default=["ca79147de41f8edbfb47c9e5", "ed2e3d3304d5ed9587592f4d"],
        help="Run IDs to analyze.",
    )
    parser.add_argument("--budget-usd", type=float, default=DEFAULT_BUDGET_USD)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    runs = [load_run_data(run_id) for run_id in args.runs]
    result = run_probe(runs=runs, budget_usd=float(args.budget_usd), dry_run=bool(args.dry_run))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _now_slug()
    base = OUTPUT_DIR / f"phase_f_embedding_probe_{slug}"
    json_path = base.with_suffix(".json")
    json_path.write_text(json.dumps(_sanitize(result), indent=2, ensure_ascii=False), encoding="utf-8")
    if not result.get("dry_run"):
        md_path = base.with_suffix(".summary.md")
        _write_summary_md(
            path=md_path,
            run_summaries=result["runs"],
            usage=result["usage"],
            estimated_cost=result,
        )
        print(f"Wrote {json_path}")
        print(f"Wrote {md_path}")
    else:
        print(f"Wrote {json_path}")


if __name__ == "__main__":
    import os

    main()
