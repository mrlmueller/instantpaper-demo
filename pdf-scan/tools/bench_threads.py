#!/usr/bin/env python3
"""
Test different thread configurations for ONNX Runtime and PyTorch.
Quick test to find optimal thread settings for this machine.
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import onnxruntime as ort
from transformers import AutoTokenizer


def make_test_batch(tokenizer, batch_size=8, max_length=1536):
    """Create a realistic test batch."""
    query = "How does changing precipitation patterns affect agricultural productivity in Mediterranean regions?"
    doc = (
        "This study examines the relationship between changing precipitation patterns and crop yields "
        "across Southern Europe. We analyze historical records spanning three centuries alongside "
        "modern satellite data to establish baseline precipitation trends and their correlation with "
        "various crop yields. Our findings indicate a strong negative correlation between precipitation "
        "variability and crop yield stability, particularly for rain-fed agricultural systems. "
        "The analysis reveals significant regional variations, with coastal areas showing more "
        "resilience than inland regions. Temperature changes coupled with precipitation shifts "
        "create compound effects that amplify the individual impacts on agricultural systems. "
    ) * 5

    enc = tokenizer(
        [query] * batch_size,
        [doc[:3500]] * batch_size,
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="np",
    )
    return enc


def benchmark_onnx_threads(model_dir: str, n_iter: int = 5):
    """Test different thread configurations for ONNX Runtime."""
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    enc = make_test_batch(tokenizer)
    seq_len = enc["input_ids"].shape[1]
    print(f"Test batch: batch_size=8, seq_len={seq_len}")

    import os

    cpu_count = os.cpu_count()
    print(f"CPU count: {cpu_count}")

    # Test configurations: (intra_op, inter_op)
    configs = [
        (0, 0, "auto/auto"),
        (cpu_count, 1, f"{cpu_count}/1"),
        (cpu_count // 2, 2, f"{cpu_count//2}/2"),
        (cpu_count // 4, 4, f"{cpu_count//4}/4"),
        (4, 1, "4/1"),
        (8, 1, "8/1"),
        (12, 1, "12/1"),
        (16, 1, "16/1"),
        (cpu_count, 2, f"{cpu_count}/2"),
    ]

    results = []

    for intra, inter, label in configs:
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        sess_options.intra_op_num_threads = intra
        sess_options.inter_op_num_threads = inter

        session = ort.InferenceSession(
            str(Path(model_dir) / "model.onnx"),
            sess_options,
            providers=["CPUExecutionProvider"],
        )

        feeds = {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}

        # Warmup
        _ = session.run(None, feeds)

        times = []
        for _ in range(n_iter):
            t0 = time.perf_counter()
            _ = session.run(None, feeds)
            times.append((time.perf_counter() - t0) * 1000)

        avg = sum(times) / len(times)
        best = min(times)
        results.append((avg, best, label, intra, inter))
        print(f"  threads={label:>10s} -> avg={avg:.0f}ms, best={best:.0f}ms")

    results.sort(key=lambda x: x[0])
    print(f"\n  Best config: threads={results[0][2]}, avg={results[0][0]:.0f}ms")
    return results


def benchmark_pytorch_threads(n_iter: int = 3):
    """Test different torch.set_num_threads configurations."""
    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    model_name = "BAAI/bge-reranker-v2-m3"
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()

    query = "How does changing precipitation patterns affect agricultural productivity?"
    doc = (
        "This study examines the relationship between changing precipitation patterns and crop yields "
        "across Southern Europe. "
    ) * 20

    enc = tokenizer(
        [query] * 8,
        [doc[:3500]] * 8,
        padding=True,
        truncation=True,
        max_length=1536,
        return_tensors="pt",
    )
    seq_len = enc["input_ids"].shape[1]
    print(f"\nPyTorch thread test (batch=8, seq_len={seq_len}):")

    import os

    cpu_count = os.cpu_count()
    thread_counts = [1, 2, 4, 8, 12, 16, cpu_count]

    for n_threads in thread_counts:
        torch.set_num_threads(n_threads)

        # Warmup
        with torch.inference_mode():
            _ = model(**enc)

        times = []
        for _ in range(n_iter):
            t0 = time.perf_counter()
            with torch.inference_mode():
                _ = model(**enc)
            times.append((time.perf_counter() - t0) * 1000)

        avg = sum(times) / len(times)
        best = min(times)
        actual = torch.get_num_threads()
        print(
            f"  threads={n_threads:>3d} (actual={actual:>3d}) -> avg={avg:.0f}ms, best={best:.0f}ms"
        )


if __name__ == "__main__":
    # Test ONNX INT8 model
    int8_dir = str(Path(__file__).resolve().parent / "onnx_reranker_int8")

    print("=== ONNX INT8 Thread Tuning ===")
    benchmark_onnx_threads(int8_dir)

    print("\n=== PyTorch Thread Tuning ===")
    benchmark_pytorch_threads()
