#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

PDF_SCAN_DIR = Path(__file__).resolve().parents[2]
if str(PDF_SCAN_DIR) not in sys.path:
    sys.path.insert(0, str(PDF_SCAN_DIR))

from tools.benchmark.evaluate_manual_benchmark import read_json


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Finalize a manually labeled topic benchmark suite.")
    parser.add_argument("--suite-id", required=True)
    args = parser.parse_args()

    suite_dir = (PDF_SCAN_DIR / "benchmark" / str(args.suite_id)).resolve()
    suite_manifest_path = suite_dir / "manifests" / "suite_manifest.json"
    suite_manifest = read_json(suite_manifest_path)

    judgment_paths = [suite_dir / rel_path for rel_path in suite_manifest.get("judgments") or []]
    judgments = [read_json(path) for path in judgment_paths]
    manifests = [read_json(suite_dir / rel_path) for rel_path in suite_manifest.get("documents") or []]

    label_counter: Counter[int] = Counter()
    gold_section_count = 0
    structural_miss_count = 0
    positive_doc_count = 0
    negative_doc_count = 0
    pending_docs: List[str] = []

    manifest_by_doc: Dict[str, Dict[str, Any]] = {str(item.get("doc_id") or ""): item for item in manifests}

    for judgment in judgments:
        doc_id = str(judgment.get("doc_id") or "")
        has_useful = judgment.get("has_useful_information")
        if has_useful is None:
            pending_docs.append(doc_id)
        elif bool(has_useful):
            positive_doc_count += 1
        else:
            negative_doc_count += 1
        gold_section_count += len(judgment.get("gold_section_refs") or [])
        structural_miss_count += len(judgment.get("structural_miss_sections") or [])
        for row in judgment.get("section_judgments") or []:
            value = row.get("label_0_to_3")
            if value is None:
                continue
            try:
                label_counter[int(value)] += 1
            except Exception:
                continue
        manifest_row = manifest_by_doc.get(doc_id)
        if manifest_row is not None:
            if has_useful is None:
                manifest_row["role_in_suite"] = "manual_review_pending"
                manifest_row["notes"] = "Manual benchmark labeling still incomplete."
            else:
                manifest_row["role_in_suite"] = "manual_exhaustive_positive" if bool(has_useful) else "manual_negative_anchor"
                manifest_row["notes"] = str(judgment.get("document_notes") or manifest_row.get("notes") or "")

    for rel_path in suite_manifest.get("documents") or []:
        current_path = suite_dir / rel_path
        doc_id = str(read_json(current_path).get("doc_id") or "")
        write_json(current_path, manifest_by_doc[doc_id])

    summary = {
        "suite_id": suite_manifest.get("suite_id"),
        "chapter_id": read_json(suite_dir / suite_manifest["chapter_specs"][0]).get("chapter_id"),
        "document_count": len(judgments),
        "positive_doc_count": positive_doc_count,
        "negative_doc_count": negative_doc_count,
        "pending_doc_count": len(pending_docs),
        "gold_section_count": gold_section_count,
        "structural_miss_count": structural_miss_count,
        "judgment_label_distribution": {str(key): value for key, value in sorted(label_counter.items())},
        "judgment_status": "complete" if not pending_docs else "incomplete",
        "pending_docs": pending_docs,
    }
    write_json(suite_dir / "suite_summary.json", summary)

    readme_lines = [
        f"# {suite_manifest.get('suite_id')}",
        "",
        "Manual exhaustive benchmark suite.",
        "",
        f"- document_count: `{summary['document_count']}`",
        f"- positive_doc_count: `{summary['positive_doc_count']}`",
        f"- negative_doc_count: `{summary['negative_doc_count']}`",
        f"- pending_doc_count: `{summary['pending_doc_count']}`",
        f"- gold_section_count: `{summary['gold_section_count']}`",
        f"- structural_miss_count: `{summary['structural_miss_count']}`",
        "",
        "Judgment meaning:",
        "- `label_0_to_3 = 0`: not useful",
        "- `label_0_to_3 = 1`: weak or marginal",
        "- `label_0_to_3 = 2`: useful support",
        "- `label_0_to_3 = 3`: core or strong support",
        "",
        f"Status: `{summary['judgment_status']}`",
    ]
    if pending_docs:
        readme_lines.extend(["", "Pending documents:"] + [f"- `{doc_id}`" for doc_id in pending_docs])
    (suite_dir / "README.md").write_text("\n".join(readme_lines).strip() + "\n", encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
