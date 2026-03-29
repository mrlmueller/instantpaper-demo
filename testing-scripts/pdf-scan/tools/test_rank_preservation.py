#!/usr/bin/env python3
"""Quick check: ranking preservation with ONNX INT8 (same text, no truncation)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from phase_f_lab import score_cross_encoder_pairs, PhaseFOptions


def load_pairs(run_id, max_pairs=80):
    run_dir = Path(__file__).resolve().parent.parent / "runs" / run_id / "rerank"
    packs = []
    with open(run_dir / "phase_f_candidate_packs.jsonl", encoding="utf-8") as f:
        for line in f:
            packs.append(json.loads(line))
    qp = json.loads((run_dir.parent / "query_plan.json").read_text(encoding="utf-8"))
    gq = qp.get("refined_question", "research question") or "research question"
    pairs = []
    for pack in packs:
        pairs.append(
            {
                "candidate_id": pack.get("candidate_id"),
                "query_kind": "global",
                "query": gq,
                "candidate_text": pack.get("candidate_text", ""),
            }
        )
        for sp in list(pack.get("chosen_subpoint_ids") or []):
            pairs.append(
                {
                    "candidate_id": pack.get("candidate_id"),
                    "query_kind": "subpoint",
                    "subpoint_id": sp,
                    "query": f"Subpoint {sp}: {gq}",
                    "candidate_text": pack.get("candidate_text", ""),
                }
            )
    return pairs[:max_pairs]


pairs = load_pairs("a33419bf76ad298d82369172", 40)
print(
    f"Testing ranking preservation with {len(pairs)} pairs (same text, no truncation)"
)

# PyTorch
opt_pt = PhaseFOptions(cross_encoder_prefer_onnx=False, cross_encoder_batch_size=8)
r_pt = score_cross_encoder_pairs(pairs, opt_pt)

# ONNX INT8
opt_ox = PhaseFOptions(cross_encoder_prefer_onnx=True, cross_encoder_batch_size=8)
r_ox = score_cross_encoder_pairs(pairs, opt_ox)

# Compare per-candidate aggregated scores
from collections import defaultdict

pt_by_cid = defaultdict(list)
ox_by_cid = defaultdict(list)
for r in r_pt["rows"]:
    pt_by_cid[r["candidate_id"]].append(r["score_prob"])
for r in r_ox["rows"]:
    ox_by_cid[r["candidate_id"]].append(r["score_prob"])

pt_avg = {cid: sum(v) / len(v) for cid, v in pt_by_cid.items()}
ox_avg = {cid: sum(v) / len(v) for cid, v in ox_by_cid.items()}

pt_ranked = sorted(pt_avg.items(), key=lambda x: x[1], reverse=True)
ox_ranked = sorted(ox_avg.items(), key=lambda x: x[1], reverse=True)

pt_rank_map = {cid: i for i, (cid, _) in enumerate(pt_ranked)}
ox_rank_map = {cid: i for i, (cid, _) in enumerate(ox_ranked)}

common = set(pt_rank_map) & set(ox_rank_map)
n = len(common)
d2 = sum((pt_rank_map[c] - ox_rank_map[c]) ** 2 for c in common)
rho = 1 - 6 * d2 / (n * (n**2 - 1)) if n > 1 else 1.0

print(f"Candidates: {n}")
print(f"Spearman rank correlation (ONNX INT8 vs PyTorch, same text): {rho:.4f}")

# Top-5 agreement
pt_top5 = set(cid for cid, _ in pt_ranked[:5])
ox_top5 = set(cid for cid, _ in ox_ranked[:5])
overlap = len(pt_top5 & ox_top5)
print(f"Top-5 overlap: {overlap}/5")

pt_top10 = set(cid for cid, _ in pt_ranked[:10])
ox_top10 = set(cid for cid, _ in ox_ranked[:10])
overlap10 = len(pt_top10 & ox_top10)
print(f"Top-10 overlap: {overlap10}/10")

# Show max score diff
max_diff = max(abs(pt_avg[c] - ox_avg.get(c, 0)) for c in common)
print(f"Max avg score diff: {max_diff:.6f}")
