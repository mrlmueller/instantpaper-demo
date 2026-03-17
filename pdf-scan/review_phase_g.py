import argparse
import json
from pathlib import Path


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def review_doc(row):
    reasons = []
    useful = bool(row.get("has_useful_information"))
    probability = float(row.get("doc_match_probability") or 0.0)
    top_score = float(row.get("top_section_score") or 0.0)
    if useful and top_score < 70.0:
        reasons.append("useful_but_top_section_below_70")
    if useful and probability < 0.63:
        reasons.append("useful_but_doc_probability_below_threshold")
    if useful and bool(row.get("only_penalized_high_sections")):
        reasons.append("useful_but_only_penalized_high_sections")
    if useful and bool(row.get("only_generic_high_sections")) and top_score < 80.0:
        reasons.append("useful_but_only_generic_high_sections")
    if (not useful) and top_score >= 78.0 and not bool(row.get("only_penalized_high_sections")):
        reasons.append("no_match_but_high_top_section")
    if (not useful) and probability >= 0.63 and top_score >= 62.0:
        reasons.append("no_match_but_probability_high")
    verdict = "strong"
    if reasons:
        verdict = "suspicious"
    return {
        "doc_id": row.get("doc_id"),
        "doc_title": row.get("doc_title"),
        "has_useful_information": useful,
        "doc_match_probability": probability,
        "top_section_title": row.get("top_section_title"),
        "top_section_score": top_score,
        "abstention_reason": row.get("abstention_reason"),
        "only_generic_high_sections": row.get("only_generic_high_sections"),
        "only_penalized_high_sections": row.get("only_penalized_high_sections"),
        "covered_subpoint_ratio": row.get("covered_subpoint_ratio"),
        "reasons": reasons,
        "verdict": verdict,
    }


def review_run(run_dir: Path):
    final_dir = run_dir / "final"
    doc_features = read_jsonl(final_dir / "doc_features.jsonl")
    output_payload = read_json(final_dir / "output.json")
    global_rankings = read_json(final_dir / "global_rankings.json")
    reviewed_docs = [review_doc(row) for row in doc_features]
    suspicious_useful = sum(1 for row in reviewed_docs if row["has_useful_information"] and row["verdict"] == "suspicious")
    suspicious_no_match = sum(1 for row in reviewed_docs if (not row["has_useful_information"]) and row["verdict"] == "suspicious")
    useful_count = sum(1 for row in reviewed_docs if row["has_useful_information"])
    no_match_count = sum(1 for row in reviewed_docs if not row["has_useful_information"])
    category = "strong"
    findings = []
    if suspicious_useful >= 2 or suspicious_no_match >= 2:
        category = "needs_follow_up"
        findings.append(f"Suspicious useful docs={suspicious_useful}, suspicious no-match docs={suspicious_no_match}.")
    elif suspicious_useful >= 1 or suspicious_no_match >= 1:
        category = "acceptable_with_noise"
        findings.append(f"Suspicious useful docs={suspicious_useful}, suspicious no-match docs={suspicious_no_match}.")
    if useful_count <= 0:
        findings.append("No PDFs were classified as useful.")
        if category == "strong":
            category = "acceptable_with_noise"
    summary = {
        "run_id": run_dir.name,
        "review_category": category,
        "useful_pdf_count": useful_count,
        "no_match_pdf_count": no_match_count,
        "suspicious_useful_count": suspicious_useful,
        "suspicious_no_match_count": suspicious_no_match,
        "findings": findings,
        "top_useful_docs": [row for row in reviewed_docs if row["has_useful_information"]][:10],
        "global_top_sections": list(global_rankings.get("rows") or [])[:10],
        "output_status": output_payload.get("status"),
    }
    output_dir = run_dir / "phase_g_review"
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase_g_review_rows.jsonl").write_text(
        "\n".join(json.dumps(row, ensure_ascii=False) for row in reviewed_docs) + ("\n" if reviewed_docs else ""),
        encoding="utf-8",
    )
    (output_dir / "phase_g_review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    parser = argparse.ArgumentParser(description="Review Phase G outputs.")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    summary = review_run(Path(args.run_dir).resolve())
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
