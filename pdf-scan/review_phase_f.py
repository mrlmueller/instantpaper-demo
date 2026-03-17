import argparse
import json
from collections import Counter
from pathlib import Path
import sys

from review_phase_e import match_concepts, normalize_text, snippet

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


GENERIC_TITLES = {
    "introduction",
    "discussion",
    "conclusion",
    "results",
    "method",
    "methods",
    "abstract",
}


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_run(run_dir: Path):
    return {
        "run_dir": run_dir,
        "sections": read_jsonl(run_dir / "normalized" / "sections.jsonl"),
        "passages": read_jsonl(run_dir / "normalized" / "passages.jsonl"),
        "rerank_results": read_jsonl(run_dir / "rerank" / "rerank_results.jsonl"),
        "cross_encoder": read_jsonl(run_dir / "rerank" / "cross_encoder.jsonl"),
        "llm_judge": read_jsonl(run_dir / "rerank" / "llm_judge.jsonl"),
        "phase_f_summary": read_json(run_dir / "rerank" / "phase_f_summary.json"),
        "phase_f_assessment": read_json(run_dir / "rerank" / "phase_f_assessment.json"),
    }


def is_generic_title(title: str) -> bool:
    low = normalize_text(title)
    if low in GENERIC_TITLES:
        return True
    if low.startswith("1. ") and any(low.endswith(value) for value in GENERIC_TITLES):
        return True
    return False


def review_row(row, section_by_id, passage_by_id):
    section = section_by_id.get(row["section_id"], {})
    text = f"{section.get('title', '')}\n{section.get('text', '')}"
    concept_hits = match_concepts(text)
    evidence = []
    for item in row.get("evidence_rows", [])[:3]:
        passage = passage_by_id.get(item.get("passage_id"))
        if not passage:
            continue
        evidence.append(
            {
                "passage_id": item.get("passage_id"),
                "snippet": snippet(passage.get("text", ""), 260),
                "concept_hits": match_concepts(passage.get("text", "")),
            }
        )
    suspicious_reasons = []
    if is_generic_title(row.get("title", "")) and float(row.get("rerank_score") or 0.0) >= 0.6 and len(concept_hits) <= 1:
        suspicious_reasons.append("generic_title_high_rank")
    if int(row.get("supporting_passage_count") or 0) <= 0:
        suspicious_reasons.append("missing_supporting_passages")
    if float(row.get("cross_encoder_score") or 0.0) < 0.45 and int(row.get("rerank_rank") or 10_000) <= 10:
        suspicious_reasons.append("weak_cross_encoder_top10")
    if list(row.get("judge_exclusion_violations") or []) and float(row.get("judge_score") or 0.0) < 0.5:
        suspicious_reasons.append("llm_judge_exclusions")
    verdict = "strong"
    if suspicious_reasons:
        verdict = "suspicious"
    elif not concept_hits and int(row.get("rerank_rank") or 10_000) <= 10:
        verdict = "partial"
    return {
        "rerank_rank": row.get("rerank_rank"),
        "doc_id": row.get("doc_id"),
        "section_id": row.get("section_id"),
        "title": row.get("title"),
        "section_type": row.get("section_type"),
        "rerank_score": row.get("rerank_score"),
        "cross_encoder_score": row.get("cross_encoder_score"),
        "judge_score": row.get("judge_score"),
        "concept_hits": concept_hits,
        "evidence_preview": evidence,
        "suspicious_reasons": suspicious_reasons,
        "verdict": verdict,
    }


def review_run(run_dir: Path):
    data = load_run(run_dir)
    section_by_id = {row["section_id"]: row for row in data["sections"]}
    passage_by_id = {row["passage_id"]: row for row in data["passages"]}
    rerank_rows = sorted(data["rerank_results"], key=lambda row: int(row.get("rerank_rank") or 10_000))
    reviewed = [review_row(row, section_by_id, passage_by_id) for row in rerank_rows]
    top10 = reviewed[:10]
    top20 = reviewed[:20]
    suspicious_top10 = sum(1 for row in top10 if row["verdict"] == "suspicious")
    partial_top10 = sum(1 for row in top10 if row["verdict"] == "partial")
    top20_unique_docs = len({row["doc_id"] for row in top20 if row.get("doc_id")})
    disagreement_avg = (data["phase_f_summary"].get("judge_disagreement_avg") if isinstance(data["phase_f_summary"], dict) else None)
    category = "strong"
    findings = []
    if suspicious_top10 >= 3:
        category = "needs_follow_up"
        findings.append(f"{suspicious_top10} suspicious candidates appear in the top10.")
    elif suspicious_top10 >= 1 or partial_top10 >= 3:
        category = "acceptable_with_noise"
        findings.append(f"Top10 contains {suspicious_top10} suspicious and {partial_top10} partial candidates.")
    if top20 and top20_unique_docs < 2:
        category = "needs_follow_up"
        findings.append(f"Top20 covers only {top20_unique_docs} documents.")
    if disagreement_avg is not None and float(disagreement_avg) > 0.4:
        findings.append(f"Cross-encoder / LLM judge disagreement is elevated at {disagreement_avg}.")
        if category == "strong":
            category = "acceptable_with_noise"
    summary = {
        "run_id": run_dir.name,
        "review_category": category,
        "top10_suspicious_count": suspicious_top10,
        "top10_partial_count": partial_top10,
        "top20_unique_docs": top20_unique_docs,
        "judge_disagreement_avg": disagreement_avg,
        "findings": findings,
        "top10_rows": top10,
        "doc_distribution_top20": Counter(row["doc_id"] for row in top20),
    }
    output_dir = run_dir / "phase_f_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase_f_review_rows.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in reviewed) + ("\n" if reviewed else ""),
        encoding="utf-8",
    )
    (output_dir / "phase_f_review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Review Phase F rerank outputs.")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    summary = review_run(Path(args.run_dir).resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
