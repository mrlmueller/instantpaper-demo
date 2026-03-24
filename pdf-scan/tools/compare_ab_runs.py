#!/usr/bin/env python3
"""
Compare two pipeline runs (baseline vs optimized) on Phase F/G outputs.

Reads the final phase_g output from each run and compares:
  1. Document rankings (which docs are relevant)
  2. Section rankings (which sections are top)
  3. Cross-encoder scores (Spearman correlation)
  4. Judge verdicts (if available)
  5. Timing differences

Usage:
  python tools/compare_ab_runs.py <baseline_run_id> <optimized_run_id>
  python tools/compare_ab_runs.py --from-json  # reads ab_test_baseline.json + ab_test_optimized.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PDF_SCAN_DIR = Path(__file__).resolve().parents[1]


def load_jsonl(path: Path) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def spearman_rank_correlation(list_a: list[float], list_b: list[float]) -> float:
    """Spearman rank correlation between two lists of values."""
    n = len(list_a)
    if n < 2:
        return 1.0

    # Rank
    def rank(values):
        indexed = sorted(enumerate(values), key=lambda x: x[1], reverse=True)
        ranks = [0.0] * n
        for rank_pos, (orig_idx, _) in enumerate(indexed):
            ranks[orig_idx] = float(rank_pos)
        return ranks

    ra = rank(list_a)
    rb = rank(list_b)
    d2 = sum((a - b) ** 2 for a, b in zip(ra, rb))
    return 1.0 - 6.0 * d2 / (n * (n * n - 1))


def compare_runs(base_dir: Path, opt_dir: Path) -> dict:
    results = {}

    # ─── Phase F: Cross-encoder scores ───
    base_f_packs = base_dir / "rerank" / "phase_f_candidate_packs.jsonl"
    opt_f_packs = opt_dir / "rerank" / "phase_f_candidate_packs.jsonl"

    if base_f_packs.exists() and opt_f_packs.exists():
        base_packs = {p["candidate_id"]: p for p in load_jsonl(base_f_packs)}
        opt_packs = {p["candidate_id"]: p for p in load_jsonl(opt_f_packs)}

        common_ids = sorted(set(base_packs) & set(opt_packs))
        results["common_candidates"] = len(common_ids)
        results["baseline_only"] = len(set(base_packs) - set(opt_packs))
        results["optimized_only"] = len(set(opt_packs) - set(base_packs))

        if common_ids:
            base_scores = [
                base_packs[cid].get("cross_encoder_score", 0) for cid in common_ids
            ]
            opt_scores = [
                opt_packs[cid].get("cross_encoder_score", 0) for cid in common_ids
            ]
            results["ce_spearman"] = spearman_rank_correlation(base_scores, opt_scores)

            # Score differences
            diffs = [abs(b - o) for b, o in zip(base_scores, opt_scores)]
            results["ce_max_diff"] = max(diffs)
            results["ce_avg_diff"] = sum(diffs) / len(diffs)
            results["ce_median_diff"] = sorted(diffs)[len(diffs) // 2]

    # ─── Phase F: Rerank summary ───
    base_f_summary = base_dir / "rerank" / "phase_f_summary.json"
    opt_f_summary = opt_dir / "rerank" / "phase_f_summary.json"
    if base_f_summary.exists() and opt_f_summary.exists():
        bs = load_json(base_f_summary)
        os_data = load_json(opt_f_summary)
        results["baseline_f_pairs"] = bs.get("total_pairs_scored", "?")
        results["optimized_f_pairs"] = os_data.get("total_pairs_scored", "?")

    # ─── Phase G: Document assessments ───
    base_g = base_dir / "final" / "phase_g_document_assessments.jsonl"
    opt_g = opt_dir / "final" / "phase_g_document_assessments.jsonl"

    if base_g.exists() and opt_g.exists():
        base_docs = {d["doc_id"]: d for d in load_jsonl(base_g)}
        opt_docs = {d["doc_id"]: d for d in load_jsonl(opt_g)}
        common_docs = sorted(set(base_docs) & set(opt_docs))

        results["doc_count"] = len(common_docs)

        # Compare document verdicts
        verdict_matches = 0
        verdict_diffs = []
        for did in common_docs:
            bv = base_docs[did].get("verdict", "?")
            ov = opt_docs[did].get("verdict", "?")
            if bv == ov:
                verdict_matches += 1
            else:
                verdict_diffs.append({"doc_id": did, "base": bv, "opt": ov})

        results["verdict_match_rate"] = (
            verdict_matches / len(common_docs) if common_docs else 1.0
        )
        results["verdict_differences"] = verdict_diffs

        # Compare document probability scores
        if common_docs:
            base_probs = [base_docs[d].get("probability", 0) for d in common_docs]
            opt_probs = [opt_docs[d].get("probability", 0) for d in common_docs]
            results["doc_prob_spearman"] = spearman_rank_correlation(
                base_probs, opt_probs
            )

            prob_diffs = [abs(b - o) for b, o in zip(base_probs, opt_probs)]
            results["doc_prob_max_diff"] = max(prob_diffs)
            results["doc_prob_avg_diff"] = sum(prob_diffs) / len(prob_diffs)

    # ─── Phase G: Section rankings ───
    base_gs = base_dir / "final" / "phase_g_section_rankings.jsonl"
    opt_gs = opt_dir / "final" / "phase_g_section_rankings.jsonl"

    if base_gs.exists() and opt_gs.exists():
        base_secs = load_jsonl(base_gs)
        opt_secs = load_jsonl(opt_gs)

        base_top10 = set(
            s.get("candidate_id", s.get("section_id")) for s in base_secs[:10]
        )
        opt_top10 = set(
            s.get("candidate_id", s.get("section_id")) for s in opt_secs[:10]
        )
        results["section_top10_overlap"] = len(base_top10 & opt_top10)
        results["section_top10_total"] = 10

        base_top5 = set(
            s.get("candidate_id", s.get("section_id")) for s in base_secs[:5]
        )
        opt_top5 = set(s.get("candidate_id", s.get("section_id")) for s in opt_secs[:5])
        results["section_top5_overlap"] = len(base_top5 & opt_top5)

    # ─── Timing ───
    base_metrics = base_dir / "metrics.json"
    opt_metrics = opt_dir / "metrics.json"
    if base_metrics.exists() and opt_metrics.exists():
        bm = load_json(base_metrics)
        om = load_json(opt_metrics)
        for phase in ["phase_f", "phase_g"]:
            bt = bm.get("stages", {}).get(phase, {}).get("wall_time_ms")
            ot = om.get("stages", {}).get(phase, {}).get("wall_time_ms")
            if bt and ot:
                results[f"{phase}_baseline_ms"] = bt
                results[f"{phase}_optimized_ms"] = ot
                results[f"{phase}_speedup"] = round(bt / ot, 2) if ot > 0 else 0

    return results


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline_run", nargs="?", default="")
    parser.add_argument("optimized_run", nargs="?", default="")
    parser.add_argument("--from-json", action="store_true")
    args = parser.parse_args()

    if args.from_json:
        base_info = load_json(PDF_SCAN_DIR / "tools" / "ab_test_baseline.json")
        opt_info = load_json(PDF_SCAN_DIR / "tools" / "ab_test_optimized.json")
        base_dir = Path(base_info["run_dir"])
        opt_dir = Path(opt_info["run_dir"])
    elif args.baseline_run and args.optimized_run:
        base_dir = PDF_SCAN_DIR / "runs" / args.baseline_run
        opt_dir = PDF_SCAN_DIR / "runs" / args.optimized_run
    else:
        print("Usage: compare_ab_runs.py <baseline_run> <optimized_run>")
        print("       compare_ab_runs.py --from-json")
        return 1

    print(f"Baseline: {base_dir}")
    print(f"Optimized: {opt_dir}")

    if not base_dir.exists():
        print(f"ERROR: {base_dir} does not exist")
        return 1
    if not opt_dir.exists():
        print(f"ERROR: {opt_dir} does not exist")
        return 1

    results = compare_runs(base_dir, opt_dir)

    print(f"\n{'='*60}")
    print("  A/B COMPARISON RESULTS")
    print(f"{'='*60}")

    if "ce_spearman" in results:
        print(
            f"\n  Cross-encoder scores ({results.get('common_candidates', '?')} common candidates):"
        )
        print(f"    Spearman rank correlation: {results['ce_spearman']:.4f}")
        print(f"    Max score difference: {results['ce_max_diff']:.6f}")
        print(f"    Avg score difference: {results['ce_avg_diff']:.6f}")

    if "doc_prob_spearman" in results:
        print(f"\n  Document assessments ({results.get('doc_count', '?')} docs):")
        print(f"    Probability Spearman: {results['doc_prob_spearman']:.4f}")
        print(f"    Max prob difference: {results['doc_prob_max_diff']:.4f}")
        print(f"    Verdict match rate: {results['verdict_match_rate']:.1%}")
        if results.get("verdict_differences"):
            for vd in results["verdict_differences"]:
                print(
                    f"      DIFF: {vd['doc_id'][:20]}... base={vd['base']} opt={vd['opt']}"
                )

    if "section_top10_overlap" in results:
        print(f"\n  Section rankings:")
        print(f"    Top-5 overlap: {results.get('section_top5_overlap', '?')}/5")
        print(f"    Top-10 overlap: {results['section_top10_overlap']}/10")

    if "phase_f_speedup" in results:
        print(f"\n  Timing:")
        print(f"    Phase F baseline: {results['phase_f_baseline_ms']/1000:.1f}s")
        print(f"    Phase F optimized: {results['phase_f_optimized_ms']/1000:.1f}s")
        print(f"    Speedup: {results['phase_f_speedup']}x")

    # Save comparison
    out = PDF_SCAN_DIR / "tools" / "ab_comparison.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\n  Full results saved: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
