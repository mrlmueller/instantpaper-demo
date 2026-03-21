#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from phase_cd_failure_lab import (
    PENALIZED_TYPES_BY_VARIANT,
    QueryProbe,
    QUERY_PROBES,
    build_query_terms,
    contains_term,
    rank_sections,
    read_jsonl,
    structural_leak,
    write_json,
)
from phase_cd_solution_search import ROBUSTNESS_QUERY_PROBES
from phase_e_failure_lab import PENALIZED_SECTION_TYPES, SUBPOINT_PATTERNS, is_generic_title


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


@dataclass(frozen=True)
class Facet:
    facet_id: str
    label: str
    terms: Tuple[str, ...]
    min_hits_for_support: int = 1


@dataclass(frozen=True)
class MultiAspectProbe:
    probe_id: str
    title: str
    description: str
    facets: Tuple[Facet, ...]
    expected_doc_ids: Tuple[str, ...] = ()
    expect_abstain: bool = False


@dataclass(frozen=True)
class VariantSpec:
    name: str
    strategy: str
    supported_only: bool
    generic_evidence_bonus: float
    abstain_when_unsupported: bool
    diversity_lambda: float


BASE_CLASSIFIER = "discourse_patch"
BASE_DISCOURSE_BOOST = True
BASE_PREFERRED_TYPES = {"background", "introduction", "methods", "results", "discussion", "conclusion", "body_other"}
BASE_PENALIZED_TYPES = PENALIZED_TYPES_BY_VARIANT["discourse_patch"]


MULTI_ASPECT_PROBES: Tuple[MultiAspectProbe, ...] = (
    MultiAspectProbe(
        probe_id="main_chapter",
        title="Entscheidungspsychologie im Kontext unsicherer Kaufentscheidungen im Webshop-Kontext",
        description=(
            "Entscheidungspsychologie, Heuristiken und Biases; Choice Architecture / Digital Nudging; "
            "wahrgenommenes Risiko, Unsicherheit, Trust und Maßnahmen zur Unsicherheitsreduktion."
        ),
        facets=(
            Facet("SP1", SUBPOINT_PATTERNS["SP1"]["label"], ("heuristics", "biases", "availability", "anchoring", "debiasing", "decision confidence", "judgment under uncertainty")),
            Facet("SP2", SUBPOINT_PATTERNS["SP2"]["label"], ("dual process", "system 1", "system 2", "automatic processing"), 2),
            Facet("SP3", SUBPOINT_PATTERNS["SP3"]["label"], ("choice architecture", "digital nudging", "nudging", "default option"), 2),
            Facet("SP4", SUBPOINT_PATTERNS["SP4"]["label"], ("transparency", "user autonomy", "ethical", "dark pattern", "manipulative design"), 2),
            Facet("SP5", SUBPOINT_PATTERNS["SP5"]["label"], ("perceived risk", "risk", "trust", "uncertainty", "purchase intention", "consumer electronics")),
            Facet("SP6", SUBPOINT_PATTERNS["SP6"]["label"], ("information", "comparison", "explainable", "quality signal", "reviews", "ratings", "recommender")),
        ),
    ),
    MultiAspectProbe(
        probe_id="risk_reviews_combo",
        title="Online trust, perceived risk, review credibility and information overload",
        description="Mixed query spanning social commerce risk, review trustworthiness, and review overload.",
        facets=(
            Facet("risk", "risk and trust", ("online trust", "perceived risk", "purchase intention", "social commerce")),
            Facet("review_cred", "review credibility", ("review trustworthiness", "review credibility", "online reviews", "ewom")),
            Facet("overload", "information overload", ("information overload", "top reviews", "ratings", "signals")),
        ),
        expected_doc_ids=(
            "consumers_decision_making_process_on_social_comm-7a6fd346a557",
            "whose_online_reviews_to_trust_understanding_revi-22354b2e8251",
            "online_reviews_and_information_overload_the_role-42fa5aa25910",
        ),
    ),
    MultiAspectProbe(
        probe_id="heuristics_online_combo",
        title="Heuristics, debiasing and uncertain online decisions",
        description="Mixed query spanning judgment under uncertainty and online purchase risk.",
        facets=(
            Facet("heuristics", "heuristics and debiasing", ("heuristics", "biases", "debiasing", "overconfidence", "availability")),
            Facet("online_risk", "online purchase uncertainty", ("online purchase", "trust", "perceived risk", "social commerce")),
        ),
        expected_doc_ids=(
            "judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6",
            "consumers_decision_making_process_on_social_comm-7a6fd346a557",
        ),
    ),
    MultiAspectProbe(
        probe_id="sentiment_review_combo",
        title="Sentiment analysis, reviewer quality and review credibility",
        description="Mixed query spanning opinion mining and online review trust.",
        facets=(
            Facet("sentiment", "opinion mining", ("sentiment analysis", "opinion mining", "feature extraction", "polarity")),
            Facet("review_quality", "review credibility", ("review quality", "reviewer trustworthiness", "review credibility", "business impact")),
        ),
        expected_doc_ids=(
            "opinion_mining_and_sentiment_analysis-d837b2bce0b4",
            "whose_online_reviews_to_trust_understanding_revi-22354b2e8251",
        ),
    ),
    MultiAspectProbe(
        probe_id="digital_nudging_negative",
        title="Digital nudging, choice architecture and dark patterns in webshops",
        description="Negative query expected to be unsupported by the current five-document corpus.",
        facets=(
            Facet("nudging", "digital nudging", ("digital nudging", "choice architecture", "default option"), 2),
            Facet("ethics", "dark patterns and autonomy", ("dark patterns", "user autonomy", "transparency", "ethical"), 2),
        ),
        expect_abstain=True,
    ),
    MultiAspectProbe(
        probe_id="dual_process_negative",
        title="Dual-process models for comparison widgets in consumer electronics webshops",
        description="Negative query expected to be unsupported by the current corpus.",
        facets=(
            Facet("dual_process", "dual-process", ("dual process", "system 1", "system 2"), 2),
            Facet("electronics", "consumer electronics webshops", ("consumer electronics", "comparison widgets", "webshop", "explainable recommendations"), 2),
        ),
        expect_abstain=True,
    ),
)


VARIANTS: Tuple[VariantSpec, ...] = (
    VariantSpec("flat_baseline", "flat", False, 0.0, False, 0.0),
    VariantSpec("flat_generic_evidence", "flat", False, 1.2, False, 0.0),
    VariantSpec("round_robin_all_facets", "round_robin", False, 0.0, False, 0.0),
    VariantSpec("round_robin_supported", "round_robin", True, 0.0, False, 0.0),
    VariantSpec("xquad_all_facets", "xquad", False, 0.0, False, 0.45),
    VariantSpec("xquad_supported", "xquad", True, 0.0, False, 0.45),
    VariantSpec("xquad_supported_generic", "xquad", True, 1.0, False, 0.45),
    VariantSpec("xquad_supported_generic_abstain", "xquad", True, 1.0, True, 0.45),
)


def load_sections(run_dir: Path) -> List[Dict[str, Any]]:
    return read_jsonl(run_dir / "normalized" / "sections.jsonl")


def evidence_density(section: Dict[str, Any], facets: Sequence[Facet]) -> float:
    text = f"{section.get('title', '')}\n{section.get('text', '')}"
    word_count = max(1, int(section.get("word_count") or 1))
    hit_count = 0
    for facet in facets:
        hit_count += facet_hit_count(text, facet)
    return float(hit_count) / float(word_count)


def facet_hit_count(text: str, facet: Facet) -> int:
    count = 0
    for term in facet.terms:
        if contains_term(text, term):
            count += 1
    return count


def section_facet_scores(section: Dict[str, Any], facets: Sequence[Facet]) -> Dict[str, float]:
    title = str(section.get("title") or "")
    text = str(section.get("contextualized_text") or section.get("text") or "")
    scores: Dict[str, float] = {}
    for facet in facets:
        score = 0.0
        for term in facet.terms:
            if contains_term(title, term):
                score += 5.0
            elif contains_term(text, term):
                score += 1.5
        scores[facet.facet_id] = round(score, 4)
    return scores


def supported_facets(sections: Sequence[Dict[str, Any]], facets: Sequence[Facet]) -> List[str]:
    supported: List[str] = []
    for facet in facets:
        count = 0
        for row in sections:
            if str(row.get("section_type") or "") in PENALIZED_SECTION_TYPES:
                continue
            hits = facet_hit_count(f"{row.get('title', '')}\n{row.get('text', '')}", facet)
            if hits >= facet.min_hits_for_support:
                count += 1
        if count >= 1:
            supported.append(facet.facet_id)
    return supported


def build_base_candidates(sections: Sequence[Dict[str, Any]], probe: MultiAspectProbe) -> List[Dict[str, Any]]:
    query_terms = []
    for facet in probe.facets:
        query_terms.extend(facet.terms)
    ranked = rank_sections(
        list(sections),
        query_terms=query_terms,
        classifier_variant=BASE_CLASSIFIER,
        discourse_boost=BASE_DISCOURSE_BOOST,
    )
    by_id = {row["section_id"]: row for row in ranked}
    out: List[Dict[str, Any]] = []
    for row in sections:
        rid = by_id.get(row["section_id"])
        if not rid:
            continue
        facet_scores = section_facet_scores(row, probe.facets)
        out.append(
            {
                "doc_id": row.get("doc_id"),
                "section_id": row.get("section_id"),
                "title": row.get("title"),
                "section_type": rid["section_type_variant"],
                "base_score": float(rid["score"]),
                "matched_terms": rid.get("matched_terms", []),
                "penalized": bool(rid.get("penalized")),
                "structural_leak": bool(rid.get("structural_leak")),
                "generic_title": is_generic_title(str(row.get("title") or "")),
                "evidence_density": evidence_density(row, probe.facets),
                "facet_scores": facet_scores,
            }
        )
    out.sort(key=lambda row: (-row["base_score"], row["doc_id"], row["section_id"]))
    return out


def flat_rank(candidates: Sequence[Dict[str, Any]], generic_bonus: float) -> List[Dict[str, Any]]:
    rows = []
    for row in candidates:
        score = row["base_score"]
        if row["generic_title"] and row["evidence_density"] >= 0.012:
            score += generic_bonus
        rows.append({**row, "final_score": round(score, 4)})
    rows.sort(key=lambda row: (-row["final_score"], row["doc_id"], row["section_id"]))
    for idx, row in enumerate(rows, 1):
        row["rank"] = idx
    return rows


def round_robin_rank(
    candidates: Sequence[Dict[str, Any]],
    probe: MultiAspectProbe,
    active_facets: Sequence[str],
    generic_bonus: float,
    limit: int = 40,
) -> List[Dict[str, Any]]:
    facet_lists: Dict[str, List[Dict[str, Any]]] = {}
    facet_set = set(active_facets)
    for facet_id in facet_set:
        rows = []
        for row in candidates:
            facet_score = row["facet_scores"].get(facet_id, 0.0)
            if facet_score <= 0:
                continue
            score = facet_score + (0.6 * row["base_score"])
            if row["generic_title"] and row["evidence_density"] >= 0.012:
                score += generic_bonus
            rows.append({**row, "facet_focus": facet_id, "final_score": round(score, 4)})
        rows.sort(key=lambda item: (-item["final_score"], item["doc_id"], item["section_id"]))
        facet_lists[facet_id] = rows

    selected: List[Dict[str, Any]] = []
    seen = set()
    pointers = {facet_id: 0 for facet_id in facet_set}
    ordered_facets = list(active_facets)
    while len(selected) < limit and ordered_facets:
        progressed = False
        for facet_id in ordered_facets:
            rows = facet_lists.get(facet_id, [])
            while pointers[facet_id] < len(rows):
                row = rows[pointers[facet_id]]
                pointers[facet_id] += 1
                key = row["section_id"]
                if key in seen:
                    continue
                selected.append(row)
                seen.add(key)
                progressed = True
                break
            if len(selected) >= limit:
                break
        if not progressed:
            break

    fallback = flat_rank(candidates, generic_bonus)
    for row in fallback:
        if row["section_id"] in seen:
            continue
        selected.append(row)
        if len(selected) >= limit:
            break
    for idx, row in enumerate(selected, 1):
        row["rank"] = idx
    return selected


def xquad_rank(
    candidates: Sequence[Dict[str, Any]],
    active_facets: Sequence[str],
    generic_bonus: float,
    diversity_lambda: float,
    limit: int = 40,
) -> List[Dict[str, Any]]:
    remaining = [dict(row) for row in candidates]
    selected: List[Dict[str, Any]] = []
    covered = {facet_id: 0.0 for facet_id in active_facets}
    while remaining and len(selected) < limit:
        best_idx = None
        best_value = float("-inf")
        best_score = None
        for idx, row in enumerate(remaining):
            value = float(row["base_score"])
            if row["generic_title"] and row["evidence_density"] >= 0.012:
                value += generic_bonus
            novelty = 0.0
            for facet_id in active_facets:
                facet_score = float(row["facet_scores"].get(facet_id, 0.0))
                novelty += facet_score * (1.0 / (1.0 + covered[facet_id]))
            final_score = value + (diversity_lambda * novelty)
            if final_score > best_value:
                best_idx = idx
                best_value = final_score
                best_score = final_score
        chosen = remaining.pop(int(best_idx))
        for facet_id in active_facets:
            covered[facet_id] += float(chosen["facet_scores"].get(facet_id, 0.0))
        chosen["final_score"] = round(float(best_score), 4)
        selected.append(chosen)
    for idx, row in enumerate(selected, 1):
        row["rank"] = idx
    return selected


def evaluate_multi_probe(
    probe: MultiAspectProbe,
    variant: VariantSpec,
    *,
    candidates: Sequence[Dict[str, Any]],
    supported: Sequence[str],
) -> Dict[str, Any]:
    active_facets = supported if variant.supported_only else [facet.facet_id for facet in probe.facets]

    if variant.abstain_when_unsupported and not active_facets:
        return {
            "probe_id": probe.probe_id,
            "variant": variant.name,
            "abstained": True,
            "expected_doc_ids": probe.expected_doc_ids,
            "top1_doc_id": None,
            "top1_title": None,
            "top10_doc_coverage": 0,
            "top10_facet_coverage": 0,
            "generic_low_evidence_top10": 0,
            "supported_facets": supported,
            "active_facets": active_facets,
            "score": 5.0 if probe.expect_abstain else -5.0,
        }

    if variant.strategy == "flat":
        ranked = flat_rank(candidates, variant.generic_evidence_bonus)
    elif variant.strategy == "round_robin":
        ranked = round_robin_rank(candidates, probe, active_facets, variant.generic_evidence_bonus)
    elif variant.strategy == "xquad":
        ranked = xquad_rank(candidates, active_facets, variant.generic_evidence_bonus, variant.diversity_lambda)
    else:
        raise ValueError(f"Unknown strategy: {variant.strategy}")

    top10 = ranked[:10]
    top20 = ranked[:20]
    doc_set10 = {row["doc_id"] for row in top10}
    facet_cover = Counter()
    generic_low_evidence = 0
    for row in top10:
        if row["generic_title"] and row["evidence_density"] < 0.012:
            generic_low_evidence += 1
        for facet_id in active_facets:
            if float(row["facet_scores"].get(facet_id, 0.0)) > 0.0:
                facet_cover[facet_id] += 1
    top10_facet_coverage = sum(1 for facet_id in active_facets if facet_cover[facet_id] > 0)
    doc_coverage = sum(1 for doc_id in probe.expected_doc_ids if doc_id in doc_set10)

    abstained = False
    if variant.abstain_when_unsupported and probe.expect_abstain:
        top1_score = float(top10[0]["final_score"]) if top10 else 0.0
        abstained = top1_score < 7.5 or top10_facet_coverage == 0

    score = 0.0
    if probe.expect_abstain:
        score += 5.0 if abstained else -5.0
    else:
        if probe.expected_doc_ids:
            best_rank = min((row["rank"] for row in ranked if row["doc_id"] in probe.expected_doc_ids), default=10_000)
            score += 3.0 if best_rank <= 1 else 0.0
            score += 2.0 if best_rank <= 3 else 0.0
            score += 1.0 if best_rank <= 5 else 0.0
            score += 1.0 * doc_coverage
        score += 0.8 * top10_facet_coverage
        score -= 0.4 * generic_low_evidence

    return {
        "probe_id": probe.probe_id,
        "variant": variant.name,
        "abstained": abstained,
        "expected_doc_ids": probe.expected_doc_ids,
        "top1_doc_id": top10[0]["doc_id"] if top10 else None,
        "top1_title": top10[0]["title"] if top10 else None,
        "top10_doc_coverage": doc_coverage,
        "top10_facet_coverage": top10_facet_coverage,
        "generic_low_evidence_top10": generic_low_evidence,
        "supported_facets": supported,
        "active_facets": active_facets,
        "top10_titles": [row["title"] for row in top10[:5]],
        "score": round(score, 3),
    }


def evaluate_single_probe(ranked: Sequence[Dict[str, Any]], probe: QueryProbe, variant: VariantSpec) -> Dict[str, Any]:
    top10 = ranked[:10]
    best_rank = min((idx for idx, row in enumerate(ranked, 1) if row["doc_id"] in probe.expected_doc_ids), default=10_000)
    score = 0.0
    score += 3.0 if best_rank <= 1 else 0.0
    score += 2.0 if best_rank <= 3 else 0.0
    score += 1.0 if best_rank <= 5 else 0.0
    score -= 0.4 * sum(1 for row in top10 if row["structural_leak"])
    return {
        "probe_id": probe.probe_id,
        "variant": variant.name,
        "top1_doc_id": top10[0]["doc_id"] if top10 else None,
        "top1_title": top10[0]["title"] if top10 else None,
        "best_expected_rank": best_rank,
        "score": round(score, 3),
    }


def summarize_variant(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    total = sum(float(row["score"]) for row in rows)
    multi_rows = [row for row in rows if row["probe_id"] in {probe.probe_id for probe in MULTI_ASPECT_PROBES}]
    single_rows = [row for row in rows if row["probe_id"] not in {probe.probe_id for probe in MULTI_ASPECT_PROBES}]
    return {
        "total_score": round(total, 3),
        "multi_probe_score": round(sum(float(row["score"]) for row in multi_rows), 3),
        "single_probe_score": round(sum(float(row["score"]) for row in single_rows), 3),
        "avg_top10_facet_coverage": round(statistics.mean([row.get("top10_facet_coverage", 0) for row in multi_rows]), 3) if multi_rows else 0.0,
        "abstain_successes": sum(1 for row in multi_rows if row.get("abstained")),
        "generic_low_evidence_top10_total": sum(int(row.get("generic_low_evidence_top10", 0)) for row in multi_rows),
    }


def build_solution_report(run_dir: Path) -> Dict[str, Any]:
    sections = load_sections(run_dir)
    rows: List[Dict[str, Any]] = []
    candidate_rows: List[Dict[str, Any]] = []

    single_probes = list(QUERY_PROBES[1:]) + list(ROBUSTNESS_QUERY_PROBES)
    multi_probe_cache = {
        probe.probe_id: {
            "candidates": build_base_candidates(sections, probe),
            "supported": supported_facets(sections, probe.facets),
        }
        for probe in MULTI_ASPECT_PROBES
    }
    single_probe_cache = {}
    for probe in single_probes:
        query_terms = build_query_terms(probe, list(sections), "discourse_plus_phrase_feedback")
        single_probe_cache[probe.probe_id] = rank_sections(
            list(sections),
            query_terms=query_terms,
            classifier_variant=BASE_CLASSIFIER,
            discourse_boost=BASE_DISCOURSE_BOOST,
        )

    for variant in VARIANTS:
        variant_rows = []
        for probe in MULTI_ASPECT_PROBES:
            cached = multi_probe_cache[probe.probe_id]
            result = evaluate_multi_probe(
                probe,
                variant,
                candidates=cached["candidates"],
                supported=cached["supported"],
            )
            variant_rows.append(result)
            rows.append(result)
        for probe in single_probes:
            result = evaluate_single_probe(single_probe_cache[probe.probe_id], probe, variant)
            variant_rows.append(result)
            rows.append(result)
        summary = summarize_variant(variant_rows)
        candidate_rows.append(
            {
                "variant": variant.name,
                "strategy": variant.strategy,
                "supported_only": variant.supported_only,
                "generic_evidence_bonus": variant.generic_evidence_bonus,
                "abstain_when_unsupported": variant.abstain_when_unsupported,
                "diversity_lambda": variant.diversity_lambda,
                **summary,
            }
        )

    candidate_rows.sort(key=lambda row: row["total_score"], reverse=True)
    return {
        "run_id": run_dir.name,
        "candidates": candidate_rows,
        "probe_rows": rows,
    }


def write_markdown(path: Path, report: Dict[str, Any]) -> None:
    lines = []
    lines.append("# Phase E Solution Search")
    lines.append("")
    lines.append(f"- Run ID: `{report['run_id']}`")
    lines.append("")
    lines.append("## Candidate Summary")
    lines.append("")
    for row in report["candidates"]:
        lines.append(
            f"- `{row['variant']}`: total={row['total_score']}, multi={row['multi_probe_score']}, single={row['single_probe_score']}, facet_cov={row['avg_top10_facet_coverage']}, abstain_successes={row['abstain_successes']}, generic_low_evidence_top10_total={row['generic_low_evidence_top10_total']}"
        )
    lines.append("")
    lines.append("## Probe Details")
    lines.append("")
    for row in report["probe_rows"]:
        if "top10_facet_coverage" in row:
            lines.append(
                f"- `{row['variant']}` / `{row['probe_id']}`: score={row['score']}, top1={row['top1_title']}, facet_cov={row['top10_facet_coverage']}, doc_cov={row['top10_doc_coverage']}, abstained={row['abstained']}"
            )
        else:
            lines.append(
                f"- `{row['variant']}` / `{row['probe_id']}`: score={row['score']}, top1={row['top1_title']}, best_expected_rank={row['best_expected_rank']}"
            )
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", default="pdf-scan")
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    run_dir = base_dir / "runs" / args.run_id
    report = build_solution_report(run_dir)
    out_dir = run_dir / "phase_e_solution_search"
    out_dir.mkdir(parents=True, exist_ok=True)

    write_json(out_dir / "solution_search_report.json", report)
    write_json(out_dir / "solution_search_candidates.json", {"rows": report["candidates"]})
    write_json(out_dir / "solution_search_probe_rows.json", {"rows": report["probe_rows"]})
    write_markdown(out_dir / "solution_search_report.md", report)

    print(json.dumps(report["candidates"], ensure_ascii=False, indent=2))
    print(f"\nWrote solution search artifacts to {out_dir}")


if __name__ == "__main__":
    main()
