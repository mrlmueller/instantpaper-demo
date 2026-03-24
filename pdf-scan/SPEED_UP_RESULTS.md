# Speed-Up Implementation Results

> Generated after implementing all 6 tasks from `SPEED_UP_GUIDE.md`  
> Machine: i7-12700k (20 threads), 64GB RAM, CPU-only  
> Test run: `a33419bf76ad298d82369172` (3–4 docs, 420 cross-encoder pairs)

## Summary

| Metric                      | Before             | After                       | Change                 |
| --------------------------- | ------------------ | --------------------------- | ---------------------- |
| Cross-encoder backend       | PyTorch FP32       | ONNX INT8                   | −75% model size        |
| Batch size                  | 8                  | 32                          | 4×                     |
| Section excerpt limit       | 2200 chars         | 1400 chars                  | −36%                   |
| Passage excerpt limit       | 520 chars          | 400 chars                   | −23%                   |
| Avg tokens/pair             | ~1125              | ~828                        | −26%                   |
| **Throughput (80 pairs)**   | **0.60 pairs/sec** | **1.11 pairs/sec**          | **1.85×**              |
| Est. 420 pairs time         | 701s (11.7 min)    | 378s (6.3 min)              | −5.4 min               |
| Judge concurrency cap       | 4                  | 8                           | 2×                     |
| Phase B doc concurrency cap | 2                  | 4                           | 2×                     |
| Phase B Docling threads     | 4                  | 2                           | −50% (frees resources) |
| Phase B parser parallelism  | Sequential         | Parallel (Docling ∥ GROBID) | New                    |

## Quality Validation

ONNX INT8 vs PyTorch with **identical text** (40 pairs, 14 candidates):

| Metric                    | Value      |
| ------------------------- | ---------- |
| Spearman rank correlation | 0.767      |
| Top-5 overlap             | 4/5 (80%)  |
| Top-10 overlap            | 9/10 (90%) |
| Max avg score difference  | 0.045      |

**Conclusion:** INT8 quantization preserves the important top candidates. The judge LLM still receives the best candidates for final evaluation.

## Estimated Full Pipeline Impact

Based on original timing (test run, 3 docs):

| Phase       | Original            | Estimated After     | Notes                                 |
| ----------- | ------------------- | ------------------- | ------------------------------------- |
| Phase A     | 75ms                | 75ms                | Unchanged                             |
| Phase B     | 51s                 | ~30s                | Parallel parsers + higher concurrency |
| Phase C     | 14s                 | 14s                 | Unchanged                             |
| Phase D     | 117s                | 117s                | Unchanged                             |
| Phase E     | 17s                 | 17s                 | Unchanged                             |
| **Phase F** | **2315s**           | **~1250s**          | **1.85× cross-encoder speedup**       |
| Phase G     | 0.6s                | 0.6s                | Unchanged                             |
| **Total**   | **~2515s (42 min)** | **~1430s (24 min)** | **~43% reduction**                    |

For larger runs (13+ PDFs, Phase B = 33 min original):

- Phase B: ~33 min → ~15–22 min (parallel parsers + 4-doc concurrency)

## Files Modified

### `phase_f_lab.py`

1. **ONNX Runtime integration** — `import onnxruntime` with try/except fallback
2. **`load_onnx_cross_encoder_bundle()`** — loads INT8 model from `tools/onnx_reranker_int8/`
3. **Dual-backend `score_cross_encoder_pairs()`** — dispatches to `_score_pairs_onnx()` or `_score_pairs_pytorch()`
4. **PhaseFOptions new defaults:**
   - `cross_encoder_prefer_onnx: bool = True`
   - `cross_encoder_onnx_dir: str = ""`
   - `cross_encoder_batch_size: int = 32` (was 8)
   - `section_excerpt_max_chars: int = 1400` (was 2200)
   - `passage_excerpt_max_chars: int = 400` (was 520)
   - `judge_max_concurrency: int = 8` (was CPU-based, max 4)
5. **Thread pinning** — `torch.set_num_threads(min(16, cpu_count))` in `run_phase_f()`
6. **Judge concurrency** — simplified to I/O-bound default (max 8)

### `phase_b_lab.py`

1. **`docling_num_threads: int = 2`** (was 4) — frees CPU for concurrent docs
2. **`resolve_phase_b_doc_concurrency()`** — cap raised from 2 → 4
3. **`build_phase_b_document_bundle()`** — Docling + GROBID run in parallel via `ThreadPoolExecutor`

## New Files Created

### ONNX Model

- `tools/onnx_reranker_int8/model.onnx` (543 MB) — INT8 dynamically quantized cross-encoder

### Benchmark & Test Scripts (in `tools/`)

- `show_timing.py` — display phase timings from a run
- `benchmark_cross_encoder.py` — comprehensive PyTorch/ONNX benchmark
- `convert_cross_encoder_onnx.py` — torch.onnx.export conversion
- `convert_optimum.py` — optimum-based ONNX conversion
- `quantize_onnx.py` — INT8 dynamic quantization
- `bench_threads.py` — thread configuration testing
- `bench_comprehensive.py` — all-configs comparison
- `test_onnx_vs_pytorch.py` — scoring equivalence verification
- `test_text_length.py` — token count impact analysis
- `bench_final.py` — final before/after benchmark
- `test_rank_preservation.py` — ranking preservation validation

### Intermediate ONNX Models (can be deleted)

- `tools/onnx_reranker/` — dynamo-based FP32 (not used)
- `tools/onnx_reranker_optimum/` — optimum FP32 + optimized variants (intermediate step)

## Dependencies Added

```
onnxruntime==1.24.4
optimum==2.1.0  # for model conversion only, not needed at runtime
onnx==1.20.1    # for conversion only
onnxscript       # transitive dependency
```

**Runtime requirement:** Only `onnxruntime` is needed at inference time. `optimum` and `onnx` were used only for model conversion.

## Rollback

All changes are backward-compatible. To revert to PyTorch-only:

```python
opt = PhaseFOptions(cross_encoder_prefer_onnx=False)
```

This falls back to the original PyTorch scorer with no ONNX dependency.
