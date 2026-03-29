#!/usr/bin/env python3
"""Convert BAAI/bge-reranker-v2-m3 to ONNX for faster CPU inference."""

import argparse
import sys
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


def convert(model_name: str, output_dir: str, opset: int = 17):
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    print(f"Loading model: {model_name}")
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForSequenceClassification.from_pretrained(model_name)
    model.eval()

    # Dummy input for export
    dummy = tokenizer(
        ["What is machine learning?"],
        ["Machine learning is a subset of AI."],
        padding=True,
        truncation=True,
        max_length=512,
        return_tensors="pt",
    )

    onnx_path = out / "model.onnx"
    print(f"Exporting to {onnx_path} (opset={opset})")

    torch.onnx.export(
        model,
        (dummy["input_ids"], dummy["attention_mask"]),
        str(onnx_path),
        opset_version=opset,
        input_names=["input_ids", "attention_mask"],
        output_names=["logits"],
        dynamic_axes={
            "input_ids": {0: "batch", 1: "seq"},
            "attention_mask": {0: "batch", 1: "seq"},
            "logits": {0: "batch"},
        },
    )

    # Save tokenizer alongside model
    tokenizer.save_pretrained(str(out))

    # Verify numerical equivalence
    print("Verifying numerical equivalence...")
    import onnxruntime as ort

    session = ort.InferenceSession(str(onnx_path))
    with torch.inference_mode():
        pt_logits = model(**dummy).logits.numpy()

    ort_logits = session.run(
        None,
        {
            "input_ids": dummy["input_ids"].numpy(),
            "attention_mask": dummy["attention_mask"].numpy(),
        },
    )[0]

    diff = float(np.max(np.abs(pt_logits - ort_logits)))
    print(f"Max absolute difference: {diff:.8f}")
    if diff > 0.001:
        print("WARNING: Numerical difference exceeds tolerance!")
        return 1

    # Test with a longer, more realistic input
    print("\nTesting with realistic input length...")
    long_dummy = tokenizer(
        [
            "How does climate change affect agricultural yields in Mediterranean regions?"
        ],
        [
            "This study examines the relationship between changing precipitation patterns and crop yields across Southern Europe. "
            * 20
        ],
        padding=True,
        truncation=True,
        max_length=1536,
        return_tensors="pt",
    )
    with torch.inference_mode():
        pt_long = model(**long_dummy).logits.numpy()

    ort_long = session.run(
        None,
        {
            "input_ids": long_dummy["input_ids"].numpy(),
            "attention_mask": long_dummy["attention_mask"].numpy(),
        },
    )[0]

    long_diff = float(np.max(np.abs(pt_long - ort_long)))
    print(f"Long input max difference: {long_diff:.8f}")
    print(f"Long input seq_len: {long_dummy['input_ids'].shape[1]}")

    model_size_mb = onnx_path.stat().st_size / (1024 * 1024)
    print(f"\nONNX model saved to {out}")
    print(f"Model size: {model_size_mb:.1f} MB")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument(
        "--output", default=str(Path(__file__).resolve().parent / "onnx_reranker")
    )
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()
    sys.exit(convert(args.model, args.output, args.opset))
