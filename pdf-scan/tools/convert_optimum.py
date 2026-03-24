#!/usr/bin/env python3
"""
Convert cross-encoder to ONNX using Hugging Face optimum (better optimization).
Also tests optimization levels and thread tuning.
"""
import sys
import time
from pathlib import Path


def convert_with_optimum(model_name: str, output_dir: str):
    """Use optimum's ORTModelForSequenceClassification for conversion."""
    from optimum.onnxruntime import ORTModelForSequenceClassification, ORTOptimizer
    from optimum.onnxruntime.configuration import AutoOptimizationConfig
    from transformers import AutoTokenizer
    import numpy as np

    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Converting {model_name} using optimum (exports + optimizes)...")
    t0 = time.perf_counter()

    # Export to ONNX directly using optimum
    model = ORTModelForSequenceClassification.from_pretrained(
        model_name,
        export=True,
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name)

    # Save to output directory
    model.save_pretrained(str(out))
    tokenizer.save_pretrained(str(out))

    convert_time = time.perf_counter() - t0
    print(f"Conversion took {convert_time:.1f}s")

    # Verify
    print("\nVerifying ONNX model...")
    import torch
    from transformers import AutoModelForSequenceClassification

    pt_model = AutoModelForSequenceClassification.from_pretrained(model_name)
    pt_model.eval()

    test_inputs = tokenizer(
        ["How does climate affect agriculture?"],
        ["Climate change significantly impacts crop yields in Mediterranean areas."],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )

    with torch.inference_mode():
        pt_logits = pt_model(**test_inputs).logits.numpy()

    ort_inputs = tokenizer(
        ["How does climate affect agriculture?"],
        ["Climate change significantly impacts crop yields in Mediterranean areas."],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="np",
    )
    ort_out = model(**ort_inputs)
    ort_logits = ort_out.logits
    if hasattr(ort_logits, "numpy"):
        ort_logits = ort_logits.numpy()
    elif not isinstance(ort_logits, np.ndarray):
        ort_logits = np.array(ort_logits)

    diff = float(np.max(np.abs(pt_logits - ort_logits)))
    print(f"Max numerical difference: {diff:.8f}")

    # Try optimization
    print("\nApplying O2 optimization...")
    opt_dir = out / "optimized"
    opt_dir.mkdir(exist_ok=True)

    try:
        optimizer = ORTOptimizer.from_pretrained(model)
        optimization_config = AutoOptimizationConfig.O2()
        optimizer.optimize(
            save_dir=str(opt_dir),
            optimization_config=optimization_config,
        )
        print(f"Optimized model saved to {opt_dir}")
    except Exception as e:
        print(f"Optimization failed: {e}")
        print("Using unoptimized model.")

    # List output files
    print(f"\nOutput files:")
    for f in sorted(out.rglob("*")):
        if f.is_file():
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"  {f.relative_to(out)}: {size_mb:.2f} MB")

    return str(out)


def quick_benchmark(
    model_dir: str, batch_size: int = 8, max_length: int = 1536, n_pairs: int = 16
):
    """Quick benchmark of the optimum ONNX model."""
    from optimum.onnxruntime import ORTModelForSequenceClassification
    from transformers import AutoTokenizer
    import numpy as np

    print(f"\n=== Quick ONNX Benchmark (optimum) ===")
    print(f"  Batch size: {batch_size}, Max length: {max_length}, Pairs: {n_pairs}")

    # Load
    t0 = time.perf_counter()
    model = ORTModelForSequenceClassification.from_pretrained(model_dir)
    tokenizer = AutoTokenizer.from_pretrained(model_dir)
    load_time = time.perf_counter() - t0
    print(f"  Model load: {load_time:.3f}s")

    # Create pairs with realistic text lengths
    query = "How does changing precipitation patterns affect agricultural productivity in Mediterranean regions during periods of climate variability?"
    doc = (
        "This study examines the relationship between changing precipitation patterns and crop yields across Southern Europe. "
        "We analyze historical records spanning three centuries alongside modern satellite data to establish baseline precipitation "
        "trends and their correlation with various crop yields. Our findings indicate a strong negative correlation between "
        "precipitation variability and crop yield stability, particularly for rain-fed agricultural systems. "
    ) * 5

    pairs_text = [(query, doc[:3500])] * n_pairs

    # Warmup
    enc = tokenizer(
        [pairs_text[0][0]],
        [pairs_text[0][1]],
        padding=True,
        truncation=True,
        max_length=max_length,
        return_tensors="np",
    )
    _ = model(**enc)

    # Benchmark
    batch_times = []
    for start in range(0, len(pairs_text), batch_size):
        batch = pairs_text[start : start + batch_size]
        t1 = time.perf_counter()
        enc = tokenizer(
            [p[0] for p in batch],
            [p[1] for p in batch],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",
        )
        result = model(**enc)
        t2 = time.perf_counter()
        batch_times.append((t2 - t1) * 1000)
        print(
            f"  Batch: {(t2-t1)*1000:.1f}ms ({len(batch)} pairs, seq={enc['input_ids'].shape[1]})"
        )

    avg = sum(batch_times) / len(batch_times)
    print(
        f"  Avg batch: {avg:.1f}ms, Throughput: {n_pairs / (sum(batch_times)/1000):.2f} pairs/sec"
    )
    return avg


if __name__ == "__main__":
    model_name = "BAAI/bge-reranker-v2-m3"
    output_dir = str(Path(__file__).resolve().parent / "onnx_reranker_optimum")

    model_dir = convert_with_optimum(model_name, output_dir)

    # Check if optimized version exists, benchmark both
    opt_dir = Path(model_dir) / "optimized"

    print("\n--- Unoptimized ---")
    quick_benchmark(model_dir)

    if opt_dir.exists() and (opt_dir / "model_optimized.onnx").exists():
        print("\n--- O2 Optimized ---")
        quick_benchmark(str(opt_dir))
