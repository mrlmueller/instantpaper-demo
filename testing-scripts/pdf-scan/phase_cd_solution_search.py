#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from phase_cd_failure_lab import (
    QUERY_PROBES,
    TITLE_PROBE_CASES,
    ProbeCase,
    QueryProbe,
    build_query_terms,
    classify_title,
    find_run_dir,
    rank_sections,
    read_jsonl,
    structural_leak,
    write_json,
)


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


ROBUSTNESS_TITLE_PROBES: Sequence[ProbeCase] = (
    ProbeCase("Theory and hypotheses", "background"),
    ProbeCase("Conceptual background", "background"),
    ProbeCase("Research methods", "methods"),
    ProbeCase("Main measures", "methods"),
    ProbeCase("Measures", "methods"),
    ProbeCase("Data analysis", "results"),
    ProbeCase("Empirical analysis", "results"),
    ProbeCase("Results and discussion", "results"),
    ProbeCase("Managerial implications", "discussion"),
    ProbeCase("Practical implications", "discussion"),
    ProbeCase("Limitations", "discussion"),
    ProbeCase("Future research", "conclusion"),
    ProbeCase("List of Tables", "table_of_contents"),
    ProbeCase("List of Figures", "table_of_contents"),
    ProbeCase("Abbreviations", "index"),
)


ROBUSTNESS_QUERY_PROBES: Sequence[QueryProbe] = (
    QueryProbe(
        probe_id="social_commerce_risk_paraphrase",
        chapter_title="Trust, risk and buying intention in social shopping",
        chapter_spec=(
            "Literature on trust formation, perceived uncertainty, and purchase intention "
            "in social commerce and online retail settings."
        ),
        expected_doc_ids=("consumers_decision_making_process_on_social_comm-7a6fd346a557",),
    ),
    QueryProbe(
        probe_id="heuristics_biases_paraphrase",
        chapter_title="Biases, calibration and debiasing in uncertain judgment",
        chapter_spec=(
            "Theory and evidence on heuristics, calibration, overconfidence, "
            "debiasing, and risk judgment under uncertainty."
        ),
        expected_doc_ids=("judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6",),
    ),
    QueryProbe(
        probe_id="review_trustworthiness_paraphrase",
        chapter_title="Credibility of customer reviews and business consequences",
        chapter_spec=(
            "Research on review credibility, reviewer trustworthiness, online reputation, "
            "and downstream business impact."
        ),
        expected_doc_ids=("whose_online_reviews_to_trust_understanding_revi-22354b2e8251",),
    ),
    QueryProbe(
        probe_id="information_overload_paraphrase",
        chapter_title="Review presentation, overload and top-review effects",
        chapter_spec=(
            "Studies about review overload, selective review display, "
            "top-review valence and product matching in e-commerce."
        ),
        expected_doc_ids=("online_reviews_and_information_overload_the_role-42fa5aa25910",),
    ),
    QueryProbe(
        probe_id="sentiment_analysis_paraphrase",
        chapter_title="Mining opinions and sentiment from review text",
        chapter_spec=(
            "Survey and methods work on opinion mining, polarity classification, "
            "feature extraction and review text analysis."
        ),
        expected_doc_ids=("opinion_mining_and_sentiment_analysis-d837b2bce0b4",),
    ),
)


@dataclass(frozen=True)
class CandidateSpec:
    name: str
    query_variant: str
    classifier_variant: str
    discourse_boost: bool = False


CANDIDATES: Sequence[CandidateSpec] = (
    CandidateSpec("baseline", "baseline", "baseline", False),
    CandidateSpec("structural_patch", "baseline", "structural_patch", False),
    CandidateSpec("discourse_patch", "baseline", "discourse_patch", False),
    CandidateSpec("conservative_lexical", "conservative_lexical", "structural_patch", False),
    CandidateSpec("discourse_conservative_lexical", "conservative_lexical", "discourse_patch", False),
    CandidateSpec("anchored_phrase_feedback", "anchored_phrase_feedback", "structural_patch", False),
    CandidateSpec("discourse_plus_phrase_feedback", "discourse_plus_phrase_feedback", "discourse_patch", True),
)


def evaluate_title_suite(variant: str, probes: Sequence[ProbeCase]) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    correct = 0
    for case in probes:
        predicted = classify_title(case.title, variant)
        ok = predicted == case.expected_type
        correct += int(ok)
        rows.append(
            {
                "variant": variant,
                "title": case.title,
                "expected_type": case.expected_type,
                "predicted_type": predicted,
                "ok": ok,
            }
        )
    total = len(probes)
    return {
        "rows": rows,
        "summary": {
            "variant": variant,
            "correct": correct,
            "total": total,
            "accuracy": round(correct / max(1, total), 3),
        },
    }


def evaluate_query_suite(
    sections: List[Dict[str, Any]],
    candidate: CandidateSpec,
    probes: Sequence[QueryProbe],
) -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    score = 0.0
    hit_at_1 = 0
    hit_at_3 = 0
    hit_at_5 = 0
    structural_leaks_total = 0
    top10_penalized_total = 0
    query_lengths: List[int] = []
    unique_docs_top10_list: List[int] = []

    for probe in probes:
        query_terms = build_query_terms(probe, sections, candidate.query_variant)
        ranked = rank_sections(
            sections,
            query_terms=query_terms,
            classifier_variant=candidate.classifier_variant,
            discourse_boost=candidate.discourse_boost,
        )
        top10 = ranked[:10]
        top20 = ranked[:20]
        doc_best_rank: Dict[str, int] = {}
        for idx, row in enumerate(ranked, start=1):
            doc_best_rank.setdefault(str(row.get("doc_id") or ""), idx)

        expected_best_rank = min(doc_best_rank.get(doc_id, 10_000) for doc_id in probe.expected_doc_ids)
        probe_hit1 = int(expected_best_rank <= 1)
        probe_hit3 = int(expected_best_rank <= 3)
        probe_hit5 = int(expected_best_rank <= 5)
        hit_at_1 += probe_hit1
        hit_at_3 += probe_hit3
        hit_at_5 += probe_hit5

        top10_penalized = sum(1 for row in top10 if bool(row.get("penalized")))
        top10_tiny = sum(1 for row in top10 if "tiny_section" in set(row.get("quality_flags") or []))
        structural_leaks = sum(1 for row in top20 if bool(row.get("structural_leak")))
        unique_docs_top10 = len({row.get("doc_id") for row in top10})
        query_lengths.append(len(query_terms))
        unique_docs_top10_list.append(unique_docs_top10)
        structural_leaks_total += structural_leaks
        top10_penalized_total += top10_penalized

        probe_score = (3.0 * probe_hit1) + (2.0 * probe_hit3) + (1.0 * probe_hit5)
        probe_score -= (2.0 * structural_leaks) + (1.0 * top10_penalized) + (0.2 * top10_tiny)
        score += probe_score

        rows.append(
            {
                "candidate": candidate.name,
                "probe_id": probe.probe_id,
                "expected_best_doc_rank": expected_best_rank,
                "hit_at_1": probe_hit1,
                "hit_at_3": probe_hit3,
                "hit_at_5": probe_hit5,
                "query_term_count": len(query_terms),
                "query_terms_preview": ", ".join(query_terms[:14]),
                "top1_doc_id": top10[0]["doc_id"] if top10 else None,
                "top1_title": top10[0]["title"] if top10 else None,
                "top10_unique_docs": unique_docs_top10,
                "top10_penalized": top10_penalized,
                "top10_tiny_sections": top10_tiny,
                "top20_structural_leaks": structural_leaks,
            }
        )

    return {
        "rows": rows,
        "summary": {
            "candidate": candidate.name,
            "probe_count": len(probes),
            "aggregate_score": round(score, 3),
            "hit_at_1_total": hit_at_1,
            "hit_at_3_total": hit_at_3,
            "hit_at_5_total": hit_at_5,
            "structural_leaks_total": structural_leaks_total,
            "top10_penalized_total": top10_penalized_total,
            "avg_query_term_count": round(statistics.mean(query_lengths), 2) if query_lengths else 0.0,
            "avg_unique_docs_top10": round(statistics.mean(unique_docs_top10_list), 2) if unique_docs_top10_list else 0.0,
        },
    }


def combine_scores(
    *,
    generic_title_accuracy: float,
    robustness_title_accuracy: float,
    primary_summary: Dict[str, Any],
    robustness_summary: Dict[str, Any],
) -> Dict[str, Any]:
    title_score = (12.0 * generic_title_accuracy) + (18.0 * robustness_title_accuracy)
    retrieval_score = float(primary_summary["aggregate_score"]) + float(robustness_summary["aggregate_score"])
    leak_penalty = (2.5 * float(primary_summary["structural_leaks_total"])) + (1.5 * float(robustness_summary["structural_leaks_total"]))
    penalty_score = (1.0 * float(primary_summary["top10_penalized_total"])) + (1.0 * float(robustness_summary["top10_penalized_total"]))
    length_penalty = max(0.0, float(primary_summary["avg_query_term_count"]) - 16.0) * 0.4
    length_penalty += max(0.0, float(robustness_summary["avg_query_term_count"]) - 16.0) * 0.4
    composite = title_score + retrieval_score - leak_penalty - penalty_score - length_penalty
    return {
        "title_score": round(title_score, 3),
        "retrieval_score": round(retrieval_score, 3),
        "leak_penalty": round(leak_penalty, 3),
        "penalty_score": round(penalty_score, 3),
        "length_penalty": round(length_penalty, 3),
        "composite_score": round(composite, 3),
    }


def iter_structural_leaks(sections: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for row in sections:
        title = str(row.get("title") or "")
        current_type = str(row.get("section_type") or "")
        structural_patch_type = classify_title(title, "structural_patch")
        discourse_patch_type = classify_title(title, "discourse_patch")
        if structural_leak(title, current_type):
            rows.append(
                {
                    "doc_id": row.get("doc_id"),
                    "section_id": row.get("section_id"),
                    "title": title,
                    "current_type": current_type,
                    "structural_patch_type": structural_patch_type,
                    "discourse_patch_type": discourse_patch_type,
                }
            )
    return rows


def load_sections(run_dir: Path) -> List[Dict[str, Any]]:
    return read_jsonl(run_dir / "normalized" / "sections.jsonl")


def build_report(run_dir: Path) -> Dict[str, Any]:
    sections = load_sections(run_dir)

    generic_title_probes = list(TITLE_PROBE_CASES)
    robustness_title_probes = list(ROBUSTNESS_TITLE_PROBES)
    primary_probes = list(QUERY_PROBES[1:])
    robustness_probes = list(ROBUSTNESS_QUERY_PROBES)

    title_results: List[Dict[str, Any]] = []
    query_results: List[Dict[str, Any]] = []
    candidate_rows: List[Dict[str, Any]] = []

    for candidate in CANDIDATES:
        generic_title = evaluate_title_suite(candidate.classifier_variant, generic_title_probes)
        robustness_title = evaluate_title_suite(candidate.classifier_variant, robustness_title_probes)
        primary_queries = evaluate_query_suite(sections, candidate, primary_probes)
        robustness_queries = evaluate_query_suite(sections, candidate, robustness_probes)
        combined = combine_scores(
            generic_title_accuracy=float(generic_title["summary"]["accuracy"]),
            robustness_title_accuracy=float(robustness_title["summary"]["accuracy"]),
            primary_summary=primary_queries["summary"],
            robustness_summary=robustness_queries["summary"],
        )
        title_results.extend(generic_title["rows"])
        title_results.extend(robustness_title["rows"])
        query_results.extend(primary_queries["rows"])
        query_results.extend(robustness_queries["rows"])
        candidate_rows.append(
            {
                "candidate": candidate.name,
                "query_variant": candidate.query_variant,
                "classifier_variant": candidate.classifier_variant,
                "discourse_boost": candidate.discourse_boost,
                "generic_title_accuracy": generic_title["summary"]["accuracy"],
                "robustness_title_accuracy": robustness_title["summary"]["accuracy"],
                "primary_probe_score": primary_queries["summary"]["aggregate_score"],
                "robustness_probe_score": robustness_queries["summary"]["aggregate_score"],
                "primary_hit_at_1": primary_queries["summary"]["hit_at_1_total"],
                "robustness_hit_at_1": robustness_queries["summary"]["hit_at_1_total"],
                "primary_structural_leaks": primary_queries["summary"]["structural_leaks_total"],
                "robustness_structural_leaks": robustness_queries["summary"]["structural_leaks_total"],
                "avg_query_term_count": round(
                    statistics.mean(
                        [
                            float(primary_queries["summary"]["avg_query_term_count"]),
                            float(robustness_queries["summary"]["avg_query_term_count"]),
                        ]
                    ),
                    2,
                ),
                **combined,
            }
        )

    candidate_rows.sort(key=lambda row: (float(row["composite_score"]), float(row["robustness_probe_score"]), float(row["primary_probe_score"])), reverse=True)
    best = candidate_rows[0] if candidate_rows else None

    return {
        "run_id": run_dir.name,
        "candidate_rows": candidate_rows,
        "title_rows": title_results,
        "query_rows": query_results,
        "structural_leaks_in_current_run": iter_structural_leaks(sections),
        "best_candidate": best,
        "probe_sets": {
            "generic_title_probe_count": len(generic_title_probes),
            "robustness_title_probe_count": len(robustness_title_probes),
            "primary_query_probe_count": len(primary_probes),
            "robustness_query_probe_count": len(robustness_probes),
        },
    }


def print_report(report: Dict[str, Any], output_dir: Path) -> None:
    print("=" * 80)
    print("Phase C/D Solution Search")
    print("=" * 80)
    print(f"run_id                   {report['run_id']}")
    print(f"output_dir               {output_dir}")
    print("probe_sets")
    for key, value in (report.get("probe_sets") or {}).items():
        print(f"  {key:28} {value}")
    print("=" * 80)
    print("Candidate Summary")
    print("=" * 80)
    for row in report.get("candidate_rows") or []:
        print(
            f"{row['candidate']:28} composite={row['composite_score']:6.2f} "
            f"title={row['generic_title_accuracy']:.3f}/{row['robustness_title_accuracy']:.3f} "
            f"primary={row['primary_probe_score']:5.2f} robust={row['robustness_probe_score']:5.2f} "
            f"leaks={row['primary_structural_leaks'] + row['robustness_structural_leaks']} "
            f"avg_terms={row['avg_query_term_count']:4.1f}"
        )
    best = report.get("best_candidate") or {}
    if best:
        print("=" * 80)
        print("Recommended Candidate")
        print("=" * 80)
        print(f"name                     {best.get('candidate')}")
        print(f"query_variant            {best.get('query_variant')}")
        print(f"classifier_variant       {best.get('classifier_variant')}")
        print(f"discourse_boost          {best.get('discourse_boost')}")
        print(f"composite_score          {best.get('composite_score')}")
        print(f"primary_probe_score      {best.get('primary_probe_score')}")
        print(f"robustness_probe_score   {best.get('robustness_probe_score')}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Search for robust Phase C/D fix combinations")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan")
    parser.add_argument("--run-id", default=None, help="Run id under pdf-scan/runs")
    parser.add_argument("--output-dir", default=None, help="Optional explicit output directory")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    run_dir = find_run_dir(base_dir, args.run_id)
    report = build_report(run_dir)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else run_dir / "solution_search"
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "solution_search_report.json", report)
    write_json(output_dir / "solution_search_candidates.json", {"rows": report.get("candidate_rows") or []})
    write_json(output_dir / "solution_search_title_rows.json", {"rows": report.get("title_rows") or []})
    write_json(output_dir / "solution_search_query_rows.json", {"rows": report.get("query_rows") or []})
    write_json(output_dir / "solution_search_structural_leaks.json", {"rows": report.get("structural_leaks_in_current_run") or []})

    print_report(report, output_dir)


if __name__ == "__main__":
    main()
