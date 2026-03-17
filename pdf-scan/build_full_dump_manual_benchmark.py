#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List


REPO_ROOT = Path(__file__).resolve().parent
PDF_SCAN_DIR = REPO_ROOT
DEFAULT_SOURCE_RUN = "386e04657c41c805f8c1b974"
SUITE_DIR = PDF_SCAN_DIR / "benchmark" / "full_dump_webshop_manual_v1"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def label_from_score(score_0_to_10: int) -> int:
    if score_0_to_10 >= 9:
        return 3
    if score_0_to_10 >= 7:
        return 2
    if score_0_to_10 >= 5:
        return 1
    return 0


DOC_SEEDS: Dict[str, Dict[str, Any]] = {
    "23 Ways to Nudge.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": (
            "Broad positive recall judgment. The user stated that nearly all dump PDFs contain useful material for the "
            "webshop chapter. This paper is kept as a positive doc-level target even though section anchors are not "
            "annotated yet."
        ),
    },
    "A review of nudges.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for nudging / choice architecture coverage. Section anchors pending.",
    },
    "Beyond self-selection the multilayered online review biases at the intersection of users, platforms and culture.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Strong for online review platform biases, cultural/platform effects, and practical "
            "implications for uncertainty and information shaping."
        ),
        "section_judgments": [
            {
                "section_title": "2.3 Platform biases in online reviews",
                "page_start": 5,
                "page_end": 5,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "Relevant for platform-level shaping of reviews and secondarily for uncertainty/trust.",
            },
            {
                "section_title": "1. Introduction",
                "page_start": 2,
                "page_end": 3,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp2"],
                "notes": "User judged the intro as relevant for the platform-bias framing of online reviews.",
            },
            {
                "section_title": "2.4 Online review biases in Chinese users",
                "page_start": 5,
                "page_end": 5,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp2"],
                "notes": "Relevant for user/platform bias mechanisms in review environments.",
            },
            {
                "section_title": "3.2.2 Central tendencies of online and offline ratings",
                "page_start": 9,
                "page_end": 9,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "Strong for rating-bias effects and implications for trust and uncertainty in review systems.",
            },
            {
                "section_title": "4.2 Findings",
                "page_start": 11,
                "page_end": 11,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "User-marked strong findings section.",
            },
            {
                "section_title": "5.1 Main findings",
                "page_start": 12,
                "page_end": 12,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "Strong summary section for the paper's substantive conclusions.",
            },
            {
                "section_title": "5.3 Practical implications",
                "page_start": 15,
                "page_end": 15,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "Strong practical tie-in to platform design and information environments.",
            },
        ],
    },
    "Consumers’ Decision-Making Process on Social Commerce Platforms Online Trust, Perceived Risk, and Purchase Intentions.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment. Strong known match for trust, perceived risk, and purchase intention.",
    },
    "Development of methodology for classification of user experience (UX) in online customer review.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Useful for online review information, trust in peer-generated content, and risk/"
            "uncertainty around product quality in consumer electronics."
        ),
        "section_judgments": [
            {
                "section_title": "1. Introduction",
                "page_start": 1,
                "page_end": 2,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": "Reviews as a channel through which customers acquire product information and reduce uncertainty.",
            },
            {
                "section_title": "2.2. Online customer review",
                "page_start": 2,
                "page_end": 2,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "e-WOM and peer-generated information are framed as more trusted than seller information.",
            },
            {
                "section_title": "5. Discussion",
                "page_start": 4,
                "page_end": 4,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Strong for product reliability/connectivity risk as a must-be quality in electronics.",
            },
        ],
    },
    "Digital Nudging Altering User Behavior in Digital Environments.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for digital nudging mechanisms and psychological effects.",
    },
    "Digital nudging with recommender systems.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for recommender-system nudging and ethics.",
    },
    "Digital Nudging.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for digital nudging basics, relevance, and future trends.",
    },
    "Evolving techniques in sentiment analysis a comprehensive review.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked weak-but-positive. Not a strong overall fit, but it contains one useful region around review "
            "manipulation, helpfulness, and information quality."
        ),
        "section_judgments": [
            {
                "section_title": "Corpus based approach",
                "page_start": 17,
                "page_end": 18,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": (
                    "Best matching area in the paper. User specifically called out the statistical approach content within "
                    "the corpus-based section as relevant to manipulated reviews and helpful voting."
                ),
            }
        ],
    },
    "Fake online reviews Literature review, synthesis, and directions for future research.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Strong for fake reviews, uncertainty, distrust, information quality degradation, "
            "platform responses, and context moderators."
        ),
        "section_judgments": [
            {
                "section_title": "3.2.2 Effects on various stakeholders",
                "page_start": 10,
                "page_end": 10,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3", "sp1"],
                "notes": "Strongest section for consumer uncertainty, distrust, discomfort, and purchase-intention effects.",
            },
            {
                "section_title": "Figure 4. Influencing mechanisms of fake reviews",
                "page_start": 9,
                "page_end": 9,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3", "sp1"],
                "notes": "Useful structural summary of how fake reviews affect stakeholders and decision outcomes.",
            },
            {
                "section_title": "3.2.1 Effects on the development of online product reviews",
                "page_start": 10,
                "page_end": 10,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Directly about information quality, credibility, informativeness, and helpfulness degradation.",
            },
            {
                "section_title": "3.3.3 Response strategies",
                "page_start": 12,
                "page_end": 12,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3", "sp2"],
                "notes": "Useful for platform-side design responses and information-display interventions.",
            },
            {
                "section_title": "3.3.1 Features extraction",
                "page_start": 10,
                "page_end": 11,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": "Quality and credibility signals distinguishing truthful and fake reviews.",
            },
        ],
    },
    "Improving  decisions about health wealth and happiness.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for nudging / choice architecture context. Section anchors pending.",
    },
    "Judgment Under Uncertainty Heuristics and Biases.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for heuristics, biases, and perceived risk.",
    },
    "Natural language processing for analyzing online customer reviews a survey, taxonomy, and open research challenges.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Strong for review authenticity, trustworthiness, helpfulness, verified purchase, "
            "information overload, and better presentation of review information."
        ),
        "section_judgments": [
            {
                "section_title": "Introduction",
                "page_start": 1,
                "page_end": 3,
                "score_0_to_10": 7,
                "supported_subpoints": ["sp3"],
                "notes": "Best general entry point for reviews as assurance and guidance in consumer choice.",
            },
            {
                "section_title": "Review analysis and management",
                "page_start": 9,
                "page_end": 10,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3", "sp1"],
                "notes": (
                    "Strongest section for authenticity, trustworthiness, quality, usefulness, fake-review detection, "
                    "verified purchase, helpfulness, and information overload."
                ),
            },
            {
                "section_title": "Marketing and brand management",
                "page_start": 14,
                "page_end": 18,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": "Useful for seller trust profiles, trust models, and verified-purchase badges.",
            },
            {
                "section_title": "Customer experience and satisfaction",
                "page_start": 10,
                "page_end": 12,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": "Useful for review-based QA and summarization as uncertainty-reduction mechanisms.",
            },
        ],
    },
    "Online Reviews and Information Overload The Role of Selective, Parsimonious, and Concordant Top Reviews.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment. Strong known fit for review overload and top-review signals.",
    },
    "Opinion Mining and Sentiment Analysis.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Strong for uncertainty in online information, concrete product-evaluation examples, "
            "feature-level explanations, helpfulness signals, and manipulation/trust issues."
        ),
        "section_judgments": [
            {
                "section_title": "The demand for information on opinions and sentiment",
                "page_start": 5,
                "page_end": 7,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3"],
                "notes": "Strong introductory framing for missing, confusing, or overwhelming online information.",
            },
            {
                "section_title": "Applications in business and government intelligence",
                "page_start": 12,
                "page_end": 13,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Laptop example is a strong fit for uncertainty in complex consumer-electronics products.",
            },
            {
                "section_title": "Sentiment polarity and degrees of positivity",
                "page_start": 20,
                "page_end": 22,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Concrete features, pros/cons, and comparisons as uncertainty-reducing signals.",
            },
            {
                "section_title": "Special considerations for extraction",
                "page_start": 37,
                "page_end": 38,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Aspect extraction and feature-level review structuring for explainability and comparison.",
            },
            {
                "section_title": "Review(er) quality",
                "page_start": 53,
                "page_end": 59,
                "score_0_to_10": 10,
                "supported_subpoints": ["sp3"],
                "notes": "Strongest section in the PDF for helpfulness signals and ranking useful reviews.",
            },
            {
                "section_title": "Implications for manipulation",
                "page_start": 63,
                "page_end": 65,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp2", "sp3"],
                "notes": "Best fit for manipulation boundaries, sock puppets, gaming the system, and trust erosion.",
            },
        ],
    },
    "Sentiment Analysis in E-Commerce Platforms A Review of Current Techniques and Future Directions.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked weak-but-positive. Useful mainly for platform quality, trust, reliability, and fake-review "
            "detection references."
        ),
        "section_judgments": [
            {
                "section_title": "1) MACHINE LEARNING BASED TECHNIQUES",
                "page_start": 5,
                "page_end": 9,
                "score_0_to_10": 7,
                "supported_subpoints": ["sp3"],
                "notes": "Useful for trust, reliability, web design, and fake-review / spam-review discussion.",
            }
        ],
    },
    "Sentiment Analysis of Product Reviews Using Machine Learning and Pre-Trained LLM.pdf": {
        "has_useful_information": False,
        "role_in_suite": "manual_negative_anchor",
        "expected_difficulty": "manual_negative",
        "document_notes": "User explicitly marked this PDF as not useful for the webshop chapter.",
    },
    "Shining a Light on Dark Patterns.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for manipulative patterns, autonomy, and ethics in interface design. Section anchors pending.",
    },
    "The effectiveness of nudging.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for choice architecture intervention effectiveness.",
    },
    "TO NUDGE, OR NOT TO NUDGE.pdf": {
        "has_useful_information": True,
        "role_in_suite": "broad_positive_candidate",
        "expected_difficulty": "broad_recall_only",
        "document_notes": "Broad positive recall judgment for nudging / policy design coverage. Section anchors pending.",
    },
    "Using Online Reviews for Customer Sentiment Analysis.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. Strong for unfamiliar/innovation products, helpfulness votes, fake or ingenuine "
            "reviews, and review-based uncertainty reduction."
        ),
        "section_judgments": [
            {
                "section_title": "INTRODUCTION",
                "page_start": 1,
                "page_end": 2,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp3"],
                "notes": "Online reviews become more important for unfamiliar and harder-to-evaluate products.",
            },
            {
                "section_title": "SENTIMENT ANALYSIS ON ONLINE REVIEWS",
                "page_start": 2,
                "page_end": 5,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp3", "sp1"],
                "notes": "Helpful-vote filtering and fake/ingenuine review concerns as quality-signaling mechanisms.",
            },
        ],
    },
    "Whose online reviews to trust Understanding reviewer trustworthiness and its impact on business.pdf": {
        "has_useful_information": True,
        "role_in_suite": "manual_positive_anchor",
        "expected_difficulty": "manual_anchor",
        "document_notes": (
            "User-marked positive. One of the strongest trust/uncertainty papers in the dump, especially for source "
            "credibility, cues, and purchase decisions under information asymmetry."
        ),
        "section_judgments": [
            {
                "section_title": "Abstract",
                "page_start": 2,
                "page_end": 3,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp1"],
                "notes": "Strong high-level framing of reviewer trustworthiness and its decision impact.",
            },
            {
                "section_title": "1. Introduction",
                "page_start": 3,
                "page_end": 7,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp1"],
                "notes": "Strong for source credibility and reviewer trustworthiness as a decision mechanism.",
            },
            {
                "section_title": "2. Literature review",
                "page_start": 7,
                "page_end": 10,
                "score_0_to_10": 8,
                "supported_subpoints": ["sp1", "sp3"],
                "notes": "Cue-based judgments from reputation, profile picture, expertise, friends, and helpfulness votes.",
            },
            {
                "section_title": "3. Hypotheses development",
                "page_start": 10,
                "page_end": 18,
                "score_0_to_10": 9,
                "supported_subpoints": ["sp1", "sp3"],
                "notes": "Strongest section for trust, information asymmetry, and reviewer characteristics reducing uncertainty.",
            },
        ],
    },
}


def load_report_index(source_run: str) -> Dict[str, Dict[str, Any]]:
    index_path = PDF_SCAN_DIR / "runs" / source_run / "pdf_reports" / "index.json"
    index = read_json(index_path)
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in index.get("documents") or []:
        report_json = PDF_SCAN_DIR / "runs" / source_run / row["report_path"].replace("\\", "/")
        report = read_json(report_json)
        source_name = Path(report["source_pdf"]).name
        by_name[source_name] = {
            "doc_id": row["doc_id"],
            "doc_title": row["doc_title"],
            "source_pdf": report["source_pdf"],
        }
    return by_name


def build_doc_manifest(doc_id: str, label: str, source_name: str, seed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "doc_id": doc_id,
        "label": label,
        "path": f"../../paper-dump/{source_name}",
        "role_in_suite": seed["role_in_suite"],
        "expected_difficulty": seed["expected_difficulty"],
        "notes": seed["document_notes"],
    }


def build_judgment(doc_id: str, chapter_id: str, seed: Dict[str, Any]) -> Dict[str, Any]:
    section_judgments: List[Dict[str, Any]] = []
    for section in seed.get("section_judgments") or []:
        section_judgments.append(
            {
                "section_ref": {
                    "section_title": section["section_title"],
                    "page_start": int(section["page_start"]),
                    "page_end": int(section["page_end"]),
                },
                "label_0_to_3": label_from_score(int(section["score_0_to_10"])),
                "supported_subpoints": list(section["supported_subpoints"]),
                "notes": f"Score {int(section['score_0_to_10'])}/10. {section['notes']}",
            }
        )
    return {
        "chapter_id": chapter_id,
        "doc_id": doc_id,
        "has_useful_information": bool(seed["has_useful_information"]),
        "section_judgments": section_judgments,
        "document_notes": seed["document_notes"],
    }


def build_suite(source_run: str) -> Dict[str, Any]:
    report_index = load_report_index(source_run)
    if set(DOC_SEEDS) != set(report_index):
        missing_in_reports = sorted(set(DOC_SEEDS) - set(report_index))
        missing_in_seeds = sorted(set(report_index) - set(DOC_SEEDS))
        raise RuntimeError(
            "Seed/report mismatch. "
            f"Missing in reports: {missing_in_reports}. Missing in seeds: {missing_in_seeds}."
        )

    source_chapter = read_json(PDF_SCAN_DIR / "benchmark" / "small_gold" / "chapters" / "chapter_001_webshop_decision_psychology.json")
    chapter_id = str(source_chapter["chapter_id"])

    suite_documents: List[str] = []
    suite_judgments: List[str] = []
    summary_rows: List[Dict[str, Any]] = []

    for source_name in sorted(DOC_SEEDS):
        meta = report_index[source_name]
        seed = DOC_SEEDS[source_name]
        doc_id = meta["doc_id"]
        label = meta["doc_title"]
        manifest_name = f"{doc_id}.json"
        judgment_name = f"{chapter_id}__{doc_id}.json"

        write_json(SUITE_DIR / "manifests" / manifest_name, build_doc_manifest(doc_id, label, source_name, seed))
        write_json(SUITE_DIR / "judgments" / judgment_name, build_judgment(doc_id, chapter_id, seed))

        suite_documents.append(f"manifests/{manifest_name}")
        suite_judgments.append(f"judgments/{judgment_name}")
        summary_rows.append(
            {
                "source_pdf_name": source_name,
                "doc_id": doc_id,
                "doc_title": label,
                "has_useful_information": bool(seed["has_useful_information"]),
                "section_anchor_count": len(seed.get("section_judgments") or []),
                "role_in_suite": seed["role_in_suite"],
            }
        )

    write_json(SUITE_DIR / "chapters" / "chapter_001_webshop_decision_psychology.json", source_chapter)
    suite_manifest = {
        "suite_id": "full_dump_webshop_manual_v1",
        "suite_type": "large_suite",
        "chapter_specs": ["chapters/chapter_001_webshop_decision_psychology.json"],
        "documents": suite_documents,
        "judgments": suite_judgments,
        "notes": (
            "Full paper-dump webshop benchmark built from the user's manual false-negative review plus broad positive "
            "doc-level recall judgments. Section anchors exist only for the manually inspected subset."
        ),
    }
    write_json(SUITE_DIR / "manifests" / "suite_manifest.json", suite_manifest)
    write_json(
        SUITE_DIR / "suite_summary.json",
        {
            "source_run": source_run,
            "suite_id": suite_manifest["suite_id"],
            "document_count": len(summary_rows),
            "positive_doc_count": sum(1 for row in summary_rows if row["has_useful_information"]),
            "negative_doc_count": sum(1 for row in summary_rows if not row["has_useful_information"]),
            "section_anchor_count": sum(int(row["section_anchor_count"]) for row in summary_rows),
            "rows": summary_rows,
        },
    )
    return suite_manifest


def main() -> None:
    parser = argparse.ArgumentParser(description="Build a manual full-dump benchmark suite from user judgments.")
    parser.add_argument("--source-run", default=DEFAULT_SOURCE_RUN)
    args = parser.parse_args()

    suite_manifest = build_suite(args.source_run)
    print(json.dumps(suite_manifest, ensure_ascii=False, indent=2))
    print(f"\nWrote benchmark suite to {SUITE_DIR}")


if __name__ == "__main__":
    main()
