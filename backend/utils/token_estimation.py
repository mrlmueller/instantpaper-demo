from __future__ import annotations

import math
import re
from functools import lru_cache


@lru_cache(maxsize=1)
def _get_encoder():
    try:
        import tiktoken  # type: ignore
    except Exception as exc:
        raise RuntimeError(
            "tiktoken is required for token estimation. Install backend deps via backend/requirements.txt."
        ) from exc

    return tiktoken.get_encoding("o200k_base")


def count_words(text: str | None) -> int:
    s = (text or "").strip()
    if not s:
        return 0
    return len(re.findall(r"\S+", s))


def count_tokens(text: str | None) -> int:
    s = text or ""
    if not s:
        return 0
    enc = _get_encoder()
    try:
        return len(enc.encode(s))
    except Exception:
        return 0


def estimate_image_tokens(width_px: int | None, height_px: int | None, tokens_per_512_tile: int = 85) -> int:
    try:
        w = int(width_px or 0)
        h = int(height_px or 0)
        if w <= 0 or h <= 0:
            return 0
    except Exception:
        return 0

    tiles_w = math.ceil(w / 512)
    tiles_h = math.ceil(h / 512)
    return int(tiles_w * tiles_h * int(tokens_per_512_tile))

