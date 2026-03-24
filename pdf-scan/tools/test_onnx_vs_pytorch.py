#!/usr/bin/env python3
"""Quick test: verify ONNX vs PyTorch scoring paths produce comparable results."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phase_f_lab import score_cross_encoder_pairs, PhaseFOptions

# Load pairs from test run
pairs = []
packs_path = (
    Path(__file__).resolve().parent.parent
    / "runs"
    / "a33419bf76ad298d82369172"
    / "rerank"
    / "phase_f_candidate_packs.jsonl"
)
with open(packs_path, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 4:
            break
        pack = json.loads(line)
        pairs.append(
            {
                "candidate_id": pack.get("candidate_id"),
                "query_kind": "global",
                "query": "How does climate affect historical conflicts?",
                "candidate_text": pack.get("candidate_text", ""),
            }
        )

print(f"Testing with {len(pairs)} pairs...\n")

# ONNX path
opt_onnx = PhaseFOptions(cross_encoder_prefer_onnx=True, cross_encoder_batch_size=4)
result_onnx = score_cross_encoder_pairs(pairs, opt_onnx)
rt = result_onnx["runtime"]
print(f"ONNX: {rt['elapsed_ms']:.0f}ms, backend={rt.get('backend')}")
for r in result_onnx["rows"]:
    print(f"  {r['candidate_id'][:16]}: prob={r['score_prob']:.6f}")

# PyTorch path
opt_pt = PhaseFOptions(cross_encoder_prefer_onnx=False, cross_encoder_batch_size=4)
result_pt = score_cross_encoder_pairs(pairs, opt_pt)
rt_pt = result_pt["runtime"]
print(f"\nPyTorch: {rt_pt['elapsed_ms']:.0f}ms, backend={rt_pt.get('backend')}")
for r in result_pt["rows"]:
    print(f"  {r['candidate_id'][:16]}: prob={r['score_prob']:.6f}")

# Compare
print("\nScore comparison (ONNX vs PyTorch):")
max_diff = 0
for o, p in zip(result_onnx["rows"], result_pt["rows"]):
    diff = abs(o["score_prob"] - p["score_prob"])
    max_diff = max(max_diff, diff)
    rank_agree = (
        "OK" if (o["score_prob"] > 0.5) == (p["score_prob"] > 0.5) else "MISMATCH"
    )
    print(
        f"  {o['candidate_id'][:16]}: onnx={o['score_prob']:.6f} pt={p['score_prob']:.6f} diff={diff:.6f} {rank_agree}"
    )

print(f"\nMax probability difference: {max_diff:.6f}")
if max_diff < 0.1:
    print("PASS: Scores are within acceptable tolerance for INT8 quantization")
else:
    print("WARNING: Large score differences detected")
