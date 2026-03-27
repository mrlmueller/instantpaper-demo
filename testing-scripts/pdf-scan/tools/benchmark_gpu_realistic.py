#!/usr/bin/env python3
"""
Realistic cross-encoder GPU benchmark with LONG text pairs.

Real pipeline pairs have section_excerpt_max_chars=2200 + passage_excerpt=520
which tokenize to ~800-1500 tokens. This script generates pairs of that length
to measure realistic GPU throughput for cost analysis.
"""

import time, os, random, json
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification

MODEL_NAME = "BAAI/bge-reranker-v2-m3"
MAX_LENGTH = 1536  # Same as pipeline

# Longer realistic text blocks (section-length excerpts from academic writing)
LONG_TEXTS = [
    "Choice architecture is the design of different ways in which choices can be presented to decision makers, and the impact of that presentation on their decision-making. It describes the practice of influencing choice by organizing the context in which people make decisions. A choice architect has the responsibility for organizing the context in which people make decisions. The term was coined by Richard Thaler and Cass Sunstein in their 2008 book Nudge: Improving Decisions about Health, Wealth, and Happiness. The framework is used across a wide range of fields including public policy, healthcare, urban planning, and digital product design. In software design, choice architecture manifests through default settings, option ordering, information disclosure patterns, and feedback mechanisms. Studies consistently show that the way options are framed significantly influences which option users select, even when the underlying options remain identical. Default effects represent one of the most powerful tools in the choice architect's toolkit, as research across multiple domains demonstrates that people tend to stick with pre-selected options regardless of their individual preferences. This phenomenon has been observed in organ donation rates, retirement savings plans, privacy settings, and consumer product configurations.",
    "The concept of nudging in behavioral economics refers to any aspect of the choice architecture that alters people's behavior in a predictable way without forbidding any options or significantly changing their economic incentives. To count as a mere nudge, the intervention must be easy and cheap to avoid. Nudges are not mandates. Digital nudging extends this concept to online environments where user interfaces serve as the choice architecture. Research has identified several key mechanisms through which digital nudges operate: default settings that pre-select options, social proof indicators that show what others have chosen, anchoring effects through initial price or value displays, scarcity cues that create urgency, and personalized recommendations that leverage cognitive biases. The effectiveness of digital nudges depends on factors including user awareness, interface design quality, cultural context, and the specific cognitive bias being leveraged. Meta-analyses of nudging interventions show effect sizes ranging from small to medium, with default-based nudges typically showing the largest and most consistent effects across studies.",
    "Dark patterns are deceptive design techniques used in websites, apps, and other digital interfaces to manipulate users into making decisions they would not otherwise make. First coined by UX designer Harry Brignull in 2010, the term encompasses a wide variety of manipulative interface designs including trick questions, sneak into basket, roach motels, privacy zuckering, misdirection, hidden costs, bait and switch, confirmshaming, disguised ads, and forced continuity. These patterns exploit cognitive biases and heuristics that humans rely on for efficient decision-making. The European Union's Digital Services Act and the proposed DETOUR Act in the United States represent legislative attempts to regulate dark patterns. Research on dark pattern effectiveness shows they can significantly increase conversion rates, subscription sign-ups, and data sharing consent, but they also erode user trust and can be counterproductive for long-term customer relationships. A growing body of academic research documents the prevalence of dark patterns across industries including e-commerce, social media, gaming, and financial services.",
    "In their seminal work on judgment under uncertainty, Daniel Kahneman and Amos Tversky demonstrated that human judgment systematically deviates from rational models in predictable ways. They identified three primary heuristics that people employ when making judgments under uncertainty: representativeness, availability, and anchoring and adjustment. The representativeness heuristic leads people to assess the probability of an event by the degree to which it resembles a prototype or stereotype. The availability heuristic causes people to estimate the likelihood of events based on how easily examples come to mind, leading to systematic overestimation of dramatic or memorable events. Anchoring and adjustment describes the tendency to make estimates by starting from an initial value and adjusting insufficiently. These heuristics, while generally useful and efficient, can lead to severe and systematic errors. Their work formed the foundation of behavioral economics and earned Kahneman the Nobel Prize in Economics in 2002. Subsequent research has extended these findings to demonstrate how heuristics and biases affect professional judgment in medicine, law, finance, and engineering.",
    "Information overload occurs when the amount of input to a system exceeds its processing capacity. In the context of consumer decision-making, information overload can lead to decision fatigue, decreased decision quality, and decision avoidance. The proliferation of online reviews, product comparisons, and recommendation systems has created unprecedented levels of information available to consumers. Research on online review systems demonstrates that while access to more reviews generally improves decision quality up to a point, beyond a certain threshold additional reviews lead to confusion and cognitive overload. Factors that moderate the relationship between information quantity and decision quality include information presentation format, individual differences in need for cognition, product complexity, and the availability of filtering and sorting tools. Machine learning approaches to review summarization and sentiment analysis represent technological attempts to address information overload by distilling large volumes of review text into actionable summaries.",
]


def generate_long_pairs(n: int) -> list:
    """Generate pairs where query (~500 chars) + passage (~2000 chars) → tokenizes to ~1000-1500 tokens."""
    pairs = []
    for i in range(n):
        # Query: combine 2 text blocks for ~400-600 chars (mimics subpoint query)
        q_parts = random.sample(LONG_TEXTS, 2)
        query = q_parts[0][:300] + " || " + q_parts[1][:200] + f" [q-{i}]"

        # Passage: full text block ~1500-2200 chars (mimics section excerpt)
        passage = (
            random.choice(LONG_TEXTS)
            + " "
            + random.choice(LONG_TEXTS)[:600]
            + f" [p-{i}]"
        )

        pairs.append(
            {
                "candidate_id": f"doc_{i:04d}",
                "query": query,
                "candidate_text": passage,
            }
        )
    return pairs


def check_token_lengths(pairs, tokenizer, max_length):
    """Sample token lengths to verify they're realistic."""
    lengths = []
    for p in pairs[:20]:
        enc = tokenizer(
            p["query"], p["candidate_text"], truncation=True, max_length=max_length
        )
        lengths.append(len(enc["input_ids"]))
    avg = sum(lengths) / len(lengths)
    print(
        f"  Token lengths (sample of {len(lengths)}): min={min(lengths)}, max={max(lengths)}, avg={avg:.0f}"
    )
    return avg


def benchmark(
    pairs, device, batch_size, max_length, tokenizer, model, warmup=2, timed=3
):
    def run_once():
        with torch.inference_mode():
            for start in range(0, len(pairs), batch_size):
                batch = pairs[start : start + batch_size]
                enc = tokenizer(
                    [p["query"] for p in batch],
                    [p["candidate_text"] for p in batch],
                    padding=True,
                    truncation=True,
                    max_length=max_length,
                    return_tensors="pt",
                )
                enc = {k: v.to(device) for k, v in enc.items()}
                logits = model(**enc).logits
        if device == "cuda":
            torch.cuda.synchronize()

    for _ in range(warmup):
        run_once()

    times = []
    for _ in range(timed):
        if device == "cuda":
            torch.cuda.synchronize()
        t0 = time.perf_counter()
        run_once()
        if device == "cuda":
            torch.cuda.synchronize()
        times.append(time.perf_counter() - t0)

    median = sorted(times)[timed // 2]
    return {
        "device": device,
        "batch_size": batch_size,
        "pair_count": len(pairs),
        "median_sec": round(median, 4),
        "pairs_per_sec": round(len(pairs) / median, 2),
        "times": [round(t, 4) for t in times],
    }


def main():
    has_cuda = torch.cuda.is_available()
    if has_cuda:
        print(
            f"GPU: {torch.cuda.get_device_name(0)} ({torch.cuda.get_device_properties(0).total_memory/1024**3:.1f} GiB)"
        )
    print(f"CPU threads: {os.cpu_count()}")
    print(f"Model: {MODEL_NAME}")
    print(f"Max length: {MAX_LENGTH} tokens\n")

    # Load tokenizer / model
    tokenizer = AutoTokenizer.from_pretrained(MODEL_NAME)

    # Generate pairs
    all_results = {}

    for n_pairs in [100, 420]:
        pairs = generate_long_pairs(n_pairs)
        print(f"{'='*60}")
        print(f"  {n_pairs} LONG pairs")
        print(f"{'='*60}")
        check_token_lengths(pairs, tokenizer, MAX_LENGTH)

        # CPU fp32
        print(f"\n  Loading model (CPU fp32)...")
        model_cpu = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
        model_cpu.eval()

        for bs in [8, 32]:
            print(f"\n  [CPU fp32] batch={bs}, {n_pairs} pairs")
            r = benchmark(
                pairs, "cpu", bs, MAX_LENGTH, tokenizer, model_cpu, warmup=1, timed=3
            )
            print(f"    → {r['pairs_per_sec']} pairs/sec ({r['median_sec']}s)")
            all_results[f"cpu_fp32_bs{bs}_{n_pairs}p"] = r

        del model_cpu
        torch.cuda.empty_cache() if has_cuda else None

        # GPU fp16
        if has_cuda:
            print(f"\n  Loading model (GPU fp16)...")
            model_gpu = AutoModelForSequenceClassification.from_pretrained(MODEL_NAME)
            model_gpu = model_gpu.half().to("cuda")
            model_gpu.eval()

            for bs in [16, 32, 64]:
                print(f"\n  [GPU fp16] batch={bs}, {n_pairs} pairs")
                try:
                    r = benchmark(
                        pairs,
                        "cuda",
                        bs,
                        MAX_LENGTH,
                        tokenizer,
                        model_gpu,
                        warmup=2,
                        timed=3,
                    )
                    print(f"    → {r['pairs_per_sec']} pairs/sec ({r['median_sec']}s)")
                    all_results[f"gpu_fp16_bs{bs}_{n_pairs}p"] = r
                except RuntimeError as e:
                    if "out of memory" in str(e).lower():
                        print(f"    → OOM at batch_size={bs}")
                        torch.cuda.empty_cache()
                    else:
                        raise

            del model_gpu
            torch.cuda.empty_cache()

    # Summary
    print(f"\n{'='*60}")
    print(f"  REALISTIC THROUGHPUT SUMMARY")
    print(f"{'='*60}")
    print(f"\n  {'Config':<28} {'Pairs':>6} {'Sec':>8} {'Pairs/s':>9}")
    print(f"  {'─'*28} {'─'*6} {'─'*8} {'─'*9}")

    for key, r in sorted(all_results.items()):
        label = key.rsplit("_", 1)[0].replace("_", " ")
        print(
            f"  {label:<28} {r['pair_count']:>6} {r['median_sec']:>8.3f} {r['pairs_per_sec']:>9.1f}"
        )

    # GPU vs CPU speedup at 420 pairs
    cpu_420 = all_results.get("cpu_fp32_bs8_420p")
    gpu_420 = all_results.get("gpu_fp16_bs32_420p") or all_results.get(
        "gpu_fp16_bs16_420p"
    )
    if cpu_420 and gpu_420:
        speedup = gpu_420["pairs_per_sec"] / cpu_420["pairs_per_sec"]
        print(f"\n  GPU/CPU speedup (420 pairs, long text): {speedup:.1f}x")
        print(f"  CPU: {cpu_420['median_sec']}s | GPU: {gpu_420['median_sec']}s")

        # L4 extrapolation
        # RTX 3080: 29.8 TFLOPS FP16 | L4: 30.3 TFLOPS FP16 (dense)
        # For compute-bound long sequences, roughly equivalent
        l4_factor = 1.0  # L4 ≈ RTX 3080 at dense FP16
        l4_pps = gpu_420["pairs_per_sec"] * l4_factor
        l4_time_420 = 420 / l4_pps

        print(f"\n  L4 GPU extrapolation (≈ RTX 3080 at dense FP16):")
        print(f"    420 pairs: ~{l4_time_420:.1f}s")
        print(f"    1000 pairs: ~{1000/l4_pps:.1f}s")

        # Cloud Run 4 vCPU extrapolation
        # Local has 20 threads but Cloud Run CPU (Xeon) per-core IPC differs
        # Conservative: 4 vCPU ≈ 4/20 * local_cpu = 0.2x local
        cr_factor = 4 / 20
        cr_pps = cpu_420["pairs_per_sec"] * cr_factor
        cr_time_420 = 420 / cr_pps

        print(
            f"\n  Cloud Run 4 vCPU extrapolation (~{cr_factor:.0%} of local 20-thread CPU):"
        )
        print(f"    420 pairs: ~{cr_time_420:.0f}s ({cr_time_420/60:.1f} min)")
        print(f"    Note: Actual measured time was 2299s (38.3 min) for 420 pairs")

    # Save
    outpath = os.path.join(os.path.dirname(__file__), "gpu_benchmark_realistic.json")
    with open(outpath, "w") as f:
        json.dump(all_results, f, indent=2)
    print(f"\n  Saved to {outpath}")


if __name__ == "__main__":
    random.seed(42)
    main()
