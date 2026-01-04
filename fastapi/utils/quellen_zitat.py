from __future__ import annotations

from typing import Any, Mapping


_ALLOWED_MODES = {"auto", "authorYear", "full", "none"}


def _one_line(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _normalize_year(value: Any) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.strip().isdigit():
        try:
            return int(value.strip())
        except Exception:
            return None
    return None


def resolve_quelle_zitat_value(meta: Mapping[str, Any] | None) -> str:
    """Return the resolved citation string for {QUELLE_ZITAT} (or "" if unavailable)."""
    if not isinstance(meta, Mapping):
        return ""

    autor = _one_line(str(meta.get("autor") or ""))
    jahr = _normalize_year(meta.get("jahr"))
    zitat_frei = _one_line(str(meta.get("zitat") or ""))

    modus_raw = str(meta.get("zitatModus") or "auto").strip()
    modus = modus_raw if modus_raw in _ALLOWED_MODES else "auto"
    if modus == "none":
        return ""

    zitat_kurz = ""
    if modus == "authorYear":
        if autor and jahr is not None:
            zitat_kurz = f"{autor}, {jahr}"
    elif modus == "full":
        if zitat_frei:
            zitat_kurz = zitat_frei
    else:
        # auto: author+year if available, else free citation
        if autor and jahr is not None:
            zitat_kurz = f"{autor}, {jahr}"
        elif zitat_frei:
            zitat_kurz = zitat_frei

    return zitat_kurz or ""
