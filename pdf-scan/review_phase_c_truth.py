#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from phase_a_lab import print_kv, print_section, print_table


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def build_review(truth_dir: Path) -> Dict[str, Any]:
    aggregate_summary = read_json(truth_dir / "aggregate_summary.json")
    aggregate_rows = list((read_json(truth_dir / "aggregate_rows.json") or {}).get("rows") or [])
    sorted_rows = sorted(
        aggregate_rows,
        key=lambda row: (
            str(row.get("category") or ""),
            float(row.get("match_ratio") or 0.0),
            -int(row.get("missing_truth_heading_count") or 0),
            -int(row.get("content_extra_count") or 0),
        ),
    )
    worst_rows = [
        row
        for row in sorted(
            aggregate_rows,
            key=lambda row: (
                0 if row.get("category") == "needs_follow_up" else 1 if row.get("category") == "acceptable_with_noise" else 2,
                float(row.get("match_ratio") or 0.0),
                -int(row.get("missing_truth_heading_count") or 0),
                -int(row.get("content_extra_count") or 0),
            )
        )
    ][:12]
    strong_rows = [row for row in aggregate_rows if row.get("category") == "strong"][:12]
    return {
        "summary": aggregate_summary,
        "worst_rows": worst_rows,
        "strong_rows": strong_rows,
        "all_rows": aggregate_rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Review aggregate Phase C truth-lab outputs.")
    parser.add_argument("--base-dir", default="pdf-scan", help="Path to pdf-scan")
    parser.add_argument("--run-id", required=True, help="Run id with phase_c_truth outputs")
    parser.add_argument("--truth-subdir", default="phase_c_truth", help="Subdirectory name under the run")
    args = parser.parse_args()

    truth_dir = (Path(args.base_dir).resolve() / "runs" / str(args.run_id) / str(args.truth_subdir)).resolve()
    review = build_review(truth_dir)

    print_section("Phase C Truth Review")
    print_kv(review["summary"])
    print_section("Worst Documents")
    print_table(
        review["worst_rows"],
        columns=[
            "doc_id",
            "match_ratio",
            "missing_truth_heading_count",
            "content_extra_count",
            "category",
            "sample_missing_truth_titles",
            "sample_content_extras",
        ],
        max_rows=20,
        max_col_width=42,
    )
    print_section("Strong Documents")
    print_table(
        review["strong_rows"],
        columns=["doc_id", "match_ratio", "missing_truth_heading_count", "content_extra_count", "category"],
        max_rows=20,
        max_col_width=42,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
