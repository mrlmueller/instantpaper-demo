#!/usr/bin/env python3
"""
Comprehensive before/after benchmark testing all speed-up combinations:
1. PyTorch baseline (batch=8, max_length=1536, default threads)
2. PyTorch + thread pinning (16 threads)
3. PyTorch + thread pinning + batch=32
4. INT8 ONNX (batch=8, optimal threads)
5. INT8 ONNX + batch=32

Uses real data from a previous run.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def load_pairs(run_id: str, max_pairs: int = 80):
    run_dir = Path(__file__).resolve().parent.parent / "runs" / run_id / "rerank"
    packs = []
    with open(run_dir / "phase_f_candidate_packs.jsonl", encoding="utf-8") as f:
        for line in f:
            packs.append(json.loads(line))

    query_plan = json.loads(
        (run_dir.parent / "query_plan.json").read_text(encoding="utf-8")
    )
    global_query = (
        query_plan.get("refined_question", "research question") or "research question"
    )

    pairs = []
    for pack in packs:
        pairs.append(
            {"query": global_query, "candidate_text": pack.get("candidate_text", "")}
        )
        for sp_id in list(pack.get("chosen_subpoint_ids") or []):
            pairs.append(
                {
                    "query": f"Subpoint {sp_id}: {global_query}",
                    "candidate_text": pack.get("candidate_text", ""),
                }
            )
    return pairs[:max_pairs]


def benchmark_pytorch(
    pairs, batch_size, max_length, n_threads=None, warmup=1, label=""
):
    import torch
    from phase_f_lab import load_cross_encoder_bundle, effective_max_length, row_sigmoid

    if n_threads:
        torch.set_num_threads(n_threads)

    model_name = "BAAI/bge-reranker-v2-m3"
    bundle = load_cross_encoder_bundle(model_name)
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    device = bundle["device"]
    max_len = effective_max_length(bundle, max_length)

    num_batches = (len(pairs) + batch_size - 1) // batch_size
    batch_times = []

    with torch.inference_mode():
        for i in range(0, len(pairs), batch_size):
            batch = pairs[i : i + batch_size]
            t1 = time.perf_counter()
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
            _ = row_sigmoid(logits)
            batch_ms = (time.perf_counter() - t1) * 1000

            batch_idx = i // batch_size
            if batch_idx < warmup:
                pass  # skip warmup
            else:
                batch_times.append(batch_ms)

    avg = sum(batch_times) / len(batch_times) if batch_times else 0
    throughput = len(pairs) / (sum(batch_times) / 1000) if sum(batch_times) > 0 else 0

    return {
        "label": label,
        "backend": "pytorch",
        "batch_size": batch_size,
        "max_length": max_len,
        "n_threads": n_threads or "default",
        "total_pairs": len(pairs),
        "avg_batch_ms": round(avg, 1),
        "throughput": round(throughput, 2),
        "total_ms": round(sum(batch_times), 0),
    }


def benchmark_onnx(
    pairs,
    batch_size,
    max_length,
    model_dir,
    intra_threads=16,
    inter_threads=1,
    warmup=1,
    label="",
):
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_dir)

    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    sess_options.intra_op_num_threads = intra_threads
    sess_options.inter_op_num_threads = inter_threads

    session = ort.InferenceSession(
        str(Path(model_dir) / "model.onnx"),
        sess_options,
        providers=["CPUExecutionProvider"],
    )

    tokenizer_limit = getattr(tokenizer, "model_max_length", None)
    max_len = (
        min(max_length, tokenizer_limit)
        if tokenizer_limit and tokenizer_limit > 0
        else max_length
    )

    num_batches = (len(pairs) + batch_size - 1) // batch_size
    batch_times = []

    for i in range(0, len(pairs), batch_size):
        batch = pairs[i : i + batch_size]
        t1 = time.perf_counter()
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
        _ = 1.0 / (1.0 + np.exp(-logits.astype(np.float64)))
        batch_ms = (time.perf_counter() - t1) * 1000

        batch_idx = i // batch_size
        if batch_idx < warmup:
            pass
        else:
            batch_times.append(batch_ms)

    avg = sum(batch_times) / len(batch_times) if batch_times else 0
    throughput = len(pairs) / (sum(batch_times) / 1000) if sum(batch_times) > 0 else 0

    return {
        "label": label,
        "backend": "onnx_int8",
        "batch_size": batch_size,
        "max_length": max_len,
        "threads": f"{intra_threads}/{inter_threads}",
        "total_pairs": len(pairs),
        "avg_batch_ms": round(avg, 1),
        "throughput": round(throughput, 2),
        "total_ms": round(sum(batch_times), 0),
    }


def extrapolate_420(result, total_pairs=420):
    """Extrapolate timing for 420 pairs based on throughput."""
    if result["throughput"] > 0:
        return round(total_pairs / result["throughput"], 1)
    return 0


def main():
    import torch

    run_id = "a33419bf76ad298d82369172"
    pairs = load_pairs(run_id, max_pairs=80)
    print(f"Loaded {len(pairs)} pairs")

    int8_dir = str(Path(__file__).resolve().parent / "onnx_reranker_int8")

    results = []

    # 1. PyTorch baseline
    print("\n[1/5] PyTorch baseline (batch=8, default threads)...")
    r = benchmark_pytorch(pairs, batch_size=8, max_length=1536, label="PT baseline")
    results.append(r)
    print(f"  avg_batch={r['avg_batch_ms']}ms, throughput={r['throughput']} pairs/sec")

    # 2. PyTorch + thread pinning
    print("\n[2/5] PyTorch + 16 threads (batch=8)...")
    r = benchmark_pytorch(
        pairs, batch_size=8, max_length=1536, n_threads=16, label="PT +threads"
    )
    results.append(r)
    print(f"  avg_batch={r['avg_batch_ms']}ms, throughput={r['throughput']} pairs/sec")

    # 3. PyTorch + threads + batch=32
    print("\n[3/5] PyTorch + 16 threads + batch=32...")
    r = benchmark_pytorch(
        pairs,
        batch_size=32,
        max_length=1536,
        n_threads=16,
        label="PT +threads +batch32",
    )
    results.append(r)
    print(f"  avg_batch={r['avg_batch_ms']}ms, throughput={r['throughput']} pairs/sec")

    # 4. INT8 ONNX (batch=8, 16/1 threads)
    print("\n[4/5] INT8 ONNX (batch=8, 16/1 threads)...")
    r = benchmark_onnx(
        pairs, batch_size=8, max_length=1536, model_dir=int8_dir, label="ONNX INT8"
    )
    results.append(r)
    print(f"  avg_batch={r['avg_batch_ms']}ms, throughput={r['throughput']} pairs/sec")

    # 5. INT8 ONNX + batch=32
    print("\n[5/5] INT8 ONNX + batch=32...")
    r = benchmark_onnx(
        pairs,
        batch_size=32,
        max_length=1536,
        model_dir=int8_dir,
        label="ONNX INT8 +batch32",
    )
    results.append(r)
    print(f"  avg_batch={r['avg_batch_ms']}ms, throughput={r['throughput']} pairs/sec")

    # Summary table
    print("\n" + "=" * 90)
    print(
        f"{'Config':<25s} {'Batch':>5s} {'Avg/batch':>10s} {'Throughput':>12s} {'Est 420 pairs':>14s} {'Speedup':>8s}"
    )
    print("-" * 90)
    baseline_throughput = results[0]["throughput"]
    for r in results:
        est = extrapolate_420(r)
        speedup = (
            r["throughput"] / baseline_throughput if baseline_throughput > 0 else 0
        )
        print(
            f"{r['label']:<25s} {r['batch_size']:>5d} {r['avg_batch_ms']:>9.1f}ms {r['throughput']:>10.2f}/sec {est:>12.1f}s {speedup:>7.2f}x"
        )
    print("=" * 90)

    # Reset threads
    torch.set_num_threads(torch.get_num_threads())

    # Save
    out = Path(__file__).resolve().parent / "comprehensive_benchmark.json"
    with open(out, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()
