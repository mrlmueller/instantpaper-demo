#!/usr/bin/env python3
"""
Cross-encoder micro-benchmark.
Loads real pair data from a previous run and benchmarks the scoring function.
Measures: model load time, per-batch time, total scoring time.

Usage:
    python tools/benchmark_cross_encoder.py [--run-id RUN_ID] [--max-pairs N] [--batch-size BS]
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add parent dir so we can import phase_f_lab
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_pairs_from_run(run_id: str, max_pairs: int = 0):
    """Load candidate packs from a previous run and reconstruct pairs."""
    run_dir = Path(__file__).resolve().parent.parent / "runs" / run_id / "rerank"
    packs_path = run_dir / "phase_f_candidate_packs.jsonl"
    config_path = run_dir / "phase_f_config.json"

    if not packs_path.exists():
        print(f"ERROR: {packs_path} not found")
        sys.exit(1)

    config = (
        json.loads(config_path.read_text(encoding="utf-8"))
        if config_path.exists()
        else {}
    )

    # Load packs
    packs = []
    with open(packs_path, encoding="utf-8") as f:
        for line in f:
            packs.append(json.loads(line))

    # Reconstruct simple pairs: each pack produces at least 1 pair (global query)
    # We use a simple dummy query since we're benchmarking throughput, not quality
    query_plan_path = run_dir.parent / "query_plan.json"
    global_query = "What are the main findings of this research?"
    if query_plan_path.exists():
        qp = json.loads(query_plan_path.read_text(encoding="utf-8"))
        global_query = qp.get("refined_question", global_query) or global_query

    pairs = []
    for pack in packs:
        pairs.append(
            {
                "candidate_id": pack.get("candidate_id"),
                "query_kind": "global",
                "subpoint_id": None,
                "query": global_query,
                "candidate_text": pack.get("candidate_text", ""),
            }
        )
        # Add subpoint queries
        for sp_id in list(pack.get("chosen_subpoint_ids") or []):
            pairs.append(
                {
                    "candidate_id": pack.get("candidate_id"),
                    "query_kind": "subpoint",
                    "subpoint_id": sp_id,
                    "query": f"Subpoint {sp_id}: {global_query}",
                    "candidate_text": pack.get("candidate_text", ""),
                }
            )

    if max_pairs > 0:
        pairs = pairs[:max_pairs]

    return pairs, config


def benchmark_pytorch(pairs, batch_size=8, max_length=1536, warmup_batches=1):
    """Benchmark PyTorch cross-encoder scoring."""
    from phase_f_lab import (
        load_cross_encoder_bundle,
        effective_max_length,
        row_sigmoid,
        PhaseFOptions,
    )
    import torch

    model_name = "BAAI/bge-reranker-v2-m3"

    # Model loading
    t0 = time.perf_counter()
    bundle = load_cross_encoder_bundle(model_name)
    load_time = time.perf_counter() - t0

    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    device = bundle["device"]
    max_len = effective_max_length(bundle, max_length)

    print(f"\n=== PyTorch Benchmark ===")
    print(f"  Model: {model_name}")
    print(f"  Device: {device}")
    print(f"  Batch size: {batch_size}")
    print(f"  Max length: {max_len}")
    print(f"  Total pairs: {len(pairs)}")
    print(f"  Model load time: {load_time:.3f}s")

    num_batches = (len(pairs) + batch_size - 1) // batch_size
    batch_times = []

    with torch.inference_mode():
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            t1 = time.perf_counter()
            enc = tokenizer(
                [str(item.get("query") or "") for item in batch],
                [str(item.get("candidate_text") or "") for item in batch],
                padding=True,
                truncation=True,
                max_length=max_len,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = model(**enc).logits
            probs = row_sigmoid(logits)
            t2 = time.perf_counter()

            batch_idx = i // batch_size
            batch_ms = (t2 - t1) * 1000

            if batch_idx < warmup_batches:
                print(
                    f"  [warmup] Batch {batch_idx}: {batch_ms:.1f}ms ({len(batch)} pairs, seq_len={enc['input_ids'].shape[1]})"
                )
            else:
                batch_times.append(batch_ms)
                if batch_idx < warmup_batches + 3 or batch_idx == num_batches - 1:
                    print(
                        f"  Batch {batch_idx}: {batch_ms:.1f}ms ({len(batch)} pairs, seq_len={enc['input_ids'].shape[1]})"
                    )

    total_time = sum(batch_times)
    avg_batch = total_time / len(batch_times) if batch_times else 0

    results = {
        "backend": "pytorch",
        "batch_size": batch_size,
        "max_length": max_len,
        "total_pairs": len(pairs),
        "num_batches": num_batches,
        "warmup_batches": warmup_batches,
        "measured_batches": len(batch_times),
        "model_load_s": round(load_time, 3),
        "total_scoring_ms": round(total_time, 1),
        "avg_batch_ms": round(avg_batch, 1),
        "estimated_full_run_ms": round(avg_batch * num_batches, 1),
        "pairs_per_second": (
            round(len(pairs) / (total_time / 1000), 2) if total_time > 0 else 0
        ),
    }

    print(f"\n  Results:")
    print(f"    Total scoring time: {total_time:.0f}ms ({total_time/1000:.1f}s)")
    print(f"    Avg batch time: {avg_batch:.1f}ms")
    print(
        f"    Estimated for {num_batches} batches: {avg_batch * num_batches / 1000:.1f}s"
    )
    print(f"    Throughput: {results['pairs_per_second']:.2f} pairs/sec")

    return results


def benchmark_onnx(pairs, batch_size=8, max_length=1536, warmup_batches=1, onnx_dir=""):
    """Benchmark ONNX cross-encoder scoring."""
    try:
        import onnxruntime as ort
    except ImportError:
        print("\n=== ONNX Benchmark: SKIPPED (onnxruntime not installed) ===")
        return None

    from transformers import AutoTokenizer
    import numpy as np

    model_name = "BAAI/bge-reranker-v2-m3"

    # Find ONNX model
    if onnx_dir:
        onnx_path = Path(onnx_dir) / "model.onnx"
    else:
        onnx_path = Path(__file__).resolve().parent / "onnx_reranker" / "model.onnx"

    if not onnx_path.exists():
        print(f"\n=== ONNX Benchmark: SKIPPED (model not found at {onnx_path}) ===")
        return None

    # Load tokenizer
    t0 = time.perf_counter()
    tokenizer_dir = onnx_path.parent
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))
    except Exception:
        tokenizer = AutoTokenizer.from_pretrained(model_name)

    # Create ONNX session
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.intra_op_num_threads = 0  # auto
    sess_options.inter_op_num_threads = 0

    session = ort.InferenceSession(
        str(onnx_path),
        sess_options,
        providers=["CPUExecutionProvider"],
    )
    load_time = time.perf_counter() - t0

    tokenizer_limit = getattr(tokenizer, "model_max_length", None)
    max_len = (
        min(max_length, tokenizer_limit)
        if tokenizer_limit and tokenizer_limit > 0
        else max_length
    )

    print(f"\n=== ONNX Benchmark ===")
    print(f"  Model: {onnx_path}")
    print(f"  Batch size: {batch_size}")
    print(f"  Max length: {max_len}")
    print(f"  Total pairs: {len(pairs)}")
    print(f"  Model load time: {load_time:.3f}s")

    num_batches = (len(pairs) + batch_size - 1) // batch_size
    batch_times = []

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i : i + batch_size]
        t1 = time.perf_counter()
        enc = tokenizer(
            [str(item.get("query") or "") for item in batch],
            [str(item.get("candidate_text") or "") for item in batch],
            padding=True,
            truncation=True,
            max_length=max_len,
            return_tensors="np",
        )
        logits = session.run(
            None,
            {
                "input_ids": enc["input_ids"],
                "attention_mask": enc["attention_mask"],
            },
        )[0]
        probs = 1.0 / (1.0 + np.exp(-logits.astype(np.float64)))
        t2 = time.perf_counter()

        batch_idx = i // batch_size
        batch_ms = (t2 - t1) * 1000

        if batch_idx < warmup_batches:
            print(
                f"  [warmup] Batch {batch_idx}: {batch_ms:.1f}ms ({len(batch)} pairs, seq_len={enc['input_ids'].shape[1]})"
            )
        else:
            batch_times.append(batch_ms)
            if batch_idx < warmup_batches + 3 or batch_idx == num_batches - 1:
                print(
                    f"  Batch {batch_idx}: {batch_ms:.1f}ms ({len(batch)} pairs, seq_len={enc['input_ids'].shape[1]})"
                )

    total_time = sum(batch_times)
    avg_batch = total_time / len(batch_times) if batch_times else 0

    results = {
        "backend": "onnx",
        "batch_size": batch_size,
        "max_length": max_len,
        "total_pairs": len(pairs),
        "num_batches": num_batches,
        "warmup_batches": warmup_batches,
        "measured_batches": len(batch_times),
        "model_load_s": round(load_time, 3),
        "total_scoring_ms": round(total_time, 1),
        "avg_batch_ms": round(avg_batch, 1),
        "estimated_full_run_ms": round(avg_batch * num_batches, 1),
        "pairs_per_second": (
            round(len(pairs) / (total_time / 1000), 2) if total_time > 0 else 0
        ),
    }

    print(f"\n  Results:")
    print(f"    Total scoring time: {total_time:.0f}ms ({total_time/1000:.1f}s)")
    print(f"    Avg batch time: {avg_batch:.1f}ms")
    print(
        f"    Estimated for {num_batches} batches: {avg_batch * num_batches / 1000:.1f}s"
    )
    print(f"    Throughput: {results['pairs_per_second']:.2f} pairs/sec")

    return results


def main():
    parser = argparse.ArgumentParser(description="Cross-encoder micro-benchmark")
    parser.add_argument(
        "--run-id", default="a33419bf76ad298d82369172", help="Run ID to load pairs from"
    )
    parser.add_argument(
        "--max-pairs", type=int, default=0, help="Limit number of pairs (0=all)"
    )
    parser.add_argument("--batch-size", type=int, default=8, help="Batch size")
    parser.add_argument("--max-length", type=int, default=1536, help="Max token length")
    parser.add_argument("--onnx-dir", default="", help="ONNX model directory")
    parser.add_argument(
        "--pytorch-only", action="store_true", help="Only benchmark PyTorch"
    )
    parser.add_argument("--onnx-only", action="store_true", help="Only benchmark ONNX")
    args = parser.parse_args()

    print(f"Loading pairs from run {args.run_id}...")
    pairs, config = load_pairs_from_run(args.run_id, args.max_pairs)
    print(f"Loaded {len(pairs)} pairs")

    # Show text length stats
    text_lengths = [len(p.get("candidate_text", "")) for p in pairs]
    query_lengths = [len(p.get("query", "")) for p in pairs]
    print(
        f"Candidate text length: min={min(text_lengths)}, max={max(text_lengths)}, avg={sum(text_lengths)/len(text_lengths):.0f}"
    )
    print(
        f"Query length: min={min(query_lengths)}, max={max(query_lengths)}, avg={sum(query_lengths)/len(query_lengths):.0f}"
    )

    results = {}

    if not args.onnx_only:
        results["pytorch"] = benchmark_pytorch(pairs, args.batch_size, args.max_length)

    if not args.pytorch_only:
        results["onnx"] = benchmark_onnx(
            pairs, args.batch_size, args.max_length, onnx_dir=args.onnx_dir
        )

    # Comparison
    if results.get("pytorch") and results.get("onnx"):
        pt = results["pytorch"]
        ox = results["onnx"]
        speedup = (
            pt["avg_batch_ms"] / ox["avg_batch_ms"] if ox["avg_batch_ms"] > 0 else 0
        )
        print(f"\n=== Comparison ===")
        print(f"  PyTorch avg batch: {pt['avg_batch_ms']:.1f}ms")
        print(f"  ONNX avg batch:    {ox['avg_batch_ms']:.1f}ms")
        print(f"  Speedup:           {speedup:.2f}x")
        print(f"  PyTorch throughput: {pt['pairs_per_second']:.2f} pairs/sec")
        print(f"  ONNX throughput:    {ox['pairs_per_second']:.2f} pairs/sec")

    # Save results
    out_path = Path(__file__).resolve().parent / "benchmark_results.json"
    with open(out_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to {out_path}")


if __name__ == "__main__":
    main()
