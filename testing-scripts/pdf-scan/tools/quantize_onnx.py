#!/usr/bin/env python3
"""
Quantize the ONNX cross-encoder model to INT8 for faster CPU inference.
Uses dynamic quantization (no calibration data needed).
"""
import sys
import time
from pathlib import Path


def quantize_dynamic(input_dir: str, output_dir: str):
    """Apply dynamic INT8 quantization to the ONNX model."""
    from onnxruntime.quantization import quantize_dynamic, QuantType

    inp = Path(input_dir)
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    model_path = inp / "model.onnx"
    if not model_path.exists():
        print(f"Model not found at {model_path}")
        return None

    quant_path = out / "model.onnx"

    print(f"Quantizing {model_path} -> {quant_path}")
    print(f"  Quantization: Dynamic INT8 (MatMul + Attention + Gather)")
    t0 = time.perf_counter()

    quantize_dynamic(
        model_input=str(model_path),
        model_output=str(quant_path),
        weight_type=QuantType.QInt8,
        extra_options={"MatMulConstBOnly": True},
    )

    elapsed = time.perf_counter() - t0
    print(f"  Quantization took {elapsed:.1f}s")

    # Copy tokenizer files
    import shutil

    for f in inp.glob("*.json"):
        shutil.copy2(f, out / f.name)

    # Compare sizes
    orig_size = sum(f.stat().st_size for f in inp.rglob("model.onnx*")) / (1024**2)
    quant_size = sum(f.stat().st_size for f in out.rglob("model.onnx*")) / (1024**2)
    print(f"  Original model size: {orig_size:.1f} MB")
    print(f"  Quantized model size: {quant_size:.1f} MB")
    print(f"  Size reduction: {(1 - quant_size/orig_size)*100:.1f}%")

    return str(quant_path)


def verify_quantized(input_dir: str, quant_dir: str):
    """Compare outputs of original and quantized models."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(input_dir)

    # Create test inputs at different lengths
    tests = [
        ("short", "What is ML?", "Machine learning uses algorithms."),
        (
            "medium",
            "How does changing precipitation patterns affect agricultural productivity?",
            "Climate change significantly impacts crop yields in Mediterranean areas. "
            * 10,
        ),
        (
            "long",
            "How does changing precipitation patterns affect agricultural productivity in Mediterranean regions during periods of climate variability?",
            "Climate change significantly impacts crop yields in Mediterranean areas. We analyze historical records spanning three centuries. "
            * 30,
        ),
    ]

    orig_session = ort.InferenceSession(str(Path(input_dir) / "model.onnx"))
    quant_session = ort.InferenceSession(str(Path(quant_dir) / "model.onnx"))

    print("\n  Numerical comparison (original vs quantized):")
    for name, q, d in tests:
        enc = tokenizer(
            [q],
            [d],
            padding=True,
            truncation=True,
            max_length=1536,
            return_tensors="np",
        )
        feeds = {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]}

        orig_out = orig_session.run(None, feeds)[0]
        quant_out = quant_session.run(None, feeds)[0]

        diff = float(np.max(np.abs(orig_out - quant_out)))
        orig_prob = 1.0 / (1.0 + np.exp(-orig_out[0][0]))
        quant_prob = 1.0 / (1.0 + np.exp(-quant_out[0][0]))
        print(
            f"    {name} (seq_len={enc['input_ids'].shape[1]}): max_diff={diff:.6f}, "
            f"orig_prob={orig_prob:.6f}, quant_prob={quant_prob:.6f}"
        )


def benchmark_both(
    input_dir: str,
    quant_dir: str,
    n_pairs: int = 16,
    batch_size: int = 8,
    max_length: int = 1536,
):
    """Side-by-side benchmark of original and quantized ONNX models."""
    import numpy as np
    import onnxruntime as ort
    from transformers import AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(input_dir)

    # Create realistic pairs
    query = "How does changing precipitation patterns affect agricultural productivity in Mediterranean regions during periods of climate variability?"
    doc_text = (
        "This study examines the relationship between changing precipitation patterns and crop yields "
        "across Southern Europe. We analyze historical records spanning three centuries alongside "
        "modern satellite data to establish baseline precipitation trends and their correlation with "
        "various crop yields. Our findings indicate a strong negative correlation between precipitation "
        "variability and crop yield stability, particularly for rain-fed agricultural systems. "
        "The analysis reveals that in regions where annual precipitation declined by more than 15%, "
        "wheat yields dropped by an average of 23% over the study period, while olive production "
        "showed more resilience with only 8% average decline. We discuss implications for food security "
        "policy and adaptation strategies in these vulnerable regions. "
    ) * 4

    pairs = [(query, doc_text[:3500])] * n_pairs

    for label, model_dir in [
        ("Original FP32", input_dir),
        ("Quantized INT8", quant_dir),
    ]:
        sess_options = ort.SessionOptions()
        sess_options.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        sess_options.intra_op_num_threads = 0
        sess_options.inter_op_num_threads = 0

        session = ort.InferenceSession(
            str(Path(model_dir) / "model.onnx"),
            sess_options,
            providers=["CPUExecutionProvider"],
        )

        # Warmup
        enc = tokenizer(
            [pairs[0][0]],
            [pairs[0][1]],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )
        _ = session.run(
            None,
            {"input_ids": enc["input_ids"], "attention_mask": enc["attention_mask"]},
        )

        batch_times = []
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            t1 = time.perf_counter()
            enc = tokenizer(
                [p[0] for p in batch],
                [p[1] for p in batch],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )
            _ = session.run(
                None,
                {
                    "input_ids": enc["input_ids"],
                    "attention_mask": enc["attention_mask"],
                },
            )
            batch_times.append((time.perf_counter() - t1) * 1000)

        avg = sum(batch_times) / len(batch_times)
        total = sum(batch_times)
        print(f"\n  {label}:")
        for i, bt in enumerate(batch_times):
            seq_len = tokenizer(
                [pairs[0][0]],
                [pairs[0][1]],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="np",
            )["input_ids"].shape[1]
            print(f"    Batch {i}: {bt:.1f}ms")
        print(
            f"    Avg: {avg:.1f}ms, Total: {total:.0f}ms, Throughput: {n_pairs/(total/1000):.2f} pairs/sec"
        )


if __name__ == "__main__":
    input_dir = str(Path(__file__).resolve().parent / "onnx_reranker_optimum")
    output_dir = str(Path(__file__).resolve().parent / "onnx_reranker_int8")

    quant_path = quantize_dynamic(input_dir, output_dir)
    if quant_path:
        verify_quantized(input_dir, output_dir)
        benchmark_both(input_dir, output_dir, n_pairs=16, batch_size=8)
