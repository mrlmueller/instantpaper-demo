#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from argparse import Namespace
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from phase_a_lab import (
    load_metrics,
    log_event,
    print_kv,
    print_section,
    print_table,
    save_metrics,
    setup_run_logger,
    stable_hash,
    stage_timer,
    run_phase_a,
)
from phase_b_lab import *  # noqa: F401,F403

# Phase C.0 - Canonical document, section, and passage normalization helpers

import json
import math
import re
import sys
import unicodedata
import xml.etree.ElementTree as ET
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PhaseCOptions:
    force_rebuild: bool = False
    doc_limit: Optional[int] = None
    include_doc_ids: Optional[List[str]] = None
    exclude_doc_ids: Optional[List[str]] = None
    max_concurrent_docs: Optional[int] = None
    prefer_outline: bool = True
    use_docling: bool = True
    use_grobid: bool = True
    use_heuristic_headings: bool = True
    heuristic_heading_min_words: int = 1
    heuristic_heading_max_words: int = 18
    heuristic_heading_max_chars: int = 160
    repeated_heading_page_threshold: int = 3
    min_section_chars: int = 120
    min_section_words: int = 20
    min_section_coverage_pct_warn: float = 70.0
    long_doc_page_threshold: int = 40
    passage_target_words: int = 180
    passage_max_words: int = 260
    passage_min_words: int = 70
    synthesize_front_matter: bool = True
    synthesize_document_body: bool = True
    metadata_filter_enabled: bool = True
    micro_section_max_words: int = 20
    micro_section_max_title_words: int = 3
    use_heuristic_recovery: bool = True
    repair_titles_from_anchor_blocks: bool = True
    strong_outline_min_headings: int = 8
    strong_outline_min_distinct_pages: int = 6
    heuristic_recovery_disable_when_strong_outline: bool = True
    heuristic_recovery_disable_when_docling_rich: bool = True
    heuristic_recovery_docling_rich_threshold: int = 12
    enable_numbered_gap_fill_when_docling_noisy: bool = True
    docling_noise_ratio_for_gap_fill: float = 0.22
    docling_numbered_gap_fill_max_words: int = 18
    docling_supplement_strong_outline_numbering_depth: int = 2

    def normalized(self) -> "PhaseCOptions":
        return PhaseCOptions(
            force_rebuild=bool(self.force_rebuild),
            doc_limit=None if self.doc_limit is None else int(self.doc_limit),
            include_doc_ids=[str(x).strip() for x in (self.include_doc_ids or []) if str(x).strip()],
            exclude_doc_ids=[str(x).strip() for x in (self.exclude_doc_ids or []) if str(x).strip()],
            max_concurrent_docs=None if self.max_concurrent_docs is None else max(1, int(self.max_concurrent_docs)),
            prefer_outline=bool(self.prefer_outline),
            use_docling=bool(self.use_docling),
            use_grobid=bool(self.use_grobid),
            use_heuristic_headings=bool(self.use_heuristic_headings),
            heuristic_heading_min_words=int(self.heuristic_heading_min_words),
            heuristic_heading_max_words=int(self.heuristic_heading_max_words),
            heuristic_heading_max_chars=int(self.heuristic_heading_max_chars),
            repeated_heading_page_threshold=int(self.repeated_heading_page_threshold),
            min_section_chars=int(self.min_section_chars),
            min_section_words=int(self.min_section_words),
            min_section_coverage_pct_warn=float(self.min_section_coverage_pct_warn),
            long_doc_page_threshold=int(self.long_doc_page_threshold),
            passage_target_words=int(self.passage_target_words),
            passage_max_words=int(self.passage_max_words),
            passage_min_words=int(self.passage_min_words),
            synthesize_front_matter=bool(self.synthesize_front_matter),
            synthesize_document_body=bool(self.synthesize_document_body),
            metadata_filter_enabled=bool(self.metadata_filter_enabled),
            micro_section_max_words=int(self.micro_section_max_words),
            micro_section_max_title_words=int(self.micro_section_max_title_words),
            use_heuristic_recovery=bool(self.use_heuristic_recovery),
            repair_titles_from_anchor_blocks=bool(self.repair_titles_from_anchor_blocks),
            strong_outline_min_headings=int(self.strong_outline_min_headings),
            strong_outline_min_distinct_pages=int(self.strong_outline_min_distinct_pages),
            heuristic_recovery_disable_when_strong_outline=bool(self.heuristic_recovery_disable_when_strong_outline),
            heuristic_recovery_disable_when_docling_rich=bool(self.heuristic_recovery_disable_when_docling_rich),
            heuristic_recovery_docling_rich_threshold=int(self.heuristic_recovery_docling_rich_threshold),
            enable_numbered_gap_fill_when_docling_noisy=bool(self.enable_numbered_gap_fill_when_docling_noisy),
            docling_noise_ratio_for_gap_fill=float(self.docling_noise_ratio_for_gap_fill),
            docling_numbered_gap_fill_max_words=int(self.docling_numbered_gap_fill_max_words),
            docling_supplement_strong_outline_numbering_depth=int(self.docling_supplement_strong_outline_numbering_depth),
        )


def read_jsonl_rows(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def ascii_fold(text: Any) -> str:
    return unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode("ascii")


def collapse_letterspaced_caps(text: Any) -> str:
    s = str(text or "")
    return re.sub(
        r"\b(?:[A-Z]\s+){3,}[A-Z]\b",
        lambda match: match.group(0).replace(" ", ""),
        s,
    )


def normalize_heading_display(text: Any) -> str:
    s = clean_text(text)
    s = s.replace("•", " ")
    s = s.replace("·", " ")
    s = s.replace("ﬁ", "fi")
    s = s.replace("ﬂ", "fl")
    s = re.sub(r"\s+", " ", s)
    s = collapse_letterspaced_caps(s)
    return s.strip(" :-\t\n\r")


def strip_heading_numbering(text: Any) -> str:
    s = normalize_heading_display(text)
    s = re.sub(r"^(?:chapter|part)\s+[ivxlcdm0-9]+(?:\s*[:.\-])?\s*", "", s, flags=re.IGNORECASE)
    numeric_match = re.match(r"^(?P<prefix>\d+(?:\.\d+){0,4}(?:[.)])?\s+)(?=[A-Za-z])", s)
    if numeric_match and is_reasonable_numeric_heading_prefix(numeric_match.group("prefix")):
        s = s[numeric_match.end() :]
    s = re.sub(r"^[ivxlcdm]+[.)]\s+", "", s, flags=re.IGNORECASE)
    s = re.sub(r"^[A-Z][.)]\s+", "", s)
    return s.strip()


def normalize_heading_key(text: Any) -> str:
    s = ascii_fold(strip_heading_numbering(text)).lower()
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return s.strip()


def heading_key_without_numbers(text: Any) -> str:
    s = normalize_heading_key(text)
    s = re.sub(r"\b\d+\b", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def has_heading_numbering(text: Any) -> bool:
    s = normalize_heading_display(text)
    numeric_match = re.match(r"^(?P<prefix>\d+(?:\.\d+){0,4}(?:[.)])?\s+)(?=[A-Za-z])", s)
    return bool(
        re.match(r"^(?:chapter|part)\s+[ivxlcdm0-9]+\b", s, flags=re.IGNORECASE)
        or (numeric_match and is_reasonable_numeric_heading_prefix(numeric_match.group("prefix")))
        or re.match(r"^[ivxlcdm]+[.)]\s*(?=[A-Za-z])", s, flags=re.IGNORECASE)
    )


def is_reasonable_numeric_heading_prefix(prefix: Any) -> bool:
    s = normalize_heading_display(prefix)
    match = re.match(r"^(?P<base>\d+)(?P<rest>(?:\.\d+){0,4}(?:[.)])?)\s*$", s)
    if not match:
        return False
    base = int(match.group("base"))
    rest = match.group("rest") or ""
    if not rest:
        return base <= 50
    return base <= 200


def alnum_ratio(text: Any) -> float:
    s = ascii_fold(text)
    visible = re.sub(r"\s+", "", s)
    if not visible:
        return 0.0
    return sum(ch.isalnum() for ch in visible) / max(1, len(visible))


def has_math_unicode_signal(text: Any) -> bool:
    for ch in str(text or ""):
        try:
            name = unicodedata.name(ch)
        except Exception:
            continue
        if "MATHEMATICAL" in name or "DOUBLE-STRUCK" in name:
            return True
    return False


def infer_heading_level(title: str, source: str, level_hint: Optional[int] = None) -> int:
    if level_hint is not None:
        try:
            return max(1, int(level_hint))
        except Exception:
            pass
    s = normalize_heading_display(title)
    match = re.match(r"^(\d+(?:\.\d+){0,4})\b", s)
    if match:
        return max(1, len(match.group(1).split(".")))
    if re.match(r"^(?:chapter|part)\b", s, flags=re.IGNORECASE):
        return 1
    if source.startswith("heuristic") and s.isupper() and count_words(s) <= 6:
        return 1
    return 1


def infer_language_guess(text: str) -> str:
    sample = " " + ascii_fold(text).lower() + " "
    english_hits = sum(sample.count(token) for token in [" the ", " and ", " of ", " is ", " for ", " with "])
    german_hits = sum(sample.count(token) for token in [" der ", " die ", " das ", " und ", " mit ", " nicht "])
    if german_hits > english_hits * 1.2:
        return "de"
    if english_hits > 0:
        return "en"
    return "unknown"


def infer_doc_type_guess(metadata: Dict[str, Any]) -> str:
    file_name = str(metadata.get("file_name") or "")
    page_count = int(metadata.get("page_count") or 0)
    outline_count = int((metadata.get("outline_counts") or {}).get("fitz") or 0)
    title = normalize_heading_display((metadata.get("fitz") or {}).get("metadata", {}).get("title") or file_name)
    blob = " ".join(
        [
            file_name,
            title,
            json.dumps((metadata.get("fitz") or {}).get("metadata", {}), ensure_ascii=False),
            json.dumps((metadata.get("pypdf") or {}).get("metadata", {}), ensure_ascii=False),
        ]
    ).lower()
    if page_count >= 120:
        return "book_or_long_report"
    if any(token in blob for token in ["journal", "doi", "accepted manuscript", "abstract"]):
        return "scholarly_article"
    if outline_count >= 15 or any(token in blob for token in ["contents", "preface", "chapter"]):
        return "report_or_book"
    return "paper_or_report"


def outline_rows_from_metadata(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for source_name in ["fitz", "pypdf"]:
        for item in ((metadata.get(source_name) or {}).get("outline") or []):
            title = normalize_heading_display(item.get("title"))
            page = int(item.get("page") or 0)
            if not title or page <= 0:
                continue
            rows.append({"source": source_name, "title": title, "page": page, "level": int(item.get("level") or 0)})
    return rows


def distinct_outline_pages(metadata: Dict[str, Any]) -> List[int]:
    return sorted({int(row.get("page") or 0) for row in outline_rows_from_metadata(metadata) if int(row.get("page") or 0) > 0})


def has_strong_outline(metadata: Dict[str, Any], options: PhaseCOptions) -> bool:
    pages = distinct_outline_pages(metadata)
    return len(pages) >= int(options.strong_outline_min_distinct_pages) and len(outline_rows_from_metadata(metadata)) >= int(options.strong_outline_min_headings)


def non_body_outline_pages(metadata: Dict[str, Any]) -> set:
    blocked = set()
    for row in outline_rows_from_metadata(metadata):
        section_type = classify_section_type(str(row.get("title") or ""))
        if section_type in {"table_of_contents", "references", "appendix", "acknowledgements", "index", "front_matter"}:
            blocked.add(int(row.get("page") or 0))
            continue
        if str(row.get("title") or "").strip().lower() in {"title page", "copyright page", "list of contributors", "preface"}:
            blocked.add(int(row.get("page") or 0))
    return {page for page in blocked if page > 0}


SECTION_TYPE_PATTERNS: List[Tuple[str, List[str]]] = [
    ("table_of_contents", [r"^contents$", r"^table of contents$", r"^list of figures$", r"^list of tables$"]),
    ("abstract", [r"^abstract$"]),
    ("introduction", [r"^introduction$", r"^1 introduction$"]),
    (
        "background",
        [
            r"^background$",
            r"^literature review$",
            r"^theoretical background$",
            r"^related work$",
            r"^conceptual background$",
            r"^conceptual framework$",
            r"^theoretical framework$",
            r"^theory and hypotheses$",
        ],
    ),
    (
        "methods",
        [
            r"^methods?$",
            r"^methodology$",
            r"^research design$",
            r"^data and methods$",
            r"^materials and methods$",
            r"^data collection$",
            r"^research methods?$",
            r"^empirical setting$",
            r"^study design$",
            r"^measures?$",
            r"^main measures$",
            r"^measurement$",
            r"^measurement model$",
            r"^sample and procedures?$",
            r"^variables?$",
        ],
    ),
    ("results", [r"^results?$", r"^analysis and results$", r"^findings$", r"^matching and findings$", r"^empirical results$", r"^analysis$", r"^empirical analysis$", r"^results and discussion$", r"^data analysis$"]),
    ("discussion", [r"^discussion$", r"^discussion and implications$", r"^implications$", r"^theoretical implications$", r"^managerial implications$", r"^practical implications$", r"^limitations$", r"^limitations and future research$"]),
    ("conclusion", [r"^conclusion$", r"^conclusions$", r"^general discussion and conclusions?$", r"^summary and conclusion$", r"^future research$", r"^concluding remarks$", r"^summary$", r"^general discussion$"]),
    ("references", [r"^references$", r"^bibliography$", r"^works cited$"]),
    ("appendix", [r"^appendix(?:\s+[a-z0-9]+)?$", r"^appendices$", r"^supplement(?:ary)? materials?$", r"^supplementary information$"]),
    ("index", [r"^index$", r"^subject index$", r"^author index$", r"^glossary$", r"^nomenclature$", r"^abbreviations?$"]),
    ("acknowledgements", [r"^acknowledg?ments?$", r"^author contributions$", r"^funding$"]),
]


def classify_section_type(title: str) -> str:
    key = normalize_heading_key(title)
    if not key:
        return "body_other"
    for section_type, patterns in SECTION_TYPE_PATTERNS:
        for pattern in patterns:
            if re.match(pattern, key, flags=re.IGNORECASE):
                return section_type
    if key in {"front matter", "title page", "copyright page", "preface", "foreword", "list of contributors", "about the authors"}:
        return "front_matter"
    return "body_other"


STRUCTURAL_WRAPPER_PATTERNS = [
    r"^part\s+[ivxlcdm0-9]+(?:\b|:)",
    r"^chapter\s+[ivxlcdm0-9]+(?:\b|:)$",
]

ALWAYS_RETRIEVAL_SUPPRESSED_TYPES = {"table_of_contents", "index", "references", "acknowledgements"}
EXPLICIT_RETRIEVAL_SUPPRESSED_TITLES = {
    "front matter",
    "title page",
    "copyright page",
    "contents",
    "table of contents",
    "list of contributors",
    "about the authors",
    "open access",
    "citation",
    "citation information",
    "conflict of interest",
    "conflict of interest statement",
    "data availability",
    "how to cite this article",
    "acmreference format",
}

CAPTION_PREFIX_PATTERNS = [
    r"^(?:table|figure|fig\.?)\s*[a-z0-9ivxlcdm]+(?:[.:)]|\b)",
]

STRONG_METADATA_LINE_PATTERNS = [
    r"^academic editor\b",
    r"^additional information and\b",
    r"^a section of the journal\b",
    r"^declarations can be found on\b",
    r"^open access\b",
    r"^journal pre[- ]proof\b",
    r"^latest updates\b",
    r"^pdf download\b",
    r"^please cite this article\b",
    r"^how to cite this article\b",
    r"^doi\b",
    r"^copyright\b",
    r"^distributed under\b",
    r"^creative commons\b",
    r"^published:\b",
    r"^this article was submitted to\b",
    r"^this article belongs to the section\b",
]

METADATA_LINE_PATTERNS = [
    *STRONG_METADATA_LINE_PATTERNS,
    r"^submitted\b",
    r"^accepted\b",
    r"^received\b",
    r"^revised\b",
    r"^total citations\b",
    r"^total downloads\b",
    r"^page \d+\b",
    r"^paper \d+\b",
    r"^[a-z]{2,}\s+\d{4}\s+paper\b",
]

CITATION_BLOCK_PATTERNS = [
    r"^citation:?$",
    r"^front\.\s*[a-z].*\d+(?:\(\d+\))?:\d+",
    r"^how to cite this article\b",
    r"^please cite this article\b",
]

HEADER_FOOTER_METADATA_PATTERNS = [
    r"^frontiers in\b",
    r"^front\.\s*[a-z]",
    r"\bwww\.",
    r"\bvolume \d+\b",
    r"\barticle \d+\b",
    r"\bdownloaded from\b",
    r"\bcommons\.org/licenses\b",
    r"\bcreative commons license\b",
    r"\bdistribution, and reproduction in any medium\b",
    r"\bpermits unrestricted use\b",
    r"\bprovided you give\b",
    r"\bappropriate credit to the original author",
    r"\blink to the creative commons license\b",
    r"\bindicate if changes were made\b",
    r"\bpublished by elsevier\b",
    r"\bcc by-nc-nd license\b",
    r"\bopen access article under the cc\b",
    r"\bbus inf syst eng\b",
    r"\bet al\.:.*\(\d{4}\)\.?$",
    r"\bdoi\.org/",
]

AFFILIATION_KEYWORDS = {
    "academy",
    "college",
    "department",
    "faculty",
    "hospital",
    "institute",
    "laboratory",
    "school",
    "university",
}

ADDRESS_LINE_PATTERNS = [
    r"\b(?:street|strasse|straße|avenue|road|boulevard|campus|suite)\b",
    r"\b\d{4,6}\b.*\b(?:city|country|kong|liechtenstein|germany|austria|switzerland|romania|china|usa|uk)\b",
]

AUTHOR_LINE_PREFIX_PATTERNS = [
    r"^(?:dr|prof|mr|mrs|ms)\.?\b",
]


def first_nonempty_line(text: Any) -> str:
    for part in re.split(r"\n+", str(text or "")):
        cleaned = clean_text(part)
        if cleaned:
            return cleaned
    return ""


def extract_heading_prefix_variant(text: Any) -> str:
    s = normalize_heading_display(text)
    if not s:
        return ""
    match = re.match(r"^(.{4,180}?)\.\s+[A-Z]", s)
    if match:
        prefix = normalize_heading_display(match.group(1))
        words = count_words(prefix)
        if 2 <= words <= 24:
            return prefix
        if words == 1 and (prefix.isupper() or classify_section_type(prefix) != "body_other"):
            return prefix
    return ""


def extract_heading_colon_prefix_variant(text: Any) -> str:
    s = normalize_heading_display(text)
    if not s or ":" not in s:
        return ""
    prefix = normalize_heading_display(s.split(":", 1)[0])
    if not prefix:
        return ""
    words = count_words(prefix)
    if 2 <= words <= 12 and not prefix.endswith("."):
        titlecase_hits = sum(1 for part in prefix.split() if part[:1].isupper())
        if has_heading_numbering(prefix) or prefix.isupper() or titlecase_hits >= max(1, math.ceil(words * 0.5)):
            return prefix
    return ""


def is_probable_caption_text(text: Any) -> bool:
    first_line = normalize_heading_display(first_nonempty_line(text))
    if not first_line:
        return False
    return any(re.match(pattern, first_line, flags=re.IGNORECASE) for pattern in CAPTION_PREFIX_PATTERNS)


def is_probable_metadata_line(text: Any) -> bool:
    return is_probable_metadata_line_for_doc(text, doc_title="")


def is_probable_running_title_line(text: Any, *, doc_title: Any) -> bool:
    line = normalize_heading_display(text)
    title = normalize_heading_display(doc_title)
    if not line or not title:
        return False
    if count_words(line) < 2 or count_words(line) > 14:
        return False
    if re.search(r"[.!?]$", line):
        return False
    line_tokens = {token for token in re.findall(r"[a-z0-9]+", ascii_fold(line).lower()) if len(token) >= 4}
    title_tokens = {token for token in re.findall(r"[a-z0-9]+", ascii_fold(title).lower()) if len(token) >= 4}
    if not line_tokens or not title_tokens:
        return False
    overlap = len(line_tokens & title_tokens) / max(1, len(line_tokens))
    return overlap >= 0.6


def is_probable_metadata_line_for_doc(text: Any, *, doc_title: Any) -> bool:
    line = normalize_heading_display(text)
    if not line:
        return False
    folded = ascii_fold(line).lower()
    if any(re.match(pattern, folded, flags=re.IGNORECASE) for pattern in METADATA_LINE_PATTERNS):
        return True
    if re.fullmatch(r"\d{1,4}", folded):
        return True
    if "@" in line or re.match(r"^(?:e-?mail|email)\s*:", folded):
        return True
    if re.match(r"^https?://", folded) and len(re.findall(r"\s+", line)) <= 2:
        return True
    if "doi.org/" in folded and count_words(line) <= 16:
        return True
    if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in HEADER_FOOTER_METADATA_PATTERNS):
        return True
    if any(re.match(pattern, folded, flags=re.IGNORECASE) for pattern in CITATION_BLOCK_PATTERNS):
        return True
    if is_probable_author_line(line) and count_words(line) <= 6:
        return True
    if is_probable_running_title_line(line, doc_title=doc_title):
        return True
    return False


def is_probable_author_line(text: Any) -> bool:
    line = normalize_heading_display(text)
    if not line:
        return False
    folded = ascii_fold(line).lower()
    if re.search(r"\bet al\.\s*$", folded) and count_words(line) <= 6:
        return True
    if any(re.match(pattern, folded, flags=re.IGNORECASE) for pattern in AUTHOR_LINE_PREFIX_PATTERNS):
        return True
    if count_words(line) < 2 or count_words(line) > 14:
        return False
    if re.search(r"[.!?]$", line):
        return False
    if "@" in line or any(keyword in folded for keyword in AFFILIATION_KEYWORDS):
        return False
    alpha_tokens = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)
    if not alpha_tokens:
        return False
    capitalized = sum(1 for token in alpha_tokens if token[:1].isupper())
    stopword_hits = sum(1 for token in alpha_tokens if ascii_fold(token).lower() in {"and", "the", "of", "in", "for", "with", "to", "from", "on"})
    if capitalized >= max(2, math.ceil(len(alpha_tokens) * 0.6)) and stopword_hits <= 1:
        return True
    return False


def is_probable_affiliation_line(text: Any) -> bool:
    line = normalize_heading_display(text)
    if not line:
        return False
    folded = ascii_fold(line).lower()
    if any(keyword in folded for keyword in AFFILIATION_KEYWORDS):
        return True
    if any(re.search(pattern, folded, flags=re.IGNORECASE) for pattern in ADDRESS_LINE_PATTERNS):
        return True
    return False


def is_probable_body_content_line(text: Any, *, doc_title: Any) -> bool:
    line = normalize_heading_display(text)
    if not line:
        return False
    folded = ascii_fold(line).lower()
    words = count_words(line)
    if words < 5:
        return False
    if is_probable_metadata_line_for_doc(line, doc_title=doc_title) or is_probable_author_line(line) or is_probable_affiliation_line(line):
        return False
    if not re.search(r"[a-z]", folded):
        return False
    alpha_tokens = re.findall(r"[A-Za-z][A-Za-z.'-]*", line)
    if alpha_tokens:
        capitalized = sum(1 for token in alpha_tokens if token[:1].isupper())
        if words <= 10 and capitalized >= max(4, math.ceil(len(alpha_tokens) * 0.85)):
            return False
    return True


def is_probable_metadata_block_text(text: Any) -> bool:
    raw = clean_text(text)
    if not raw:
        return False
    lines = [clean_text(part) for part in re.split(r"\n+", raw) if clean_text(part)]
    if not lines:
        return False
    hits = sum(1 for line in lines if is_probable_metadata_line(line))
    if hits >= max(1, math.ceil(len(lines) * 0.5)):
        return True
    blob = ascii_fold(raw).lower()
    if any(token in blob for token in ["doi ", "open access", "journal pre-proof", "academic editor", "total citations", "total downloads", "pdf download", "creative commons"]):
        return True
    return False


def strip_metadata_lines(text: Any, *, doc_title: Any = "") -> Tuple[str, int]:
    raw = clean_text(text)
    if not raw:
        return "", 0
    lines = [clean_text(part) for part in re.split(r"\n+", raw) if clean_text(part)]
    kept: List[str] = []
    removed = 0
    skip_short_followups = 0
    body_started = False
    in_metadata_run = False
    for line in lines:
        body_like = is_probable_body_content_line(line, doc_title=doc_title)
        author_like = is_probable_author_line(line)
        affiliation_like = is_probable_affiliation_line(line)
        citation_like = any(re.match(pattern, ascii_fold(normalize_heading_display(line)).lower(), flags=re.IGNORECASE) for pattern in CITATION_BLOCK_PATTERNS)
        if in_metadata_run:
            if body_like:
                in_metadata_run = False
                body_started = True
            else:
                removed += 1
                continue
        if skip_short_followups > 0 and count_words(line) <= 12 and not body_like:
            removed += 1
            skip_short_followups -= 1
            continue
        folded = ascii_fold(normalize_heading_display(line)).lower()
        strong_match = any(re.match(pattern, folded, flags=re.IGNORECASE) for pattern in STRONG_METADATA_LINE_PATTERNS)
        if strong_match:
            removed += 1
            if count_words(line) <= 4 or line.endswith(":"):
                skip_short_followups = max(skip_short_followups, 1)
            continue
        if is_probable_metadata_line_for_doc(line, doc_title=doc_title):
            removed += 1
            if citation_like or line.endswith(":"):
                skip_short_followups = max(skip_short_followups, 4 if citation_like else 2)
                in_metadata_run = True
            continue
        if not body_started:
            if body_like:
                body_started = True
                kept.append(line)
                continue
            if author_like or affiliation_like or count_words(line) <= 4:
                removed += 1
                if author_like or affiliation_like:
                    in_metadata_run = True
                    skip_short_followups = max(skip_short_followups, 2)
                continue
        kept.append(line)
    return "\n".join(kept).strip(), removed


def clean_section_block_text(text: Any, *, options: PhaseCOptions, doc_title: Any = "") -> Tuple[str, int]:
    raw = clean_text(text)
    if not raw:
        return "", 0
    if not bool(options.metadata_filter_enabled):
        return raw, 0
    cleaned, removed = strip_metadata_lines(raw, doc_title=doc_title)
    return cleaned, removed


def infer_structural_wrapper_reasons(
    *,
    title: str,
    section_type: str,
    section_text: str,
    word_count: int,
    title_word_count: int,
    level: int,
    quality_flags: List[str],
    child_count: int,
    options: PhaseCOptions,
) -> List[str]:
    key = normalize_heading_key(title)
    reasons: List[str] = []
    if word_count <= 15:
        reasons.append("near_empty_section")
    if is_probable_caption_text(section_text) and word_count <= 40:
        reasons.append("caption_like_section")
    if is_probable_metadata_block_text(section_text) and word_count <= 80:
        reasons.append("metadata_block_section")
    if "metadata_stripped" in set(quality_flags or []) and word_count <= 30 and section_type == "body_other":
        reasons.append("metadata_residual_section")
    if section_type in ALWAYS_RETRIEVAL_SUPPRESSED_TYPES:
        reasons.append(f"{section_type}_section")
    if key in EXPLICIT_RETRIEVAL_SUPPRESSED_TITLES:
        reasons.append("explicit_wrapper_title")
    if any(re.match(pattern, key, flags=re.IGNORECASE) for pattern in STRUCTURAL_WRAPPER_PATTERNS):
        if child_count > 0 or "tiny_section" in set(quality_flags or []) or word_count <= 120:
            reasons.append("part_or_chapter_wrapper")
    if child_count > 0 and "tiny_section" in set(quality_flags or []) and section_type in {"body_other", "front_matter"}:
        reasons.append("tiny_parent_wrapper")
    if (
        level >= 2
        and title_word_count <= int(options.micro_section_max_title_words)
        and word_count <= int(options.micro_section_max_words)
        and child_count == 0
        and section_type == "body_other"
    ):
        reasons.append("micro_section")
    return list(dict.fromkeys([reason for reason in reasons if reason]))


KNOWN_NOISE_HEADING_PATTERNS = [
    r"^accepted manuscript$",
    r"^author contributions$",
    r"^credit author statement$",
    r"^credit authorship contribution statement$",
    r"^highlights$",
    r"^keywords$",
    r"^open access$",
    r"^orcid$",
    r"^research article$",
    r"^please cite this article",
    r"^how to cite this article$",
    r"^citation$",
    r"^doi$",
    r"^pii$",
    r"^received date$",
    r"^revised date$",
    r"^accepted date$",
    r"^significance$",
    r"^to appear in$",
    r"^publication year$",
    r"^standard error$",
    r"^reference$",
    r"^figure \d+",
    r"^table \d+",
    r"^model(?: \d+)?$",
    r"^sample$",
    r"^dv[: ]",
    r"^products with$",
]


def is_probable_noise_heading(
    title: str,
    *,
    source: str,
    repeated_pages: int,
    repeated_page_threshold: int,
    doc_title_key: str,
) -> Tuple[bool, str]:
    display = normalize_heading_display(title)
    key = normalize_heading_key(display)
    words = count_words(display)
    if re.search(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", str(title or "")):
        return True, "control_characters"
    if has_math_unicode_signal(title):
        return True, "mathematical_unicode_signal"
    if not key:
        return True, "empty_after_normalization"
    if len(display) < 3:
        return True, "too_short"
    if len(display) > 180:
        return True, "too_long"
    if words > 24:
        return True, "too_many_words"
    if display[:1].islower() and not has_heading_numbering(display):
        return True, "starts_lowercase"
    if alnum_ratio(display) < 0.45 and not has_heading_numbering(display):
        return True, "low_alnum_ratio"
    if repeated_pages >= int(repeated_page_threshold) and not source.startswith("outline"):
        return True, "repeated_page_header"
    if re.search(r"(->|<-|=|<|>|@|\bvol\.\b|\bno\.\b|issn|isbn|doi:)", display, flags=re.IGNORECASE):
        return True, "metadata_or_table_signal"
    if re.match(r"^\d+\.\s+(?:[A-Z]\.\s*){1,4}[A-Z]", display):
        return True, "reference_entry_signal"
    if is_probable_reference_heading(display):
        return True, "reference_or_author_heading"
    if re.search(r"\*{2,}|={2,}|%|±|β|γ|δ", display):
        return True, "formula_or_numeric_signal"
    if key and sum(ch.isdigit() for ch in display) >= max(3, math.ceil(len(display) * 0.18)) and not has_heading_numbering(display):
        return True, "digit_heavy"
    for pattern in KNOWN_NOISE_HEADING_PATTERNS:
        if re.match(pattern, key, flags=re.IGNORECASE):
            return True, "known_noise_pattern"
    if doc_title_key and not source.startswith("outline") and title_similarity(key, doc_title_key) >= 0.9:
        return True, "document_title_repeat"
    return False, ""


def is_doc_title_prefix_fragment(title: str, *, doc_title_key: str, doc_title_loose_key: str) -> bool:
    key = normalize_heading_key(title)
    loose_key = heading_key_without_numbers(title) or key
    if not key or not doc_title_key:
        return False
    if key == doc_title_key or (doc_title_loose_key and loose_key == doc_title_loose_key):
        return False
    if count_words(title) < 3:
        return False
    if (
        doc_title_key.startswith(key)
        and len(key) >= max(12, int(len(doc_title_key) * 0.45))
    ):
        return True
    if (
        doc_title_loose_key
        and loose_key
        and doc_title_loose_key.startswith(loose_key)
        and len(loose_key) >= max(12, int(len(doc_title_loose_key) * 0.45))
    ):
        return True
    return False


def is_probable_reference_heading(text: Any) -> bool:
    display = normalize_heading_display(text)
    if not display:
        return False
    words = count_words(display)
    if words < 2 or words > 20:
        return False
    if re.search(r"\(\d{4}\)\.?$", display) and display.count(",") >= 1:
        return True
    if re.match(r"^[A-Z][A-Za-z'’.-]+,\s+(?:[A-Z]\.\s*){1,4}", display):
        return True
    if re.match(r"^[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?(?:\s*(?:and|&)\s+[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?)*\.?$", display):
        return True
    if re.match(r"^[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?,\s*(?:and|&)\s+[A-Z][A-Za-z'’.-]+,\s*[A-Z](?:\.)?\.?$", display):
        return True
    if re.match(r"^(?:[A-Z]\.\s*){1,4}[A-Z][A-Za-z'’-]+(?:,\s*(?:[A-Z]\.\s*){1,4}[A-Z][A-Za-z'’-]+)+", display):
        return True
    if display.count(",") >= 2 and any(ch.isdigit() for ch in display) and not re.search(r"[.!?]$", display):
        return True
    if re.match(r"^report no\.", ascii_fold(display).lower()):
        return True
    return False


def title_similarity(a: str, b: str) -> float:
    a_key = normalize_heading_key(a)
    b_key = normalize_heading_key(b)
    if not a_key or not b_key:
        return 0.0
    if a_key == b_key:
        return 1.0
    a_tokens = set(a_key.split())
    b_tokens = set(b_key.split())
    overlap = len(a_tokens & b_tokens) / max(1, len(a_tokens | b_tokens))
    seq = SequenceMatcher(None, a_key, b_key).ratio()
    return max(overlap, seq)


def block_text_variants(text: str) -> List[str]:
    raw = clean_text(text)
    if not raw:
        return []
    variants = [raw]
    parts = [normalize_heading_display(part) for part in re.split(r"\n+", raw) if normalize_heading_display(part)]
    variants.extend(parts[:6])
    first_line = first_nonempty_line(raw)
    if first_line:
        variants.append(first_line)
    prefix = extract_heading_prefix_variant(raw)
    if prefix:
        variants.append(prefix)
    stripped_prefix = strip_heading_numbering(prefix) if prefix else ""
    if stripped_prefix and stripped_prefix != prefix:
        variants.append(stripped_prefix)
    colon_prefix = extract_heading_colon_prefix_variant(raw)
    if colon_prefix:
        variants.append(colon_prefix)
    stripped_colon_prefix = strip_heading_numbering(colon_prefix) if colon_prefix else ""
    if stripped_colon_prefix and stripped_colon_prefix != colon_prefix:
        variants.append(stripped_colon_prefix)
    return list(dict.fromkeys([v for v in variants if v]))


def heading_candidates_from_block_text(text: Any, options: PhaseCOptions, *, include_raw: bool = False) -> List[str]:
    raw = clean_text(text)
    if not raw:
        return []
    variants = [extract_heading_prefix_variant(raw), extract_heading_colon_prefix_variant(raw)]
    if include_raw:
        variants.insert(0, normalize_heading_display(raw))
    expanded: List[str] = []
    for variant in variants:
        value = normalize_heading_display(variant)
        if not value:
            continue
        expanded.append(value)
        stripped = strip_heading_numbering(value)
        if stripped and stripped != value:
            expanded.append(stripped)
        if value.endswith(".") and count_words(value) <= 8:
            expanded.append(value[:-1].strip())
    out: List[str] = []
    seen = set()
    for candidate in expanded:
        normalized = normalize_heading_display(candidate)
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        if is_probable_caption_text(normalized):
            continue
        if looks_like_heading_text(normalized, options):
            out.append(normalized)
    return out


def page_has_probable_multi_column_layout(page_rows: List[Dict[str, Any]]) -> bool:
    text_rows = [
        row
        for row in page_rows
        if count_words(row.get("text")) >= 2
        and int(row.get("char_len") or len(str(row.get("text") or ""))) >= 12
        and float(row.get("x1") or 0.0) > float(row.get("x0") or 0.0)
    ]
    if len(text_rows) < 6:
        return False
    min_x = min(float(row.get("x0") or 0.0) for row in text_rows)
    max_x = max(float(row.get("x1") or 0.0) for row in text_rows)
    page_width = max(1.0, max_x - min_x)
    mid_x = min_x + page_width * 0.5
    narrow_rows = [
        row
        for row in text_rows
        if (float(row.get("x1") or 0.0) - float(row.get("x0") or 0.0)) <= page_width * 0.72
    ]
    left_rows = [row for row in narrow_rows if ((float(row.get("x0") or 0.0) + float(row.get("x1") or 0.0)) * 0.5) < mid_x]
    right_rows = [row for row in narrow_rows if ((float(row.get("x0") or 0.0) + float(row.get("x1") or 0.0)) * 0.5) >= mid_x]
    if len(left_rows) < 2 or len(right_rows) < 2:
        return False
    left_right_edge = max(float(row.get("x1") or 0.0) for row in left_rows)
    right_left_edge = min(float(row.get("x0") or 0.0) for row in right_rows)
    return (right_left_edge - left_right_edge) >= page_width * 0.04


def sort_page_blocks_for_reading_order(page_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if not page_rows:
        return []
    multi_column = page_has_probable_multi_column_layout(page_rows)
    min_x = min(float(row.get("x0") or 0.0) for row in page_rows)
    max_x = max(float(row.get("x1") or 0.0) for row in page_rows)
    max_y = max(float(row.get("y1") or 0.0) for row in page_rows)
    page_width = max(1.0, max_x - min_x)
    mid_x = min_x + page_width * 0.5
    top_band = max_y * 0.24

    def key(row: Dict[str, Any]) -> Tuple[float, float, float, float, int]:
        x0 = float(row.get("x0") or 0.0)
        x1 = float(row.get("x1") or 0.0)
        y0 = float(row.get("y0") or 0.0)
        width = max(0.0, x1 - x0)
        block_index = int(row.get("block_index") or 0)
        if not multi_column:
            return (round(y0 / 12.0), y0, x0, width * -1.0, block_index)
        center_x = (x0 + x1) * 0.5
        is_full_width = width >= page_width * 0.72
        if is_full_width and y0 <= top_band:
            column_rank = -1
        elif is_full_width:
            column_rank = 2
        else:
            column_rank = 0 if center_x < mid_x else 1
        return (column_rank, round(y0 / 12.0), y0, x0, block_index)

    return sorted(page_rows, key=key)


def build_block_index(block_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    pages: Dict[int, List[Dict[str, Any]]] = {}
    for row in block_rows:
        page = int(row.get("page") or 0)
        pages.setdefault(page, []).append(dict(row))

    ordered: List[Dict[str, Any]] = []
    page_layout_flags: Dict[int, Dict[str, Any]] = {}
    for page in sorted(pages):
        ordered_page = sort_page_blocks_for_reading_order(pages[page])
        page_layout_flags[page] = {
            "probable_multi_column": page_has_probable_multi_column_layout(pages[page]),
            "block_count": len(ordered_page),
        }
        pages[page] = ordered_page
        ordered.extend(ordered_page)

    repeated: Dict[str, set] = {}
    repeated_loose: Dict[str, set] = {}
    for abs_idx, row in enumerate(ordered):
        row["abs_block_index"] = abs_idx
        page = int(row.get("page") or 0)
        key = normalize_heading_key(row.get("text"))
        loose_key = heading_key_without_numbers(row.get("text"))
        words = count_words(row.get("text"))
        if key and 1 <= words <= 8 and len(normalize_heading_display(row.get("text"))) <= 80:
            repeated.setdefault(key, set()).add(page)
        if loose_key and 2 <= len(loose_key.split()) <= 12 and len(normalize_heading_display(row.get("text"))) <= 120:
            repeated_loose.setdefault(loose_key, set()).add(page)
    return {
        "ordered_blocks": ordered,
        "blocks_by_page": pages,
        "repeated_heading_pages": {key: len(page_set) for key, page_set in repeated.items()},
        "repeated_heading_pages_wo_numbers": {key: len(page_set) for key, page_set in repeated_loose.items()},
        "total_block_chars": sum(int(row.get("char_len") or len(row.get("text") or "")) for row in ordered),
        "total_block_words": sum(int(row.get("word_count") or count_words(row.get("text"))) for row in ordered),
        "page_layout_flags": page_layout_flags,
    }


def load_phase_b_bundle(run_ctx: Any, bundle_row: Dict[str, Any]) -> Dict[str, Any]:
    run_dir = Path(run_ctx.run_dir)

    def resolve(rel_path: Optional[str]) -> Optional[Path]:
        if not rel_path:
            return None
        path = Path(rel_path)
        if not path.is_absolute():
            path = run_dir / path
        return path

    metadata_path = resolve(bundle_row.get("metadata_json"))
    pages_path = resolve(bundle_row.get("pymupdf_pages_jsonl"))
    blocks_path = resolve(bundle_row.get("pymupdf_blocks_jsonl"))
    docling_path = resolve(bundle_row.get("docling_json"))
    diagnostics_path = resolve(bundle_row.get("diagnostics_json"))
    grobid_summary_path = resolve(bundle_row.get("grobid_summary_json"))
    grobid_tei_path = resolve(bundle_row.get("grobid_tei_xml"))
    return {
        "bundle_row": bundle_row,
        "metadata": read_json(metadata_path) if metadata_path and metadata_path.exists() else {},
        "pages": read_jsonl_rows(pages_path) if pages_path and pages_path.exists() else [],
        "blocks": read_jsonl_rows(blocks_path) if blocks_path and blocks_path.exists() else [],
        "docling": read_json(docling_path) if docling_path and docling_path.exists() else {},
        "diagnostics": read_json(diagnostics_path) if diagnostics_path and diagnostics_path.exists() else {},
        "grobid_summary": read_json(grobid_summary_path) if grobid_summary_path and grobid_summary_path.exists() else {},
        "grobid_tei_text": grobid_tei_path.read_text(encoding="utf-8", errors="ignore") if grobid_tei_path and grobid_tei_path.exists() else "",
        "paths": {
            "metadata": metadata_path,
            "pages": pages_path,
            "blocks": blocks_path,
            "docling": docling_path,
            "diagnostics": diagnostics_path,
            "grobid_summary": grobid_summary_path,
            "grobid_tei": grobid_tei_path,
        },
    }


def extract_outline_proposals(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    seen = set()
    for source_name in ["fitz", "pypdf"]:
        outline = ((metadata.get(source_name) or {}).get("outline") or [])
        for idx, item in enumerate(outline):
            title = normalize_heading_display(item.get("title"))
            page = item.get("page")
            level = item.get("level")
            key = (normalize_heading_key(title), int(page or 0), int(level or 0), source_name)
            if key in seen or not title:
                continue
            seen.add(key)
            proposals.append(
                {
                    "proposal_id": f"outline_{source_name}_{idx}",
                    "source": f"outline_{source_name}",
                    "title": title,
                    "page": int(page) if page else None,
                    "level_hint": int(level) if level else None,
                    "source_priority": 100 if source_name == "fitz" else 95,
                    "raw": item,
                }
            )
    return proposals


def extract_docling_proposals(docling_bundle: Dict[str, Any]) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    section_headers = list((docling_bundle or {}).get("section_headers") or [])
    if section_headers:
        texts = section_headers
    else:
        doc = (docling_bundle or {}).get("document") or {}
        texts = doc.get("texts") or []
    for idx, item in enumerate(texts):
        if str(item.get("label") or "") != "section_header":
            continue
        title = normalize_heading_display(item.get("text"))
        prov = item.get("prov") or []
        page = None
        if prov:
            page = prov[0].get("page_no")
        proposals.append(
            {
                "proposal_id": f"docling_{idx}",
                "source": "docling",
                "title": title,
                "page": int(page) if page else None,
                "level_hint": None,
                "source_priority": 80,
                "raw": item,
            }
        )
    return proposals


def extract_grobid_proposals(grobid_tei_text: str) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    xml_text = str(grobid_tei_text or "").strip()
    if not xml_text:
        return proposals
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return proposals
    idx = 0
    for head in root.findall(".//{*}head"):
        title = normalize_heading_display("".join(head.itertext()))
        if not title:
            continue
        proposals.append(
            {
                "proposal_id": f"grobid_{idx}",
                "source": "grobid",
                "title": title,
                "page": None,
                "level_hint": None,
                "source_priority": 90,
                "raw": {"tag": head.tag},
            }
        )
        idx += 1
    return proposals


def estimate_docling_noise_ratio(docling_props: List[Dict[str, Any]]) -> float:
    if not docling_props:
        return 0.0
    noisy = 0
    for row in docling_props:
        title = normalize_heading_display(row.get("title"))
        if (
            not title
            or is_probable_caption_text(title)
            or is_probable_metadata_block_text(title)
            or is_probable_heuristic_heading_noise(title)
            or normalize_heading_key(title) in {"keywords", "accepted manuscript"}
        ):
            noisy += 1
    return noisy / max(1, len(docling_props))


def count_numbered_proposals(rows: List[Dict[str, Any]]) -> int:
    return sum(1 for row in rows if has_heading_numbering(row.get("title")))


def extract_numbered_gap_fill_proposals(block_rows: List[Dict[str, Any]], options: PhaseCOptions) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    for row in block_rows:
        text = normalize_heading_display(row.get("text"))
        if not text or not has_heading_numbering(text):
            continue
        page = int(row.get("page") or 0) or None
        if (
            is_probable_caption_text(text)
            or is_probable_metadata_block_text(text)
            or has_table_row_signal(text)
            or is_probable_heuristic_heading_noise(text)
            or is_sentence_like_heading_noise(text)
        ):
            continue
        stripped = strip_heading_numbering(text)
        if count_words(stripped) > int(options.docling_numbered_gap_fill_max_words):
            continue
        folded = ascii_fold(stripped).lower()
        if page and page <= 2 and any(token in folded for token in ["department of", "school of", "university", "college", "institute"]):
            continue
        if re.search(r"\b(?:vol\.?|no\.?|quarterly|journal|issue|september|october|november|december|january|february|march|april|may|june|july|august)\b", folded):
            continue
        if re.match(r"^\d{1,2}\s+(?:january|february|march|april|may|june|july|august|september|october|november|december)\s+\d{4}\)?$", folded):
            continue
        section_type = classify_section_type(stripped)
        titlecase_hits = sum(1 for token in stripped.split() if token[:1].isupper())
        if (
            section_type == "body_other"
            and not (stripped.isupper() and count_words(stripped) <= 8)
            and titlecase_hits < max(1, math.ceil(count_words(stripped) * 0.5))
        ):
            continue
        if stripped.endswith(".") and count_words(stripped) >= 4:
            continue
        proposals.append(
            {
                "proposal_id": f"heur_gap_{row.get('page')}_{row.get('block_index')}",
                "source": "heuristic_gap_fill",
                "title": text,
                "page": page,
                "level_hint": infer_heading_level(text, "heuristic_gap_fill"),
                "source_priority": 76,
                "raw": {"page": row.get("page"), "block_index": row.get("block_index")},
                "anchor_page": row.get("page"),
                "anchor_block_index": row.get("block_index"),
                "anchor_abs_block_index": row.get("abs_block_index"),
                "anchor_method": "direct_block",
                "anchor_confidence": 1.0,
            }
        )
    return proposals


def extract_structural_gap_fill_proposals(
    block_rows: List[Dict[str, Any]],
    options: PhaseCOptions,
    *,
    existing_title_keys: Optional[set] = None,
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    seen = set(existing_title_keys or set())
    structural_types = {"references", "appendix", "acknowledgements", "table_of_contents", "index", "abstract"}
    for row in block_rows:
        page = int(row.get("page") or 0) or None
        raw_text = normalize_heading_display(row.get("text"))
        if not raw_text:
            continue
        candidate_titles = heading_candidates_from_block_text(raw_text, options, include_raw=True) or [raw_text]
        for title_idx, text in enumerate(candidate_titles[:4]):
            section_type = classify_section_type(text)
            if section_type not in structural_types:
                continue
            if (
                is_probable_caption_text(text)
                or is_probable_metadata_block_text(text)
                or has_table_row_signal(text)
                or is_probable_reference_heading(text)
            ):
                continue
            key = heading_key_without_numbers(text) or normalize_heading_key(text)
            if not key or key in seen:
                continue
            seen.add(key)
            proposals.append(
                {
                    "proposal_id": f"heur_struct_{row.get('page')}_{row.get('block_index')}_{title_idx}",
                    "source": "heuristic_structural_gap_fill",
                    "title": text,
                    "page": page,
                    "level_hint": infer_heading_level(text, "heuristic_structural_gap_fill"),
                    "source_priority": 74,
                    "raw": {"page": row.get("page"), "block_index": row.get("block_index")},
                    "anchor_page": row.get("page"),
                    "anchor_block_index": row.get("block_index"),
                    "anchor_abs_block_index": row.get("abs_block_index"),
                    "anchor_method": "direct_block",
                    "anchor_confidence": 1.0,
                }
            )
    return proposals


def looks_like_heading_text(text: Any, options: PhaseCOptions) -> bool:
    text = normalize_heading_display(text)
    if not text:
        return False
    if has_table_row_signal(text):
        return False
    words = count_words(text)
    if words < int(options.heuristic_heading_min_words) or words > int(options.heuristic_heading_max_words):
        return False
    if len(text) > int(options.heuristic_heading_max_chars):
        return False
    if alnum_ratio(text) < 0.5 and not has_heading_numbering(text):
        return False
    if text.endswith(".") and words > 6:
        return False
    titlecase_hits = sum(1 for part in text.split() if part[:1].isupper())
    if titlecase_hits >= max(1, math.ceil(words * 0.5)):
        return True
    if has_heading_numbering(text):
        return True
    if text.isupper() and words <= 8:
        return True
    if classify_section_type(text) != "body_other":
        return True
    return False


def is_short_titlecase_heading(text: Any) -> bool:
    value = normalize_heading_display(text)
    words = count_words(value)
    if not value or words < 2 or words > 8:
        return False
    titlecase_hits = sum(1 for part in value.split() if part[:1].isupper())
    return titlecase_hits >= max(1, math.ceil(words * 0.5))


def looks_like_heading_block(row: Dict[str, Any], options: PhaseCOptions) -> bool:
    return looks_like_heading_text(row.get("text"), options)


def extract_heuristic_proposals(block_rows: List[Dict[str, Any]], options: PhaseCOptions) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    for row in block_rows:
        text = normalize_heading_display(row.get("text"))
        if not looks_like_heading_block(row, options):
            continue
        proposals.append(
            {
                "proposal_id": f"heur_{row.get('page')}_{row.get('block_index')}",
                "source": "heuristic_block",
                "title": text,
                "page": int(row.get("page") or 0) or None,
                "level_hint": infer_heading_level(text, "heuristic_block"),
                "source_priority": 60,
                "raw": {"page": row.get("page"), "block_index": row.get("block_index")},
                "anchor_page": row.get("page"),
                "anchor_block_index": row.get("block_index"),
                "anchor_abs_block_index": row.get("abs_block_index"),
                "anchor_method": "direct_block",
                "anchor_confidence": 1.0,
            }
        )
    return proposals


def extract_heuristic_recovery_proposals(
    block_rows: List[Dict[str, Any]],
    options: PhaseCOptions,
    *,
    existing_title_keys: Optional[set] = None,
    blocked_pages: Optional[set] = None,
) -> List[Dict[str, Any]]:
    proposals: List[Dict[str, Any]] = []
    seen = set(existing_title_keys or set())
    blocked = {int(page) for page in (blocked_pages or set()) if int(page) > 0}
    for row in block_rows:
        page = int(row.get("page") or 0) or None
        if page in blocked:
            continue
        candidate_titles = heading_candidates_from_block_text(row.get("text"), options, include_raw=False)
        if not candidate_titles:
            continue
        raw_text = normalize_heading_display(row.get("text"))
        if is_probable_caption_text(raw_text) or is_probable_metadata_block_text(raw_text):
            continue
        for title_idx, text in enumerate(candidate_titles):
            stripped = strip_heading_numbering(text)
            alpha_chars = sum(1 for ch in ascii_fold(text) if ch.isalpha())
            if not (
                has_heading_numbering(text)
                or text.isupper()
                or classify_section_type(text) != "body_other"
                or is_short_titlecase_heading(text)
            ):
                continue
            if text.isupper() and alpha_chars < 4:
                continue
            if re.match(r"^[•]", text) or (text.startswith("(") and count_words(text) <= 2):
                continue
            if has_heading_numbering(text) and classify_section_type(text) == "body_other":
                if count_words(stripped) > 10 or len(stripped) > 100:
                    continue
            if page and page <= 2 and has_heading_numbering(text) and classify_section_type(text) == "body_other":
                if any(token in normalize_heading_key(stripped) for token in ["department", "university", "school of", "institute"]):
                    continue
                if count_words(stripped) > 7:
                    continue
            loose_key = heading_key_without_numbers(text) or normalize_heading_key(text)
            if not loose_key or loose_key in seen:
                continue
            seen.add(loose_key)
            proposals.append(
                {
                    "proposal_id": f"heur_recover_{row.get('page')}_{row.get('block_index')}_{title_idx}",
                    "source": "heuristic_recovery",
                    "title": text,
                    "page": page,
                    "level_hint": infer_heading_level(text, "heuristic_recovery"),
                    "source_priority": 70,
                    "raw": {"page": row.get("page"), "block_index": row.get("block_index")},
                    "anchor_page": row.get("page"),
                    "anchor_block_index": row.get("block_index"),
                    "anchor_abs_block_index": row.get("abs_block_index"),
                    "anchor_method": "direct_block",
                    "anchor_confidence": 1.0,
                }
            )
    return proposals


def score_anchor_match(title: str, block_text: str) -> float:
    best = 0.0
    title_key = normalize_heading_key(title)
    title_loose_key = heading_key_without_numbers(title) or title_key
    if not title_key:
        return 0.0
    for variant in block_text_variants(block_text):
        variant_key = normalize_heading_key(variant)
        variant_loose_key = heading_key_without_numbers(variant) or variant_key
        if not variant_key:
            continue
        if variant_key == title_key:
            return 1.0
        if variant_loose_key == title_loose_key:
            best = max(best, 0.99)
            continue
        if (
            variant_key.startswith(title_key)
            or title_key.startswith(variant_key)
            or variant_loose_key.startswith(title_loose_key)
            or title_loose_key.startswith(variant_loose_key)
        ):
            best = max(best, 0.93)
        else:
            best = max(best, title_similarity(title_loose_key, variant_loose_key))
    if is_probable_caption_text(block_text) and not is_probable_caption_text(title):
        best -= 0.18
    if is_probable_metadata_block_text(block_text):
        best -= 0.2
    return max(0.0, min(1.0, best))


def anchor_proposal(proposal: Dict[str, Any], block_index: Dict[str, Any]) -> Dict[str, Any]:
    if proposal.get("anchor_abs_block_index") is not None:
        return proposal
    title = proposal.get("title")
    page = proposal.get("page")
    search_blocks: List[Dict[str, Any]] = []
    if page is not None:
        search_blocks.extend(block_index["blocks_by_page"].get(int(page), []))
        if not search_blocks:
            search_blocks.extend(block_index["blocks_by_page"].get(int(page) - 1, []))
            search_blocks.extend(block_index["blocks_by_page"].get(int(page) + 1, []))
    if not search_blocks:
        search_blocks = block_index["ordered_blocks"]
    best_row = None
    best_score = 0.0
    for row in search_blocks:
        score = score_anchor_match(title, row.get("text"))
        if score > best_score:
            best_score = score
            best_row = row
    anchored = dict(proposal)
    if best_row is not None and best_score >= 0.78:
        anchored["anchor_page"] = int(best_row.get("page") or 0) or None
        anchored["anchor_block_index"] = int(best_row.get("block_index") or 0)
        anchored["anchor_abs_block_index"] = int(best_row.get("abs_block_index") or 0)
        anchored["anchor_method"] = "block_text_match"
        anchored["anchor_confidence"] = round(float(best_score), 3)
        anchored["anchor_block_text"] = best_row.get("text")
        return anchored
    if page is not None and block_index["blocks_by_page"].get(int(page)):
        fallback = block_index["blocks_by_page"][int(page)][0]
        anchored["anchor_page"] = int(fallback.get("page") or 0) or None
        anchored["anchor_block_index"] = int(fallback.get("block_index") or 0)
        anchored["anchor_abs_block_index"] = int(fallback.get("abs_block_index") or 0)
        anchored["anchor_method"] = "page_start_fallback"
        anchored["anchor_confidence"] = round(float(best_score), 3)
        anchored["anchor_block_text"] = fallback.get("text")
        return anchored
    return anchored


def repair_proposal_title_from_anchor(proposal: Dict[str, Any], options: PhaseCOptions, *, block_index: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not bool(options.repair_titles_from_anchor_blocks):
        return proposal
    if str(proposal.get("source") or "").startswith("outline"):
        return proposal
    title = normalize_heading_display(proposal.get("title"))
    block_text = proposal.get("anchor_block_text")
    if not title or not block_text:
        return proposal
    title_key = normalize_heading_key(title)
    best_candidate = ""
    best_score = 0.0
    for variant in block_text_variants(str(block_text)):
        candidate = normalize_heading_display(variant)
        if not candidate or candidate == title:
            continue
        if not looks_like_heading_text(candidate, options):
            continue
        if is_probable_caption_text(candidate) or is_probable_metadata_block_text(candidate):
            continue
        candidate_key = normalize_heading_key(candidate)
        if not candidate_key:
            continue
        if (
            count_words(candidate) < count_words(title)
            and (title_key.startswith(candidate_key) or (heading_key_without_numbers(title) or title_key).startswith(heading_key_without_numbers(candidate) or candidate_key))
        ):
            continue
        similarity = title_similarity(candidate, title)
        is_containing_upgrade = (
            candidate_key.startswith(title_key)
            and count_words(candidate) > count_words(title)
            and len(candidate) > len(title)
        )
        if not is_containing_upgrade and similarity < 0.86:
            continue
        score = similarity
        if is_containing_upgrade:
            score += 0.12
        if ":" in candidate and ":" not in title:
            score += 0.03
        if score > best_score:
            best_candidate = candidate
            best_score = score
    if not best_candidate:
        return proposal
    repaired = dict(proposal)
    repaired["title"] = best_candidate
    repaired["title_repaired_from_anchor"] = True
    repaired["original_title"] = title
    repaired["title_repair_score"] = round(best_score, 3)
    return repaired


def is_sentence_like_heading_noise(title: str) -> bool:
    display = normalize_heading_display(title)
    if not display or has_heading_numbering(display):
        return False
    if classify_section_type(display) != "body_other":
        return False
    words = count_words(display)
    if words < 4:
        return False
    if display[:1].islower():
        return True
    if re.match(r"^[\"'“”‘’`]", display):
        return True
    if re.match(r"^[a-e]\.\s+[A-Z]", display):
        return True
    if (
        words <= 4
        and re.match(
            r"^(?:as|and|but|because|however|therefore|thus|while|when|whereas|although|since)\b",
            ascii_fold(display).lower(),
        )
    ):
        return True
    if display.endswith(".") and words >= 5:
        return True
    return False


def is_probable_heuristic_heading_noise(title: Any) -> bool:
    display = normalize_heading_display(title)
    if not display:
        return False
    folded = ascii_fold(display).lower()
    if count_words(display) >= 6 and re.match(r"^\d+\.\s+.+\.\s+\d+$", display):
        return True
    if len(re.findall(r"\b\d+\.", display)) >= 2 and count_words(display) >= 6:
        return True
    if re.match(r"^[a-e]\.\s+[a-z]", folded):
        return True
    if (
        re.match(r"^\d+\.\s+[a-z][a-z'’.-]+(?:\s*(?:&|and)\s*[a-z][a-z'’.-]+)?\s*\(\d{4}\)(?:\s+\d+)?$", folded)
        and count_words(display) <= 8
    ):
        return True
    if count_words(display) <= 3 and is_probable_author_line(display):
        return True
    if (
        count_words(display) <= 4
        and re.match(
            r"^(?:as|and|but|because|however|therefore|thus|while|when|whereas|although|since)\b",
            folded,
        )
    ):
        return True
    return False


def has_table_row_signal(text: Any) -> bool:
    display = normalize_heading_display(text)
    if not display:
        return False
    if any(symbol in display for symbol in ["√", "✓", "✔", "☑", "☒"]):
        return True
    ascii_text = ascii_fold(display)
    if "|" in ascii_text:
        return True
    if has_heading_numbering(display):
        return False
    numeric_tokens = re.findall(r"\b\d[\d,]*(?:\.\d+)?\b", ascii_text)
    if len(numeric_tokens) >= 3 and "," in ascii_text and count_words(display) >= 6:
        return True
    return False


def filter_and_anchor_proposals(proposals: List[Dict[str, Any]], *, block_index: Dict[str, Any], metadata: Dict[str, Any], options: PhaseCOptions) -> Dict[str, Any]:
    doc_title = normalize_heading_display((metadata.get("fitz") or {}).get("metadata", {}).get("title") or metadata.get("label") or metadata.get("file_name"))
    doc_title_key = normalize_heading_key(doc_title)
    doc_title_loose_key = heading_key_without_numbers(doc_title)
    strong_outline = has_strong_outline(metadata, options)
    repeated_pages = block_index.get("repeated_heading_pages") or {}
    repeated_pages_loose = block_index.get("repeated_heading_pages_wo_numbers") or {}
    proposal_rows: List[Dict[str, Any]] = []
    accepted: List[Dict[str, Any]] = []
    seen_keys: Dict[Tuple[int, str], Dict[str, Any]] = {}
    seen_loose_keys: Dict[Tuple[int, str], Dict[str, Any]] = {}
    seen_anchor_only: Dict[int, Dict[str, Any]] = {}

    sorted_proposals = sorted(
        proposals,
        key=lambda row: (
            row.get("page") is None,
            int(row.get("page") or 0),
            -(int(row.get("source_priority") or 0)),
            normalize_heading_key(row.get("title")),
        ),
    )

    for proposal in sorted_proposals:
        source = str(proposal.get("source") or "")
        anchored = repair_proposal_title_from_anchor(anchor_proposal(proposal, block_index), options, block_index=block_index)
        title = normalize_heading_display(anchored.get("title"))
        key = normalize_heading_key(title)
        loose_key = heading_key_without_numbers(title) or key
        repeated = max(int(repeated_pages.get(key, 0)), int(repeated_pages_loose.get(heading_key_without_numbers(title), 0)))
        rejected, reason = is_probable_noise_heading(
            title,
            source=source,
            repeated_pages=repeated,
            repeated_page_threshold=int(options.repeated_heading_page_threshold),
            doc_title_key=doc_title_key,
        )
        row = dict(anchored)
        row["title"] = title
        row["normalized_title_key"] = key
        row["normalized_title_key_wo_numbers"] = loose_key
        row["repeated_pages"] = repeated
        row["accepted"] = False
        row["rejection_reason"] = reason if rejected else ""
        if anchored.get("anchor_abs_block_index") is None:
            row["rejection_reason"] = row["rejection_reason"] or "unanchored"
            rejected = True
        anchored_page = int(anchored.get("anchor_page") or proposal.get("page") or 0)
        titlecase_hits = sum(1 for part in title.split() if part[:1].isupper())
        if (
            not rejected
            and anchored_page == 1
            and not source.startswith("outline")
            and not has_heading_numbering(title)
            and classify_section_type(title) == "body_other"
            and 1 <= count_words(title) <= 10
            and titlecase_hits >= max(1, count_words(title) - 1)
        ):
            row["rejection_reason"] = "probable_author_or_front_matter_line"
            rejected = True
        if (
            not rejected
            and anchored_page <= 2
            and not source.startswith("outline")
            and (
                key == doc_title_key
                or (doc_title_key and key.startswith(doc_title_key))
                or (doc_title_loose_key and loose_key.startswith(doc_title_loose_key))
                or title_similarity(title, doc_title) >= 0.8
            )
        ):
            row["rejection_reason"] = "document_title_repeat"
            rejected = True
        if (
            not rejected
            and not source.startswith("outline")
            and is_doc_title_prefix_fragment(title, doc_title_key=doc_title_key, doc_title_loose_key=doc_title_loose_key)
        ):
            row["rejection_reason"] = "document_title_prefix_fragment"
            rejected = True
        if (
            not rejected
            and not source.startswith("outline")
            and is_sentence_like_heading_noise(title)
        ):
            row["rejection_reason"] = "sentence_like_body_line"
            rejected = True
        if (
            not rejected
            and source == "heuristic_recovery"
            and has_table_row_signal(title)
        ):
            row["rejection_reason"] = "table_like_row"
            rejected = True
        if (
            not rejected
            and strong_outline
            and source == "heuristic_recovery"
            and bool(options.heuristic_recovery_disable_when_strong_outline)
        ):
            row["rejection_reason"] = "heuristic_recovery_suppressed_under_strong_outline"
            rejected = True
        if (
            not rejected
            and strong_outline
            and source == "docling"
            and classify_section_type(title) == "body_other"
            and not has_heading_numbering(title)
            and not (title.isupper() and count_words(title) <= 6)
        ):
            row["rejection_reason"] = "docling_detail_under_strong_outline"
            rejected = True
        if (
            not rejected
            and strong_outline
            and source == "docling"
            and has_heading_numbering(title)
        ):
            match = re.match(r"^(\d+(?:\.\d+){0,4})\b", normalize_heading_display(title))
            numbering_depth = len(match.group(1).split(".")) if match else 1
            if numbering_depth > int(options.docling_supplement_strong_outline_numbering_depth):
                row["rejection_reason"] = "docling_numbering_too_deep_under_strong_outline"
                rejected = True
        if (
            not rejected
            and source == "heuristic_recovery"
            and is_probable_heuristic_heading_noise(title)
        ):
            row["rejection_reason"] = "heuristic_fragment_or_reference_noise"
            rejected = True
        if not rejected:
            anchor_abs = int(anchored.get("anchor_abs_block_index") or -1)
            dedupe_key = (anchor_abs, key)
            dedupe_loose_key = (anchor_abs, loose_key)
            existing = seen_keys.get(dedupe_key)
            existing_loose = seen_loose_keys.get(dedupe_loose_key)
            existing_at_anchor = seen_anchor_only.get(anchor_abs)
            if existing is not None:
                if int(anchored.get("source_priority") or 0) > int(existing.get("source_priority") or 0):
                    existing.setdefault("merged_sources", []).append(existing.get("source"))
                    row["merged_sources"] = list(dict.fromkeys((existing.get("merged_sources") or []) + [existing.get("source")]))
                    row["accepted"] = True
                    seen_keys[dedupe_key] = row
                    accepted = [item for item in accepted if item is not existing]
                    accepted.append(row)
                else:
                    existing.setdefault("merged_sources", []).append(source)
                    row["rejection_reason"] = "duplicate_of_higher_priority_heading"
                    rejected = True
            elif existing_loose is not None and loose_key:
                if int(anchored.get("source_priority") or 0) > int(existing_loose.get("source_priority") or 0):
                    existing_loose.setdefault("merged_sources", []).append(existing_loose.get("source"))
                    row["merged_sources"] = list(dict.fromkeys((existing_loose.get("merged_sources") or []) + [existing_loose.get("source")]))
                    row["accepted"] = True
                    accepted = [item for item in accepted if item is not existing_loose]
                    accepted.append(row)
                    seen_keys[dedupe_key] = row
                    seen_loose_keys[dedupe_loose_key] = row
                    seen_anchor_only[anchor_abs] = row
                else:
                    existing_loose.setdefault("merged_sources", []).append(source)
                    row["rejection_reason"] = "duplicate_without_numbering_of_higher_priority_heading"
                    rejected = True
            elif existing_at_anchor is not None and (
                str(anchored.get("anchor_method") or "") == "page_start_fallback"
                or str(existing_at_anchor.get("anchor_method") or "") == "page_start_fallback"
            ):
                if int(anchored.get("source_priority") or 0) > int(existing_at_anchor.get("source_priority") or 0):
                    existing_at_anchor.setdefault("merged_sources", []).append(existing_at_anchor.get("source"))
                    row["merged_sources"] = list(dict.fromkeys((existing_at_anchor.get("merged_sources") or []) + [existing_at_anchor.get("source")]))
                    row["accepted"] = True
                    accepted = [item for item in accepted if item is not existing_at_anchor]
                    accepted.append(row)
                    seen_anchor_only[anchor_abs] = row
                    seen_keys[dedupe_key] = row
                    seen_loose_keys[dedupe_loose_key] = row
                else:
                    existing_at_anchor.setdefault("merged_sources", []).append(source)
                    row["rejection_reason"] = "duplicate_anchor_fallback_collision"
                    rejected = True
            else:
                row["accepted"] = True
                row["merged_sources"] = []
                seen_keys[dedupe_key] = row
                seen_loose_keys[dedupe_loose_key] = row
                seen_anchor_only[anchor_abs] = row
                accepted.append(row)
        proposal_rows.append(row)

    accepted = sorted(
        accepted,
        key=lambda row: (
            int(row.get("anchor_abs_block_index") or 0),
            int(row.get("level_hint") or infer_heading_level(row.get("title"), row.get("source"))),
            -int(row.get("source_priority") or 0),
        ),
    )
    return {"proposal_rows": proposal_rows, "accepted_headings": accepted, "doc_title": doc_title}


def build_section_tree(accepted_headings: List[Dict[str, Any]], *, block_index: Dict[str, Any], metadata: Dict[str, Any], options: PhaseCOptions, doc_id: str, stable_hash_fn: Any) -> List[Dict[str, Any]]:
    ordered_blocks = block_index["ordered_blocks"]
    if not ordered_blocks:
        return []

    headings = list(accepted_headings)
    if not headings and bool(options.synthesize_document_body):
        headings = [
            {
                "proposal_id": "synthetic_document_body",
                "source": "synthetic",
                "title": "Document Body",
                "page": int(ordered_blocks[0].get("page") or 1),
                "level_hint": 1,
                "source_priority": 10,
                "anchor_page": int(ordered_blocks[0].get("page") or 1),
                "anchor_block_index": int(ordered_blocks[0].get("block_index") or 0),
                "anchor_abs_block_index": int(ordered_blocks[0].get("abs_block_index") or 0),
                "anchor_method": "synthetic",
                "anchor_confidence": 1.0,
                "accepted": True,
                "merged_sources": [],
            }
        ]

    headings = sorted(headings, key=lambda row: (int(row.get("anchor_abs_block_index") or 0), -int(row.get("source_priority") or 0)))

    if bool(options.synthesize_front_matter) and headings and int(headings[0].get("anchor_abs_block_index") or 0) > 0:
        first = ordered_blocks[0]
        headings = [
            {
                "proposal_id": "synthetic_front_matter",
                "source": "synthetic",
                "title": "Front Matter",
                "page": int(first.get("page") or 1),
                "level_hint": 1,
                "source_priority": 10,
                "anchor_page": int(first.get("page") or 1),
                "anchor_block_index": int(first.get("block_index") or 0),
                "anchor_abs_block_index": int(first.get("abs_block_index") or 0),
                "anchor_method": "synthetic",
                "anchor_confidence": 1.0,
                "accepted": True,
                "merged_sources": [],
            }
        ] + headings

    deduped: List[Dict[str, Any]] = []
    seen_anchor_titles = set()
    for row in headings:
        key = (int(row.get("anchor_abs_block_index") or 0), normalize_heading_key(row.get("title")))
        if key in seen_anchor_titles:
            continue
        seen_anchor_titles.add(key)
        deduped.append(row)
    headings = deduped

    doc_title = normalize_heading_display((metadata.get("fitz") or {}).get("metadata", {}).get("title") or metadata.get("label") or metadata.get("file_name"))
    sections: List[Dict[str, Any]] = []
    for idx, heading in enumerate(headings):
        start_idx = int(heading.get("anchor_abs_block_index") or 0)
        end_idx = int(headings[idx + 1].get("anchor_abs_block_index") or len(ordered_blocks)) - 1 if idx + 1 < len(headings) else len(ordered_blocks) - 1
        start_idx = max(0, min(start_idx, len(ordered_blocks) - 1))
        end_idx = max(start_idx, min(end_idx, len(ordered_blocks) - 1))
        span_blocks = ordered_blocks[start_idx : end_idx + 1]
        filtered_block_texts: List[str] = []
        metadata_filtered_block_count = 0
        metadata_filtered_line_count = 0
        for row in span_blocks:
            cleaned_block_text, removed_line_count = clean_section_block_text(row.get("text"), options=options, doc_title=doc_title)
            if removed_line_count:
                metadata_filtered_block_count += 1
                metadata_filtered_line_count += int(removed_line_count)
            if cleaned_block_text:
                filtered_block_texts.append(cleaned_block_text)
        block_texts = filtered_block_texts
        section_text = "\n\n".join(block_texts).strip()
        level = infer_heading_level(heading.get("title"), str(heading.get("source") or ""), heading.get("level_hint"))
        section_type = classify_section_type(heading.get("title"))
        section_id = stable_hash_fn(doc_id, f"section::{idx}::{heading.get('title')}::{start_idx}::{end_idx}", length=16)
        sections.append(
            {
                "doc_id": doc_id,
                "section_id": section_id,
                "parent_section_id": None,
                "level": level,
                "title": normalize_heading_display(heading.get("title")),
                "title_path": [],
                "section_type": section_type,
                "page_start": int(span_blocks[0].get("page") or 1),
                "page_end": int(span_blocks[-1].get("page") or span_blocks[0].get("page") or 1),
                "char_len": len(section_text),
                "word_count": count_words(section_text),
                "text": section_text,
                "contextualized_text": "",
                "parser_sources": list(dict.fromkeys([str(heading.get("source") or "")] + list(heading.get("merged_sources") or []))),
                "quality_flags": [
                    flag
                    for flag in [
                        "synthetic" if str(heading.get("source") or "") == "synthetic" else "",
                        "fallback_anchor" if str(heading.get("anchor_method") or "") == "page_start_fallback" else "",
                        "tiny_section" if len(section_text) < int(options.min_section_chars) or count_words(section_text) < int(options.min_section_words) else "",
                        "metadata_stripped" if metadata_filtered_block_count > 0 else "",
                    ]
                    if flag
                ],
                "heading_anchor": {
                    "page": heading.get("anchor_page"),
                    "block_index": heading.get("anchor_block_index"),
                    "abs_block_index": heading.get("anchor_abs_block_index"),
                    "method": heading.get("anchor_method"),
                    "confidence": heading.get("anchor_confidence"),
                },
                "span": {
                    "start_abs_block_index": start_idx,
                    "end_abs_block_index": end_idx,
                    "block_count": len(span_blocks),
                },
                "metadata_filtering": {
                    "filtered_block_count": metadata_filtered_block_count,
                    "filtered_line_count": metadata_filtered_line_count,
                },
                "block_rows": span_blocks,
            }
        )

    stack: List[Dict[str, Any]] = []
    for section in sections:
        while stack and int(stack[-1]["level"]) >= int(section["level"]):
            stack.pop()
        if stack:
            section["parent_section_id"] = stack[-1]["section_id"]
            section["title_path"] = list(stack[-1]["title_path"]) + [section["title"]]
        else:
            section["title_path"] = [section["title"]]
        stack.append(section)

    child_counts: Dict[str, int] = {}
    for section in sections:
        parent_id = str(section.get("parent_section_id") or "").strip()
        if parent_id:
            child_counts[parent_id] = child_counts.get(parent_id, 0) + 1

    first_references_index = next(
        (idx for idx, section in enumerate(sections) if str(section.get("section_type") or "") == "references"),
        None,
    )

    for idx, section in enumerate(sections):
        flags = list(dict.fromkeys(section.get("quality_flags") or []))
        wrapper_reasons = infer_structural_wrapper_reasons(
            title=str(section.get("title") or ""),
            section_type=str(section.get("section_type") or "body_other"),
            section_text=str(section.get("text") or ""),
            word_count=int(section.get("word_count") or 0),
            title_word_count=count_words(section.get("title") or ""),
            level=int(section.get("level") or 1),
            quality_flags=flags,
            child_count=int(child_counts.get(str(section.get("section_id") or ""), 0)),
            options=options,
        )
        if (
            first_references_index is not None
            and idx > int(first_references_index)
            and str(section.get("section_type") or "") not in {"appendix", "index"}
        ):
            wrapper_reasons.append("post_references_end_matter")
        if wrapper_reasons:
            flags.extend(["structural_wrapper", "retrieval_suppressed"])
        section["quality_flags"] = list(dict.fromkeys([flag for flag in flags if flag]))
        section["retrieval_eligible"] = not bool(wrapper_reasons)
        section["retrieval_suppression_reasons"] = wrapper_reasons

    for section in sections:
        path_text = " > ".join(section.get("title_path") or [section.get("title")])
        section["contextualized_text"] = f"Document Title: {doc_title}\nSection Path: {path_text}\n\n{section.get('text') or ''}".strip()

    return sections


def chunk_words(text: str, *, max_words: int) -> List[str]:
    words = re.findall(r"\S+", str(text or ""))
    if not words:
        return []
    chunks: List[str] = []
    for start in range(0, len(words), max_words):
        chunks.append(" ".join(words[start : start + max_words]))
    return chunks


def build_passages(sections: List[Dict[str, Any]], *, metadata: Dict[str, Any], options: PhaseCOptions, stable_hash_fn: Any) -> List[Dict[str, Any]]:
    passages: List[Dict[str, Any]] = []
    doc_title = normalize_heading_display((metadata.get("fitz") or {}).get("metadata", {}).get("title") or metadata.get("label") or metadata.get("file_name"))
    for section in sections:
        current_texts: List[str] = []
        current_pages: List[int] = []
        section_passages: List[Dict[str, Any]] = []
        passage_index = 0

        def flush_current() -> None:
            nonlocal passage_index, current_texts, current_pages, section_passages
            joined = "\n\n".join([part for part in current_texts if part]).strip()
            if not joined:
                current_texts = []
                current_pages = []
                return
            word_count_val = count_words(joined)
            path_text = " > ".join(section.get("title_path") or [section.get("title")])
            if word_count_val > int(options.passage_max_words) * 1.35:
                for sub_idx, part in enumerate(chunk_words(joined, max_words=int(options.passage_max_words))):
                    sub_words = count_words(part)
                    passage_id = stable_hash_fn(section["doc_id"], section["section_id"], f"passage::{passage_index}::{sub_idx}::{part[:80]}", length=16)
                    section_passages.append(
                        {
                            "doc_id": section["doc_id"],
                            "section_id": section["section_id"],
                            "passage_id": passage_id,
                            "passage_index": passage_index,
                            "text": part,
                            "contextualized_text": f"Document Title: {doc_title}\nSection Path: {path_text}\n\n{part}".strip(),
                            "page_span": {
                                "page_start": min(current_pages) if current_pages else section.get("page_start"),
                                "page_end": max(current_pages) if current_pages else section.get("page_end"),
                            },
                            "token_len": max(1, round(sub_words * 1.3)),
                            "word_count": sub_words,
                            "quality_flags": list(section.get("quality_flags") or []),
                            "retrieval_eligible": bool(section.get("retrieval_eligible", True)),
                        }
                    )
                    passage_index += 1
            else:
                passage_id = stable_hash_fn(section["doc_id"], section["section_id"], f"passage::{passage_index}::{joined[:80]}", length=16)
                section_passages.append(
                    {
                        "doc_id": section["doc_id"],
                        "section_id": section["section_id"],
                        "passage_id": passage_id,
                        "passage_index": passage_index,
                        "text": joined,
                        "contextualized_text": f"Document Title: {doc_title}\nSection Path: {path_text}\n\n{joined}".strip(),
                        "page_span": {
                            "page_start": min(current_pages) if current_pages else section.get("page_start"),
                            "page_end": max(current_pages) if current_pages else section.get("page_end"),
                        },
                        "token_len": max(1, round(word_count_val * 1.3)),
                        "word_count": word_count_val,
                        "quality_flags": list(section.get("quality_flags") or []),
                        "retrieval_eligible": bool(section.get("retrieval_eligible", True)),
                    }
                )
                passage_index += 1
            current_texts = []
            current_pages = []

        for row in section.get("block_rows") or []:
            text = clean_text(row.get("text"))
            if not text:
                continue
            words = count_words(text)
            if words >= int(options.passage_max_words) * 1.35:
                flush_current()
                current_texts = [text]
                current_pages = [int(row.get("page") or section.get("page_start") or 1)]
                flush_current()
                continue
            tentative = "\n\n".join(current_texts + [text]) if current_texts else text
            if current_texts and count_words(tentative) > int(options.passage_target_words):
                flush_current()
            current_texts.append(text)
            current_pages.append(int(row.get("page") or section.get("page_start") or 1))
        flush_current()

        if not section_passages and section.get("text"):
            section_text = section.get("text") or ""
            path_text = " > ".join(section.get("title_path") or [section.get("title")])
            passage_id = stable_hash_fn(section["doc_id"], section["section_id"], f"passage::fallback::{section_text[:80]}", length=16)
            section_passages.append(
                {
                    "doc_id": section["doc_id"],
                    "section_id": section["section_id"],
                    "passage_id": passage_id,
                    "passage_index": 0,
                    "text": section_text,
                    "contextualized_text": f"Document Title: {doc_title}\nSection Path: {path_text}\n\n{section_text}".strip(),
                    "page_span": {"page_start": section.get("page_start"), "page_end": section.get("page_end")},
                    "token_len": max(1, round(count_words(section_text) * 1.3)),
                    "word_count": count_words(section_text),
                    "quality_flags": list(section.get("quality_flags") or []),
                    "retrieval_eligible": bool(section.get("retrieval_eligible", True)),
                }
            )
        passages.extend(section_passages)
    return passages


def build_document_record(doc_id: str, metadata: Dict[str, Any], sections: List[Dict[str, Any]], accepted_headings: List[Dict[str, Any]], loaded_bundle: Dict[str, Any]) -> Dict[str, Any]:
    title = normalize_heading_display((metadata.get("fitz") or {}).get("metadata", {}).get("title") or metadata.get("label") or metadata.get("file_name"))
    sample_text = "\n".join(str(row.get("text") or "") for row in (loaded_bundle.get("pages") or [])[:2])
    page_count = int(metadata.get("page_count") or 0)
    return {
        "doc_id": doc_id,
        "source_path": metadata.get("source_path"),
        "sha256": metadata.get("sha256"),
        "title": title,
        "page_count": page_count,
        "language_guess": infer_language_guess(title + " " + sample_text),
        "doc_type_guess": infer_doc_type_guess(metadata),
        "has_outline": bool((metadata.get("outline_counts") or {}).get("fitz") or (metadata.get("outline_counts") or {}).get("pypdf")),
        "section_count": len(sections),
        "accepted_heading_count": len(accepted_headings),
    }


def qc_row(*, check: str, status: str, value: Any, expected: Any, why: str, fix: str) -> Dict[str, Any]:
    return {
        "check": str(check),
        "status": str(status),
        "value": str(value),
        "expected": str(expected),
        "why": str(why),
        "fix": str(fix),
    }


def assess_phase_c(*, summary_rows: List[Dict[str, Any]], section_rows: List[Dict[str, Any]], passage_rows: List[Dict[str, Any]], options: PhaseCOptions) -> Dict[str, Any]:
    failures: List[str] = []
    warnings: List[str] = []
    if not summary_rows:
        failures.append("No documents were processed in Phase C.")
    if not section_rows:
        failures.append("No sections were produced.")
    if not passage_rows:
        failures.append("No passages were produced.")

    doc_ids_with_sections = {row.get("doc_id") for row in section_rows}
    doc_ids_with_passages = {row.get("doc_id") for row in passage_rows}
    section_ids = {row.get("section_id") for row in section_rows}
    for row in summary_rows:
        doc_id = row.get("doc_id")
        eligible_tiny_raw = row.get("retrieval_eligible_tiny_section_count")
        eligible_tiny_count = int(eligible_tiny_raw if eligible_tiny_raw is not None else (row.get("tiny_section_count") or 0))
        if doc_id not in doc_ids_with_sections:
            failures.append(f"{doc_id}: no sections")
        if doc_id not in doc_ids_with_passages:
            failures.append(f"{doc_id}: no passages")
        if float(row.get("section_coverage_pct") or 0.0) < float(options.min_section_coverage_pct_warn):
            warnings.append(f"{doc_id}: low section coverage ({row.get('section_coverage_pct')}%)")
        if int(row.get("section_count") or 0) <= 1 and int(row.get("page_count") or 0) >= 10:
            warnings.append(f"{doc_id}: collapsed to a single section on a multi-page document")
        if int(row.get("page_count") or 0) >= int(options.long_doc_page_threshold) and not bool(row.get("has_references_section")):
            warnings.append(f"{doc_id}: no references section detected in a long document")
        if int(row.get("fallback_anchor_count") or 0) > 0:
            warnings.append(f"{doc_id}: {row.get('fallback_anchor_count')} headings used fallback anchoring")
        section_count = int(row.get("section_count") or 0)
        if int(row.get("page_count") or 0) >= 20 and section_count and (eligible_tiny_count / max(1, section_count)) >= 0.25:
            warnings.append(f"{doc_id}: high retrieval-eligible tiny-section ratio ({eligible_tiny_count}/{section_count})")

    orphan_passages = [row.get("passage_id") for row in passage_rows if row.get("section_id") not in section_ids]
    if orphan_passages:
        failures.append(f"Orphan passages detected: {len(orphan_passages)}")

    status = "success"
    quality_band = "high"
    if failures:
        status = "failed"
        quality_band = "insufficient"
    elif warnings:
        status = "success_with_warnings"
        quality_band = "acceptable_with_issues"

    low_coverage_docs = [row for row in summary_rows if float(row.get("section_coverage_pct") or 0.0) < float(options.min_section_coverage_pct_warn)]
    high_tiny_ratio_docs = []
    for row in summary_rows:
        eligible_tiny_raw = row.get("retrieval_eligible_tiny_section_count")
        eligible_tiny_count = int(eligible_tiny_raw if eligible_tiny_raw is not None else (row.get("tiny_section_count") or 0))
        if (
            int(row.get("page_count") or 0) >= 20
            and int(row.get("section_count") or 0) > 0
            and (eligible_tiny_count / max(1, int(row.get("section_count") or 0))) >= 0.25
        ):
            high_tiny_ratio_docs.append(row)
    qc_rows = [
        qc_row(
            check="documents_processed",
            status="OK" if summary_rows else "FAIL",
            value=len(summary_rows),
            expected=">= 1",
            why="Phase C needs at least one normalized document.",
            fix="check Phase B outputs and Phase C doc filters",
        ),
        qc_row(
            check="sections_produced",
            status="OK" if section_rows else "FAIL",
            value=len(section_rows),
            expected=">= 1",
            why="Section ranking depends on canonical sections.",
            fix="inspect accepted_headings.jsonl and phase_c_diagnostics.json",
        ),
        qc_row(
            check="passages_produced",
            status="OK" if passage_rows else "FAIL",
            value=len(passage_rows),
            expected=">= 1",
            why="Later retrieval and evidence display depend on passages.",
            fix="inspect sections.jsonl and passage chunking options",
        ),
        qc_row(
            check="orphan_passages",
            status="OK" if not orphan_passages else "FAIL",
            value="none" if not orphan_passages else len(orphan_passages),
            expected="none",
            why="Every passage must map back to one canonical section.",
            fix="inspect section_id assignment during passage construction",
        ),
        qc_row(
            check="low_coverage_docs",
            status="OK" if not low_coverage_docs else "WARN",
            value="none" if not low_coverage_docs else ", ".join(row.get("doc_id") for row in low_coverage_docs),
            expected=f">= {options.min_section_coverage_pct_warn}% section text coverage",
            why="Low coverage indicates that headings or section spans are dropping content.",
            fix="inspect section span boundaries and fallback synthesis",
        ),
        qc_row(
            check="high_tiny_ratio_docs",
            status="OK" if not high_tiny_ratio_docs else "WARN",
            value="none" if not high_tiny_ratio_docs else ", ".join(
                f"{row.get('doc_id')} ({(row.get('retrieval_eligible_tiny_section_count') if row.get('retrieval_eligible_tiny_section_count') is not None else row.get('tiny_section_count'))}/{row.get('section_count')})"
                for row in high_tiny_ratio_docs
            ),
            expected="< 25% retrieval-eligible tiny sections on docs >= 20 pages",
            why="Tiny sections matter when they are still eligible retrieval targets; suppressed structural stubs are less concerning.",
            fix="inspect section_proposals.jsonl and retrieval_suppression_reasons in sections.jsonl",
        ),
    ]

    return {
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": not failures,
        "failures": failures,
        "warnings": warnings,
        "counts": {
            "document_count": len(summary_rows),
            "section_count": len(section_rows),
            "passage_count": len(passage_rows),
            "orphan_passage_count": len(orphan_passages),
            "warning_count": len(warnings),
            "failure_count": len(failures),
        },
        "qc_rows": qc_rows,
    }


def resolve_phase_c_doc_concurrency(options: PhaseCOptions, *, doc_count: int) -> int:
    if int(doc_count) <= 1:
        return 1
    if options.max_concurrent_docs is not None:
        return max(1, min(int(doc_count), int(options.max_concurrent_docs)))
    return max(1, min(int(doc_count), min(available_cpu_count(), 8)))


def build_phase_c_document_bundle(
    *,
    run_ctx: Any,
    normalized_dir: Path,
    bundle_row: Dict[str, Any],
    options: PhaseCOptions,
    stable_hash_local: Any,
) -> Dict[str, Any]:
    doc_id = str(bundle_row.get("doc_id") or "")
    doc_dir = ensure_dir(normalized_dir / doc_id)
    doc_artifacts = {
        "document_json": doc_dir / "document.json",
        "section_proposals_jsonl": doc_dir / "section_proposals.jsonl",
        "accepted_headings_jsonl": doc_dir / "accepted_headings.jsonl",
        "sections_jsonl": doc_dir / "sections.jsonl",
        "passages_jsonl": doc_dir / "passages.jsonl",
        "diagnostics_json": doc_dir / "phase_c_diagnostics.json",
    }

    loaded = load_phase_b_bundle(run_ctx, bundle_row)
    metadata = loaded["metadata"] or {}
    block_index = build_block_index(loaded["blocks"] or [])
    proposals: List[Dict[str, Any]] = []
    source_counts: Dict[str, int] = {}
    outline_props: List[Dict[str, Any]] = []
    docling_props: List[Dict[str, Any]] = []
    grobid_props: List[Dict[str, Any]] = []
    if bool(options.prefer_outline):
        outline_props = extract_outline_proposals(metadata)
        proposals.extend(outline_props)
        source_counts["outline"] = len(outline_props)
    if bool(options.use_docling):
        docling_props = extract_docling_proposals(loaded["docling"] or {})
        proposals.extend(docling_props)
        source_counts["docling"] = len(docling_props)
    if bool(options.use_grobid):
        grobid_props = extract_grobid_proposals(loaded.get("grobid_tei_text") or "")
        proposals.extend(grobid_props)
        source_counts["grobid"] = len(grobid_props)
    strong_outline = has_strong_outline(metadata, options)
    docling_noise_ratio = estimate_docling_noise_ratio(docling_props)
    heuristic_enabled_for_doc = bool(
        options.use_heuristic_headings
        and not outline_props
        and (
            (len(docling_props) < 4 and len(grobid_props) < 4)
            or (
                bool(options.enable_numbered_gap_fill_when_docling_noisy)
                and docling_noise_ratio >= float(options.docling_noise_ratio_for_gap_fill)
            )
        )
    )
    if heuristic_enabled_for_doc:
        if len(docling_props) >= 4 or len(grobid_props) >= 4:
            heuristic_props = extract_numbered_gap_fill_proposals(block_index["ordered_blocks"], options)
        else:
            heuristic_props = extract_heuristic_proposals(block_index["ordered_blocks"], options)
        proposals.extend(heuristic_props)
        source_counts["heuristic"] = len(heuristic_props)
    else:
        source_counts["heuristic"] = 0
    existing_heading_keys = {
        heading_key_without_numbers(item.get("title")) or normalize_heading_key(item.get("title"))
        for item in proposals
        if normalize_heading_display(item.get("title"))
    }
    structural_gap_fill_props = extract_structural_gap_fill_proposals(
        block_index["ordered_blocks"],
        options,
        existing_title_keys=existing_heading_keys,
    )
    proposals.extend(structural_gap_fill_props)
    source_counts["heuristic_structural_gap_fill"] = len(structural_gap_fill_props)
    heuristic_recovery_enabled_for_doc = bool(options.use_heuristic_recovery)
    if heuristic_recovery_enabled_for_doc and len(docling_props) > 0:
        heuristic_recovery_enabled_for_doc = False
    if heuristic_recovery_enabled_for_doc and bool(options.heuristic_recovery_disable_when_strong_outline) and strong_outline:
        heuristic_recovery_enabled_for_doc = False
    if (
        heuristic_recovery_enabled_for_doc
        and bool(options.heuristic_recovery_disable_when_docling_rich)
        and len(docling_props) >= int(options.heuristic_recovery_docling_rich_threshold)
    ):
        heuristic_recovery_enabled_for_doc = False
    if heuristic_recovery_enabled_for_doc:
        existing_heading_keys = {
            heading_key_without_numbers(item.get("title")) or normalize_heading_key(item.get("title"))
            for item in proposals
            if normalize_heading_display(item.get("title"))
        }
        heuristic_recovery_props = extract_heuristic_recovery_proposals(
            block_index["ordered_blocks"],
            options,
            existing_title_keys=existing_heading_keys,
            blocked_pages=non_body_outline_pages(metadata),
        )
        proposals.extend(heuristic_recovery_props)
        source_counts["heuristic_recovery"] = len(heuristic_recovery_props)
    else:
        source_counts["heuristic_recovery"] = 0

    filtered = filter_and_anchor_proposals(proposals, block_index=block_index, metadata=metadata, options=options)
    accepted_headings = filtered["accepted_headings"]
    sections = build_section_tree(
        accepted_headings,
        block_index=block_index,
        metadata=metadata,
        options=options,
        doc_id=doc_id,
        stable_hash_fn=stable_hash_local,
    )
    doc_record = build_document_record(doc_id, metadata, sections, accepted_headings, loaded)
    passages = build_passages(sections, metadata=metadata, options=options, stable_hash_fn=stable_hash_local)

    section_export_rows: List[Dict[str, Any]] = []
    for row in sections:
        section_export_rows.append({k: v for k, v in row.items() if k != "block_rows"})

    covered_abs_indices = {
        idx
        for row in sections
        for idx in range(int((row.get("span") or {}).get("start_abs_block_index") or 0), int((row.get("span") or {}).get("end_abs_block_index") or -1) + 1)
    }
    coverage_chars = sum(
        int(block.get("char_len") or len(block.get("text") or ""))
        for block in block_index["ordered_blocks"]
        if int(block.get("abs_block_index") or -1) in covered_abs_indices
    )
    total_chars = int(block_index.get("total_block_chars") or 0)
    coverage_pct = round((coverage_chars / total_chars) * 100.0, 2) if total_chars else 0.0
    fallback_anchor_count = sum(1 for row in accepted_headings if str(row.get("anchor_method") or "") == "page_start_fallback")
    section_types = [row.get("section_type") for row in sections]
    tiny_section_count = sum(1 for row in sections if "tiny_section" in (row.get("quality_flags") or []))
    deep_section_count = sum(1 for row in sections if int(row.get("level") or 0) >= 4)
    retrieval_suppressed_section_count = sum(1 for row in sections if not bool(row.get("retrieval_eligible", True)))
    retrieval_eligible_tiny_section_count = sum(
        1 for row in sections if "tiny_section" in (row.get("quality_flags") or []) and bool(row.get("retrieval_eligible", True))
    )
    structural_wrapper_count = sum(1 for row in sections if "structural_wrapper" in (row.get("quality_flags") or []))
    metadata_stripped_section_count = sum(1 for row in sections if "metadata_stripped" in (row.get("quality_flags") or []))
    accepted_source_counts = {
        "outline": sum(1 for row in accepted_headings if str(row.get("source") or "").startswith("outline")),
        "docling": sum(1 for row in accepted_headings if str(row.get("source") or "") == "docling"),
        "grobid": sum(1 for row in accepted_headings if str(row.get("source") or "") == "grobid"),
        "heuristic": sum(1 for row in accepted_headings if str(row.get("source") or "").startswith("heuristic")),
        "synthetic": sum(1 for row in accepted_headings if str(row.get("source") or "") == "synthetic"),
    }
    summary_row = {
        "doc_id": doc_id,
        "file_name": metadata.get("file_name"),
        "page_count": metadata.get("page_count"),
        "outline_count": (metadata.get("outline_counts") or {}).get("fitz") or (metadata.get("outline_counts") or {}).get("pypdf") or 0,
        "proposal_count": len(filtered["proposal_rows"]),
        "accepted_heading_count": len(accepted_headings),
        "section_count": len(section_export_rows),
        "passage_count": len(passages),
        "section_coverage_pct": coverage_pct,
        "fallback_anchor_count": fallback_anchor_count,
        "tiny_section_count": tiny_section_count,
        "deep_section_count": deep_section_count,
        "retrieval_suppressed_section_count": retrieval_suppressed_section_count,
        "retrieval_eligible_tiny_section_count": retrieval_eligible_tiny_section_count,
        "structural_wrapper_count": structural_wrapper_count,
        "metadata_stripped_section_count": metadata_stripped_section_count,
        "docling_status": (loaded.get("docling") or {}).get("status"),
        "grobid_status": (loaded.get("grobid_summary") or {}).get("status") or (loaded.get("grobid_summary") or {}).get("service_status") or "no_data",
        "strategy": "outline_first" if source_counts.get("outline") else ("docling_first" if source_counts.get("docling") else "heuristic_only"),
        "heading_sources": ", ".join(sorted({str(row.get("source") or "") for row in accepted_headings})) or "none",
        "accepted_outline_heading_count": accepted_source_counts["outline"],
        "accepted_docling_heading_count": accepted_source_counts["docling"],
        "accepted_grobid_heading_count": accepted_source_counts["grobid"],
        "accepted_heuristic_heading_count": accepted_source_counts["heuristic"],
        "has_references_section": bool(any(item == "references" for item in section_types)),
        "has_appendix_section": bool(any(item == "appendix" for item in section_types)),
        "collapsed_to_single_section": bool(len(section_export_rows) <= 1),
    }
    diagnostics = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_c",
        "doc_id": doc_id,
        "source_counts": source_counts,
        "proposal_count": len(filtered["proposal_rows"]),
        "accepted_heading_count": len(accepted_headings),
        "section_count": len(section_export_rows),
        "passage_count": len(passages),
        "section_coverage_pct": coverage_pct,
        "summary_row": summary_row,
        "notes": {
            "doc_title": filtered.get("doc_title"),
            "docling_status": (loaded.get("docling") or {}).get("status"),
            "grobid_status": (loaded.get("grobid_summary") or {}).get("status") or (loaded.get("grobid_summary") or {}).get("service_status") or "no_data",
            "heuristics_enabled_for_doc": heuristic_enabled_for_doc,
            "accepted_source_counts": accepted_source_counts,
            "accepted_heuristic_recovery_heading_count": sum(1 for row in accepted_headings if str(row.get("source") or "") == "heuristic_recovery"),
            "tiny_section_titles": [row.get("title") for row in sections if "tiny_section" in (row.get("quality_flags") or [])][:20],
            "retrieval_eligible_tiny_section_titles": [
                row.get("title")
                for row in sections
                if "tiny_section" in (row.get("quality_flags") or []) and bool(row.get("retrieval_eligible", True))
            ][:20],
            "retrieval_suppressed_titles": [row.get("title") for row in sections if not bool(row.get("retrieval_eligible", True))][:20],
            "structural_wrapper_titles": [row.get("title") for row in sections if "structural_wrapper" in (row.get("quality_flags") or [])][:20],
            "metadata_stripped_titles": [row.get("title") for row in sections if "metadata_stripped" in (row.get("quality_flags") or [])][:20],
        },
    }

    doc_record.update(
        {
            "strategy": summary_row["strategy"],
            "heading_sources": summary_row["heading_sources"],
            "section_coverage_pct": coverage_pct,
            "fallback_anchor_count": fallback_anchor_count,
            "tiny_section_count": tiny_section_count,
            "deep_section_count": deep_section_count,
            "retrieval_suppressed_section_count": retrieval_suppressed_section_count,
            "retrieval_eligible_tiny_section_count": retrieval_eligible_tiny_section_count,
            "structural_wrapper_count": structural_wrapper_count,
            "metadata_stripped_section_count": metadata_stripped_section_count,
            "docling_status": summary_row["docling_status"],
            "grobid_status": summary_row["grobid_status"],
            "accepted_outline_heading_count": accepted_source_counts["outline"],
            "accepted_docling_heading_count": accepted_source_counts["docling"],
            "accepted_grobid_heading_count": accepted_source_counts["grobid"],
            "accepted_heuristic_heading_count": accepted_source_counts["heuristic"],
            "quality_flags": [
                flag
                for flag in [
                    "fallback_anchor_headings" if fallback_anchor_count else "",
                    "high_tiny_section_ratio" if len(section_export_rows) and (tiny_section_count / max(1, len(section_export_rows))) >= 0.25 else "",
                    "retrieval_suppressed_sections_present" if retrieval_suppressed_section_count else "",
                ]
                if flag
            ],
            "normalization_notes": diagnostics["notes"],
        }
    )

    write_json_atomic(doc_artifacts["document_json"], doc_record)
    write_jsonl_rows(doc_artifacts["section_proposals_jsonl"], filtered["proposal_rows"])
    write_jsonl_rows(doc_artifacts["accepted_headings_jsonl"], accepted_headings)
    write_jsonl_rows(doc_artifacts["sections_jsonl"], section_export_rows)
    write_jsonl_rows(doc_artifacts["passages_jsonl"], passages)
    write_json_atomic(doc_artifacts["diagnostics_json"], diagnostics)

    bundle_index_row = {
        "doc_id": doc_id,
        "document_json": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["document_json"]),
        "section_proposals_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["section_proposals_jsonl"]),
        "accepted_headings_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["accepted_headings_jsonl"]),
        "sections_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["sections_jsonl"]),
        "passages_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["passages_jsonl"]),
        "diagnostics_json": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["diagnostics_json"]),
        "bundle_status": "ok",
    }

    return {
        "doc_id": doc_id,
        "document_row": doc_record,
        "section_rows": section_export_rows,
        "passage_rows": passages,
        "summary_row": summary_row,
        "bundle_index_row": bundle_index_row,
        "log_payload": {
            "proposal_count": len(filtered["proposal_rows"]),
            "accepted_heading_count": len(accepted_headings),
            "section_count": len(section_export_rows),
            "passage_count": len(passages),
            "coverage_pct": coverage_pct,
        },
        "event_payload": {
            "doc_id": doc_id,
            "proposal_count": len(filtered["proposal_rows"]),
            "accepted_heading_count": len(accepted_headings),
            "section_count": len(section_export_rows),
            "passage_count": len(passages),
            "section_coverage_pct": coverage_pct,
        },
    }


def run_phase_c(run_ctx: Any, options: PhaseCOptions, *, stable_hash_fn=None, log_event_fn=None, run_logger=None) -> Dict[str, Any]:
    options = options.normalized()
    stable_hash_local = stable_hash_fn or stable_hash
    normalized_dir = ensure_dir(Path(run_ctx.artifacts.normalized_dir))
    config_path = normalized_dir / "phase_c_config.json"
    runtime_path = normalized_dir / "phase_c_runtime.json"
    summary_path = normalized_dir / "phase_c_summary.json"
    assessment_path = normalized_dir / "phase_c_assessment.json"
    documents_path = normalized_dir / "documents.jsonl"
    sections_path = normalized_dir / "sections.jsonl"
    passages_path = normalized_dir / "passages.jsonl"
    index_path = normalized_dir / "normalized_document_bundles.jsonl"

    phase_b_assessment_path = Path(run_ctx.artifacts.parser_dir) / "phase_b_assessment.json"
    phase_b_index_path = Path(run_ctx.artifacts.parser_dir) / "parsed_document_bundles.jsonl"
    if not phase_b_index_path.exists():
        raise FileNotFoundError(f"Phase B index not found: {phase_b_index_path}")

    phase_b_assessment = read_json(phase_b_assessment_path) if phase_b_assessment_path.exists() else {}
    phase_b_can_continue = bool(((phase_b_assessment or {}).get("assessment") or {}).get("can_continue_to_next_phase", True))
    if not phase_b_can_continue:
        raise RuntimeError("Phase B assessment does not allow continuation to Phase C.")

    bundle_rows = read_jsonl_rows(phase_b_index_path)
    include_set = set(options.include_doc_ids or [])
    exclude_set = set(options.exclude_doc_ids or [])
    selected_bundles: List[Dict[str, Any]] = []
    for row in bundle_rows:
        doc_id = str(row.get("doc_id") or "")
        if include_set and doc_id not in include_set:
            continue
        if doc_id in exclude_set:
            continue
        selected_bundles.append(row)
    if options.doc_limit is not None:
        selected_bundles = selected_bundles[: int(options.doc_limit)]
    resolved_doc_concurrency = resolve_phase_c_doc_concurrency(options, doc_count=len(selected_bundles))

    runtime_payload = {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_c",
        "options": json_safe(asdict(options)),
        "python_runtime": {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
        },
        "phase_b_assessment_path": rel_to_run(Path(run_ctx.run_dir), phase_b_assessment_path),
        "phase_b_index_path": rel_to_run(Path(run_ctx.run_dir), phase_b_index_path),
        "selected_doc_count": len(selected_bundles),
        "available_cpu_count": available_cpu_count(),
        "resolved_doc_concurrency": resolved_doc_concurrency,
    }
    write_json_atomic(runtime_path, runtime_payload)
    write_json_atomic(config_path, {"generated_at_utc": utc_now_iso(), "phase": "phase_c", "options": json_safe(asdict(options))})

    if run_logger is not None:
        run_logger.info(
            "Phase C start | selected_docs=%s | concurrency=%s | cpu_count=%s | prefer_outline=%s | use_docling=%s | use_grobid=%s | use_heuristics=%s",
            len(selected_bundles),
            resolved_doc_concurrency,
            available_cpu_count(),
            options.prefer_outline,
            options.use_docling,
            options.use_grobid,
            options.use_heuristic_headings,
        )
    if log_event_fn is not None:
        log_event_fn(run_ctx, stage="phase_c", event="phase_started", selected_doc_count=len(selected_bundles), options=json_safe(asdict(options)))

    results_by_pos: Dict[int, Dict[str, Any]] = {}
    pending_bundles: List[tuple[int, Dict[str, Any]]] = []

    for position, bundle_row in enumerate(selected_bundles):
        doc_id = str(bundle_row.get("doc_id") or "")
        doc_dir = ensure_dir(normalized_dir / doc_id)
        doc_artifacts = {
            "document_json": doc_dir / "document.json",
            "section_proposals_jsonl": doc_dir / "section_proposals.jsonl",
            "accepted_headings_jsonl": doc_dir / "accepted_headings.jsonl",
            "sections_jsonl": doc_dir / "sections.jsonl",
            "passages_jsonl": doc_dir / "passages.jsonl",
            "diagnostics_json": doc_dir / "phase_c_diagnostics.json",
        }

        use_cache = bool(not options.force_rebuild and all(path.exists() for path in doc_artifacts.values()))
        if use_cache:
            doc_record = read_json(doc_artifacts["document_json"])
            doc_sections = read_jsonl_rows(doc_artifacts["sections_jsonl"])
            doc_passages = read_jsonl_rows(doc_artifacts["passages_jsonl"])
            diagnostics = read_json(doc_artifacts["diagnostics_json"])
            results_by_pos[position] = {
                "document_row": doc_record,
                "section_rows": doc_sections,
                "passage_rows": doc_passages,
                "summary_row": diagnostics.get("summary_row") or {},
                "bundle_index_row": {
                    "doc_id": doc_id,
                    "document_json": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["document_json"]),
                    "section_proposals_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["section_proposals_jsonl"]),
                    "accepted_headings_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["accepted_headings_jsonl"]),
                    "sections_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["sections_jsonl"]),
                    "passages_jsonl": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["passages_jsonl"]),
                    "diagnostics_json": rel_to_run(Path(run_ctx.run_dir), doc_artifacts["diagnostics_json"]),
                    "bundle_status": "cached",
                },
            }
            if run_logger is not None:
                run_logger.info("Phase C doc cached | doc_id=%s | sections=%s | passages=%s", doc_id, len(doc_sections), len(doc_passages))
            continue
        pending_bundles.append((position, bundle_row))

    if pending_bundles:
        with ThreadPoolExecutor(max_workers=resolved_doc_concurrency) as executor:
            future_map = {
                executor.submit(
                    build_phase_c_document_bundle,
                    run_ctx=run_ctx,
                    normalized_dir=normalized_dir,
                    bundle_row=bundle_row,
                    options=options,
                    stable_hash_local=stable_hash_local,
                ): (position, bundle_row)
                for position, bundle_row in pending_bundles
            }
            for future in as_completed(future_map):
                position, bundle_row = future_map[future]
                doc_id = str(bundle_row.get("doc_id") or "")
                try:
                    result = future.result()
                except Exception as exc:
                    if run_logger is not None:
                        run_logger.exception("Phase C doc failed | doc_id=%s", doc_id)
                    if log_event_fn is not None:
                        log_event_fn(
                            run_ctx,
                            stage="phase_c",
                            event="doc_failed",
                            doc_id=doc_id,
                            error_type=type(exc).__name__,
                            error_message=short_blob(str(exc), max_len=600) or type(exc).__name__,
                        )
                    continue
                results_by_pos[position] = {
                    "document_row": dict(result["document_row"]),
                    "section_rows": list(result["section_rows"]),
                    "passage_rows": list(result["passage_rows"]),
                    "summary_row": dict(result["summary_row"]),
                    "bundle_index_row": dict(result["bundle_index_row"]),
                }
                if run_logger is not None:
                    log_payload = dict(result.get("log_payload") or {})
                    run_logger.info(
                        "Phase C doc built | doc_id=%s | proposals=%s | accepted_headings=%s | sections=%s | passages=%s | coverage_pct=%s",
                        doc_id,
                        log_payload.get("proposal_count"),
                        log_payload.get("accepted_heading_count"),
                        log_payload.get("section_count"),
                        log_payload.get("passage_count"),
                        log_payload.get("coverage_pct"),
                    )
                if log_event_fn is not None:
                    log_event_fn(run_ctx, stage="phase_c", event="doc_normalized", **dict(result.get("event_payload") or {}))

    document_rows: List[Dict[str, Any]] = []
    section_rows: List[Dict[str, Any]] = []
    passage_rows: List[Dict[str, Any]] = []
    summary_rows: List[Dict[str, Any]] = []
    bundle_index_rows: List[Dict[str, Any]] = []
    for position in range(len(selected_bundles)):
        result = results_by_pos.get(position)
        if not result:
            continue
        document_rows.append(dict(result["document_row"]))
        section_rows.extend(list(result["section_rows"]))
        passage_rows.extend(list(result["passage_rows"]))
        summary_rows.append(dict(result["summary_row"]))
        bundle_index_rows.append(dict(result["bundle_index_row"]))

    write_jsonl_rows(documents_path, document_rows)
    write_jsonl_rows(sections_path, section_rows)
    write_jsonl_rows(passages_path, passage_rows)
    write_jsonl_rows(index_path, bundle_index_rows)

    assessment = assess_phase_c(summary_rows=summary_rows, section_rows=section_rows, passage_rows=passage_rows, options=options)
    assessment_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_c",
        "assessment": {k: v for k, v in assessment.items() if k != "qc_rows"},
        "qc_rows": assessment["qc_rows"],
        "runtime_path": rel_to_run(Path(run_ctx.run_dir), runtime_path),
        "summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
        "index_path": rel_to_run(Path(run_ctx.run_dir), index_path),
    }
    summary_payload = {
        "generated_at_utc": utc_now_iso(),
        "run_id": run_ctx.run_id,
        "phase": "phase_c",
        "options": json_safe(asdict(options)),
        "runtime_path": rel_to_run(Path(run_ctx.run_dir), runtime_path),
        "assessment": assessment_payload["assessment"],
        "qc_rows": assessment["qc_rows"],
        "documents": summary_rows,
        "artifacts": bundle_index_rows,
    }
    write_json_atomic(assessment_path, assessment_payload)
    write_json_atomic(summary_path, summary_payload)

    if run_logger is not None:
        run_logger.info(
            "Phase C finished | status=%s | quality_band=%s | documents=%s | sections=%s | passages=%s",
            assessment_payload["assessment"].get("status"),
            assessment_payload["assessment"].get("quality_band"),
            len(summary_rows),
            len(section_rows),
            len(passage_rows),
        )
    if log_event_fn is not None:
        log_event_fn(
            run_ctx,
            stage="phase_c",
            event="phase_finished",
            status=assessment_payload["assessment"].get("status"),
            quality_band=assessment_payload["assessment"].get("quality_band"),
            document_count=len(summary_rows),
            section_count=len(section_rows),
            passage_count=len(passage_rows),
        )

    from pdf_reporting import update_run_pdf_reports

    update_run_pdf_reports(run_ctx, phase_name="phase_c")

    return {
        "config_path": config_path,
        "runtime_path": runtime_path,
        "summary_path": summary_path,
        "assessment_path": assessment_path,
        "documents_path": documents_path,
        "sections_path": sections_path,
        "passages_path": passages_path,
        "index_path": index_path,
        "summary_rows": summary_rows,
        "bundle_rows": bundle_index_rows,
        "document_rows": document_rows,
        "section_rows": section_rows,
        "passage_rows": passage_rows,
        "assessment": assessment_payload["assessment"],
        "qc_rows": assessment["qc_rows"],
        "selected_count": len(selected_bundles),
        "metrics_update": {
            "status": assessment_payload["assessment"].get("status"),
            "quality_band": assessment_payload["assessment"].get("quality_band"),
            "document_count": len(summary_rows),
            "section_count": len(section_rows),
            "passage_count": len(passage_rows),
            "warning_count": assessment_payload["assessment"].get("counts", {}).get("warning_count"),
            "failure_count": assessment_payload["assessment"].get("counts", {}).get("failure_count"),
            "phase_c_summary_path": rel_to_run(Path(run_ctx.run_dir), summary_path),
            "phase_c_assessment_path": rel_to_run(Path(run_ctx.run_dir), assessment_path),
        },
    }


def build_phase_c_preview_rows(summary_rows, section_rows, *, per_doc: int = 6, preview_chars: int = 180) -> List[Dict[str, Any]]:
    sections_by_doc: Dict[str, List[Dict[str, Any]]] = {}
    for row in section_rows or []:
        sections_by_doc.setdefault(str(row.get("doc_id") or ""), []).append(row)

    priority_types = ["introduction", "background", "methods", "results", "discussion", "conclusion", "references", "appendix"]
    preview_rows: List[Dict[str, Any]] = []

    for summary in summary_rows or []:
        doc_id = str(summary.get("doc_id") or "")
        file_name = str(summary.get("file_name") or "")
        doc_sections = sorted(
            sections_by_doc.get(doc_id, []),
            key=lambda row: (
                int(row.get("page_start") or 0),
                int((row.get("span") or {}).get("start_abs_block_index") or 0),
            ),
        )
        selected: List[Dict[str, Any]] = []
        selected_ids = set()

        def add_row(row: Optional[Dict[str, Any]]) -> None:
            if not row:
                return
            section_id = str(row.get("section_id") or "")
            if not section_id or section_id in selected_ids:
                return
            selected.append(row)
            selected_ids.add(section_id)

        for row in doc_sections[:3]:
            add_row(row)

        for section_type in priority_types:
            match = next((row for row in doc_sections if str(row.get("section_type") or "") == section_type), None)
            add_row(match)
            if len(selected) >= int(per_doc):
                break

        for row in doc_sections:
            if len(selected) >= int(per_doc):
                break
            add_row(row)

        for row in selected[: int(per_doc)]:
            preview_rows.append(
                {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "title": row.get("title"),
                    "section_type": row.get("section_type"),
                    "pages": f"{row.get('page_start')}-{row.get('page_end')}",
                    "parser_sources": ", ".join(row.get("parser_sources") or []),
                    "text_preview": _truncate(clean_text(row.get("text")), max_len=preview_chars),
                }
            )

    return preview_rows


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase C lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="manual")
    parser.add_argument("--pipeline-version", default="pdf_scan_v3_phase_c_lab")
    parser.add_argument("--force-rebuild-phase-a", action="store_true")
    parser.add_argument("--force-rebuild-phase-b", action="store_true")
    parser.add_argument("--force-rebuild-phase-c", action="store_true")
    parser.add_argument("--suite-manifest", default="")
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

    summary_rows = phase_c_result["summary_rows"]
    rel = lambda path: rel_to_run(Path(run_ctx.run_dir), Path(path))

    print_section("Phase C Lab - Normalization Capabilities")
    print_kv({
        "selected_documents": phase_c_result["selected_count"],
        "documents_jsonl": rel(phase_c_result["documents_path"]),
        "sections_jsonl": rel(phase_c_result["sections_path"]),
        "passages_jsonl": rel(phase_c_result["passages_path"]),
    })

    print_section("Phase C Lab - What Happened")
    print_kv({
        "phase_c_config_json": rel(phase_c_result["config_path"]),
        "phase_c_runtime_json": rel(phase_c_result["runtime_path"]),
        "phase_c_summary_json": rel(phase_c_result["summary_path"]),
        "phase_c_assessment_json": rel(phase_c_result["assessment_path"]),
        "documents_processed": len(summary_rows),
        "sections_written": len(phase_c_result["section_rows"]),
        "passages_written": len(phase_c_result["passage_rows"]),
        "phase_status": phase_c_result["assessment"].get("status"),
        "quality_band": phase_c_result["assessment"].get("quality_band"),
    })

    print_section("Phase C Lab - Document Summary")
    print_table(
        summary_rows,
        columns=["doc_id", "file_name", "page_count", "strategy", "accepted_heading_count", "section_count", "passage_count", "section_coverage_pct", "fallback_anchor_count"],
        max_rows=20,
        max_col_width=44,
    )

    print_section("Phase C Lab - QC")
    print_table(
        phase_c_result["qc_rows"],
        columns=["check", "status", "value", "expected", "why", "fix"],
        max_rows=20,
        max_col_width=46,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
