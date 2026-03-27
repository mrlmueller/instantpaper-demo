#!/usr/bin/env python3
"""
Final before/after benchmark using the score_cross_encoder_pairs function
from phase_f_lab.py with all optimizations applied.

Tests:
1. Original config (PT, batch=8, max_length=1536, old text lengths)
2. New config (ONNX INT8, batch=32, max_length=1536, new text lengths)

Uses real data from test run.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phase_f_lab import score_cross_encoder_pairs, PhaseFOptions


def load_pairs_with_text_sim(
    run_id: str, max_pairs: int = 80, section_max: int = 2200, passage_max: int = 520
):
    """Load pairs and simulate text truncation as if they were built with given limits."""
    run_dir = Path(__file__).resolve().parent.parent / "runs" / run_id / "rerank"

    packs = []
    with open(run_dir / "phase_f_candidate_packs.jsonl", encoding="utf-8") as f:
        for line in f:
            packs.append(json.loads(line))

    qp = json.loads((run_dir.parent / "query_plan.json").read_text(encoding="utf-8"))
    global_query = (
        qp.get("refined_question", "research question") or "research question"
    )

    pairs = []
    for pack in packs:
        text = pack.get("candidate_text", "")
        # Approximate text truncation based on the ratio of excerpt limits
        # Original packs were built with section_max=2200, passage_max=520
        if section_max != 2200 or passage_max != 520:
            old_budget = 2200 + 3 * 520  # ~3760 chars
            new_budget = section_max + 3 * passage_max
            ratio = new_budget / old_budget
            text = text[: int(len(text) * ratio)]

        pairs.append(
            {
                "candidate_id": pack.get("candidate_id"),
                "query_kind": "global",
                "query": global_query,
                "candidate_text": text,
            }
        )
        for sp_id in list(pack.get("chosen_subpoint_ids") or []):
            pairs.append(
                {
                    "candidate_id": pack.get("candidate_id"),
                    "query_kind": "subpoint",
                    "subpoint_id": sp_id,
                    "query": f"Subpoint {sp_id}: {global_query}",
                    "candidate_text": text,
                }
            )

    return pairs[:max_pairs]


def main():
    run_id = "a33419bf76ad298d82369172"
    max_pairs = 80

    # ======================================
    # CONFIG 1: BEFORE (original defaults)
    # ======================================
    print("=" * 70)
    print("BEFORE: Original config (PyTorch, batch=8, old text lengths)")
    print("=" * 70)

    pairs_old = load_pairs_with_text_sim(
        run_id, max_pairs, section_max=2200, passage_max=520
    )
    text_lens_old = [len(p["candidate_text"]) for p in pairs_old]
    print(
        f"  Pairs: {len(pairs_old)}, Avg text: {sum(text_lens_old)/len(text_lens_old):.0f} chars"
    )

    opt_before = PhaseFOptions(
        cross_encoder_prefer_onnx=False,  # Force PyTorch
        cross_encoder_batch_size=8,  # Old batch size
        cross_encoder_max_length=1536,
        section_excerpt_max_chars=2200,  # Old text length
        passage_excerpt_max_chars=520,
    )

    result_before = score_cross_encoder_pairs(pairs_old, opt_before)
    rt_before = result_before["runtime"]
    print(f"  Backend: {rt_before.get('backend', 'pytorch')}")
    print(
        f"  Elapsed: {rt_before['elapsed_ms']:.0f}ms ({rt_before['elapsed_ms']/1000:.1f}s)"
    )
    print(
        f"  Throughput: {len(pairs_old) / (rt_before['elapsed_ms'] / 1000):.2f} pairs/sec"
    )

    # ======================================
    # CONFIG 2: AFTER (all optimizations)
    # ======================================
    print()
    print("=" * 70)
    print("AFTER: Optimized config (ONNX INT8, batch=32, shorter texts)")
    print("=" * 70)

    pairs_new = load_pairs_with_text_sim(
        run_id, max_pairs, section_max=1400, passage_max=400
    )
    text_lens_new = [len(p["candidate_text"]) for p in pairs_new]
    print(
        f"  Pairs: {len(pairs_new)}, Avg text: {sum(text_lens_new)/len(text_lens_new):.0f} chars"
    )

    opt_after = PhaseFOptions(
        cross_encoder_prefer_onnx=True,  # Use ONNX INT8
        cross_encoder_batch_size=32,  # New batch size
        cross_encoder_max_length=1536,
        section_excerpt_max_chars=1400,  # Shorter text
        passage_excerpt_max_chars=400,
    )

    result_after = score_cross_encoder_pairs(pairs_new, opt_after)
    rt_after = result_after["runtime"]
    print(f"  Backend: {rt_after.get('backend', 'unknown')}")
    print(
        f"  Elapsed: {rt_after['elapsed_ms']:.0f}ms ({rt_after['elapsed_ms']/1000:.1f}s)"
    )
    print(
        f"  Throughput: {len(pairs_new) / (rt_after['elapsed_ms'] / 1000):.2f} pairs/sec"
    )

    # ======================================
    # COMPARISON
    # ======================================
    print()
    print("=" * 70)
    print("COMPARISON")
    print("=" * 70)
    speedup = (
        rt_before["elapsed_ms"] / rt_after["elapsed_ms"]
        if rt_after["elapsed_ms"] > 0
        else 0
    )
    throughput_before = len(pairs_old) / (rt_before["elapsed_ms"] / 1000)
    throughput_after = len(pairs_new) / (rt_after["elapsed_ms"] / 1000)

    # Extrapolate to 420 pairs (full run)
    est_before_420 = 420 / throughput_before
    est_after_420 = 420 / throughput_after

    print(
        f"  Before: {rt_before['elapsed_ms']/1000:.1f}s for {len(pairs_old)} pairs ({throughput_before:.2f}/sec)"
    )
    print(
        f"  After:  {rt_after['elapsed_ms']/1000:.1f}s for {len(pairs_new)} pairs ({throughput_after:.2f}/sec)"
    )
    print(f"  Speedup: {speedup:.2f}x")
    print()
    print(f"  Estimated for 420 pairs (full run):")
    print(f"    Before: {est_before_420:.0f}s ({est_before_420/60:.1f} min)")
    print(f"    After:  {est_after_420:.0f}s ({est_after_420/60:.1f} min)")
    print(
        f"    Savings: {est_before_420 - est_after_420:.0f}s ({(est_before_420 - est_after_420)/60:.1f} min)"
    )

    # Score correlation check
    print()
    print("Score correlation (ranking preservation):")
    before_scores = sorted(
        [(r["candidate_id"], r["score_prob"]) for r in result_before["rows"]],
        key=lambda x: x[1],
        reverse=True,
    )
    after_scores = sorted(
        [(r["candidate_id"], r["score_prob"]) for r in result_after["rows"]],
        key=lambda x: x[1],
        reverse=True,
    )

    before_rank = {cid: i for i, (cid, _) in enumerate(before_scores)}
    after_rank = {cid: i for i, (cid, _) in enumerate(after_scores)}

    # Spearman-like rank correlation
    common = set(before_rank.keys()) & set(after_rank.keys())
    if common:
        n = len(common)
        d_squared = sum((before_rank[cid] - after_rank[cid]) ** 2 for cid in common)
        rho = 1 - (6 * d_squared) / (n * (n**2 - 1)) if n > 1 else 1.0
        print(f"  Spearman rank correlation: {rho:.4f}")
        if rho > 0.9:
            print(f"  PASS: Rankings well preserved (rho > 0.9)")
        else:
            print(f"  WARNING: Rankings may have shifted (rho <= 0.9)")

    # Save results
    results = {
        "before": {
            "config": "PyTorch, batch=8, text=2200/520",
            "elapsed_ms": rt_before["elapsed_ms"],
            "throughput": round(throughput_before, 2),
            "est_420_sec": round(est_before_420, 1),
        },
        "after": {
            "config": "ONNX INT8, batch=32, text=1400/400",
            "elapsed_ms": rt_after["elapsed_ms"],
            "throughput": round(throughput_after, 2),
            "est_420_sec": round(est_after_420, 1),
        },
        "speedup": round(speedup, 2),
    }

    out_path = Path(__file__).resolve().parent / "final_benchmark.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n  Saved to {out_path}")


if __name__ == "__main__":
    main()
