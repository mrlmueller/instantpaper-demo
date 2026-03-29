from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


RUN_ID = "386e04657c41c805f8c1b974"
SOURCE_SUITE_ID = "full_dump_webshop_manual_v1"
TARGET_SUITE_ID = "full_dump_webshop_manual_v2_exhaustive"


ROOT = Path(__file__).resolve().parents[2]
BENCHMARK_ROOT = ROOT / "benchmark"
SOURCE_SUITE_DIR = BENCHMARK_ROOT / SOURCE_SUITE_ID
TARGET_SUITE_DIR = BENCHMARK_ROOT / TARGET_SUITE_ID
SECTION_INSPECTION_DIR = ROOT / "runs" / RUN_ID / "section_inspection"


SECTION_LABEL_BANDS = {
    0: "not_useful",
    1: "weak_or_marginal",
    2: "useful_support",
    3: "core_or_strong_support",
}


DOC_NOTES: dict[str, str] = {
    "23_ways_to_nudge-220b81fc44ca": (
        "Rich source for digital nudging mechanisms, dual-process framing, ethical boundaries, and examples of manipulative vs. legitimate interface steering."
    ),
    "a_review_of_nudges-8a314b3ef5a0": (
        "Strong conceptual source on nudge definitions, justificatory debates, transparency, avoidability, and libertarian-paternalistic grounding."
    ),
    "beyond_self_selection_the_multilayered_online_re-d629822f9d43": (
        "Strong source on user and platform biases in online reviews, aggregation distortions, cultural effects, and practical implications for transparency and trust."
    ),
    "consumers_decision_making_process_on_social_comm-7a6fd346a557": (
        "Direct trust/perceived-risk source for online purchase decisions. Strong for trust building, social commerce signals, and purchase intention."
    ),
    "development_of_methodology_for_classification_of-566c7dba63b4": (
        "Applied but useful source. Best for e-WOM, online reviews as decision input, and a concrete consumer-electronics case around wireless earbuds and UX reliability."
    ),
    "digital_nudging_altering_user_behavior_in_digita-790f8fc6abef": (
        "Strong digital nudging survey with behavioral foundations, UI design implications, and a detailed catalog of psychological effects and nudges."
    ),
    "digital_nudging-c70013fb5862": (
        "Short conceptual source on digital nudging, bounded rationality, heuristics, and future implications for digital choice environments."
    ),
    "digital_nudging_with_recommender_systems-b0730604bb9e": (
        "Very strong source for recommender-system nudging, underlying psychological phenomena, decision-information nudges, and design-level interventions."
    ),
    "evolving_techniques_in_sentiment_analysis_a_comp-68fe188f165a": (
        "Weak-but-positive source. Mostly technical, but includes useful material around review analysis, manipulated reviews, helpfulness, and feature-level review information."
    ),
    "fake_online_reviews_literature_review_synthesis_-e9bbe09bb4bf": (
        "Strong source on fake reviews, uncertainty, distrust, review credibility degradation, and platform response strategies."
    ),
    "improving_decisions_about_health_wealth_and_happ-7cd933237011": (
        "Narrow but useful source. Mainly valuable as an accessible framing text on nudging, libertarian paternalism, and autonomy debates."
    ),
    "judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6": (
        "Core theory source for heuristics, biases, representativeness, availability, base rates, risk perception, and confidence under uncertainty."
    ),
    "natural_language_processing_for_analyzing_online-152aaa107e77": (
        "Useful survey source for review authenticity, fake-review detection, trust models, verified-purchase-like signals, overload, and review summarization."
    ),
    "online_reviews_and_information_overload_the_role-42fa5aa25910": (
        "Strong source on information overload, top reviews, signaling, parsimony, signal concordance, and platform design for reducing uncertainty."
    ),
    "opinion_mining_and_sentiment_analysis-d837b2bce0b4": (
        "Strong source for online opinion demand, helpfulness signals, product-feature extraction, manipulation, and review quality/trust issues."
    ),
    "sentiment_analysis_in_e_commerce_platforms_a_rev-0c59fc64f2e7": (
        "Modest but positive source. Mostly overview material, with some relevant passages on e-commerce review data, fake/spam review issues, and trust-related platform signals."
    ),
    "sentiment_analysis_of_product_reviews_using_mach-1897724bd012": (
        "Mostly technical and not a good fit for the chapter. Explainability material is adjacent, but overall the PDF is too method-centric for the benchmark's usefulness threshold."
    ),
    "shining_a_light_on_dark_patterns-8d4057c0e9fb": (
        "Strong source for manipulative digital choice architecture, System 1/System 2 links, behavioral impact of dark patterns, and ethical boundaries."
    ),
    "the_effectiveness_of_nudging-76e15b34d02c": (
        "Strong meta-analytic source for the effectiveness of choice-architecture interventions and the relative value of different nudge families."
    ),
    "to_nudge_or_not_to_nudge-16624afd839e": (
        "Moderate positive source. Useful mainly for broad nudging framing, public-policy applications, and ethical/strategic considerations."
    ),
    "using_online_reviews_for_customer_sentiment_anal-ba995f136320": (
        "Useful applied source for unfamiliar/complex products, smartphone reviews, helpfulness filtering, and fake/ingenuine review concerns."
    ),
    "whose_online_reviews_to_trust_understanding_revi-22354b2e8251": (
        "Strong trust-focused source on reviewer credibility, source cues, trustworthiness, and how reviewer characteristics reduce uncertainty in online purchases."
    ),
}


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def stable_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def usefulness_to_label(score: int) -> int:
    if score <= 2:
        return 0
    if score <= 5:
        return 1
    if score <= 7:
        return 2
    return 3


def usefulness_to_role(score: int) -> str:
    if score >= 9:
        return "core_evidence"
    if score >= 7:
        return "strong_support"
    if score >= 5:
        return "optional_support"
    if score >= 3:
        return "weak_context"
    if score >= 1:
        return "low_value"
    return "not_useful"


def category_to_subpoints(categories: list[str]) -> list[str]:
    mapping = {
        "decision_psychology_theory": {"sp1"},
        "nudging_choice_architecture": {"sp2"},
        "trust_risk_uncertainty": {"sp3"},
        "review_quality_authenticity": {"sp3"},
        "information_presentation_filtering_comparison": {"sp3"},
        "consumer_electronics_or_product_examples": {"sp3"},
    }
    out: set[str] = set()
    for category in categories:
        out.update(mapping.get(category, set()))
    return sorted(out)


def derive_document_label(section_rows: list[dict[str, Any]], has_useful_information: bool) -> int:
    if not has_useful_information:
        return 0
    strong = sum(1 for row in section_rows if row["usefulness_0_to_10"] >= 8)
    core = sum(1 for row in section_rows if row["usefulness_0_to_10"] >= 9)
    useful = sum(1 for row in section_rows if row["usefulness_0_to_10"] >= 7)
    if core >= 3 or strong >= 5:
        return 3
    if useful >= 2:
        return 2
    return 1


def build_benchmark() -> None:
    source_suite_manifest = load_json(SOURCE_SUITE_DIR / "manifests" / "suite_manifest.json")
    source_suite_summary = load_json(SOURCE_SUITE_DIR / "suite_summary.json")
    chapter_payload = load_json(SOURCE_SUITE_DIR / "chapters" / "chapter_001_webshop_decision_psychology.json")

    section_rows = load_jsonl(SECTION_INSPECTION_DIR / "section_scores_openai.jsonl")
    benchmark_target_rows = load_jsonl(SECTION_INSPECTION_DIR / "benchmark_target_reviews.jsonl")

    manifests_by_doc: dict[str, dict[str, Any]] = {}
    for manifest_ref in source_suite_manifest["documents"]:
        payload = load_json(SOURCE_SUITE_DIR / manifest_ref)
        manifests_by_doc[payload["doc_id"]] = payload

    old_judgments_by_doc: dict[str, dict[str, Any]] = {}
    for judgment_ref in source_suite_manifest["judgments"]:
        payload = load_json(SOURCE_SUITE_DIR / judgment_ref)
        old_judgments_by_doc[payload["doc_id"]] = payload

    target_overrides_by_doc_and_title: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for row in benchmark_target_rows:
        title_key = row["matched_section_title"] or row["expected_section_title"]
        if title_key:
            target_overrides_by_doc_and_title[row["doc_id"]][title_key].append(row)

    section_rows_by_doc: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in section_rows:
        section_rows_by_doc[row["doc_id"]].append(row)

    judgments_refs: list[str] = []
    manifest_refs: list[str] = []
    gold_section_total = 0
    exhaustive_section_total = 0
    structural_miss_total = 0

    review_packet_root = TARGET_SUITE_DIR / "review_packets"
    review_packet_root.mkdir(parents=True, exist_ok=True)

    for doc_id in sorted(manifests_by_doc):
        manifest = manifests_by_doc[doc_id]
        section_items = sorted(
            section_rows_by_doc.get(doc_id, []),
            key=lambda row: (
                row.get("page_start") if row.get("page_start") is not None else 99999,
                row.get("page_end") if row.get("page_end") is not None else 99999,
                row.get("title") or "",
            ),
        )
        old_judgment = old_judgments_by_doc[doc_id]
        has_useful_information = bool(old_judgment["has_useful_information"])

        exhaustive_sections: list[dict[str, Any]] = []
        gold_sections: list[dict[str, Any]] = []
        near_miss_sections: list[dict[str, Any]] = []

        for row in section_items:
            raw_score = row.get("usefulness_0_to_10")
            score = int(raw_score) if raw_score is not None else 0
            categories = [item for item in [row.get("primary_category")] + row.get("secondary_categories", []) if item]
            supported_subpoints = category_to_subpoints(categories)

            override_rows = target_overrides_by_doc_and_title[doc_id].get(row["title"], [])
            benchmark_override = None
            if override_rows:
                benchmark_override = sorted(
                    override_rows,
                    key=lambda item: (
                        -(item.get("usefulness_0_to_10") or -1),
                        -(item.get("benchmark_label_0_to_3") or -1),
                    ),
                )[0]
                score = max(score, int(benchmark_override["usefulness_0_to_10"]))
                supported_subpoints = sorted(set(supported_subpoints) | set(benchmark_override.get("benchmark_supported_subpoints", [])))
                categories = [
                    item
                    for item in [benchmark_override.get("primary_category")] + benchmark_override.get("secondary_categories", [])
                    if item
                ]

            label_0_to_3 = usefulness_to_label(score)
            role = usefulness_to_role(score)
            notes = row["short_rationale"]
            if benchmark_override:
                notes = f"{notes} Benchmark-reviewed note: {benchmark_override['why_not_surfaced']}".strip()

            section_payload = {
                "section_ref": {
                    "section_id": row["section_id"],
                    "section_title": row["title"],
                    "page_start": row["page_start"],
                    "page_end": row["page_end"],
                    "section_type": row["section_type"],
                },
                "usefulness_0_to_10": score,
                "label_0_to_3": label_0_to_3,
                "label_band": SECTION_LABEL_BANDS[label_0_to_3],
                "judgment_role": role,
                "supported_subpoints": supported_subpoints,
                "benchmark_categories": categories,
                "retrieval_eligible": bool(row["retrieval_eligible"]),
                "quality_flags": row.get("quality_flags", []),
                "notes": notes,
                "pipeline_trace": {
                    "phase_e_doc_rank": row.get("phase_e_doc_rank"),
                    "phase_f_doc_rank": row.get("phase_f_doc_rank"),
                    "phase_g_doc_rank": row.get("phase_g_doc_rank"),
                    "phase_g_score_0_to_100": row.get("phase_g_score_0_to_100"),
                    "doc_has_useful_information": row.get("doc_has_useful_information"),
                },
            }
            if benchmark_override:
                section_payload["benchmark_override"] = {
                    "expected_section_title": benchmark_override["expected_section_title"],
                    "benchmark_label_0_to_3": benchmark_override["benchmark_label_0_to_3"],
                    "benchmark_notes": benchmark_override["benchmark_notes"],
                    "miss_reason": benchmark_override["miss_reason"],
                    "pipeline_reason": benchmark_override["pipeline_reason"],
                }

            exhaustive_sections.append(section_payload)

            if score >= 8:
                gold_sections.append(
                    {
                        "section_title": row["title"],
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "usefulness_0_to_10": score,
                        "supported_subpoints": supported_subpoints,
                        "benchmark_categories": categories,
                        "notes": notes,
                    }
                )
            elif 3 <= score <= 5:
                near_miss_sections.append(
                    {
                        "section_title": row["title"],
                        "page_start": row["page_start"],
                        "page_end": row["page_end"],
                        "usefulness_0_to_10": score,
                        "notes": notes,
                    }
                )

        structural_misses: list[dict[str, Any]] = []
        for target in benchmark_target_rows:
            if target["doc_id"] != doc_id:
                continue
            if target["miss_reason"] != "phase_c_structure_issue":
                continue
            structural_misses.append(
                {
                    "expected_section_title": target["expected_section_title"],
                    "page_start": target["expected_page_start"],
                    "page_end": target["expected_page_end"],
                    "usefulness_0_to_10": target["usefulness_0_to_10"],
                    "benchmark_label_0_to_3": target["benchmark_label_0_to_3"],
                    "supported_subpoints": target["benchmark_supported_subpoints"],
                    "notes": target["benchmark_notes"],
                    "why_missing": target["why_not_surfaced"],
                    "suggested_pipeline_change": target["suggested_pipeline_change"],
                }
            )

        document_label_0_to_3 = derive_document_label(exhaustive_sections, has_useful_information)
        document_notes = DOC_NOTES[doc_id]
        if old_judgment.get("document_notes"):
            document_notes = f"{document_notes} Existing benchmark note: {old_judgment['document_notes']}"

        judgment_payload = {
            "chapter_id": chapter_payload["chapter_id"],
            "doc_id": doc_id,
            "doc_title": manifest["label"],
            "has_useful_information": has_useful_information,
            "document_label_0_to_3": document_label_0_to_3,
            "document_label_band": SECTION_LABEL_BANDS[document_label_0_to_3],
            "document_notes": document_notes,
            "manual_review_basis": [
                "full extracted section inventory",
                f"run {RUN_ID} section inspection packets",
                "benchmark target direct excerpt review where available",
            ],
            "gold_section_refs": gold_sections,
            "near_miss_sections": near_miss_sections,
            "structural_miss_sections": structural_misses,
            "section_judgments": exhaustive_sections,
        }
        judgment_name = f"{chapter_payload['chapter_id']}__{doc_id}.json"
        stable_write_json(TARGET_SUITE_DIR / "judgments" / judgment_name, judgment_payload)
        judgments_refs.append(f"judgments/{judgment_name}")

        manifest_payload = {
            "doc_id": manifest["doc_id"],
            "label": manifest["label"],
            "path": manifest["path"],
            "role_in_suite": (
                "manual_negative_anchor"
                if not has_useful_information
                else "manual_exhaustive_positive"
            ),
            "expected_difficulty": "manual_exhaustive",
            "notes": document_notes,
        }
        manifest_name = f"{doc_id}.json"
        stable_write_json(TARGET_SUITE_DIR / "manifests" / manifest_name, manifest_payload)
        manifest_refs.append(f"manifests/{manifest_name}")

        packet_lines = [
            f"# {manifest['label']}",
            "",
            f"- doc_id: `{doc_id}`",
            f"- has_useful_information: `{has_useful_information}`",
            f"- document_label_0_to_3: `{document_label_0_to_3}`",
            f"- gold_sections: `{len(gold_sections)}`",
            f"- structural_miss_sections: `{len(structural_misses)}`",
            "",
            "## Gold Sections",
            "",
        ]
        if gold_sections:
            for section in gold_sections:
                packet_lines.extend(
                    [
                        f"### {section['section_title']}",
                        "",
                        f"- pages: `{section['page_start']}-{section['page_end']}`",
                        f"- usefulness_0_to_10: `{section['usefulness_0_to_10']}`",
                        f"- supported_subpoints: `{', '.join(section['supported_subpoints']) or '-'}`",
                        f"- categories: `{', '.join(section['benchmark_categories'])}`",
                        f"- notes: {section['notes']}",
                        "",
                    ]
                )
        else:
            packet_lines.extend(["No gold sections.", ""])

        packet_lines.extend(["## Exhaustive Sections", ""])
        for section in exhaustive_sections:
            packet_lines.extend(
                [
                    f"### {section['section_ref']['section_title']}",
                    "",
                    f"- pages: `{section['section_ref']['page_start']}-{section['section_ref']['page_end']}`",
                    f"- usefulness_0_to_10: `{section['usefulness_0_to_10']}`",
                    f"- label_0_to_3: `{section['label_0_to_3']}`",
                    f"- judgment_role: `{section['judgment_role']}`",
                    f"- supported_subpoints: `{', '.join(section['supported_subpoints']) or '-'}`",
                    f"- categories: `{', '.join(section['benchmark_categories'])}`",
                    f"- retrieval_eligible: `{section['retrieval_eligible']}`",
                    f"- notes: {section['notes']}",
                    "",
                ]
            )
        review_packet_path = review_packet_root / f"{doc_id}.md"
        review_packet_path.write_text("\n".join(packet_lines).strip() + "\n", encoding="utf-8")

        gold_section_total += len(gold_sections)
        exhaustive_section_total += len(exhaustive_sections)
        structural_miss_total += len(structural_misses)

    stable_write_json(TARGET_SUITE_DIR / "chapters" / "chapter_001_webshop_decision_psychology.json", chapter_payload)

    suite_manifest = {
        "suite_id": TARGET_SUITE_ID,
        "suite_type": "large_suite_exhaustive",
        "chapter_specs": ["chapters/chapter_001_webshop_decision_psychology.json"],
        "documents": manifest_refs,
        "judgments": judgments_refs,
        "notes": (
            "Exhaustive full-dump benchmark built from manual assistant review of the extracted section inventory and direct benchmark-target inspection. "
            "Each PDF now carries section-level judgments for the full extracted section set, plus gold sections, near misses, and structural-miss notes."
        ),
    }
    stable_write_json(TARGET_SUITE_DIR / "manifests" / "suite_manifest.json", suite_manifest)

    suite_summary = {
        "source_run": RUN_ID,
        "source_suite": SOURCE_SUITE_ID,
        "suite_id": TARGET_SUITE_ID,
        "document_count": len(manifest_refs),
        "positive_doc_count": sum(
            1 for judgment_ref in judgments_refs if load_json(TARGET_SUITE_DIR / judgment_ref)["has_useful_information"]
        ),
        "negative_doc_count": sum(
            1 for judgment_ref in judgments_refs if not load_json(TARGET_SUITE_DIR / judgment_ref)["has_useful_information"]
        ),
        "exhaustive_section_count": exhaustive_section_total,
        "gold_section_count": gold_section_total,
        "structural_miss_count": structural_miss_total,
        "judgment_label_distribution": Counter(
            section["label_0_to_3"]
            for judgment_ref in judgments_refs
            for section in load_json(TARGET_SUITE_DIR / judgment_ref)["section_judgments"]
        ),
    }
    suite_summary["judgment_label_distribution"] = {
        str(key): value for key, value in sorted(suite_summary["judgment_label_distribution"].items())
    }
    stable_write_json(TARGET_SUITE_DIR / "suite_summary.json", suite_summary)

    readme_lines = [
        f"# {TARGET_SUITE_ID}",
        "",
        "This suite is an exhaustive benchmark for the current webshop decision-psychology chapter.",
        "",
        "Judgment meaning:",
        "- `label_0_to_3 = 0`: not useful",
        "- `label_0_to_3 = 1`: weak or marginal",
        "- `label_0_to_3 = 2`: useful support",
        "- `label_0_to_3 = 3`: core or strong support",
        "",
        "Role meaning:",
        "- `core_evidence`: highly useful section that should strongly matter in evaluation",
        "- `strong_support`: clearly useful section that broadens or grounds the chapter",
        "- `optional_support`: somewhat useful but not essential",
        "- `weak_context`: context or background with limited standalone value",
        "- `low_value` / `not_useful`: should not materially count as a success",
        "",
        "Artifacts:",
        "- `judgments/`: exhaustive per-document judgments",
        "- `manifests/`: document manifests plus suite manifest",
        "- `review_packets/`: human-readable per-document review packets",
        "",
        f"Built from run `{RUN_ID}` and the source suite `{SOURCE_SUITE_ID}`.",
    ]
    (TARGET_SUITE_DIR / "README.md").write_text("\n".join(readme_lines).strip() + "\n", encoding="utf-8")


if __name__ == "__main__":
    build_benchmark()
