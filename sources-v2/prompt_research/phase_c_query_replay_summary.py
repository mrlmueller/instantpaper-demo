from __future__ import annotations

import argparse
import csv
import json
import statistics
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = ROOT / "probe_outputs"


def _read_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _latest_probe() -> Path:
    paths = sorted(OUTPUT_DIR.glob("phase_c_query_replay_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not paths:
        raise FileNotFoundError(f"No replay probe JSON files found under {OUTPUT_DIR}")
    return paths[0]


def _fmt_num(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:.2f}"
    return str(value)


def _fmt_pct(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100.0:.1f}%"


def _median(values: List[float]) -> Optional[float]:
    if not values:
        return None
    return float(statistics.median(values))


def _flatten_openalex(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for row in rows:
        cur = row.get("current") or {}
        alt = row.get("alt_surface_probe") or {}
        flat.append(
            {
                "provider": "openalex",
                "index": row.get("index"),
                "intent": row.get("intent"),
                "language": row.get("language"),
                "search_field": row.get("search_field"),
                "chars": row.get("chars"),
                "current_count": cur.get("count"),
                "current_status": (cur.get("http") or {}).get("status_code"),
                "current_anchor_rate": (cur.get("sample") or {}).get("sample_title_anchor_rate"),
                "current_core_rate": (cur.get("sample") or {}).get("sample_title_core_rate"),
                "alt_surface": alt.get("surface"),
                "alt_count": alt.get("count"),
                "alt_status": (alt.get("http") or {}).get("status_code"),
                "alt_over_current_ratio": row.get("alt_over_current_ratio"),
                "notes": row.get("notes"),
                "query_string": row.get("query_string"),
            }
        )
    return flat


def _flatten_s2(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    flat: List[Dict[str, Any]] = []
    for row in rows:
        bulk = row.get("bulk") or {}
        search = row.get("search") or {}
        no_neg = row.get("bulk_without_negatives") or {}
        flat.append(
            {
                "provider": "semanticscholar",
                "index": row.get("index"),
                "intent": row.get("intent"),
                "language": row.get("language"),
                "chars": row.get("chars"),
                "required_groups": row.get("required_groups"),
                "negative_count": row.get("negative_count"),
                "has_advanced_syntax": row.get("has_advanced_syntax"),
                "bulk_total": bulk.get("total"),
                "bulk_status": (bulk.get("http") or {}).get("status_code"),
                "bulk_anchor_rate": (bulk.get("sample") or {}).get("sample_title_anchor_rate"),
                "bulk_core_rate": (bulk.get("sample") or {}).get("sample_title_core_rate"),
                "search_total": search.get("total"),
                "search_status": (search.get("http") or {}).get("status_code"),
                "search_over_bulk_ratio": row.get("search_over_bulk_ratio"),
                "bulk_without_negatives_total": no_neg.get("total"),
                "no_negative_over_current_ratio": row.get("no_negative_over_current_ratio"),
                "notes": row.get("notes"),
                "query_string": row.get("query_string"),
            }
        )
    return flat


def _write_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def _top_openalex_surface_lifts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = [r for r in rows if isinstance(r.get("alt_over_current_ratio"), (int, float))]
    ranked.sort(key=lambda r: (-(float(r.get("alt_over_current_ratio") or 0.0)), int(r.get("current_count") or 0)))
    return ranked[:8]


def _top_s2_negative_penalties(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = [r for r in rows if isinstance(r.get("no_negative_over_current_ratio"), (int, float))]
    ranked.sort(key=lambda r: (-(float(r.get("no_negative_over_current_ratio") or 0.0)), int(r.get("bulk_total") or 0)))
    return ranked[:8]


def _top_s2_endpoint_divergence(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ranked = [r for r in rows if isinstance(r.get("search_over_bulk_ratio"), (int, float))]
    ranked.sort(key=lambda r: float(r.get("search_over_bulk_ratio") or 0.0))
    return ranked[:8]


def _top_low_yield(rows: List[Dict[str, Any]], key: str, *, n: int = 8) -> List[Dict[str, Any]]:
    ranked = [r for r in rows if isinstance(r.get(key), int)]
    ranked.sort(key=lambda r: (int(r.get(key) or 0), str(r.get("language") or ""), str(r.get("intent") or "")))
    return ranked[:n]


def _summarize_openalex_lang(rows: List[Dict[str, Any]], lang: str) -> Dict[str, Any]:
    sub = [r for r in rows if r.get("language") == lang]
    counts = [int(r.get("current_count") or 0) for r in sub]
    zero = sum(1 for c in counts if c == 0)
    anchor_rates = [float(r.get("current_anchor_rate")) for r in sub if isinstance(r.get("current_anchor_rate"), (int, float))]
    return {
        "queries": len(sub),
        "zero": zero,
        "zero_rate": (float(zero) / float(max(1, len(sub)))) if sub else None,
        "count_median": statistics.median(counts) if counts else None,
        "sample_anchor_rate_median": _median(anchor_rates),
    }


def _summarize_s2_lang(rows: List[Dict[str, Any]], lang: str) -> Dict[str, Any]:
    sub = [r for r in rows if r.get("language") == lang]
    bulk_totals = [int(r.get("bulk_total") or 0) for r in sub]
    zero = sum(1 for c in bulk_totals if c == 0)
    anchor_rates = [float(r.get("bulk_anchor_rate")) for r in sub if isinstance(r.get("bulk_anchor_rate"), (int, float))]
    return {
        "queries": len(sub),
        "zero": zero,
        "zero_rate": (float(zero) / float(max(1, len(sub)))) if sub else None,
        "bulk_total_median": statistics.median(bulk_totals) if bulk_totals else None,
        "sample_anchor_rate_median": _median(anchor_rates),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Summarize Phase C query replay probe output into markdown and CSV.")
    parser.add_argument("--input", type=Path, default=None, help="Replay probe JSON file. Defaults to latest.")
    parser.add_argument("--markdown-out", type=Path, default=None)
    parser.add_argument("--openalex-csv-out", type=Path, default=None)
    parser.add_argument("--s2-csv-out", type=Path, default=None)
    args = parser.parse_args()

    input_path = (args.input or _latest_probe()).resolve()
    data = _read_json(input_path)

    oa_rows = _flatten_openalex((data.get("openalex") or {}).get("queries") or [])
    s2_rows = _flatten_s2((data.get("semanticscholar") or {}).get("queries") or [])

    stem = input_path.stem
    md_path = args.markdown_out or (input_path.with_suffix(".summary.md"))
    oa_csv = args.openalex_csv_out or (input_path.with_name(f"{stem}.openalex.csv"))
    s2_csv = args.s2_csv_out or (input_path.with_name(f"{stem}.semanticscholar.csv"))

    _write_csv(oa_csv, oa_rows)
    _write_csv(s2_csv, s2_rows)

    oa_en = _summarize_openalex_lang(oa_rows, "en")
    oa_de = _summarize_openalex_lang(oa_rows, "de")
    s2_en = _summarize_s2_lang(s2_rows, "en")
    s2_de = _summarize_s2_lang(s2_rows, "de")

    lines: List[str] = []
    lines.append(f"# Phase C Query Replay Summary")
    lines.append("")
    lines.append(f"- Input: `{input_path}`")
    lines.append(f"- Run dir: `{data.get('run_dir')}`")
    lines.append(f"- OpenAlex CSV: `{oa_csv}`")
    lines.append(f"- S2 CSV: `{s2_csv}`")
    lines.append("")
    lines.append("## Provider Summary")
    lines.append("")
    oa_summary = (data.get("openalex") or {}).get("summary") or {}
    s2_summary = (data.get("semanticscholar") or {}).get("summary") or {}
    lines.append(f"- OpenAlex queries: {_fmt_num(oa_summary.get('queries'))}")
    lines.append(f"- OpenAlex zero-query rate: {_fmt_pct(oa_summary.get('zero_rate'))}")
    lines.append(f"- OpenAlex median count: {_fmt_num(oa_summary.get('count_median'))}")
    lines.append(f"- OpenAlex median alt/current surface ratio: {_fmt_num(oa_summary.get('alt_surface_ratio_median'))}")
    lines.append(f"- S2 queries: {_fmt_num(s2_summary.get('queries'))}")
    lines.append(f"- S2 bulk zero-query rate: {_fmt_pct(s2_summary.get('bulk_zero_rate'))}")
    lines.append(f"- S2 median bulk total: {_fmt_num(s2_summary.get('bulk_total_median'))}")
    lines.append(f"- S2 median search total: {_fmt_num(s2_summary.get('search_total_median'))}")
    lines.append(f"- S2 median no-negative/current ratio: {_fmt_num(s2_summary.get('negative_lift_median'))}")
    lines.append("")
    lines.append("## Language Breakdown")
    lines.append("")
    lines.append(f"- OpenAlex EN: queries={oa_en['queries']}, zero_rate={_fmt_pct(oa_en['zero_rate'])}, median_count={_fmt_num(oa_en['count_median'])}, median_sample_anchor_rate={_fmt_pct(oa_en['sample_anchor_rate_median'])}")
    lines.append(f"- OpenAlex DE: queries={oa_de['queries']}, zero_rate={_fmt_pct(oa_de['zero_rate'])}, median_count={_fmt_num(oa_de['count_median'])}, median_sample_anchor_rate={_fmt_pct(oa_de['sample_anchor_rate_median'])}")
    lines.append(f"- S2 EN: queries={s2_en['queries']}, zero_rate={_fmt_pct(s2_en['zero_rate'])}, median_bulk_total={_fmt_num(s2_en['bulk_total_median'])}, median_sample_anchor_rate={_fmt_pct(s2_en['sample_anchor_rate_median'])}")
    lines.append(f"- S2 DE: queries={s2_de['queries']}, zero_rate={_fmt_pct(s2_de['zero_rate'])}, median_bulk_total={_fmt_num(s2_de['bulk_total_median'])}, median_sample_anchor_rate={_fmt_pct(s2_de['sample_anchor_rate_median'])}")
    lines.append("")

    lines.append("## OpenAlex Surface-Lift Candidates")
    lines.append("")
    for row in _top_openalex_surface_lifts(oa_rows):
        lines.append(
            f"- #{row['index']} {row['language']} {row['intent']}: current={row['current_count']}, alt={row['alt_count']}, ratio={_fmt_num(row['alt_over_current_ratio'])}, note={row['notes']}"
        )
    lines.append("")

    lines.append("## Lowest-Yield OpenAlex Queries")
    lines.append("")
    for row in _top_low_yield(oa_rows, "current_count"):
        lines.append(f"- #{row['index']} {row['language']} {row['intent']}: count={row['current_count']}, field={row['search_field']}, note={row['notes']}")
    lines.append("")

    lines.append("## S2 Negative Penalty Candidates")
    lines.append("")
    for row in _top_s2_negative_penalties(s2_rows):
        lines.append(
            f"- #{row['index']} {row['language']} {row['intent']}: current={row['bulk_total']}, no_negative={row['bulk_without_negatives_total']}, ratio={_fmt_num(row['no_negative_over_current_ratio'])}, note={row['notes']}"
        )
    lines.append("")

    lines.append("## S2 Bulk-vs-Search Divergence")
    lines.append("")
    for row in _top_s2_endpoint_divergence(s2_rows):
        lines.append(
            f"- #{row['index']} {row['language']} {row['intent']}: bulk={row['bulk_total']}, search={row['search_total']}, search/bulk={_fmt_num(row['search_over_bulk_ratio'])}, note={row['notes']}"
        )
    lines.append("")

    lines.append("## Lowest-Yield S2 Queries")
    lines.append("")
    for row in _top_low_yield(s2_rows, "bulk_total"):
        lines.append(
            f"- #{row['index']} {row['language']} {row['intent']}: bulk_total={row['bulk_total']}, negatives={row['negative_count']}, groups={row['required_groups']}, note={row['notes']}"
        )
    lines.append("")

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(md_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
