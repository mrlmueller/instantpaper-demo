# Pipeline CPU/GPU Split

## What Changed

The PDF scan pipeline has been split into two independent runners that can be executed separately:

| Runner           | Phases            | Compute                          | File                  |
| ---------------- | ----------------- | -------------------------------- | --------------------- |
| **CPU Pipeline** | A → B → C → D → E | CPU-only (no GPU needed)         | `run_pipeline_cpu.py` |
| **GPU Pipeline** | F → G             | Benefits from GPU (~80x speedup) | `run_pipeline_gpu.py` |

### How it works

1. `run_pipeline_cpu.py` runs phases A-E and produces all intermediate artifacts in `runs/{run_id}/`
2. `run_pipeline_gpu.py` takes a `--run-dir` argument, reconstructs the run context, and runs phases F+G
3. The original monolithic pipeline runner (`tools/benchmark/run_manual_topic_pipeline.py`) is unchanged and still works

### Usage (local development)

```bash
cd pdf-scan

# Step 1: Run CPU phases
python run_pipeline_cpu.py \
    --theme-md tools/test_theme_nudging.md \
    --pdf-dir paper-dump/Nudging \
    --max-pdfs 5

# Step 2: Run GPU phases (uses CUDA automatically if available)
python run_pipeline_gpu.py \
    --run-dir runs/{run_id}
```

### What was NOT changed

- **No phase_lab files were modified.** The phase code (phase_a_lab.py through phase_g_lab.py) is identical to the committed versions.
- The existing monolithic runner still works as before.
- All phase options/parameters are identical to the production pipeline.

---

## GPU Benchmark Results

Measured locally with RTX 3080 (10 GB VRAM) on BAAI/bge-reranker-v2-m3 cross-encoder, 420 realistic text pairs (~480 tokens avg):

| Backend                     | Pairs/sec | Time (420 pairs) | Speedup  |
| --------------------------- | --------- | ---------------- | -------- |
| Cloud Run 4 vCPU (measured) | 0.18      | 2,299s (38 min)  | 1x       |
| Local CPU fp32 (20 threads) | 1.68      | 250s             | 9.2x     |
| ONNX INT8 CPU (20 threads)  | 17.75     | 24s              | 97x      |
| **GPU fp16 (RTX 3080)**     | **136.6** | **3.1s**         | **750x** |

The L4 GPU on Cloud Run has comparable dense FP16 performance to the RTX 3080 (~30 TFLOPS each), so these numbers translate directly.

---

## Production Deployment Considerations

### 1. Storage: How the GPU Job Gets Its Data

The CPU and GPU jobs need to share the run directory (`runs/{run_id}/`). Options:

| Option                              | Pros                                     | Cons                                                              |
| ----------------------------------- | ---------------------------------------- | ----------------------------------------------------------------- |
| **GCS bucket (recommended)**        | Standard, scales, cheap ($0.02/GB/month) | CPU job uploads, GPU job downloads; adds ~10-30s transfer time    |
| **Cloud Storage FUSE**              | Mount GCS as filesystem, no code changes | Some latency on small file reads, requires `gcsfuse` in container |
| **Filestore (NFS)**                 | Fastest shared filesystem                | Expensive ($0.20/GB/month min 1TB = $204/month) — overkill        |
| **Artifact Registry + Cloud Build** | N/A                                      | Not applicable for run data                                       |

**Recommended approach: GCS bucket**

- CPU job writes artifacts to GCS at the end of Phase E
- GPU job downloads artifacts from GCS at the start of Phase F
- Total transfer: ~5-50 MB (JSONL files, no PDFs needed for F+G)
- Transfer time: <10 seconds

The run directory files that Phase F needs:

- `normalized/sections.jsonl` — section metadata
- `normalized/passages.jsonl` — passage text
- `normalized/documents.jsonl` — document metadata
- `retrieval/fused_candidates.jsonl` — Phase E candidates
- `retrieval/phase_e_subpoint_support.json` — active subpoints
- `query_plan.json` — query plan from Phase D
- `config.json` — run configuration

Phase G additionally needs Phase F's output:

- `rerank/rerank_results.jsonl` — reranked candidates

### 2. Docker Image Changes

The GPU job needs a CUDA-enabled Docker base image:

```dockerfile
# Current (CPU-only)
FROM python:3.11-slim

# GPU version
FROM nvidia/cuda:12.2.2-runtime-ubuntu22.04
# Then install Python 3.11, pip, etc.
```

The cross-encoder model (`BAAI/bge-reranker-v2-m3`, ~2.2 GB) needs to be available:

| Option                               | Cold start | Image size | Recommendation                  |
| ------------------------------------ | ---------- | ---------- | ------------------------------- |
| Download at runtime from HuggingFace | +60-120s   | Small      | Bad for jobs                    |
| **Bake into Docker image**           | 0s         | +2.2 GB    | Good for consistent cold starts |
| Store in GCS, download at startup    | +10-20s    | Small      | Good balance                    |

**Recommended: Bake into Docker image.** The GPU job runs for <1 minute, so a 60s model download overhead would double execution time. Baking adds 2.2 GB to the image but eliminates variable cold starts.

### 3. Cloud Run Configuration

**CPU Job (Phases A-E):**

- Region: europe-west1 (Tier 1, cheaper than current west3)
- Resources: 4 vCPU, 16 GiB memory (same as current)
- Timeout: 4 hours (same as current)
- No GPU

**GPU Job (Phases F-G):**

- Region: europe-west1 (L4 GPU available)
- Resources: 4 vCPU, 16 GiB memory, 1x L4 GPU
- Timeout: 1 hour (GPU jobs max)
- L4 GPU: 24 GB VRAM, NVIDIA Ada Lovelace architecture

GPU Cloud Run Jobs constraints:

- Max task timeout: **1 hour** (fine — GPU Phase F takes <1 minute)
- Min resources with GPU: 4 vCPU, 16 GiB
- Scale to zero when idle (no charge)
- L4 available in: europe-west1, europe-west4, us-central1, us-east4, asia-southeast1
- NOT available in europe-west3 (Frankfurt) — must use Belgium or Netherlands

### 4. Orchestration: Chaining CPU → GPU

In production, the CPU job needs to trigger the GPU job after Phase E completes. Options:

| Option                                   | Complexity | Notes                                                                 |
| ---------------------------------------- | ---------- | --------------------------------------------------------------------- |
| **Cloud Run Jobs API call from CPU job** | Low        | CPU job calls `jobs.run()` API at the end, passing run_dir as env var |
| **Pub/Sub trigger**                      | Medium     | CPU job publishes message, GPU job subscribes                         |
| **Cloud Workflows**                      | Medium     | Declarative YAML workflow, good visibility                            |
| **Single job, env-var flag**             | Lowest     | Same job image with `--phases=a-e` or `--phases=f-g` flag             |

**Recommended: Single image, phase flag.** The simplest approach is one Docker image with a `--phases` argument:

```bash
# CPU job
python run_pipeline.py --phases a-e --run-dir /tmp/run ...

# GPU job
python run_pipeline.py --phases f-g --run-dir gs://bucket/runs/{run_id}
```

This avoids maintaining two separate Docker images and deployment configs.

### 5. Cost Impact

For a pipeline run that previously took **2 hours on CPU and cost ~$1.00**:

| Component                | CPU-only (current) | With GPU split             |
| ------------------------ | ------------------ | -------------------------- |
| Phase A-E (CPU)          | ~3 min, $0.024     | ~3 min, $0.019 (Tier 1)    |
| Phase F cross-encoder    | ~115 min, $0.93    | ~0.1 min (6s), $0.001      |
| Phase F judge + G        | ~2 min, $0.016     | ~2 min, $0.007             |
| **GPU charge**           | —                  | ~0.6 min (38s), **$0.007** |
| **Infrastructure total** | **$0.97**          | **$0.034**                 |
| OpenAI API               | ~$0.50-0.80        | ~$0.50-0.80 (unchanged)    |

**Infrastructure cost: $0.97 → $0.034 per run (96.5% reduction)**

At 40 runs/month: **$38.80 → $1.36/month infrastructure**

The GPU is billed for ~38 seconds (15s model load + 6s cross-encoder + 14s judge + 3s Phase G) at $0.0001867/sec = $0.007.

### 6. FP16 vs FP32 on GPU

The cross-encoder code in `phase_f_lab.py` currently uses FP32. The `load_cross_encoder_bundle()` function loads the model as-is and moves it to CUDA. For GPU deployment, adding `.half()` (FP16) conversion would:

- Use half the VRAM (1.1 GB vs 2.2 GB)
- Be slightly faster on L4 tensor cores
- Have negligible quality impact for reranking scores

This is a one-line change in `load_cross_encoder_bundle()`:

```python
model.to(device)
if device == "cuda":
    model = model.half()
```

Consider adding this as a `PhaseFOptions` flag (`cross_encoder_fp16: bool = True`) so it can be controlled per-run.

### 7. Migration Path

Recommended order:

1. **Move region** europe-west3 → europe-west1 (immediate 12% cost saving, no code changes)
2. **Add GPU Cloud Run Job** using same image with `--phases f-g` flag
3. **Build CUDA Docker image** (change base image, bake model in)
4. **Add GCS integration** for run data transfer between jobs
5. **Add FP16 flag** to phase_f_lab.py for GPU inference
6. **Update GitHub Actions** to deploy both CPU and GPU jobs
7. **Test end-to-end** with a real pipeline run
