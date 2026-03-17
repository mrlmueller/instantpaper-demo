import argparse
import json
import sys
from collections import Counter
from pathlib import Path


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def load_phase_e_review(run_dir: Path):
    review_dir = run_dir / "phase_e_review"
    return {
        "summary": read_json(review_dir / "phase_e_review_summary.json"),
        "top_rows": read_json(review_dir / "phase_e_top_candidates.json"),
    }


def load_phase_f_review(run_dir: Path):
    review_dir = run_dir / "phase_f_review"
    return {
        "summary": read_json(review_dir / "phase_f_review_summary.json"),
        "rows": read_jsonl(review_dir / "phase_f_review_rows.jsonl"),
    }


def top_doc_count(rows, k):
    return len({str(row.get("doc_id") or "") for row in rows[:k] if str(row.get("doc_id") or "")})


def generic_count(rows, k):
    total = 0
    for row in rows[:k]:
        if bool(row.get("generic_title")):
            total += 1
    return total


def verdict_counter(rows, k, key="verdict"):
    return Counter(str(row.get(key) or "") for row in rows[:k] if str(row.get(key) or ""))


def by_section_id(rows):
    return {str(row.get("section_id") or ""): row for row in rows if str(row.get("section_id") or "")}


def overlap_ids(rows_a, rows_b, k):
    ids_a = {str(row.get("section_id") or "") for row in rows_a[:k] if str(row.get("section_id") or "")}
    ids_b = {str(row.get("section_id") or "") for row in rows_b[:k] if str(row.get("section_id") or "")}
    return {
        "k": k,
        "overlap_count": len(ids_a & ids_b),
        "jaccard": round(len(ids_a & ids_b) / max(1, len(ids_a | ids_b)), 4),
    }


def promote_demote_analysis(phase_e_rows, phase_f_rows, k_e=20, k_f=10):
    e_by_id = by_section_id(phase_e_rows)
    f_by_id = by_section_id(phase_f_rows)
    e_rank = {str(row.get("section_id") or ""): int(row.get("fused_rank") or 10_000) for row in phase_e_rows}
    f_rank = {str(row.get("section_id") or ""): int(row.get("rerank_rank") or 10_000) for row in phase_f_rows}

    promoted = []
    for row in phase_f_rows[:k_f]:
        sid = str(row.get("section_id") or "")
        if not sid:
            continue
        if int(e_rank.get(sid, 10_000)) > int(k_e):
            promoted.append(
                {
                    "section_id": sid,
                    "title": row.get("title"),
                    "doc_id": row.get("doc_id"),
                    "phase_e_rank": e_rank.get(sid),
                    "phase_f_rank": row.get("rerank_rank"),
                    "phase_f_score": row.get("rerank_score"),
                    "phase_f_verdict": row.get("verdict"),
                }
            )

    demoted = []
    for row in phase_e_rows[:k_f]:
        sid = str(row.get("section_id") or "")
        if not sid:
            continue
        if int(f_rank.get(sid, 10_000)) > int(k_e):
            demoted.append(
                {
                    "section_id": sid,
                    "title": row.get("title"),
                    "doc_id": row.get("doc_id"),
                    "phase_e_rank": row.get("fused_rank"),
                    "phase_e_verdict": row.get("verdict"),
                    "phase_f_rank": f_rank.get(sid),
                    "phase_f_verdict": (f_by_id.get(sid) or {}).get("verdict"),
                }
            )
    return {"promoted_into_top10": promoted, "demoted_out_of_top20": demoted}


def rank_shift_rows(phase_e_rows, phase_f_rows, limit=15):
    e_rank = {str(row.get("section_id") or ""): int(row.get("fused_rank") or 10_000) for row in phase_e_rows}
    combined = []
    for row in phase_f_rows:
        sid = str(row.get("section_id") or "")
        if not sid or sid not in e_rank:
            continue
        shift = int(e_rank[sid]) - int(row.get("rerank_rank") or 10_000)
        combined.append(
            {
                "section_id": sid,
                "title": row.get("title"),
                "doc_id": row.get("doc_id"),
                "phase_e_rank": e_rank[sid],
                "phase_f_rank": row.get("rerank_rank"),
                "rank_shift": shift,
                "phase_f_verdict": row.get("verdict"),
                "phase_f_score": row.get("rerank_score"),
                "cross_encoder_score": row.get("cross_encoder_score"),
            }
        )
    upward = sorted(combined, key=lambda row: (row["rank_shift"], -float(row.get("phase_f_score") or 0.0)), reverse=True)[:limit]
    downward = sorted(combined, key=lambda row: (row["rank_shift"], float(row.get("phase_f_score") or 0.0)))[:limit]
    return {"biggest_upward_moves": upward, "biggest_downward_moves": downward}


def build_summary(run_dir: Path):
    phase_e = load_phase_e_review(run_dir)
    phase_f = load_phase_f_review(run_dir)
    e_rows = list(phase_e["top_rows"])
    f_rows = list(phase_f["rows"])
    overlap10 = overlap_ids(e_rows, f_rows, 10)
    overlap20 = overlap_ids(e_rows, f_rows, 20)
    top10_e = verdict_counter(e_rows, 10)
    top10_f = verdict_counter(f_rows, 10)
    top20_e = verdict_counter(e_rows, 20)
    top20_f = verdict_counter(f_rows, 20)
    generic_top10_e = generic_count(e_rows, 10)
    generic_top10_f = generic_count(f_rows, 10)
    generic_top20_e = generic_count(e_rows, 20)
    generic_top20_f = generic_count(f_rows, 20)
    summary = {
        "run_id": run_dir.name,
        "phase_e_status": phase_e["summary"].get("phase_e_status"),
        "phase_f_status": (phase_f["summary"] or {}).get("review_category"),
        "top10_overlap": overlap10,
        "top20_overlap": overlap20,
        "top10_unique_docs": {
            "phase_e": top_doc_count(e_rows, 10),
            "phase_f": top_doc_count(f_rows, 10),
        },
        "top20_unique_docs": {
            "phase_e": top_doc_count(e_rows, 20),
            "phase_f": top_doc_count(f_rows, 20),
        },
        "generic_titles": {
            "top10_phase_e": generic_top10_e,
            "top10_phase_f": generic_top10_f,
            "top20_phase_e": generic_top20_e,
            "top20_phase_f": generic_top20_f,
        },
        "verdicts": {
            "top10_phase_e": dict(top10_e),
            "top10_phase_f": dict(top10_f),
            "top20_phase_e": dict(top20_e),
            "top20_phase_f": dict(top20_f),
        },
        "phase_e_warnings": list(phase_e["summary"].get("warnings") or []),
        "phase_f_findings": list(phase_f["summary"].get("findings") or []),
        "promotions_demotions": promote_demote_analysis(e_rows, f_rows),
        "rank_shifts": rank_shift_rows(e_rows, f_rows),
    }
    return summary


def write_report(run_dir: Path, summary: dict):
    out_dir = run_dir / "phase_ef_review"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "phase_ef_review_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = []
    lines.append(f"# Phase E/F Review - {run_dir.name}")
    lines.append("")
    lines.append("## Headline")
    lines.append("")
    lines.append(f"- Top-10 overlap: `{summary['top10_overlap']['overlap_count']}` (Jaccard `{summary['top10_overlap']['jaccard']}`)")
    lines.append(f"- Top-20 overlap: `{summary['top20_overlap']['overlap_count']}` (Jaccard `{summary['top20_overlap']['jaccard']}`)")
    lines.append(f"- Top-10 unique docs: Phase E `{summary['top10_unique_docs']['phase_e']}` -> Phase F `{summary['top10_unique_docs']['phase_f']}`")
    lines.append(f"- Top-20 unique docs: Phase E `{summary['top20_unique_docs']['phase_e']}` -> Phase F `{summary['top20_unique_docs']['phase_f']}`")
    lines.append(f"- Generic titles top-10: Phase E `{summary['generic_titles']['top10_phase_e']}` -> Phase F `{summary['generic_titles']['top10_phase_f']}`")
    lines.append(f"- Generic titles top-20: Phase E `{summary['generic_titles']['top20_phase_e']}` -> Phase F `{summary['generic_titles']['top20_phase_f']}`")
    lines.append("")
    if summary["phase_e_warnings"]:
        lines.append("## Phase E warnings")
        lines.append("")
        for item in summary["phase_e_warnings"]:
            lines.append(f"- {item}")
        lines.append("")
    if summary["phase_f_findings"]:
        lines.append("## Phase F findings")
        lines.append("")
        for item in summary["phase_f_findings"]:
            lines.append(f"- {item}")
        lines.append("")
    lines.append("## Promoted Into Phase F Top-10")
    lines.append("")
    promoted = summary["promotions_demotions"]["promoted_into_top10"]
    if promoted:
        for row in promoted:
            lines.append(f"- `{row['phase_e_rank']} -> {row['phase_f_rank']}` | `{row['doc_id']}` | `{row['title']}` | verdict `{row['phase_f_verdict']}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Demoted Out Of Phase F Top-20")
    lines.append("")
    demoted = summary["promotions_demotions"]["demoted_out_of_top20"]
    if demoted:
        for row in demoted:
            lines.append(f"- `E {row['phase_e_rank']} -> F {row['phase_f_rank']}` | `{row['doc_id']}` | `{row['title']}` | E verdict `{row['phase_e_verdict']}`")
    else:
        lines.append("- none")
    lines.append("")
    lines.append("## Biggest Upward Moves")
    lines.append("")
    for row in summary["rank_shifts"]["biggest_upward_moves"][:10]:
        lines.append(f"- `Δ {row['rank_shift']}` | `E {row['phase_e_rank']} -> F {row['phase_f_rank']}` | `{row['doc_id']}` | `{row['title']}` | score `{row['phase_f_score']}`")
    lines.append("")
    lines.append("## Biggest Downward Moves")
    lines.append("")
    for row in summary["rank_shifts"]["biggest_downward_moves"][:10]:
        lines.append(f"- `Δ {row['rank_shift']}` | `E {row['phase_e_rank']} -> F {row['phase_f_rank']}` | `{row['doc_id']}` | `{row['title']}` | score `{row['phase_f_score']}`")
    lines.append("")
    (out_dir / "phase_ef_review_report.md").write_text("\n".join(lines), encoding="utf-8")
    return out_dir


def main():
    parser = argparse.ArgumentParser(description="Compare Phase E fused ranking against Phase F reranking.")
    parser.add_argument("run_dir")
    args = parser.parse_args()
    run_dir = Path(args.run_dir).resolve()
    summary = build_summary(run_dir)
    out_dir = write_report(run_dir, summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nWrote review artifacts to {out_dir}")


if __name__ == "__main__":
    main()
