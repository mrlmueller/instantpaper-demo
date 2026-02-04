from __future__ import annotations

import re
import unicodedata
from typing import Any, Dict, Optional, Tuple

_LIGATURES = {
    "ﬁ": "fi",
    "ﬂ": "fl",
    "ﬀ": "ff",
    "ﬃ": "ffi",
    "ﬄ": "ffl",
    "ﬅ": "st",
    "ﬆ": "st",
}

_QUOTE_DASH_MAP = {
    "\u00a0": " ",  # nbsp
    "\u00ad": "",  # soft hyphen
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "’": "'",
    "‘": "'",
    "‛": "'",
    "–": "-",
    "—": "-",
    "−": "-",
    "‐": "-",
    "‑": "-",
    "‒": "-",
}

_STRIP_CHARS = "\"'“”„‟‘’‛()[]{}<>.,;:!?"


def normalize_ws(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip()


def normalize_spaces(s: str) -> str:
    # Backward-compat alias
    return normalize_ws(s)


def norm_match(s: str) -> str:
    """
    Text-level normalization for matching across:
    - Vector store chunks (EVIDENCE)
    - LLM anchors
    - PyMuPDF text extraction
    """
    s = unicodedata.normalize("NFKC", s or "")
    s = "".join(_LIGATURES.get(ch, ch) for ch in s)
    for a, b in _QUOTE_DASH_MAP.items():
        s = s.replace(a, b)
    s = normalize_ws(s)
    return s


def norm_token(w: str) -> str:
    """
    Token-level normalization for robust word-based matching.
    Removes punctuation and hyphens to survive PDF hyphenation / typography.
    """
    w = norm_match(w).lower().strip()
    w = w.strip(_STRIP_CHARS)
    w = re.sub(r"^[^\w]+|[^\w]+$", "", w)
    w = w.replace("-", "")
    return w


def norm_word(w: str) -> str:
    # Backward-compat alias
    return norm_token(w)


def find_token_sequence(hay_tokens: list, needle_tokens: list) -> Optional[int]:
    n = len(needle_tokens)
    if n <= 0:
        return None
    if len(hay_tokens) < n:
        return None
    for i in range(0, len(hay_tokens) - n + 1):
        if hay_tokens[i : i + n] == needle_tokens:
            return int(i)
    return None


def validate_anchor(
    anchor_raw: Any,
    evidence: str,
    *,
    min_words: int,
    max_words: int,
) -> Dict[str, Any]:
    """
    Validate that an anchor is a literal substring of the provided EVIDENCE
    (word-based, tolerant to typography/whitespace). If found, returns the
    snapped anchor exactly as it appears in evidence (single spaces).

    Returns dict:
      {text, ok, reason, span}
    where span is (start_word_index, word_count) in evidence_norm (or None).
    """
    raw = anchor_raw if isinstance(anchor_raw, str) else ""
    candidate = normalize_ws(raw)
    if not candidate:
        return {"text": "", "ok": False, "reason": "empty", "span": None}
    if "…" in candidate or "..." in candidate:
        return {"text": candidate, "ok": False, "reason": "ellipsis", "span": None}

    words = candidate.split(" ")
    if len(words) < int(min_words) or len(words) > int(max_words):
        return {"text": candidate, "ok": False, "reason": "word_count", "span": None}

    evidence_norm = normalize_ws(evidence)
    evidence_cmp = norm_match(evidence).lower()
    evidence_words = evidence_norm.split(" ") if evidence_norm else []
    evidence_words_cmp = [norm_token(w) for w in evidence_words]

    if evidence_words:
        needle = [norm_token(w) for w in words]
        start = find_token_sequence(evidence_words_cmp, needle)
        if start is not None:
            snapped = " ".join(evidence_words[start : start + len(words)])
            return {
                "text": snapped,
                "ok": True,
                "reason": "snapped",
                "span": (int(start), int(len(words))),
            }

    cand_cmp = norm_match(candidate).lower()
    if evidence_cmp and cand_cmp and cand_cmp in evidence_cmp:
        return {"text": candidate, "ok": True, "reason": "normalized_substring", "span": None}

    return {"text": candidate, "ok": False, "reason": "not_found_in_evidence", "span": None}


def derive_anchor_alt_from_span(
    evidence: str,
    span: Any,
    *,
    min_words: int = 6,
    max_words: int = 14,
) -> Optional[str]:
    if not span:
        return None
    words = normalize_ws(evidence).split(" ")
    try:
        start, n = int(span[0]), int(span[1])
    except Exception:
        return None
    take = min(10, n, int(max_words))
    take = max(int(min_words), int(take))
    return " ".join(words[start : start + take])


def expand_span(
    evidence: str,
    span: Any,
    *,
    min_words: int = 8,
    max_words: int = 20,
) -> Optional[Tuple[int, int]]:
    if not span:
        return None
    words = normalize_ws(evidence).split(" ")
    try:
        start, n = int(span[0]), int(span[1])
    except Exception:
        return None
    left = max(0, start)
    right = min(len(words), start + n)

    while (right - left) < int(min_words) and (right < len(words) or left > 0):
        if right < len(words):
            right += 1
        elif left > 0:
            left -= 1
        else:
            break

    if (right - left) > int(max_words):
        right = left + int(max_words)
    if (right - left) < int(min_words):
        return None
    return (int(left), int(right - left))

