#!/usr/bin/env python3
"""Test the impact of text length reduction on token counts."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from transformers import AutoTokenizer

tokenizer = AutoTokenizer.from_pretrained("BAAI/bge-reranker-v2-m3")

packs_path = (
    Path(__file__).resolve().parent.parent
    / "runs"
    / "a33419bf76ad298d82369172"
    / "rerank"
    / "phase_f_candidate_packs.jsonl"
)
packs = []
with open(packs_path, encoding="utf-8") as f:
    for line in f:
        packs.append(json.loads(line))

query = "How does climate affect historical conflicts and societal changes in the late Roman period?"

# Simulate old (2200/520) vs new (1400/400) text lengths
for label, max_excerpt, max_passage in [
    ("OLD (2200/520)", 2200, 520),
    ("NEW (1400/400)", 1400, 400),
]:
    token_counts = []
    text_lengths = []
    for pack in packs[:20]:
        text = pack.get("candidate_text", "")
        # Truncate to simulate different excerpt lengths
        if label.startswith("NEW"):
            # Re-truncate section_excerpt and evidence portions
            # Approximate: candidate_text is proportional to excerpt + passages
            old_len = len(text)
            ratio = (max_excerpt + 3 * max_passage) / (2200 + 3 * 520)
            text = text[: int(old_len * ratio)]

        enc = tokenizer(query, text, truncation=True, max_length=1536)
        token_counts.append(len(enc["input_ids"]))
        text_lengths.append(len(text))

    avg_tokens = sum(token_counts) / len(token_counts)
    max_tokens = max(token_counts)
    avg_chars = sum(text_lengths) / len(text_lengths)
    print(f"{label}:")
    print(
        f"  Avg chars: {avg_chars:.0f}, Avg tokens: {avg_tokens:.0f}, Max tokens: {max_tokens}"
    )
    print(
        f"  Token distribution: {sorted(token_counts)[:5]} ... {sorted(token_counts)[-5:]}"
    )
