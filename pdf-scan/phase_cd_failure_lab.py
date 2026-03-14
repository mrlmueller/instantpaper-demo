#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import re
import statistics
import sys
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "bei",
    "by",
    "das",
    "der",
    "die",
    "ein",
    "eine",
    "einer",
    "eines",
    "for",
    "from",
    "im",
    "in",
    "is",
    "of",
    "on",
    "or",
    "the",
    "to",
    "und",
    "von",
    "with",
    "zu",
}


BASELINE_SECTION_TYPE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("table_of_contents", [r"^contents$", r"^table of contents$"]),
    ("abstract", [r"^abstract$"]),
    ("introduction", [r"^introduction$", r"^1 introduction$"]),
    ("background", [r"^background$", r"^literature review$", r"^theoretical background$", r"^related work$"]),
    ("methods", [r"^methods?$", r"^methodology$", r"^research design$", r"^data and methods$", r"^materials and methods$"]),
    ("results", [r"^results?$", r"^analysis and results$", r"^findings$", r"^matching and findings$", r"^empirical results$"]),
    ("discussion", [r"^discussion$", r"^discussion and implications$", r"^implications$", r"^theoretical implications$"]),
    ("conclusion", [r"^conclusion$", r"^conclusions$", r"^general discussion and conclusions?$", r"^summary and conclusion$"]),
    ("references", [r"^references$", r"^bibliography$", r"^works cited$"]),
    ("appendix", [r"^appendix(?:\s+[a-z0-9]+)?$", r"^appendices$", r"^supplement(?:ary)? materials?$", r"^supplementary information$"]),
    ("acknowledgements", [r"^acknowledg?ments?$", r"^author contributions$", r"^funding$"]),
]

STRUCTURAL_PATCH_PATTERNS: List[Tuple[str, List[str]]] = [
    ("index", [r"^index$", r"^subject index$", r"^author index$", r"^glossary$", r"^nomenclature$", r"^abbreviations?$"]),
    ("table_of_contents", [r"^list of figures$", r"^list of tables$", r"^contents$"]),
]

DISCOURSE_PATCH_PATTERNS: List[Tuple[str, List[str]]] = [
    (
        "background",
        [
            r"^conceptual background$",
            r"^conceptual framework$",
            r"^theoretical framework$",
            r"^theory and hypotheses$",
        ],
    ),
    (
        "methods",
        [
            r"^data collection$",
            r"^measures?$",
            r"^main measures$",
            r"^measurement$",
            r"^measurement model$",
            r"^method$",
            r"^research methods?$",
            r"^empirical setting$",
            r"^study design$",
            r"^sample and procedures?$",
            r"^variables?$",
        ],
    ),
    ("results", [r"^analysis$", r"^empirical analysis$", r"^results and discussion$", r"^data analysis$"]),
    ("discussion", [r"^theoretical implications$", r"^managerial implications$", r"^practical implications$", r"^limitations$", r"^limitations and future research$"]),
    ("conclusion", [r"^future research$", r"^concluding remarks$", r"^summary$", r"^general discussion$"]),
]

FRONT_MATTER_TITLES = {
    "front matter",
    "title page",
    "copyright page",
    "preface",
    "foreword",
    "list of contributors",
    "about the authors",
}

PENALIZED_TYPES_BY_VARIANT = {
    "baseline": {"front_matter", "table_of_contents", "acknowledgements", "references", "appendix"},
    "structural_patch": {"front_matter", "table_of_contents", "acknowledgements", "references", "appendix", "index"},
    "discourse_patch": {"front_matter", "table_of_contents", "acknowledgements", "references", "appendix", "index"},
}


@dataclass(frozen=True)
class ProbeCase:
    title: str
    expected_type: str


@dataclass(frozen=True)
class QueryProbe:
    probe_id: str
    chapter_title: str
    chapter_spec: str
    expected_doc_ids: Tuple[str, ...] = ()


QUERY_PROBES: Tuple[QueryProbe, ...] = (
    QueryProbe(
        probe_id="main_chapter",
        chapter_title="Entscheidungspsychologie im Kontext unsicherer Kaufentscheidungen im Webshop-Kontext",
        chapter_spec=(
            "Entscheidungspsychologie im Kontext unsicherer Kaufentscheidungen "
            "(Heuristiken, Biases, Dual-Process-Ansätze) und deren Rolle bei decision confidence "
            "bzw. Entscheidungssicherheit; Choice Architecture / Digital Nudging im digitalen Kontext, "
            "Gestaltungsprinzipien, Wirkmechanismen, Grenzen sowie Abgrenzung zu manipulativen Mustern; "
            "wahrgenommenes Risiko/Unsicherheit im Online-Kauf und Faktoren, die Unsicherheit reduzieren."
        ),
        expected_doc_ids=(),
    ),
    QueryProbe(
        probe_id="social_commerce_risk",
        chapter_title="Online trust, perceived risk and purchase intention in social commerce",
        chapter_spec=(
            "Empirical and review literature on social commerce, online trust, perceived risk, "
            "consumer purchase intention, and purchase decision-making in online retail environments."
        ),
        expected_doc_ids=("consumers_decision_making_process_on_social_comm-7a6fd346a557",),
    ),
    QueryProbe(
        probe_id="heuristics_biases",
        chapter_title="Heuristics and biases under uncertainty",
        chapter_spec=(
            "Theoretical and empirical work on heuristics, biases, calibration, debiasing, "
            "risk perception, and judgment under uncertainty."
        ),
        expected_doc_ids=("judgment_under_uncertainty_heuristics_and_biases-5d61ba1a71f6",),
    ),
    QueryProbe(
        probe_id="review_trustworthiness",
        chapter_title="Trustworthiness of online reviews and its business impact",
        chapter_spec=(
            "Literature on reviewer trustworthiness, online reputation, review credibility, "
            "and the effects of online reviews on business outcomes."
        ),
        expected_doc_ids=("whose_online_reviews_to_trust_understanding_revi-22354b2e8251",),
    ),
    QueryProbe(
        probe_id="information_overload",
        chapter_title="Online reviews, top reviews and information overload",
        chapter_spec=(
            "Research on online reviews, information overload, top review valence, matching, "
            "and review presentation effects in e-commerce."
        ),
        expected_doc_ids=("online_reviews_and_information_overload_the_role-42fa5aa25910",),
    ),
    QueryProbe(
        probe_id="sentiment_analysis",
        chapter_title="Opinion mining and sentiment analysis",
        chapter_spec=(
            "Survey and methods literature on opinion mining, sentiment analysis, review mining, "
            "feature extraction, polarity detection, and review-related websites."
        ),
        expected_doc_ids=("opinion_mining_and_sentiment_analysis-d837b2bce0b4",),
    ),
)


TITLE_PROBE_CASES: Tuple[ProbeCase, ...] = (
    ProbeCase("Front Matter", "front_matter"),
    ProbeCase("Title Page", "front_matter"),
    ProbeCase("Preface", "front_matter"),
    ProbeCase("Contents", "table_of_contents"),
    ProbeCase("Table of Contents", "table_of_contents"),
    ProbeCase("List of Figures", "table_of_contents"),
    ProbeCase("References", "references"),
    ProbeCase("Bibliography", "references"),
    ProbeCase("Appendix A", "appendix"),
    ProbeCase("Author Contributions", "acknowledgements"),
    ProbeCase("Index", "index"),
    ProbeCase("Subject Index", "index"),
    ProbeCase("Glossary", "index"),
    ProbeCase("Research Design", "methods"),
    ProbeCase("Data Collection", "methods"),
    ProbeCase("5. Analysis and results", "results"),
    ProbeCase("Empirical Analysis", "results"),
    ProbeCase("Theoretical implications", "discussion"),
    ProbeCase("Managerial implications", "discussion"),
    ProbeCase("Limitations and future research", "discussion"),
    ProbeCase("General Discussion and Conclusions", "conclusion"),
)


def ascii_fold(value: Any) -> str:
    text = str(value or "")
    normalized = unicodedata.normalize("NFKD", text)
    return normalized.encode("ascii", "ignore").decode("ascii")


def normalize_text(value: Any) -> str:
    text = ascii_fold(value).lower()
    text = re.sub(r"[^a-z0-9*]+", " ", text)
    return " ".join(text.split())


def normalize_heading_key(value: Any) -> str:
    text = normalize_text(value)
    text = re.sub(r"^\d+(?:\.\d+)*\s+", "", text)
    return text.strip()


def count_words(text: Any) -> int:
    return len(re.findall(r"[A-Za-z0-9]+", str(text or "")))


def read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def classify_title(title: str, variant: str) -> str:
    key = normalize_heading_key(title)
    if not key:
        return "body_other"

    patterns: List[Tuple[str, List[str]]] = list(BASELINE_SECTION_TYPE_PATTERNS)
    if variant in {"structural_patch", "discourse_patch"}:
        patterns = STRUCTURAL_PATCH_PATTERNS + patterns
    if variant == "discourse_patch":
        patterns = patterns + DISCOURSE_PATCH_PATTERNS

    for section_type, regexes in patterns:
        for regex in regexes:
            if re.match(regex, key, flags=re.IGNORECASE):
                return section_type
    if key in FRONT_MATTER_TITLES:
        return "front_matter"
    return "body_other"


def extract_seed_terms(title: str, spec: str, *, max_terms: int = 18) -> List[str]:
    raw = f"{title}; {spec}"
    parenthetical_bits = re.findall(r"\(([^)]+)\)", raw)
    segments = re.split(r"[;:,\n/]| and | und | sowie ", raw)
    segments.extend(parenthetical_bits)
    cleaned: List[str] = []
    seen = set()
    for segment in segments:
        text = " ".join(str(segment or "").split()).strip(" -")
        if not text:
            continue
        if len(text) < 3:
            continue
        if count_words(text) > 8:
            continue
        key = normalize_text(text)
        if not key or key in seen:
            continue
        seen.add(key)
        cleaned.append(text)
        if len(cleaned) >= max_terms:
            break
    return cleaned


def lexical_variants(term: str) -> List[str]:
    base = " ".join(str(term or "").split())
    if not base:
        return []
    variants = [base]
    lowered = base.lower()
    if "-" in base:
        variants.append(base.replace("-", " "))
    if " " in base:
        variants.append(base.replace(" ", "-"))
    if lowered.endswith("ies"):
        variants.append(base[:-3] + "y")
    if lowered.endswith("s") and len(base) > 4:
        variants.append(base[:-1])
    if lowered.endswith("y") and len(base) > 4:
        variants.append(base[:-1] + "ies")
    if "dual process" in lowered or "dual-process" in lowered:
        variants.extend(["dual-process", "dual process", "system 1", "system 2"])
    if "heuristic" in lowered and "*" not in lowered:
        variants.append("heuristic*")
    if "review" in lowered and "*" not in lowered:
        variants.append("review*")
    out: List[str] = []
    seen = set()
    for item in variants:
        key = normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def conservative_lexical_variants(term: str) -> List[str]:
    base = " ".join(str(term or "").split())
    if not base:
        return []
    variants = [base]
    lowered = base.lower()
    if "-" in base:
        variants.append(base.replace("-", " "))
    if " " in base:
        variants.append(base.replace(" ", "-"))
    if "dual process" in lowered or "dual-process" in lowered:
        variants.extend(["dual-process", "dual process", "system 1", "system 2"])
    out: List[str] = []
    seen = set()
    for item in variants:
        key = normalize_text(item)
        if key and key not in seen:
            seen.add(key)
            out.append(item)
    return out


def contains_term(text: str, term: str) -> bool:
    haystack_tokens = normalize_text(text).split()
    needle_tokens = normalize_text(term).split()
    if not needle_tokens or len(needle_tokens) > len(haystack_tokens):
        return False
    for start in range(len(haystack_tokens) - len(needle_tokens) + 1):
        matched = True
        for offset, needle in enumerate(needle_tokens):
            candidate = haystack_tokens[start + offset]
            if needle.endswith("*"):
                prefix = needle[:-1]
                if not prefix or not candidate.startswith(prefix):
                    matched = False
                    break
            elif candidate != needle:
                matched = False
                break
        if matched:
            return True
    return False


def score_section(
    section: Dict[str, Any],
    *,
    query_terms: Sequence[str],
    preferred_types: set[str],
    penalized_types: set[str],
    classifier_variant: str,
    discourse_boost: bool,
) -> Dict[str, Any]:
    title = str(section.get("title") or "")
    text = str(section.get("contextualized_text") or section.get("text") or "")
    section_type = classify_title(title, classifier_variant)
    score = 0.0
    matched_terms: List[str] = []

    for term in query_terms:
        if contains_term(title, term):
            score += 5.0
            matched_terms.append(term)
        elif contains_term(text, term):
            score += 1.5
            matched_terms.append(term)

    if section_type in preferred_types:
        score += 1.0
    if discourse_boost and section_type in {"methods", "results", "discussion", "background", "conclusion"}:
        score += 1.0
    if section_type in penalized_types:
        score -= 10.0
    quality_flags = set(section.get("quality_flags") or [])
    if "tiny_section" in quality_flags:
        score -= 1.5
    if "synthetic" in quality_flags:
        score -= 0.5

    return {
        "score": round(score, 4),
        "matched_terms": sorted(set(matched_terms)),
        "section_type_variant": section_type,
    }


def extract_title_feedback_terms(rows: Sequence[Dict[str, Any]], *, max_terms: int = 8) -> List[str]:
    token_counter: Counter[str] = Counter()
    bigram_counter: Counter[str] = Counter()
    doc_hits: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        title = str(row.get("title") or "")
        tokens = [tok for tok in normalize_text(title).split() if len(tok) >= 4 and tok not in STOPWORDS and not tok.isdigit()]
        for tok in tokens:
            token_counter[tok] += 1
            doc_hits[tok].add(doc_id)
        for left, right in zip(tokens, tokens[1:]):
            phrase = f"{left} {right}"
            bigram_counter[phrase] += 1
            doc_hits[phrase].add(doc_id)

    ranked: List[Tuple[str, float]] = []
    for term, count in token_counter.items():
        ranked.append((term, count + 0.5 * len(doc_hits.get(term, set()))))
    for term, count in bigram_counter.items():
        ranked.append((term, count + len(doc_hits.get(term, set()))))

    ranked.sort(key=lambda item: (item[1], len(item[0].split()), item[0]), reverse=True)
    out: List[str] = []
    seen = set()
    for term, _score in ranked:
        if term in seen:
            continue
        if term in {"index", "references", "appendix", "contents"}:
            continue
        seen.add(term)
        out.append(term)
        if len(out) >= max_terms:
            break
    return out


def extract_phrase_feedback_terms(rows: Sequence[Dict[str, Any]], *, max_terms: int = 6) -> List[str]:
    bigram_counter: Counter[str] = Counter()
    trigram_counter: Counter[str] = Counter()
    doc_hits: Dict[str, set[str]] = defaultdict(set)
    for row in rows:
        doc_id = str(row.get("doc_id") or "")
        tokens = [tok for tok in normalize_text(row.get("title")).split() if len(tok) >= 4 and tok not in STOPWORDS and not tok.isdigit()]
        for n in (2, 3):
            for start in range(len(tokens) - n + 1):
                phrase = " ".join(tokens[start : start + n])
                if phrase in {"top reviews", "online reviews"}:
                    # Too generic in this corpus; it caused drift in the probe set.
                    continue
                if n == 2:
                    bigram_counter[phrase] += 1
                else:
                    trigram_counter[phrase] += 1
                doc_hits[phrase].add(doc_id)

    ranked: List[Tuple[str, float]] = []
    for term, count in trigram_counter.items():
        ranked.append((term, count + (2.0 * len(doc_hits.get(term, set())))))
    for term, count in bigram_counter.items():
        ranked.append((term, count + len(doc_hits.get(term, set()))))
    ranked.sort(key=lambda item: (item[1], len(item[0].split()), item[0]), reverse=True)

    out: List[str] = []
    seen = set()
    for term, _score in ranked:
        key = normalize_text(term)
        if key and key not in seen:
            seen.add(key)
            out.append(term)
        if len(out) >= max_terms:
            break
    return out


def build_query_terms(probe: QueryProbe, sections: List[Dict[str, Any]], variant_name: str) -> List[str]:
    seeds = extract_seed_terms(probe.chapter_title, probe.chapter_spec, max_terms=18)
    terms: List[str] = []
    for seed in seeds:
        if variant_name in {"lexical_plus_structural", "corpus_feedback_titles", "discourse_plus_feedback"}:
            terms.extend(lexical_variants(seed))
        elif variant_name in {"conservative_lexical", "anchored_phrase_feedback", "discourse_plus_phrase_feedback"}:
            terms.extend(conservative_lexical_variants(seed))
        else:
            terms.append(seed)
    deduped: List[str] = []
    seen = set()
    for term in terms:
        key = normalize_text(term)
        if key and key not in seen:
            seen.add(key)
            deduped.append(term)

    if variant_name in {"corpus_feedback_titles", "discourse_plus_feedback"}:
        provisional = rank_sections(
            sections,
            query_terms=deduped,
            classifier_variant="structural_patch" if variant_name == "corpus_feedback_titles" else "discourse_patch",
            discourse_boost=(variant_name == "discourse_plus_feedback"),
        )
        feedback = extract_title_feedback_terms(provisional[:12], max_terms=8)
        for term in feedback:
            key = normalize_text(term)
            if key not in seen:
                seen.add(key)
                deduped.append(term)
    if variant_name in {"anchored_phrase_feedback", "discourse_plus_phrase_feedback"}:
        provisional = rank_sections(
            sections,
            query_terms=deduped,
            classifier_variant="structural_patch" if variant_name == "anchored_phrase_feedback" else "discourse_patch",
            discourse_boost=(variant_name == "discourse_plus_phrase_feedback"),
        )
        feedback = extract_phrase_feedback_terms(provisional[:10], max_terms=6)
        for term in feedback:
            key = normalize_text(term)
            if key not in seen:
                seen.add(key)
                deduped.append(term)
    return deduped


def structural_leak(title: str, section_type_variant: str) -> bool:
    title_key = normalize_heading_key(title)
    if title_key in {"index", "subject index", "author index", "glossary"}:
        return section_type_variant not in {"index"}
    if title_key in {"references", "bibliography", "contents", "table of contents"}:
        return section_type_variant not in {"references", "table_of_contents"}
    return False


def rank_sections(
    sections: List[Dict[str, Any]],
    *,
    query_terms: Sequence[str],
    classifier_variant: str,
    discourse_boost: bool,
) -> List[Dict[str, Any]]:
    preferred_types = {"background", "related_work", "methods", "results", "discussion", "body_other", "conclusion"}
    penalized_types = PENALIZED_TYPES_BY_VARIANT[classifier_variant]
    ranked: List[Dict[str, Any]] = []
    for section in sections:
        score_row = score_section(
            section,
            query_terms=query_terms,
            preferred_types=preferred_types,
            penalized_types=penalized_types,
            classifier_variant=classifier_variant,
            discourse_boost=discourse_boost,
        )
        ranked.append(
            {
                "doc_id": str(section.get("doc_id") or ""),
                "section_id": str(section.get("section_id") or ""),
                "title": str(section.get("title") or ""),
                "page_start": section.get("page_start"),
                "page_end": section.get("page_end"),
                "quality_flags": list(section.get("quality_flags") or []),
                "score": score_row["score"],
                "matched_terms": score_row["matched_terms"],
                "section_type_variant": score_row["section_type_variant"],
                "penalized": score_row["section_type_variant"] in penalized_types,
                "structural_leak": structural_leak(str(section.get("title") or ""), score_row["section_type_variant"]),
            }
        )

    ranked.sort(
        key=lambda row: (
            float(row["score"]),
            not bool(row["penalized"]),
            -len(row["matched_terms"]),
            row["doc_id"],
            row["title"],
        ),
        reverse=True,
    )
    return ranked


def evaluate_title_probes() -> Dict[str, Any]:
    variants = ["baseline", "structural_patch", "discourse_patch"]
    rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    for variant in variants:
        correct = 0
        for case in TITLE_PROBE_CASES:
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
        summary_rows.append(
            {
                "variant": variant,
                "accuracy": round(correct / len(TITLE_PROBE_CASES), 3),
                "correct": correct,
                "total": len(TITLE_PROBE_CASES),
            }
        )
    return {"rows": rows, "summary": summary_rows}


def evaluate_variants(sections: List[Dict[str, Any]]) -> Dict[str, Any]:
    variant_specs = [
        {"variant": "baseline", "classifier_variant": "baseline", "discourse_boost": False},
        {"variant": "structural_patch", "classifier_variant": "structural_patch", "discourse_boost": False},
        {"variant": "discourse_patch", "classifier_variant": "discourse_patch", "discourse_boost": False},
        {"variant": "conservative_lexical", "classifier_variant": "structural_patch", "discourse_boost": False},
        {"variant": "lexical_plus_structural", "classifier_variant": "structural_patch", "discourse_boost": False},
        {"variant": "anchored_phrase_feedback", "classifier_variant": "structural_patch", "discourse_boost": False},
        {"variant": "corpus_feedback_titles", "classifier_variant": "structural_patch", "discourse_boost": False},
        {"variant": "discourse_plus_phrase_feedback", "classifier_variant": "discourse_patch", "discourse_boost": True},
        {"variant": "discourse_plus_feedback", "classifier_variant": "discourse_patch", "discourse_boost": True},
    ]

    probe_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []

    for spec in variant_specs:
        total_score = 0.0
        structural_leaks_total = 0
        top10_penalized_total = 0
        hit_at_1_total = 0
        hit_at_3_total = 0

        for probe in QUERY_PROBES:
            query_terms = build_query_terms(probe, sections, spec["variant"])
            ranked = rank_sections(
                sections,
                query_terms=query_terms,
                classifier_variant=spec["classifier_variant"],
                discourse_boost=spec["discourse_boost"],
            )
            top10 = ranked[:10]
            top20 = ranked[:20]
            doc_best_rank: Dict[str, int] = {}
            for idx, row in enumerate(ranked, start=1):
                doc_best_rank.setdefault(row["doc_id"], idx)

            expected_best_rank = None
            if probe.expected_doc_ids:
                expected_best_rank = min(doc_best_rank.get(doc_id, 10_000) for doc_id in probe.expected_doc_ids)
                hit_at_1 = int(expected_best_rank <= 1)
                hit_at_3 = int(expected_best_rank <= 3)
                hit_at_5 = int(expected_best_rank <= 5)
                hit_at_1_total += hit_at_1
                hit_at_3_total += hit_at_3
                total_score += (3.0 * hit_at_1) + (2.0 * hit_at_3) + (1.0 * hit_at_5)
            else:
                hit_at_1 = hit_at_3 = hit_at_5 = None
                total_score += min(len({row["doc_id"] for row in top10}), 3)

            structural_leaks = sum(1 for row in top20 if row["structural_leak"])
            top10_penalized = sum(1 for row in top10 if row["penalized"])
            top10_tiny = sum(1 for row in top10 if "tiny_section" in set(row["quality_flags"] or []))
            unique_docs_top10 = len({row["doc_id"] for row in top10})
            structural_leaks_total += structural_leaks
            top10_penalized_total += top10_penalized
            total_score -= (2.0 * structural_leaks) + (1.0 * top10_penalized) + (0.2 * top10_tiny)

            probe_rows.append(
                {
                    "variant": spec["variant"],
                    "probe_id": probe.probe_id,
                    "query_term_count": len(query_terms),
                    "query_terms_preview": ", ".join(query_terms[:12]),
                    "top1_title": top10[0]["title"] if top10 else None,
                    "top1_doc_id": top10[0]["doc_id"] if top10 else None,
                    "top10_unique_docs": unique_docs_top10,
                    "top10_penalized": top10_penalized,
                    "top10_tiny_sections": top10_tiny,
                    "top20_structural_leaks": structural_leaks,
                    "expected_best_doc_rank": expected_best_rank,
                    "hit_at_1": hit_at_1,
                    "hit_at_3": hit_at_3,
                    "hit_at_5": hit_at_5,
                }
            )

        summary_rows.append(
            {
                "variant": spec["variant"],
                "aggregate_score": round(total_score, 3),
                "structural_leaks_total": structural_leaks_total,
                "top10_penalized_total": top10_penalized_total,
                "hit_at_1_total": hit_at_1_total,
                "hit_at_3_total": hit_at_3_total,
            }
        )

    summary_rows.sort(key=lambda row: row["aggregate_score"], reverse=True)
    return {"summary": summary_rows, "probe_rows": probe_rows}


def find_run_dir(base_dir: Path, run_id: Optional[str]) -> Path:
    runs_dir = base_dir / "runs"
    if run_id:
        run_dir = runs_dir / run_id
        if not run_dir.exists():
            raise FileNotFoundError(f"Run directory not found: {run_dir}")
        return run_dir
    candidates = [path for path in runs_dir.iterdir() if path.is_dir() and (path / "normalized" / "sections.jsonl").exists()]
    if not candidates:
        raise FileNotFoundError(f"No suitable run directories found under {runs_dir}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def build_diagnosis(run_dir: Path) -> Dict[str, Any]:
    sections = read_jsonl(run_dir / "normalized" / "sections.jsonl")
    query_plan = read_json(run_dir / "query_plan.json").get("query_plan") or {}
    title_probe_results = evaluate_title_probes()
    variant_results = evaluate_variants(sections)

    current_counts = Counter(str(row.get("section_type") or "") for row in sections)
    structural_leaks = [
        {
            "doc_id": row.get("doc_id"),
            "section_id": row.get("section_id"),
            "title": row.get("title"),
            "current_type": row.get("section_type"),
            "baseline_variant_type": classify_title(str(row.get("title") or ""), "baseline"),
            "structural_patch_type": classify_title(str(row.get("title") or ""), "structural_patch"),
            "discourse_patch_type": classify_title(str(row.get("title") or ""), "discourse_patch"),
        }
        for row in sections
        if normalize_heading_key(row.get("title")) in {"index", "subject index", "author index", "glossary"}
    ]

    unsupported_must_terms = []
    for term in query_plan.get("must_terms") or []:
        title_hits = 0
        text_hits = 0
        for row in sections:
            if contains_term(str(row.get("title") or ""), term):
                title_hits += 1
            elif contains_term(str(row.get("contextualized_text") or row.get("text") or ""), term):
                text_hits += 1
        unsupported_must_terms.append(
            {
                "term": term,
                "title_hits": title_hits,
                "text_hits": text_hits,
                "any_hits": title_hits + text_hits,
            }
        )

    diagnosis = {
        "run_id": run_dir.name,
        "section_type_counts": dict(current_counts),
        "title_probe_results": title_probe_results,
        "variant_results": variant_results,
        "structural_leaks": structural_leaks,
        "unsupported_must_terms": unsupported_must_terms,
    }
    return diagnosis


def main() -> None:
    parser = argparse.ArgumentParser(description="Phase C / D failure lab")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan")
    parser.add_argument("--run-id", default=None, help="Run id under pdf-scan/runs")
    parser.add_argument("--output-dir", default=None, help="Optional explicit output directory")
    args = parser.parse_args()

    base_dir = Path(args.base_dir).resolve()
    run_dir = find_run_dir(base_dir, args.run_id)
    diagnosis = build_diagnosis(run_dir)

    output_dir = Path(args.output_dir).resolve() if args.output_dir else run_dir / "failure_lab"
    output_dir.mkdir(parents=True, exist_ok=True)

    write_json(output_dir / "diagnosis.json", diagnosis)
    write_json(output_dir / "title_probe_results.json", diagnosis["title_probe_results"])
    write_json(output_dir / "variant_results.json", diagnosis["variant_results"])
    write_json(output_dir / "structural_leaks.json", {"rows": diagnosis["structural_leaks"]})
    write_json(output_dir / "unsupported_must_terms.json", {"rows": diagnosis["unsupported_must_terms"]})

    print("=" * 80)
    print("Phase C/D Failure Lab")
    print("=" * 80)
    print(f"run_id                   {diagnosis['run_id']}")
    print(f"output_dir               {output_dir}")
    print("section_type_counts")
    for key, value in diagnosis["section_type_counts"].items():
        print(f"  {key:24} {value}")
    print("=" * 80)
    print("Title Probe Accuracy")
    print("=" * 80)
    for row in diagnosis["title_probe_results"]["summary"]:
        print(f"{row['variant']:24} accuracy={row['accuracy']:.3f} ({row['correct']}/{row['total']})")
    print("=" * 80)
    print("Variant Ranking Summary")
    print("=" * 80)
    for row in diagnosis["variant_results"]["summary"]:
        print(
            f"{row['variant']:24} score={row['aggregate_score']:6.2f} "
            f"hit@1={row['hit_at_1_total']} hit@3={row['hit_at_3_total']} "
            f"structural_leaks={row['structural_leaks_total']} penalized_top10={row['top10_penalized_total']}"
        )
    print("=" * 80)
    print("Unsupported Must Terms")
    print("=" * 80)
    for row in diagnosis["unsupported_must_terms"]:
        if row["any_hits"] == 0:
            print(f"{row['term']}")
    print("=" * 80)
    print("Structural Leaks")
    print("=" * 80)
    for row in diagnosis["structural_leaks"]:
        print(
            f"{row['doc_id'][:42]:42} | {row['title'][:40]:40} | current={row['current_type']} | patched={row['structural_patch_type']}"
        )


if __name__ == "__main__":
    main()
