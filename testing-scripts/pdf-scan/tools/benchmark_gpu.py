#!/usr/bin/env python3
"""
Benchmark cross-encoder (BAAI/bge-reranker-v2-m3) on CPU vs GPU.

Tests: PyTorch CPU, PyTorch GPU (RTX 3080), ONNX INT8 CPU, optionally ONNX GPU.
Varies batch sizes and pair counts to simulate real pipeline loads.

Output: speedup ratios and pairs/second for cost analysis.
"""

import time
import sys
import os
import json
import random

# ---------------------------------------------------------------------------
# Synthetic pair generator — mimics real pipeline data
# ---------------------------------------------------------------------------

SAMPLE_QUERIES = [
    "Choice Architecture and Default Options || nudging || behavioral economics || default effects",
    "How do digital nudges affect consumer decision-making in online environments || digital nudging || recommender systems",
    "Dark patterns in user interface design || deceptive design || UX manipulation || consumer protection",
    "Cognitive biases and heuristics in judgment under uncertainty || Kahneman || Tversky || prospect theory",
    "Information overload and online review systems || consumer choice || decision quality || review helpfulness",
]

SAMPLE_PASSAGES = [
    "The concept of choice architecture refers to the practice of influencing choice by organizing the context in which people make decisions. A choice architect has the responsibility for organizing the context in which people make decisions. There are many parallels between choice architecture and more traditional forms of architecture. A crucial parallel is that there is no such thing as a neutral design.",
    "Digital nudging is defined as the use of user-interface design elements to guide people's behavior in digital choice environments. Unlike traditional nudging in physical environments, digital nudging operates through the specific affordances of digital technology. Key mechanisms include default settings, social proof indicators, and personalized recommendations that leverage cognitive biases.",
    "Dark patterns are user interface design choices that benefit an online service by coercing, steering, or deceiving users into making unintended and potentially harmful decisions. These deceptive design patterns exploit cognitive biases and can be categorized into several types: trick questions, sneak into basket, roach motels, privacy zuckering, and forced continuity.",
    "In their seminal work on judgment under uncertainty, Kahneman and Tversky identified three heuristics that are employed in making judgments under uncertainty: representativeness, availability, and anchoring. These heuristics are highly economical and usually effective, but they lead to systematic and predictable errors. A better understanding of these heuristics and of the biases to which they lead could improve judgments and decisions.",
    "The proliferation of online reviews has created an information overload problem for consumers. When faced with an overwhelming number of reviews, decision quality may actually decrease. Research suggests that review helpfulness, source credibility, and review extremity affect how consumers process and use online review information.",
]


def generate_pairs(n: int) -> list:
    pairs = []
    for i in range(n):
        q = random.choice(SAMPLE_QUERIES)
        p = random.choice(SAMPLE_PASSAGES)
        # Add some variation to avoid caching effects
        suffix = f" [pair-{i}]"
        pairs.append(
            {
                "candidate_id": f"doc_{i:04d}",
                "query": q + suffix,
                "candidate_text": p + suffix,
            }
        )
    return pairs


# ---------------------------------------------------------------------------
# Benchmarking functions
# ---------------------------------------------------------------------------


def benchmark_pytorch(pairs, device, batch_size, max_length=1536, warmup_runs=2):
    """Benchmark PyTorch cross-encoder on specified device."""
    import torch
    from transformers import AutoTokenizer, AutoModelForSequenceClassification

    model_name = "BAAI/bge-reranker-v2-m3"
    print(f"  Loading model to {device}...")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)

    if device == "cuda":
        model = model.half()  # FP16 for GPU (2x memory savings, faster on tensor cores)
    model.to(device)
    model.eval()

    tok_limit = getattr(tokenizer, "model_max_length", max_length)
    max_len = min(max_length, tok_limit)

    def run_once():
        rows = []
        with torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                batch = pairs[start : start + batch_size]
                enc = tokenizer(
                    [p["query"] for p in batch],
                    [p["candidate_text"] for p in batch],
                    padding=True,
                    truncation=True,
                    max_length=max_len,
                    return_tensors="pt",
                )
                enc = {k: v.to(device) for k, v in enc.items()}
                logits = model(**enc).logits
                scores = logits.detach().cpu().float().tolist()
                for idx, item in enumerate(batch):
                    rows.append(
                        float(
                            scores[idx][-1]
                            if isinstance(scores[idx], list)
                            else scores[idx]
                        )
                    )
        if device == "cuda":
            torch.cuda.synchronize()
        return rows

    # Warmup
    for _ in range(warmup_runs):
        run_once()

    # Timed runs
    n_timed = 3
    times = []
    for _ in range(n_timed):
        if device == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        scores = run_once()
        if device == "cuda":
            torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)

    median_time = sorted(times)[n_timed // 2]
    return {
        "device": device,
        "backend": "pytorch" + ("_fp16" if device == "cuda" else "_fp32"),
        "batch_size": batch_size,
        "pair_count": len(pairs),
        "median_sec": round(median_time, 4),
        "pairs_per_sec": round(len(pairs) / median_time, 2),
        "times": [round(t, 4) for t in times],
        "sample_scores": scores[:3],
    }


def benchmark_onnx_cpu(pairs, batch_size, max_length=1536, warmup_runs=2):
    """Benchmark ONNX INT8 cross-encoder on CPU."""
    import onnxruntime as ort
    import numpy as np
    from transformers import AutoTokenizer

    onnx_dir = os.path.join(os.path.dirname(__file__), "onnx_reranker_int8")
    model_path = os.path.join(onnx_dir, "model.onnx")
    if not os.path.exists(model_path):
        return {"error": f"ONNX model not found at {model_path}"}

    print(f"  Loading ONNX INT8 model...")
    tokenizer = AutoTokenizer.from_pretrained(onnx_dir)

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_opts.intra_op_num_threads = os.cpu_count() or 4
    sess_opts.inter_op_num_threads = 1

    session = ort.InferenceSession(
        model_path, sess_opts, providers=["CPUExecutionProvider"]
    )

    tok_limit = getattr(tokenizer, "model_max_length", max_length)
    max_len = min(max_length, tok_limit)

    def run_once():
        rows = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            enc = tokenizer(
                [p["query"] for p in batch],
                [p["candidate_text"] for p in batch],
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
            for idx in range(len(batch)):
                raw = logits[idx]
                rows.append(float(raw[-1] if len(raw) else 0.0))
        return rows

    # Warmup
    for _ in range(warmup_runs):
        run_once()

    # Timed runs
    n_timed = 3
    times = []
    for _ in range(n_timed):
        t0 = time.perf_counter()
        scores = run_once()
        times.append(time.perf_counter() - t0)

    median_time = sorted(times)[n_timed // 2]
    return {
        "device": "cpu",
        "backend": "onnx_int8",
        "batch_size": batch_size,
        "pair_count": len(pairs),
        "median_sec": round(median_time, 4),
        "pairs_per_sec": round(len(pairs) / median_time, 2),
        "times": [round(t, 4) for t in times],
        "sample_scores": scores[:3],
    }


def benchmark_onnx_gpu(pairs, batch_size, max_length=1536, warmup_runs=2):
    """Benchmark ONNX cross-encoder on GPU via CUDAExecutionProvider."""
    import onnxruntime as ort

    if "CUDAExecutionProvider" not in ort.get_available_providers():
        return {
            "error": "CUDAExecutionProvider not available in onnxruntime. "
            "Install onnxruntime-gpu to enable."
        }

    import numpy as np
    from transformers import AutoTokenizer

    onnx_dir = os.path.join(os.path.dirname(__file__), "onnx_reranker_int8")
    model_path = os.path.join(onnx_dir, "model.onnx")
    if not os.path.exists(model_path):
        return {"error": f"ONNX model not found at {model_path}"}

    print(f"  Loading ONNX model with CUDAExecutionProvider...")
    tokenizer = AutoTokenizer.from_pretrained(onnx_dir)

    sess_opts = ort.SessionOptions()
    sess_opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    session = ort.InferenceSession(
        model_path, sess_opts, providers=["CUDAExecutionProvider"]
    )

    tok_limit = getattr(tokenizer, "model_max_length", max_length)
    max_len = min(max_length, tok_limit)

    def run_once():
        rows = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            enc = tokenizer(
                [p["query"] for p in batch],
                [p["candidate_text"] for p in batch],
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
            for idx in range(len(batch)):
                raw = logits[idx]
                rows.append(float(raw[-1] if len(raw) else 0.0))
        return rows

    for _ in range(warmup_runs):
        run_once()

    n_timed = 3
    times = []
    for _ in range(n_timed):
        t0 = time.perf_counter()
        scores = run_once()
        times.append(time.perf_counter() - t0)

    median_time = sorted(times)[n_timed // 2]
    return {
        "device": "cuda",
        "backend": "onnx_int8_gpu",
        "batch_size": batch_size,
        "pair_count": len(pairs),
        "median_sec": round(median_time, 4),
        "pairs_per_sec": round(len(pairs) / median_time, 2),
        "times": [round(t, 4) for t in times],
        "sample_scores": scores[:3],
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    import torch

    pair_counts = [100, 420, 1000]
    batch_sizes_cpu = [8, 32]
    batch_sizes_gpu = [32, 64, 128]

    has_cuda = torch.cuda.is_available()
    if has_cuda:
        gpu_name = torch.cuda.get_device_name(0)
        gpu_mem = torch.cuda.get_device_properties(0).total_memory / 1024**3
        print(f"GPU: {gpu_name} ({gpu_mem:.1f} GiB VRAM)")
    else:
        print("WARNING: No CUDA GPU available. Running CPU-only benchmarks.")

    print(f"CPU: {os.cpu_count()} threads")
    print()

    results = []

    for n_pairs in pair_counts:
        pairs = generate_pairs(n_pairs)
        print(f"{'='*60}")
        print(f"  {n_pairs} pairs")
        print(f"{'='*60}")

        # --- PyTorch CPU ---
        for bs in batch_sizes_cpu:
            print(f"\n[PyTorch CPU fp32] batch_size={bs}")
            r = benchmark_pytorch(pairs, "cpu", bs)
            print(f"  → {r['pairs_per_sec']} pairs/sec, median={r['median_sec']}s")
            results.append(r)

        # --- ONNX INT8 CPU ---
        for bs in batch_sizes_cpu:
            print(f"\n[ONNX INT8 CPU] batch_size={bs}")
            r = benchmark_onnx_cpu(pairs, bs)
            if "error" in r:
                print(f"  → SKIPPED: {r['error']}")
            else:
                print(f"  → {r['pairs_per_sec']} pairs/sec, median={r['median_sec']}s")
            results.append(r)

        # --- PyTorch GPU ---
        if has_cuda:
            for bs in batch_sizes_gpu:
                print(f"\n[PyTorch GPU fp16] batch_size={bs}")
                r = benchmark_pytorch(pairs, "cuda", bs)
                print(f"  → {r['pairs_per_sec']} pairs/sec, median={r['median_sec']}s")
                results.append(r)

            # --- ONNX GPU (if available) ---
            for bs in batch_sizes_gpu:
                print(f"\n[ONNX INT8 GPU] batch_size={bs}")
                r = benchmark_onnx_gpu(pairs, bs)
                if "error" in r:
                    print(f"  → SKIPPED: {r['error']}")
                else:
                    print(
                        f"  → {r['pairs_per_sec']} pairs/sec, median={r['median_sec']}s"
                    )
                results.append(r)

    # --- Summary ---
    valid = [r for r in results if "error" not in r]
    print(f"\n{'='*60}")
    print(f"  SUMMARY")
    print(f"{'='*60}")
    print(
        f"\n  {'Backend':<22} {'Pairs':>6} {'Batch':>6} {'Sec':>8} {'Pairs/s':>9} {'Speedup':>8}"
    )
    print(f"  {'─'*22} {'─'*6} {'─'*6} {'─'*8} {'─'*9} {'─'*8}")

    # Group by pair_count, find CPU baseline for speedup calc
    for n_pairs in pair_counts:
        subset = [r for r in valid if r["pair_count"] == n_pairs]
        cpu_baseline = next(
            (
                r
                for r in subset
                if r["backend"] == "pytorch_fp32" and r["batch_size"] == 8
            ),
            None,
        )
        baseline_pps = cpu_baseline["pairs_per_sec"] if cpu_baseline else 1.0

        for r in subset:
            speedup = r["pairs_per_sec"] / baseline_pps
            print(
                f"  {r['backend']:<22} {r['pair_count']:>6} {r['batch_size']:>6} "
                f"{r['median_sec']:>8.3f} {r['pairs_per_sec']:>9.1f} {speedup:>7.1f}x"
            )
        print()

    # Extrapolate to Cloud Run L4
    if has_cuda:
        # RTX 3080 = 8704 CUDA cores, 29.77 TFLOPS FP16
        # L4 = 7680 CUDA cores, 121 TFLOPS FP16 (with sparsity), ~30.3 TFLOPS dense FP16
        # So L4 ≈ 1.02x RTX 3080 at dense FP16, but much better at INT8 (242 TOPS vs ~?)
        # Conservative: L4 ≈ 0.9-1.2x RTX 3080 for this workload (transformer inference)
        print(f"  L4 GPU EXTRAPOLATION:")
        print(f"  RTX 3080: 8704 CUDA cores, 29.8 TFLOPS FP16 (dense)")
        print(f"  L4 (Ada): 7680 CUDA cores, 30.3 TFLOPS FP16 (dense)")
        print(
            f"  → L4 expected ~0.9-1.1x RTX 3080 for dense FP16 transformer inference"
        )
        print(
            f"  → L4 has FP8 TensorCores + better INT8: could be faster for quantized models"
        )
        print()

    # Save results
    outpath = os.path.join(os.path.dirname(__file__), "gpu_benchmark_results.json")
    with open(outpath, "w") as f:
        json.dump(results, f, indent=2)
    print(f"  Results saved to {outpath}")


if __name__ == "__main__":
    random.seed(42)
    main()
