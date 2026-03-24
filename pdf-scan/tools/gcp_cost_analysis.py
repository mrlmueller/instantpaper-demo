#!/usr/bin/env python3
"""
GCP Cloud Run cost calculator for the PDF scan pipeline.

Compares architectural options:
  A) Current: Single CPU-only Cloud Run Job
  B) CPU + ONNX INT8 optimization (same hardware)
  C) Split: CPU phases + GPU Phase F (separate Cloud Run Job with L4)
  D) Single GPU instance for all phases

Pricing source: https://cloud.google.com/run/pricing (as of March 2026)

GPU Benchmark data (measured locally, RTX 3080 ≈ L4 at dense FP16):
  - CPU fp32 (20 threads, 420 long pairs): 1.68 pairs/sec → 250s
  - GPU fp16 (RTX 3080, 420 long pairs):  136.6 pairs/sec → 3.1s
  - GPU/CPU speedup (same machine): 81.3x
  - Cloud Run 4 vCPU measured: 0.183 pairs/sec → 2299s for 420 pairs
  - L4 ≈ RTX 3080 at dense FP16 (both ~30 TFLOPS)
"""

# ─── GCP Cloud Run Pricing (per second) ─────────────────────────────────

# Tier 1 regions: europe-west1 (Belgium), europe-west4 (Netherlands)
# Tier 2 regions: europe-west3 (Frankfurt)
# Tier 2 is ~10% more expensive (Jobs follow Tier1/Tier2 structure)

# Jobs pricing (Tier 1)
CPU_PER_VCPU_SEC_T1 = 0.000018  # per vCPU-second
MEM_PER_GIB_SEC_T1 = 0.000002  # per GiB-second
GPU_L4_PER_SEC = 0.0001867  # L4 GPU, no zonal redundancy

# Tier 2 markup (~12% based on GCP pricing tables)
TIER2_MARKUP = 1.12
CPU_PER_VCPU_SEC_T2 = CPU_PER_VCPU_SEC_T1 * TIER2_MARKUP
MEM_PER_GIB_SEC_T2 = MEM_PER_GIB_SEC_T1 * TIER2_MARKUP


def cloud_run_job_cost(
    cpu: int,
    mem_gib: int,
    runtime_sec: float,
    region_tier: int = 2,
    gpu_l4: bool = False,
) -> dict:
    """Calculate Cloud Run Job cost for a single execution."""
    if region_tier == 1:
        cpu_rate = CPU_PER_VCPU_SEC_T1
        mem_rate = MEM_PER_GIB_SEC_T1
    else:
        cpu_rate = CPU_PER_VCPU_SEC_T2
        mem_rate = MEM_PER_GIB_SEC_T2

    cpu_cost = cpu * runtime_sec * cpu_rate
    mem_cost = mem_gib * runtime_sec * mem_rate
    gpu_cost = runtime_sec * GPU_L4_PER_SEC if gpu_l4 else 0.0

    return {
        "cpu_cost": cpu_cost,
        "mem_cost": mem_cost,
        "gpu_cost": gpu_cost,
        "total": cpu_cost + mem_cost + gpu_cost,
        "runtime_sec": runtime_sec,
        "runtime_min": runtime_sec / 60,
    }


# ─── Pipeline Runtime: MEASURED on Cloud Run (4 vCPU, 16 GiB, europe-west3) ──

# From actual Cloud Run execution (test run a33419bf76ad298d82369172, 3-4 docs):
#   phase_a: 0.075s, phase_b: 51.3s, phase_c: 14.2s,
#   phase_d: 117.3s, phase_e: 17.3s, phase_f: 2315.0s, phase_g: 0.6s
#   Total: ~2515s (42 min)
#
# Phase F breakdown (420 pairs):
#   - Cross-encoder scoring: 2299s (96.6% of Phase F) — 0.183 pairs/sec
#   - Judge LLM (gpt-5-mini via OpenAI): 13.8s (0.6%)
#   - Other (pack building, scoring): ~2.2s

PHASE_RUNTIMES_CPU_4VCPU_BASELINE = {
    "phase_a": 0.1,
    "phase_b": 51.3,  # 3-4 small PDFs; 5 mixed PDFs with 500pg = longer
    "phase_c": 14.2,
    "phase_d": 117.3,  # OpenAI API calls (mostly wait time)
    "phase_e": 17.3,  # OpenAI embeddings (mostly wait time)
    "phase_f_cross_encoder": 2299.0,  # CPU-bound, 420 pairs on 4 vCPU
    "phase_f_judge": 13.8,  # OpenAI API call (I/O bound)
    "phase_f_other": 2.2,  # Pack building etc.
    "phase_g": 0.6,
}

# ─── GPU Benchmark: MEASURED locally (RTX 3080 ≈ L4 at dense FP16) ───────────

# Benchmark: tools/benchmark_gpu_realistic.py (420 long pairs, ~480 tokens avg)
#   CPU fp32 (local, 20 threads): 1.68 pairs/sec → 250s
#   GPU fp16 (RTX 3080, bs=32):  136.6 pairs/sec → 3.1s
#   GPU/CPU local speedup: 81.3x
#
# Cloud Run extrapolation:
#   Cloud Run 4 vCPU measured: 0.183 pairs/sec (2299s for 420 pairs)
#   L4 GPU expected: ~137 pairs/sec (≈ RTX 3080 at dense FP16)
#   GPU speedup vs Cloud Run 4 vCPU: ~750x
#
# Note: benchmark pairs averaged 480 tokens. Real pipeline pairs may be longer
# (up to 1536 tokens), which would slow both CPU and GPU proportionally.
# Using measured 3.1s as optimistic and 2x safety factor → 6.2s conservative.

GPU_CE_TIME_420_PAIRS = 3.1  # Measured on RTX 3080, 420 pairs
GPU_CE_TIME_CONSERVATIVE = 6.2  # 2x safety factor for longer real-world text

# ONNX INT8 speedup on cross-encoder (measured: 1.85x on local 20-thread CPU)
# On 4 vCPU Cloud Run: less benefit because fewer threads for batching
# Conservative estimate: 1.4x on 4 vCPU (ONNX INT8 + batch_size=32)
ONNX_SPEEDUP_4VCPU = 1.4


def compute_scenario(name, runtimes, cpu, mem, tier, gpu=False, monthly_runs=40):
    total_sec = sum(runtimes.values())
    cost = cloud_run_job_cost(cpu, mem, total_sec, tier, gpu)
    monthly = cost["total"] * monthly_runs
    return {
        "name": name,
        "cpu": cpu,
        "mem_gib": mem,
        "tier": tier,
        "gpu": gpu,
        "total_sec": total_sec,
        "total_min": total_sec / 60,
        "cost_per_run": cost["total"],
        "cost_monthly": monthly,
        **{f"cost_{k}": v for k, v in cost.items() if k != "total"},
    }


def main():
    monthly_runs = 40  # ~10 runs/week

    print("=" * 75)
    print("  GCP CLOUD RUN — PDF SCAN PIPELINE COST ANALYSIS")
    print("  (with measured GPU benchmark data from RTX 3080)")
    print("=" * 75)

    # ─── Scenario A: Current (CPU-only, 4 vCPU, 16 GiB, europe-west3) ───
    rt_a = dict(PHASE_RUNTIMES_CPU_4VCPU_BASELINE)
    rt_a["phase_f"] = (
        rt_a.pop("phase_f_cross_encoder")
        + rt_a.pop("phase_f_judge")
        + rt_a.pop("phase_f_other")
    )
    a = compute_scenario("A: Current CPU-only (europe-west3)", rt_a, 4, 16, tier=2)

    # ─── Scenario B: CPU + ONNX INT8 (same hardware) ───
    rt_b = dict(PHASE_RUNTIMES_CPU_4VCPU_BASELINE)
    rt_b["phase_f_cross_encoder"] /= ONNX_SPEEDUP_4VCPU
    rt_b["phase_f"] = (
        rt_b.pop("phase_f_cross_encoder")
        + rt_b.pop("phase_f_judge")
        + rt_b.pop("phase_f_other")
    )
    b = compute_scenario("B: CPU + ONNX INT8 (europe-west3)", rt_b, 4, 16, tier=2)

    # ─── Scenario C: Split — CPU phases in west3, GPU Phase F in west1 ───
    # CPU job: phases A-E
    rt_c_cpu = {
        "phase_a": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_a"],
        "phase_b": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_b"],
        "phase_c": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_c"],
        "phase_d": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_d"],
        "phase_e": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_e"],
    }
    c_cpu = compute_scenario(
        "C-cpu: Phases A-E (europe-west3)",
        rt_c_cpu,
        4,
        16,
        tier=2,
        monthly_runs=monthly_runs,
    )

    # GPU job: Phase F + G (L4, 4 vCPU min, 16 GiB min, europe-west1)
    model_load_time = 15.0  # cold start + model loading from GCS/baked image
    rt_c_gpu_optimistic = {
        "model_load": model_load_time,
        "phase_f_cross_encoder": GPU_CE_TIME_420_PAIRS,  # 3.1s measured
        "phase_f_judge": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_f_judge"],
        "phase_f_other": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_f_other"],
        "phase_g": PHASE_RUNTIMES_CPU_4VCPU_BASELINE["phase_g"],
    }
    rt_c_gpu_conservative = dict(rt_c_gpu_optimistic)
    rt_c_gpu_conservative["phase_f_cross_encoder"] = (
        GPU_CE_TIME_CONSERVATIVE  # 6.2s with 2x safety
    )

    c_gpu_opt = compute_scenario(
        "C-gpu-opt: F+G GPU (europe-west1)",
        rt_c_gpu_optimistic,
        4,
        16,
        tier=1,
        gpu=True,
        monthly_runs=monthly_runs,
    )
    c_gpu_con = compute_scenario(
        "C-gpu-con: F+G GPU (europe-west1)",
        rt_c_gpu_conservative,
        4,
        16,
        tier=1,
        gpu=True,
        monthly_runs=monthly_runs,
    )

    # ─── Scenario D: All phases on single GPU instance ───
    rt_d = dict(PHASE_RUNTIMES_CPU_4VCPU_BASELINE)
    rt_d["model_load"] = 15.0
    rt_d["phase_f_cross_encoder"] = GPU_CE_TIME_CONSERVATIVE
    rt_d["phase_f"] = (
        rt_d.pop("phase_f_cross_encoder")
        + rt_d.pop("phase_f_judge")
        + rt_d.pop("phase_f_other")
    )
    d = compute_scenario(
        "D: Single GPU instance (europe-west1)", rt_d, 8, 32, tier=1, gpu=True
    )

    # ─── Scenario E: CPU only but move to Tier 1 region (west1) ───
    rt_e = dict(rt_b)  # same as ONNX optimized
    e = compute_scenario("E: CPU+ONNX in Tier 1 (europe-west1)", rt_e, 4, 16, tier=1)

    # ─── Print results ───
    # For C, combine sub-scenarios
    c_total_opt = {
        "name": "C-opt: CPU+GPU split (optimistic)",
        "total_sec": c_cpu["total_sec"] + c_gpu_opt["total_sec"],
        "total_min": c_cpu["total_min"] + c_gpu_opt["total_min"],
        "cost_per_run": c_cpu["cost_per_run"] + c_gpu_opt["cost_per_run"],
        "cost_monthly": c_cpu["cost_monthly"] + c_gpu_opt["cost_monthly"],
    }
    c_total_con = {
        "name": "C-con: CPU+GPU split (conservative)",
        "total_sec": c_cpu["total_sec"] + c_gpu_con["total_sec"],
        "total_min": c_cpu["total_min"] + c_gpu_con["total_min"],
        "cost_per_run": c_cpu["cost_per_run"] + c_gpu_con["cost_per_run"],
        "cost_monthly": c_cpu["cost_monthly"] + c_gpu_con["cost_monthly"],
    }

    all_scenarios = [a, b, e, c_total_opt, c_total_con, d]

    print(f"\n  Assumptions: {monthly_runs} runs/month, test run = 420 pairs, 3-4 docs")
    print(f"  GPU data: MEASURED on RTX 3080 (≈ L4 at dense FP16)")
    print(f"  ONNX INT8 speedup on 4 vCPU: {ONNX_SPEEDUP_4VCPU}x (conservative)")
    print(f"  GPU cross-encoder: 3.1s (measured) / 6.2s (2x safety factor)")
    print()

    # Header
    print(f"  {'Scenario':<42} {'Runtime':>8} {'$/run':>8} {'$/month':>9}")
    print(f"  {'─'*42} {'─'*8} {'─'*8} {'─'*9}")

    for s in all_scenarios:
        print(
            f"  {s['name']:<42} {s['total_min']:>6.1f}m  ${s['cost_per_run']:>6.4f}  ${s['cost_monthly']:>7.2f}"
        )

    # ─── Detailed breakdown for C (split) ───
    print(f"\n  Scenario C breakdown (conservative):")
    print(
        f"    CPU job (A-E):  {c_cpu['total_min']:.1f}min  ${c_cpu['cost_per_run']:.4f}/run"
    )
    print(
        f"    GPU job (F+G):  {c_gpu_con['total_min']:.1f}min  ${c_gpu_con['cost_per_run']:.4f}/run"
    )
    print(
        f"      Cross-encoder on GPU: {GPU_CE_TIME_CONSERVATIVE:.1f}s (vs {PHASE_RUNTIMES_CPU_4VCPU_BASELINE['phase_f_cross_encoder']:.0f}s on CPU)"
    )
    print(f"      Model load overhead: {model_load_time:.0f}s")
    print(
        f"      GPU idle time (judge+pack+G): {PHASE_RUNTIMES_CPU_4VCPU_BASELINE['phase_f_judge'] + PHASE_RUNTIMES_CPU_4VCPU_BASELINE['phase_f_other'] + PHASE_RUNTIMES_CPU_4VCPU_BASELINE['phase_g']:.1f}s"
    )

    # ─── Key insights ───
    print(f"\n{'='*75}")
    print("  KEY INSIGHTS (with measured GPU data)")
    print(f"{'='*75}")

    savings_b = a["cost_monthly"] - b["cost_monthly"]
    savings_c = a["cost_monthly"] - c_total_con["cost_monthly"]
    savings_e = a["cost_monthly"] - e["cost_monthly"]

    print(
        f"""
  1. ONNX INT8 on current hardware (B vs A):
     Saves ${savings_b:.2f}/month ({savings_b/a['cost_monthly']*100:.0f}% infrastructure cost reduction)
     Runtime: {a['total_min']:.1f}min → {b['total_min']:.1f}min ({(1-b['total_min']/a['total_min'])*100:.0f}% faster)

  2. Move to Tier 1 region + ONNX (E vs A):
     Saves ${savings_e:.2f}/month ({savings_e/a['cost_monthly']*100:.0f}% reduction)
     Same runtime as B, cheaper region

  3. GPU split architecture (C-conservative vs A):
     Monthly cost: ${c_total_con['cost_monthly']:.2f} vs ${a['cost_monthly']:.2f}
     Saves ${savings_c:.2f}/month ({savings_c/a['cost_monthly']*100:.0f}% reduction)
     Runtime: {a['total_min']:.1f}min → {c_total_con['total_min']:.1f}min ({(1-c_total_con['total_min']/a['total_min'])*100:.0f}% faster)
     Phase F: 2299s → {GPU_CE_TIME_CONSERVATIVE}s (371x speedup on cloud)

  4. MEASURED GPU PERFORMANCE (RTX 3080 ≈ L4):
     CPU (20 local threads): 1.68 pairs/sec
     GPU fp16 (RTX 3080):    136.6 pairs/sec (81.3x faster)
     Cloud Run 4 vCPU:       0.183 pairs/sec (measured)
     L4 GPU (projected):     ~137 pairs/sec (~750x faster than Cloud Run CPU!)

  5. WHERE THE MONEY GOES ({monthly_runs} runs/month):
     OpenAI API:     ~$15-25/month (phases D, E, F-judge)
     Current infra:  ${a['cost_monthly']:.2f}/month (mostly Phase F cross-encoder time)
     GPU-split infra: ${c_total_con['cost_monthly']:.2f}/month
     Infrastructure savings: ${savings_c:.2f}/month ({savings_c/a['cost_monthly']*100:.0f}%)

  6. QUICK WINS (no architecture change needed):
     a) Move region europe-west3 → europe-west1: -12% cost, 1 config line
     b) Add ONNX INT8: -{savings_b/a['cost_monthly']*100:.0f}% cost, code change only

  7. BIG WIN (requires architecture change):
     GPU split: -${savings_c:.2f}/month + {(1-c_total_con['total_min']/a['total_min'])*100:.0f}% faster pipeline
     Needs: CUDA Docker image, L4 GPU Cloud Run Job, GCS for model storage
"""
    )

    # ─── Region comparison ───
    print(f"  REGION COMPARISON:")
    print(f"    europe-west3 (Frankfurt) = Tier 2 pricing, no GPU available")
    print(
        f"    europe-west1 (Belgium)   = Tier 1 pricing, L4 GPU available, EU/GDPR compliant"
    )
    print(
        f"    europe-west4 (Netherlands) = Tier 1 pricing, L4 GPU available, EU/GDPR compliant"
    )
    print(f"    → Recommendation: europe-west1 for best pricing + GPU option")

    # ─── GPU Job constraints ───
    print(f"\n  GPU CLOUD RUN JOB CONSTRAINTS:")
    print(f"    - L4 GPU: 24 GB VRAM, NVIDIA driver 535 (CUDA 12.2)")
    print(f"    - Minimum: 4 vCPU, 16 GiB memory")
    print(f"    - Max task timeout for GPU jobs: 1 hour")
    print(f"    - GPU instance cold start: ~5 seconds + model load time")
    print(f"    - Scale-to-zero supported (no charge when idle)")
    print(f"    - Initial quota: 3 GPUs per project per region")

    # ─── Scaling analysis ───
    print(f"\n  SCALING ANALYSIS (when does GPU save money?):")

    cpu_total_rate = 4 * CPU_PER_VCPU_SEC_T2 + 16 * MEM_PER_GIB_SEC_T2
    gpu_total_rate = 4 * CPU_PER_VCPU_SEC_T1 + 16 * MEM_PER_GIB_SEC_T1 + GPU_L4_PER_SEC

    cpu_pairs_per_sec = 420 / 2299  # measured on Cloud Run
    gpu_pairs_per_sec = 136.6  # measured on RTX 3080 ≈ L4

    cost_per_pair_cpu = cpu_total_rate / cpu_pairs_per_sec
    cost_per_pair_gpu = gpu_total_rate / gpu_pairs_per_sec
    gpu_fixed_cost = model_load_time * gpu_total_rate

    if cost_per_pair_cpu > cost_per_pair_gpu:
        breakeven_pairs = gpu_fixed_cost / (cost_per_pair_cpu - cost_per_pair_gpu)
        print(
            f"    GPU is cheaper than CPU after {breakeven_pairs:.0f} pairs (including model load overhead)"
        )
        print(
            f"    Current runs: ~420 pairs → {'GPU is MUCH cheaper' if 420 > breakeven_pairs else 'CPU is cheaper'}"
        )
    else:
        print(f"    GPU is always more expensive than CPU at current pricing")

    print(
        f"\n    Cost per pair (CPU, 4 vCPU, Tier 2):  ${cost_per_pair_cpu*1000:.4f} per 1000 pairs"
    )
    print(
        f"    Cost per pair (GPU L4, Tier 1):         ${cost_per_pair_gpu*1000:.6f} per 1000 pairs"
    )
    print(
        f"    GPU/CPU cost ratio per pair:             {cost_per_pair_gpu/cost_per_pair_cpu*100:.2f}%"
    )
    print(f"    GPU fixed overhead (model load):        ${gpu_fixed_cost:.4f} per run")
    print(
        f"    Total GPU Phase F cost (420 pairs):     ${gpu_fixed_cost + 420 * cost_per_pair_gpu:.4f}"
    )
    print(f"    Total CPU Phase F cost (420 pairs):     ${420 * cost_per_pair_cpu:.4f}")


if __name__ == "__main__":
    main()
