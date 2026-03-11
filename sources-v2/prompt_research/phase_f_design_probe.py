from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import tiktoken
from openai import OpenAI

import phase_f_embedding_probe as base


OUTPUT_DIR = base.OUTPUT_DIR
CACHE_DIR = base.CACHE_DIR
USAGE_LOG_PATH = OUTPUT_DIR / "phase_f_design_probe_usage.jsonl"
SMALL_MODEL = base.SMALL_MODEL
HYDE_MODEL = "gpt-5-mini"
HYDE_PRICES_USD_PER_1M = {"input": 0.25, "output": 2.0}
DEFAULT_BUDGET_USD = 2.0
JUNK_TITLES = {
    "index",
    "references",
    "table of contents",
    "editorial",
    "book reviews",
    "book review",
    "bibliography",
}


def _now_slug() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _clean_title(text: str) -> str:
    s = html.unescape(str(text or ""))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _norm_title(text: str) -> str:
    s = _clean_title(text).casefold()
    s = re.sub(r"[^\w\s]+", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(base._sanitize(obj), ensure_ascii=False) + "\n")


def candidate_doc_text_variant(c: base.Candidate, *, abstract_chars: int, include_meta: bool) -> str:
    title = _clean_title(c.title)
    if include_meta:
        parts = [
            f"Title: {title}",
            f"Year: {c.year or ''}",
            f"Venue: {c.venue or ''}",
            f"Authors: {', '.join(c.authors[:8])}",
        ]
    else:
        parts = [f"Title: {title}"]
    if c.abstract:
        parts.append(f"Abstract: {base._clean_space(c.abstract)[:abstract_chars]}")
    return "\n".join([p for p in parts if base._clean_space(p)])


def build_target_doc(run: base.RunData) -> str:
    plan = json.loads((run.run_dir / "query_plan.json").read_text(encoding="utf-8"))
    must_keep = ", ".join([base._clean_space(x) for x in (plan.get("must_keep_constraints") or [])[:8] if base._clean_space(x)])
    drift = ", ".join([base._clean_space(x) for x in (plan.get("drift_risks") or [])[:6] if base._clean_space(x)])
    parts = [
        f"Chapter title: {run.chapter_title}",
        f"Chapter spec: {run.chapter_spec}",
        f"Topic summary EN: {run.topic_summary_en}",
        f"Topic summary DE: {run.topic_summary_de}",
        "Core object terms EN: " + ", ".join(run.core_object_terms_en[:10]),
        "Core object terms DE: " + ", ".join(run.core_object_terms_de[:10]),
        "Primary anchors EN: " + ", ".join(run.anchors_en[:8]),
        "Primary anchors DE: " + ", ".join(run.anchors_de[:8]),
        f"Must keep: {must_keep}",
        f"Drift risks: {drift}",
    ]
    return "\n".join([p for p in parts if base._clean_space(p)])


def hyde_prompt(run: base.RunData) -> str:
    return "\n".join(
        [
            "Write a hypothetical abstract of a strong, highly relevant academic paper for the chapter below.",
            "Keep it faithful to the chapter object, scope, and constraints.",
            "Do not invent datasets or claims that contradict the chapter.",
            "Make the abstract retrieval-oriented: object-led, concrete, and terminology-rich.",
            "Length: 180-260 words.",
            "",
            f"Chapter title: {run.chapter_title}",
            f"Chapter spec: {run.chapter_spec}",
            f"Topic summary EN: {run.topic_summary_en}",
            "Core object terms EN: " + ", ".join(run.core_object_terms_en[:10]),
            "Primary anchors EN: " + ", ".join(run.anchors_en[:8]),
        ]
    )


def generate_hyde_docs(*, client: OpenAI, runs: List[base.RunData], session_id: str) -> Tuple[Dict[str, str], Dict[str, Any]]:
    docs: Dict[str, str] = {}
    usage = {"input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "api_calls": 0}
    for run in runs:
        resp = client.chat.completions.create(
            model=HYDE_MODEL,
            messages=[
                {"role": "system", "content": "You write hypothetical relevant-paper abstracts for retrieval experiments."},
                {"role": "user", "content": hyde_prompt(run)},
            ],
        )
        text = ""
        for choice in (resp.choices or []):
            msg = getattr(choice, "message", None)
            if msg is not None:
                text = str(getattr(msg, "content", "") or "")
                if text:
                    break
        text = base._clean_space(text)
        if not text:
            raise RuntimeError(f"HyDE generation returned empty text for run {run.run_id}")
        docs[run.run_id] = text
        in_tok = int(getattr(getattr(resp, "usage", None), "prompt_tokens", 0) or 0)
        out_tok = int(getattr(getattr(resp, "usage", None), "completion_tokens", 0) or 0)
        cost = (in_tok / 1_000_000.0) * HYDE_PRICES_USD_PER_1M["input"] + (out_tok / 1_000_000.0) * HYDE_PRICES_USD_PER_1M["output"]
        usage["input_tokens"] += in_tok
        usage["output_tokens"] += out_tok
        usage["api_calls"] += 1
        usage["cost_usd"] += cost
        _append_jsonl(
            USAGE_LOG_PATH,
            {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "session_id": session_id,
                "kind": "hyde_generation",
                "run_id": run.run_id,
                "model": HYDE_MODEL,
                "input_tokens": in_tok,
                "output_tokens": out_tok,
                "cost_usd": round(cost, 8),
            },
        )
    usage["cost_usd"] = round(float(usage["cost_usd"]), 8)
    return docs, usage


def _sort_scores(scores: np.ndarray) -> List[int]:
    return list(np.argsort(-scores))


def _apply_hygiene(run: base.RunData, order: List[int], *, limit: Optional[int] = None) -> List[int]:
    seen_titles: set[str] = set()
    out: List[int] = []
    for idx in order:
        cand = run.candidates[idx]
        title_norm = _norm_title(cand.title)
        if not title_norm:
            continue
        if title_norm in JUNK_TITLES:
            continue
        if title_norm in seen_titles:
            continue
        seen_titles.add(title_norm)
        out.append(idx)
        if limit is not None and len(out) >= limit:
            break
    return out


def _top_rows(run: base.RunData, indices: List[int], scores: np.ndarray, limit: int = 20) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for rank, idx in enumerate(indices[:limit], start=1):
        cand = run.candidates[idx]
        rows.append(
            {
                "rank": rank,
                "id": cand.id,
                "score": round(float(scores[idx]), 6),
                "year": cand.year,
                "title": _clean_title(cand.title),
                "venue": cand.venue,
                "providers": cand.providers,
                "intents": cand.intents,
                "citations": cand.citations,
                "abstract": base._clean_space(cand.abstract or "")[:1200],
            }
        )
    return rows


def _variant_metrics(run: base.RunData, indices: List[int], scores: np.ndarray, doc_vectors: np.ndarray) -> Dict[str, Any]:
    top20 = indices[:20]
    titles = [_norm_title(run.candidates[idx].title) for idx in top20]
    junk = sum(1 for t in titles if t in JUNK_TITLES)
    dup = len(titles) - len(set(titles))
    title_hits = sum(1 for idx in top20 if base._any_term_in_text(run.candidates[idx].title, run.core_object_terms_en + run.core_object_terms_de))
    abstract_hits = sum(1 for idx in top20 if base._any_term_in_text((run.candidates[idx].abstract or ""), run.core_object_terms_en + run.core_object_terms_de))
    years = [run.candidates[idx].year for idx in top20 if run.candidates[idx].year]
    return {
        "top20_score_mean": round(float(np.mean([scores[idx] for idx in top20])), 6) if top20 else None,
        "top20_title_core_hit_rate": round(title_hits / max(1, len(top20)), 4),
        "top20_abstract_core_hit_rate": round(abstract_hits / max(1, len(top20)), 4),
        "top20_mean_pairwise_similarity": base._mean_pairwise_similarity(doc_vectors, top20),
        "top20_duplicate_titles": dup,
        "top20_junk_titles": junk,
        "top20_year_min": min(years) if years else None,
        "top20_year_max": max(years) if years else None,
        "top20_year_median": statistics.median(years) if years else None,
    }


def _write_top_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = ["rank", "id", "score", "year", "citations", "providers", "intents", "title", "venue", "abstract"]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            out = dict(row)
            out["providers"] = ", ".join(out.get("providers") or [])
            out["intents"] = ", ".join(out.get("intents") or [])
            writer.writerow(out)


def _write_summary_md(path: Path, result: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# Phase F Design Probe Summary")
    lines.append("")
    lines.append("## Cost")
    lines.append("")
    lines.append(f"- Estimated additional embedding cost before run: `${result['estimated_additional_embedding_cost_usd']:.4f}`")
    lines.append(f"- HyDE generation cost: `${result['hyde_usage']['cost_usd']:.4f}`")
    lines.append(f"- Actual embedding cost in this run: `${result['embedding_usage_cost_usd']:.4f}`")
    lines.append(f"- Actual total cost in this run: `${result['actual_total_cost_usd']:.4f}`")
    for run_id, payload in result["runs"].items():
        lines.append("")
        lines.append(f"## Run `{run_id}`")
        lines.append("")
        lines.append(f"- Chapter: {payload['chapter_title']}")
        lines.append(f"- Candidates: {payload['candidate_count']}")
        for variant_name, variant in payload["variants"].items():
            m = variant["metrics"]
            lines.append("")
            lines.append(f"### {variant_name}")
            lines.append("")
            lines.append(
                f"- mean_score={m['top20_score_mean']} | title_core={m['top20_title_core_hit_rate']} | abstract_core={m['top20_abstract_core_hit_rate']} | pair20={m['top20_mean_pairwise_similarity']} | dup={m['top20_duplicate_titles']} | junk={m['top20_junk_titles']}"
            )
            for row in variant["top20"][:10]:
                lines.append(f"- {row['rank']:02d}. {row['title']} ({row.get('year') or 'n.d.'})")
    path.write_text("\n".join(lines), encoding="utf-8")


def run_probe(*, runs: List[base.RunData], budget_usd: float, dry_run: bool) -> Dict[str, Any]:
    base._load_env_fallback()
    api_key = base.os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY missing.")

    encoder = tiktoken.get_encoding("cl100k_base")
    session_id = _now_slug()
    client = OpenAI(api_key=api_key, timeout=180.0, max_retries=5)
    embed_cache = base.EmbeddingCache(
        client=client,
        encoder=encoder,
        cache_dir=CACHE_DIR,
        usage_log_path=USAGE_LOG_PATH,
        session_id=session_id,
    )
    hyde_docs, hyde_usage = generate_hyde_docs(client=client, runs=runs, session_id=session_id)

    small_cache_hashes = {p.stem for p in (CACHE_DIR / SMALL_MODEL).glob("*.npy")}
    text_sets: Dict[str, List[str]] = {}
    prepared: Dict[str, Dict[str, Any]] = {}
    for run in runs:
        target_doc = build_target_doc(run)
        summary_doc = base._build_summary_doc(run)
        topic_doc = base._build_topic_doc(run)
        prepared[run.run_id] = {
            "topic_doc": topic_doc,
            "summary_doc": summary_doc,
            "target_doc": target_doc,
            "hyde_doc": hyde_docs[run.run_id],
            "rich_400": [candidate_doc_text_variant(c, abstract_chars=400, include_meta=True) for c in run.candidates],
            "rich_800": [candidate_doc_text_variant(c, abstract_chars=800, include_meta=True) for c in run.candidates],
            "rich_1400": [candidate_doc_text_variant(c, abstract_chars=1400, include_meta=True) for c in run.candidates],
            "core_800": [candidate_doc_text_variant(c, abstract_chars=800, include_meta=False) for c in run.candidates],
        }
        for key in ["rich_400", "rich_800", "rich_1400", "core_800"]:
            text_sets[f"{run.run_id}:{key}"] = prepared[run.run_id][key]
        text_sets[f"{run.run_id}:queries"] = [topic_doc, summary_doc, target_doc, hyde_docs[run.run_id]]

    stats = base._unique_text_cost_stats(
        texts=[text for texts in text_sets.values() for text in texts],
        cache_hashes=small_cache_hashes,
        encoder=encoder,
        price_per_1m=base.MODEL_PRICES_USD_PER_1M[SMALL_MODEL],
    )
    estimated_additional_cost = float(stats["missing_cost_usd"]) + float(hyde_usage["cost_usd"])
    if estimated_additional_cost > budget_usd:
        raise RuntimeError(f"Estimated additional cost ${estimated_additional_cost:.4f} exceeds budget ${budget_usd:.2f}")
    if dry_run:
        return {
            "dry_run": True,
            "session_id": session_id,
            "estimated_embedding_stats": stats,
            "estimated_additional_embedding_cost_usd": round(float(stats["missing_cost_usd"]), 6),
            "hyde_usage": hyde_usage,
            "estimated_additional_cost_usd": round(estimated_additional_cost, 6),
        }

    run_payloads: Dict[str, Any] = {}
    for run in runs:
        info = prepared[run.run_id]
        rich_400 = embed_cache.embed_texts(model=SMALL_MODEL, texts=info["rich_400"], kind=f"{run.run_id}:rich_400")
        rich_800 = embed_cache.embed_texts(model=SMALL_MODEL, texts=info["rich_800"], kind=f"{run.run_id}:rich_800")
        rich_1400 = embed_cache.embed_texts(model=SMALL_MODEL, texts=info["rich_1400"], kind=f"{run.run_id}:rich_1400")
        core_800 = embed_cache.embed_texts(model=SMALL_MODEL, texts=info["core_800"], kind=f"{run.run_id}:core_800")
        q_topic = embed_cache.embed_texts(model=SMALL_MODEL, texts=[info["topic_doc"]], kind=f"{run.run_id}:topic_q")[0]
        q_summary = embed_cache.embed_texts(model=SMALL_MODEL, texts=[info["summary_doc"]], kind=f"{run.run_id}:summary_q")[0]
        q_target = embed_cache.embed_texts(model=SMALL_MODEL, texts=[info["target_doc"]], kind=f"{run.run_id}:target_q")[0]
        q_hyde = embed_cache.embed_texts(model=SMALL_MODEL, texts=[info["hyde_doc"]], kind=f"{run.run_id}:hyde_q")[0]

        s_topic_r800 = base._cosine_scores(q_topic, rich_800)
        s_summary_r800 = base._cosine_scores(q_summary, rich_800)
        s_target_r400 = base._cosine_scores(q_target, rich_400)
        s_target_r800 = base._cosine_scores(q_target, rich_800)
        s_target_r1400 = base._cosine_scores(q_target, rich_1400)
        s_target_core800 = base._cosine_scores(q_target, core_800)
        s_hyde_r800 = base._cosine_scores(q_hyde, rich_800)
        s_hyde_hybrid = (0.65 * s_target_r800) + (0.35 * s_hyde_r800)

        shortlist = _sort_scores(s_target_r800)[: base.STAGED_SHORTLIST]
        chunk_texts: List[str] = []
        chunk_owner: List[int] = []
        for idx in shortlist:
            cand = run.candidates[idx]
            if not cand.abstract:
                continue
            for chunk in base.chunk_abstract(cand.abstract):
                chunk_texts.append(f"Title: {_clean_title(cand.title)}\nAbstract chunk: {chunk}")
                chunk_owner.append(idx)
        staged_target = s_target_r800.copy()
        staged_hyde_hybrid = s_hyde_hybrid.copy()
        if chunk_texts:
            chunk_vecs = embed_cache.embed_texts(model=SMALL_MODEL, texts=chunk_texts, kind=f"{run.run_id}:chunks_design")
            chunk_target_scores = base._cosine_scores(q_target, chunk_vecs)
            chunk_hyde_scores = base._cosine_scores(q_hyde, chunk_vecs)
            best_target: Dict[int, float] = {}
            best_hyde: Dict[int, float] = {}
            for idx, score_t, score_h in zip(chunk_owner, chunk_target_scores, chunk_hyde_scores):
                best_target[idx] = max(best_target.get(idx, -1.0), float(score_t))
                best_hyde[idx] = max(best_hyde.get(idx, -1.0), float(score_h))
            for idx in best_target:
                staged_target[idx] = (0.55 * s_target_r800[idx]) + (0.45 * best_target[idx])
                hyde_chunk = best_hyde.get(idx, best_target[idx])
                staged_hyde_hybrid[idx] = (0.55 * s_hyde_hybrid[idx]) + (0.45 * max(best_target[idx], hyde_chunk))

        variants = {
            "topic_r800": s_topic_r800,
            "summary_r800": s_summary_r800,
            "target_r400": s_target_r400,
            "target_r800": s_target_r800,
            "target_r1400": s_target_r1400,
            "target_core800": s_target_core800,
            "hyde_r800": s_hyde_r800,
            "hyde_hybrid_r800": s_hyde_hybrid,
            "staged_target_r800": staged_target,
            "staged_hyde_hybrid_r800": staged_hyde_hybrid,
        }

        variant_payload: Dict[str, Any] = {}
        for name, scores in variants.items():
            order = _sort_scores(scores)
            hygienic = _apply_hygiene(run, order, limit=20) + [idx for idx in order if idx not in set(_apply_hygiene(run, order, limit=20))]
            if name.startswith("staged_"):
                hygienic_top20 = base._mmr_select(scores=scores, vectors=rich_800, candidate_order=hygienic, top_k=20)
                hygienic = hygienic_top20 + [idx for idx in hygienic if idx not in set(hygienic_top20)]
            top20 = _top_rows(run, hygienic, scores, limit=20)
            variant_payload[name] = {
                "metrics": _variant_metrics(run, hygienic, scores, rich_800),
                "top20": top20,
            }
            _write_top_csv(OUTPUT_DIR / f"phase_f_design_top20_{run.run_id}_{name}.csv", top20)

        run_payloads[run.run_id] = {
            "chapter_title": run.chapter_title,
            "candidate_count": len(run.candidates),
            "hyde_doc": hyde_docs[run.run_id],
            "variants": variant_payload,
        }

    embedding_usage_cost = sum(float(v.get("cost_usd") or 0.0) for v in embed_cache.usage.values())
    result = {
        "dry_run": False,
        "session_id": session_id,
        "estimated_embedding_stats": stats,
        "estimated_additional_embedding_cost_usd": round(float(stats["missing_cost_usd"]), 6),
        "hyde_usage": hyde_usage,
        "embedding_usage_cost_usd": round(embedding_usage_cost, 6),
        "actual_total_cost_usd": round(embedding_usage_cost + float(hyde_usage["cost_usd"]), 6),
        "runs": run_payloads,
    }
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extended Phase F design probe.")
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
    runs = [base.load_run_data(run_id) for run_id in args.runs]
    result = run_probe(runs=runs, budget_usd=float(args.budget_usd), dry_run=bool(args.dry_run))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = _now_slug()
    json_path = OUTPUT_DIR / f"phase_f_design_probe_{slug}.json"
    json_path.write_text(json.dumps(base._sanitize(result), indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {json_path}")
    if not result.get("dry_run"):
        md_path = OUTPUT_DIR / f"phase_f_design_probe_{slug}.summary.md"
        _write_summary_md(md_path, result)
        print(f"Wrote {md_path}")


if __name__ == "__main__":
    main()
