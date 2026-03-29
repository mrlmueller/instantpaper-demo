# PDF Scan Pipeline — Speed-Up Implementation Guide

> **Goal**: Reduce single-chapter pipeline runtime from **~128 min → ~45-55 min** (57% reduction)
> without changing any pipeline semantics or output quality.
>
> **Scope**: Only files in `pdf-scan/`. No FastAPI changes.
>
> **Baseline** (13 PDFs, 4 vCPU Cloud Run, no GPU):
>
> | Phase     | Current      | Target         | Savings       |
> | --------- | ------------ | -------------- | ------------- |
> | A         | 0.1 s        | 0.1 s          | —             |
> | B         | 33 min       | 15–20 min      | 13–18 min     |
> | C         | 1 min        | 1 min          | —             |
> | D         | 4 min        | 4 min          | —             |
> | E         | 40 s         | 40 s           | —             |
> | **F**     | **90 min**   | **25–35 min**  | **55–65 min** |
> | G         | 0.1 s        | 0.1 s          | —             |
> | **Total** | **~128 min** | **~45–60 min** |               |

---

## Table of Contents

1. [Task 1 — ONNX Runtime for Cross-Encoder (Phase F)](#task-1--onnx-runtime-for-cross-encoder-phase-f)
2. [Task 2 — Phase F Batch Size & Text Length Tuning](#task-2--phase-f-batch-size--text-length-tuning)
3. [Task 3 — Phase F LLM Judge Concurrency](#task-3--phase-f-llm-judge-concurrency)
4. [Task 4 — Phase B Docling Concurrency Raise](#task-4--phase-b-docling-concurrency-raise)
5. [Task 5 — Phase B Internal Parser Parallelism](#task-5--phase-b-internal-parser-parallelism)
6. [Task 6 — Thread Pinning & torch.set_num_threads](#task-6--thread-pinning--torchset_num_threads)
7. [Dependency & Rollout Order](#dependency--rollout-order)
8. [Validation Checklist](#validation-checklist)

---

## Task 1 — ONNX Runtime for Cross-Encoder (Phase F)

**Impact**: HIGH — reduces cross-encoder inference from **~60 min → 15–30 min** (2–4× speedup)

### 1.1 Background

The cross-encoder (`BAAI/bge-reranker-v2-m3`, 568M params) currently runs through
PyTorch on CPU. With `batch_size=8`, `max_length=1536`, and ~540 pairs, this produces
~68 batches taking ~50–60 seconds each.

ONNX Runtime provides 2–4× CPU speedup through:

- Graph-level optimizations (operator fusion, constant folding)
- More efficient memory access patterns
- Parallelized operations tuned for CPU inference

### 1.2 New Dependency

Add to `requirements.txt`:

```
onnxruntime>=1.18.0
```

No need for `onnxruntime-gpu` — we target CPU only.

### 1.3 ONNX Model Conversion Script

Create a new file `pdf-scan/tools/convert_cross_encoder_onnx.py`.

This script will:

1. Load the HuggingFace model (`BAAI/bge-reranker-v2-m3`)
2. Export to ONNX using `torch.onnx.export()`
3. Save the ONNX model alongside the tokenizer in a local directory
4. Verify numerical equivalence with the original model

```python
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
    print(f"ONNX model saved to {out}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="BAAI/bge-reranker-v2-m3")
    parser.add_argument("--output", default="pdf-scan/tools/onnx_reranker")
    parser.add_argument("--opset", type=int, default=17)
    args = parser.parse_args()
    sys.exit(convert(args.model, args.output, args.opset))
```

**Run once** to produce the ONNX model:

```bash
cd pdf-scan
python tools/convert_cross_encoder_onnx.py --output tools/onnx_reranker
```

This creates `pdf-scan/tools/onnx_reranker/model.onnx` + tokenizer files.

### 1.4 Modify `phase_f_lab.py` — Imports

**Current imports** (lines 1–45):

```python
try:
    import torch
except Exception as e:
    torch = None
    PHASE_F_TORCH_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_F_TORCH_IMPORT_ERROR = None

try:
    from transformers import AutoModelForSequenceClassification, AutoTokenizer
except Exception as e:
    AutoModelForSequenceClassification = None
    AutoTokenizer = None
    PHASE_F_TRANSFORMERS_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_F_TRANSFORMERS_IMPORT_ERROR = None
```

**Add after the existing imports** (after line ~45):

```python
try:
    import onnxruntime as ort
except Exception as e:
    ort = None
    PHASE_F_ORT_IMPORT_ERROR = f"{type(e).__name__}: {e}"
else:
    PHASE_F_ORT_IMPORT_ERROR = None
```

### 1.5 Modify `phase_f_lab.py` — Add ONNX Loading Function

**Add a new function right after `load_cross_encoder_bundle()` (after line ~233)**:

```python
@lru_cache(maxsize=4)
def load_onnx_cross_encoder_bundle(model_name: str, onnx_dir: str = ""):
    """Load ONNX cross-encoder session + tokenizer.

    Falls back to PyTorch if ONNX model not found or ort unavailable.
    """
    if ort is None:
        return None  # Caller falls back to PyTorch

    # Resolve ONNX directory
    if onnx_dir:
        onnx_path = Path(onnx_dir) / "model.onnx"
    else:
        # Default: look in tools/onnx_reranker relative to phase_f_lab.py
        phase_f_dir = Path(__file__).resolve().parent
        onnx_path = phase_f_dir / "tools" / "onnx_reranker" / "model.onnx"

    if not onnx_path.exists():
        return None  # Caller falls back to PyTorch

    # Load tokenizer from ONNX directory (saved by conversion script)
    tokenizer_dir = onnx_path.parent
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(tokenizer_dir))
    except Exception:
        # Fall back to loading tokenizer from HuggingFace model name
        if AutoTokenizer is None:
            return None
        tokenizer = AutoTokenizer.from_pretrained(model_name)

    # Configure ONNX Runtime session
    sess_options = ort.SessionOptions()
    sess_options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
    # Let ORT choose thread count based on available CPUs
    sess_options.intra_op_num_threads = 0
    sess_options.inter_op_num_threads = 0

    session = ort.InferenceSession(
        str(onnx_path),
        sess_options,
        providers=["CPUExecutionProvider"],
    )

    tokenizer_limit = getattr(tokenizer, "model_max_length", None)
    return {
        "tokenizer": tokenizer,
        "session": session,
        "device": "onnx_cpu",
        "max_position_embeddings": None,  # Not needed for ONNX
        "tokenizer_model_max_length": tokenizer_limit,
        "architecture": "onnx_cross_encoder",
        "num_labels": 1,
        "backend": "onnx",
    }
```

### 1.6 Modify `phase_f_lab.py` — New `PhaseFOptions` Fields

**Add two new fields to `PhaseFOptions`** (after line ~54, after `cross_encoder_model`):

```python
    cross_encoder_prefer_onnx: bool = True
    cross_encoder_onnx_dir: str = ""
```

**And in `normalized()` method** add:

```python
    cross_encoder_prefer_onnx=bool(self.cross_encoder_prefer_onnx),
    cross_encoder_onnx_dir=str(self.cross_encoder_onnx_dir or "").strip(),
```

### 1.7 Modify `phase_f_lab.py` — Replace `score_cross_encoder_pairs()`

**Current function** (lines 245–290):

```python
def score_cross_encoder_pairs(pairs: List[Dict[str, str]], options: PhaseFOptions) -> Dict[str, Any]:
    bundle = load_cross_encoder_bundle(options.cross_encoder_model)
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    device = bundle["device"]
    batch_size = max(1, int(options.cross_encoder_batch_size))
    max_length = effective_max_length(bundle, int(options.cross_encoder_max_length))
    rows = []
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            enc = tokenizer(
                [str(item.get("query") or "") for item in batch],
                [str(item.get("candidate_text") or "") for item in batch],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = model(**enc).logits
            probs = row_sigmoid(logits)
            raw_logits = logits.detach().cpu().reshape(len(batch), -1).tolist()
            for idx, item in enumerate(batch):
                rows.append(
                    {
                        **item,
                        "raw_logit": float(raw_logits[idx][-1] if raw_logits[idx] else 0.0),
                        "score_prob": round(float(probs[idx]), 8),
                    }
                )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "rows": rows,
        "runtime": { ... },
    }
```

**Replace with a dual-backend version** that tries ONNX first, falls back to PyTorch:

```python
def score_cross_encoder_pairs(pairs: List[Dict[str, str]], options: PhaseFOptions) -> Dict[str, Any]:
    # Try ONNX backend first
    onnx_bundle = None
    if bool(options.cross_encoder_prefer_onnx):
        onnx_bundle = load_onnx_cross_encoder_bundle(
            options.cross_encoder_model,
            options.cross_encoder_onnx_dir,
        )

    if onnx_bundle is not None:
        return _score_pairs_onnx(pairs, options, onnx_bundle)
    return _score_pairs_pytorch(pairs, options)


def _score_pairs_onnx(pairs: List[Dict[str, str]], options: PhaseFOptions, bundle: Dict[str, Any]) -> Dict[str, Any]:
    tokenizer = bundle["tokenizer"]
    session = bundle["session"]
    batch_size = max(1, int(options.cross_encoder_batch_size))
    max_length = int(options.cross_encoder_max_length)
    tokenizer_limit = bundle.get("tokenizer_model_max_length")
    if tokenizer_limit and int(tokenizer_limit) > 0:
        max_length = min(max_length, int(tokenizer_limit))
    rows = []
    started = time.perf_counter()

    for start in range(0, len(pairs), batch_size):
        batch = pairs[start : start + batch_size]
        enc = tokenizer(
            [str(item.get("query") or "") for item in batch],
            [str(item.get("candidate_text") or "") for item in batch],
            padding=True,
            truncation=True,
            max_length=max_length,
            return_tensors="np",  # Return numpy directly for ONNX
        )
        logits = session.run(
            None,
            {
                "input_ids": enc["input_ids"],
                "attention_mask": enc["attention_mask"],
            },
        )[0]  # shape: (batch_size, num_labels)

        # Sigmoid conversion (numpy)
        import numpy as _np
        probs = 1.0 / (1.0 + _np.exp(-logits.astype(_np.float64)))

        for idx, item in enumerate(batch):
            raw = logits[idx]
            rows.append(
                {
                    **item,
                    "raw_logit": float(raw[-1] if len(raw) else 0.0),
                    "score_prob": round(float(probs[idx][-1] if len(probs[idx]) else 0.0), 8),
                }
            )

    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "rows": rows,
        "runtime": {
            "pair_count": len(pairs),
            "elapsed_ms": elapsed_ms,
            "batch_size": batch_size,
            "max_length": max_length,
            "device": "onnx_cpu",
            "architecture": "onnx_cross_encoder",
            "num_labels": 1,
            "max_position_embeddings": None,
            "backend": "onnx",
        },
    }


def _score_pairs_pytorch(pairs: List[Dict[str, str]], options: PhaseFOptions) -> Dict[str, Any]:
    """Original PyTorch scoring path — used as fallback when ONNX unavailable."""
    bundle = load_cross_encoder_bundle(options.cross_encoder_model)
    tokenizer = bundle["tokenizer"]
    model = bundle["model"]
    device = bundle["device"]
    batch_size = max(1, int(options.cross_encoder_batch_size))
    max_length = effective_max_length(bundle, int(options.cross_encoder_max_length))
    rows = []
    started = time.perf_counter()
    with torch.inference_mode():
        for start in range(0, len(pairs), batch_size):
            batch = pairs[start : start + batch_size]
            enc = tokenizer(
                [str(item.get("query") or "") for item in batch],
                [str(item.get("candidate_text") or "") for item in batch],
                padding=True,
                truncation=True,
                max_length=max_length,
                return_tensors="pt",
            )
            enc = {k: v.to(device) for k, v in enc.items()}
            logits = model(**enc).logits
            probs = row_sigmoid(logits)
            raw_logits = logits.detach().cpu().reshape(len(batch), -1).tolist()
            for idx, item in enumerate(batch):
                rows.append(
                    {
                        **item,
                        "raw_logit": float(raw_logits[idx][-1] if raw_logits[idx] else 0.0),
                        "score_prob": round(float(probs[idx]), 8),
                    }
                )
    elapsed_ms = round((time.perf_counter() - started) * 1000.0, 3)
    return {
        "rows": rows,
        "runtime": {
            "pair_count": len(pairs),
            "elapsed_ms": elapsed_ms,
            "batch_size": batch_size,
            "max_length": max_length,
            "device": device,
            "architecture": bundle.get("architecture"),
            "num_labels": bundle.get("num_labels"),
            "max_position_embeddings": bundle.get("max_position_embeddings"),
            "backend": "pytorch",
        },
    }
```

### 1.8 Verification Strategy

1. Run the pipeline **without** ONNX model present → must fall back to PyTorch silently
2. Run the conversion script → produces `tools/onnx_reranker/model.onnx`
3. Run the pipeline **with** ONNX model → should use ONNX, check `runtime.backend == "onnx"` in `phase_f_runtime.json`
4. Compare output scores between ONNX and PyTorch runs — max diff < 0.001
5. Compare wall-clock time in `phase_f_runtime.json`

### 1.9 Expected Impact

| Metric            | Before      | After            |
| ----------------- | ----------- | ---------------- |
| Backend           | PyTorch CPU | ONNX Runtime CPU |
| Pair scoring time | ~60 min     | ~15–30 min       |
| Memory usage      | ~2.5 GB     | ~1.5 GB          |

---

## Task 2 — Phase F Batch Size & Text Length Tuning

**Impact**: MEDIUM — additional 20–40% speedup on top of ONNX, plus reduced tokenization overhead

### 2.1 Background

Current defaults in `PhaseFOptions` (lines 48–107):

```python
cross_encoder_batch_size: int = 8
cross_encoder_max_length: int = 1536
section_excerpt_max_chars: int = 2200
supporting_passage_count: int = 3
passage_excerpt_max_chars: int = 520
```

With `section_excerpt_max_chars=2200` + 3 passages × 520 chars + metadata, each candidate
text is ~3,760 chars. After tokenization this often reaches ~1,200–1,400 tokens, close to
the `max_length=1536` limit.

### 2.2 Changes to `PhaseFOptions` Defaults

**File**: `phase_f_lab.py`, lines 48–107

Change these default values:

| Field                       | Old  | New  | Rationale                                                                      |
| --------------------------- | ---- | ---- | ------------------------------------------------------------------------------ |
| `cross_encoder_batch_size`  | 8    | 32   | Larger batches = fewer tokenization passes, better ONNX throughput             |
| `section_excerpt_max_chars` | 2200 | 1400 | Reduces token count per pair; cross-encoder captures gist in first ~1400 chars |
| `passage_excerpt_max_chars` | 520  | 400  | Slightly tighter; passages are already contextualized                          |

**Updated lines (in `PhaseFOptions.__init__`)**:

```python
    cross_encoder_batch_size: int = 32     # was 8
    section_excerpt_max_chars: int = 1400  # was 2200
    passage_excerpt_max_chars: int = 400   # was 520
```

### 2.3 Update Production Config in `run_pdf_scan_pipeline.py`

The production orchestrator (`fastapi/run_pdf_scan_pipeline.py`, around line ~300) creates
`PhaseFOptions` with explicit values. When we later update that file, ensure:

```python
phase_f_options = PhaseFOptions(
    ...
    cross_encoder_batch_size=32,     # was 8
    section_excerpt_max_chars=1400,  # was 2200
    passage_excerpt_max_chars=400,   # was 520
    ...
)
```

> **Note**: We are NOT modifying `run_pdf_scan_pipeline.py` yet (it's in `fastapi/`).
> This is a reminder for when the fast API integration happens.

### 2.4 Impact Analysis

**Old**: `3760 chars → ~1300 tokens → max_length=1536`
**New**: `2400 chars → ~850 tokens → max_length=1536` (but effective length much shorter)

- Shorter sequences → less quadratic attention cost → ~30% faster per batch
- Larger batch size → fewer Python loop iterations → ~10% amortized overhead savings
- Combined with ONNX: multiplicative benefit

### 2.5 Risk: Quality Degradation

The section excerpt reduction (2200→1400) removes ~800 chars of trailing text from long
sections. Cross-encoders are attention-based and weight earlier tokens more heavily, so the
relevance signal is concentrated in the first ~1000 chars.

**Validation**: Compare Phase G output (`useful_pdfs`, `section_scores`) between old and
new defaults on a benchmark run. Acceptable if:

- Same set of "useful" PDFs (no false negatives)
- Section score rank correlation ≥ 0.95

---

## Task 3 — Phase F LLM Judge Concurrency

**Impact**: MEDIUM — reduces LLM judge time from **~25 min → 8–12 min**

### 3.1 Background

The LLM judge sends 18–24 individual OpenAI API calls (one per candidate). Currently
limited to max **4 concurrent workers** by `resolve_phase_f_judge_concurrency()`:

```python
# phase_f_lab.py, lines 689-700
def resolve_phase_f_judge_concurrency(*, candidate_count: int) -> int:
    if int(candidate_count) <= 1:
        return 1
    cpu_count = available_cpu_count()
    if cpu_count <= 2:
        auto = 1
    elif cpu_count <= 4:
        auto = 2
    elif cpu_count <= 8:
        auto = 3
    else:
        auto = 4
    return max(1, min(int(candidate_count), auto))
```

This function caps concurrency based on CPU count, but the LLM judge is **purely I/O-bound**
(HTTP calls to OpenAI API). CPU utilization during judge calls is near zero.

### 3.2 Replace `resolve_phase_f_judge_concurrency()`

**Replace the function at lines 689–700 with**:

```python
def resolve_phase_f_judge_concurrency(*, candidate_count: int) -> int:
    """Resolve concurrency for LLM judge calls.

    The judge is I/O-bound (HTTP API calls), not CPU-bound.
    CPU-based heuristics are inappropriate here.
    """
    if int(candidate_count) <= 1:
        return 1
    # I/O-bound: use 8 concurrent workers (OpenAI rate limits are the real cap)
    return max(1, min(int(candidate_count), 8))
```

### 3.3 Optionally Add `PhaseFOptions` Control

To make this configurable without code changes, add a new field:

```python
    judge_max_concurrency: int = 8
```

And update `resolve_phase_f_judge_concurrency` to accept it:

```python
def resolve_phase_f_judge_concurrency(*, candidate_count: int, max_concurrency: int = 8) -> int:
    if int(candidate_count) <= 1:
        return 1
    return max(1, min(int(candidate_count), int(max_concurrency)))
```

Then update the call site in `run_phase_f()` (~line 1020):

```python
resolved_judge_concurrency = resolve_phase_f_judge_concurrency(
    candidate_count=len(judge_candidates),
    max_concurrency=opt.judge_max_concurrency,
)
```

### 3.4 Impact Analysis

| Metric                       | Before                        | After                           |
| ---------------------------- | ----------------------------- | ------------------------------- |
| Max workers                  | 4                             | 8                               |
| ~24 judge calls at ~70s each | 6 rounds × 70s = 420s (7 min) | 3 rounds × 70s = 210s (3.5 min) |
| Typical range                | 15–25 min                     | 5–12 min                        |

### 3.5 Risk: Rate Limiting

OpenAI rate limits for `gpt-5-mini` are typically 500+ RPM. With 8 concurrent workers
and 24 calls, we produce ~8 simultaneous requests — well within limits.

If rate limiting is hit, the existing retry logic in `call_openai_llm_judge()` handles it.

---

## Task 4 — Phase B Docling Concurrency Raise

**Impact**: HIGH — reduces Phase B from **33 min → 15–22 min**

### 4.1 Background

Current concurrency is hardcapped at 2 (line 1517):

```python
# phase_b_lab.py, lines 1505-1518
def resolve_phase_b_doc_concurrency(options: PhaseBOptions, *, capabilities: Dict[str, Any], doc_count: int) -> int:
    if int(doc_count) <= 1:
        return 1
    if options.max_concurrent_docs is not None:
        return max(1, min(int(doc_count), int(options.max_concurrent_docs)))
    cpu_count = available_cpu_count()
    if bool(options.try_docling) and bool(capabilities.get("docling_available")):
        per_doc_threads = max(1, int(options.docling_num_threads), int(options.docling_chunk_num_threads))
        auto = max(1, cpu_count // per_doc_threads)
        return max(1, min(int(doc_count), min(auto, 2)))  # ← HARD CAP AT 2
    return max(1, min(int(doc_count), min(cpu_count, 6)))
```

The concern is "Docling becomes unstable when too many PDFs are parsed in parallel."
We address this by reducing per-doc threads and raising the cap conservatively.

### 4.2 Two-Part Strategy

**Part A**: Reduce `docling_num_threads` from 4 → 2 per converter instance.
This frees CPU budget for more concurrent documents.

**Part B**: Raise the hard cap from 2 → 4.

### 4.3 Modify `PhaseBOptions` Default

**File**: `phase_b_lab.py`, line 120

Change:

```python
    docling_num_threads: int = 4
```

To:

```python
    docling_num_threads: int = 2
```

### 4.4 Modify `resolve_phase_b_doc_concurrency()`

**Replace lines 1505–1518 with**:

```python
def resolve_phase_b_doc_concurrency(options: PhaseBOptions, *, capabilities: Dict[str, Any], doc_count: int) -> int:
    if int(doc_count) <= 1:
        return 1
    if options.max_concurrent_docs is not None:
        return max(1, min(int(doc_count), int(options.max_concurrent_docs)))

    cpu_count = available_cpu_count()
    if bool(options.try_docling) and bool(capabilities.get("docling_available")):
        per_doc_threads = max(1, int(options.docling_num_threads), int(options.docling_chunk_num_threads))
        auto = max(1, cpu_count // per_doc_threads)
        # Docling stability improves with lower per-doc threads.
        # With docling_num_threads=2, allow up to 4 concurrent docs.
        return max(1, min(int(doc_count), min(auto, 4)))
    return max(1, min(int(doc_count), min(cpu_count, 6)))
```

### 4.5 Impact Math

**Old**: `docling_num_threads=4`, max 2 concurrent, 13 docs → 7 batches × 5 min = 33 min
**New**: `docling_num_threads=2`, max 4 concurrent, 13 docs → 4 batches × 5 min = 20 min

On Cloud Run (4 vCPU): `auto = 4 // 2 = 2`, capped at `min(2, 4) = 2` — same as before.

On a machine with 8+ vCPU (e.g. local i7-12700k with 20 threads): `auto = 20 // 2 = 10`, capped at `min(10, 4) = 4` — 4 concurrent.

**Important**: On 4 vCPU Cloud Run, this change alone doesn't help much because `auto=2`.
The benefit comes primarily on local machines or larger Cloud Run instances. To also help
on 4 vCPU, combine with Task 5 (internal parallelism).

### 4.6 Risk: Docling Stability

The original cap at 2 was conservative. With `docling_num_threads=2`:

- Each instance uses 2 threads instead of 4
- Total thread usage: 4 instances × 2 threads = 8 threads (vs old 2 × 4 = 8)
- Same total thread pressure, better throughput

Monitor for: segfaults, memory spikes, or corrupted results.

**Fallback**: If instability is observed, the user can always set
`max_concurrent_docs=2` explicitly to override auto-detection.

---

## Task 5 — Phase B Internal Parser Parallelism

**Impact**: HIGH — reduces per-document parse time by **30–50%**

### 5.1 Background

Within `build_phase_b_document_bundle()` (lines 1530–1566), the 4 parsers run
**sequentially**:

```python
t0 = time.perf_counter()
fitz_bundle = extract_fitz_bundle(source_path, ...)          # ~2 sec
pypdf_bundle = extract_pypdf_bundle(source_path)             # ~1 sec
# ... extract page_count from fitz/pypdf ...
docling_bundle = extract_docling_bundle(source_path, page_count, options)  # ~3-5 min
grobid_bundle = extract_grobid_bundle(source_path, manifest_row, page_count, options, capabilities)  # ~10-120 sec
```

**Critical dependency analysis**:

- `fitz` + `pypdf` → extract `page_count` (takes ~3 sec combined)
- `docling` receives: `source_path`, `page_count`, `options` — does NOT consume fitz/pypdf results
- `grobid` receives: `source_path`, `manifest_row`, `page_count`, `options`, `capabilities` — does NOT consume docling results

Therefore: **Docling and GROBID are completely independent** and can run in parallel.

### 5.2 Modify `build_phase_b_document_bundle()`

**Replace the sequential parser calls** (lines ~1541–1563) **with**:

```python
    t0 = time.perf_counter()

    # Step 1: Fast parsers (sequential, ~3 sec combined)
    fitz_bundle = extract_fitz_bundle(source_path, min_page_words=options.min_page_words)
    pypdf_bundle = extract_pypdf_bundle(source_path)
    page_count = fitz_bundle.get("page_count") or pypdf_bundle.get("page_count") or manifest_row.get("page_count")

    # ... existing page analysis code (lines 1545-1559) stays exactly the same ...

    # Step 2: Heavy parsers (parallel — independent of each other)
    docling_bundle = {}
    grobid_bundle = {}

    def _run_docling():
        return extract_docling_bundle(source_path, page_count, options)

    def _run_grobid():
        return extract_grobid_bundle(source_path, manifest_row, page_count, options, capabilities)

    with ThreadPoolExecutor(max_workers=2) as inner_executor:
        docling_future = inner_executor.submit(_run_docling)
        grobid_future = inner_executor.submit(_run_grobid)
        docling_bundle = docling_future.result()
        grobid_bundle = grobid_future.result()

    docling_success = str(docling_bundle.get("status") or "") == "success"
    fallback_activated = bool(readable_without_ocr and not docling_success and str(fitz_bundle.get("status") or "") == "ok")
    bundle_status = "ok" if readable_without_ocr and str(fitz_bundle.get("status") or "") == "ok" else "needs_attention"
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
```

### 5.3 Impact Analysis

**Before**: fitz(2s) + pypdf(1s) + docling(300s) + grobid(60s) = **363s per doc**
**After**: fitz(2s) + pypdf(1s) + max(docling(300s), grobid(60s)) = **303s per doc** (17% faster)

For documents where GROBID takes longer (120s), savings increase. The benefit scales with
the ratio of GROBID time to Docling time.

### 5.4 ThreadPoolExecutor Nesting

Note: this creates a **nested** ThreadPoolExecutor (inner 2-thread pool inside the outer
doc-level pool). This is safe in Python because:

- The inner pool uses only 2 threads
- There's no deadlock risk (inner futures don't depend on outer futures)
- `ThreadPoolExecutor` doesn't have a global lock

### 5.5 Edge Cases

- If `try_docling=False`: docling returns immediately with `status="disabled"`, grobid runs alone
- If `try_grobid=False`: grobid returns immediately with `status="not_attempted"`, docling runs alone
- If both disabled: both return immediately, no wasted threads

---

## Task 6 — Thread Pinning & torch.set_num_threads

**Impact**: LOW-MEDIUM — prevents CPU contention between cross-encoder and other operations

### 6.1 Background

Currently there are **NO explicit `torch.set_num_threads()` calls** in the pipeline.
PyTorch defaults to using all available CPU cores for intra-op parallelism.

On a 4-vCPU Cloud Run instance, this means the cross-encoder forward pass tries to use
all 4 cores. If the LLM judge threads are also running (after Task 3 raises concurrency),
there could be contention.

### 6.2 Add Thread Control to `load_cross_encoder_bundle()`

**In `load_cross_encoder_bundle()` (line ~210), add before `model.eval()`**:

```python
    # Pin PyTorch thread count to avoid contention with LLM judge threads
    if torch is not None:
        cpu_count = os.cpu_count() or 4
        # Reserve 2 threads for I/O (judge calls, etc.)
        torch_threads = max(1, cpu_count - 2)
        torch.set_num_threads(torch_threads)
```

### 6.3 Risk

`torch.set_num_threads()` is process-global. This is fine because:

- The cross-encoder is the only torch workload in the pipeline
- It runs sequentially (not in a thread pool)
- No other phase uses torch

### 6.4 For ONNX Runtime

ONNX Runtime thread control is handled in `load_onnx_cross_encoder_bundle()` via
`sess_options.intra_op_num_threads` (already set in Task 1).

---

## Dependency & Rollout Order

```
Task 1 (ONNX) ──→ Task 2 (batch/text tuning) ──→ Task 6 (thread pinning)
                                                        ↑
Task 3 (judge concurrency) ────────────────────────────┘

Task 4 (docling concurrency) ──→ Task 5 (internal parallelism)
```

**Recommended implementation order**:

1. **Task 4 + Task 5** (Phase B) — Independent of Phase F changes, easiest to test
2. **Task 3** (Judge concurrency) — Tiny change, immediate benefit
3. **Task 1** (ONNX) — Biggest single change, needs conversion script
4. **Task 2** (Batch/text tuning) — Tune after ONNX is working
5. **Task 6** (Thread pinning) — Final polish

### After Each Task, Validate:

1. Run the pipeline on a known test set (e.g., the 13-PDF benchmark)
2. Compare `output.json` results (useful PDFs, scores) vs baseline
3. Check `*_runtime.json` for timing improvements
4. Verify no errors in `run.log`

---

## Validation Checklist

### Phase B Changes (Tasks 4 + 5)

- [ ] Run pipeline with `docling_num_threads=2`, verify Docling still produces correct output
- [ ] Run with `max_concurrent_docs=4` on local machine (8+ cores), verify speedup
- [ ] Run on 4-vCPU Cloud Run, verify no regression (auto resolves to 2)
- [ ] Verify GROBID and Docling results are identical to baseline (JSON diff)
- [ ] Check memory usage doesn't exceed 16 GB with 4 concurrent docs

### Phase F Changes (Tasks 1 + 2 + 3 + 6)

- [ ] Run ONNX conversion script, verify `model.onnx` produced
- [ ] Run pipeline with ONNX: verify `runtime.backend == "onnx"` in `phase_f_runtime.json`
- [ ] Run pipeline without ONNX model file: verify silent fallback to PyTorch
- [ ] Compare cross-encoder scores: ONNX vs PyTorch max diff < 0.001
- [ ] Verify `batch_size=32` doesn't cause OOM (watch memory)
- [ ] Verify `section_excerpt_max_chars=1400` doesn't degrade ranking quality
- [ ] Verify LLM judge runs with 8 concurrent workers without rate limit errors
- [ ] Run full benchmark: confirm total time < 60 min

### End-to-End

- [ ] Compare `output.json` between old and new pipeline (same set of useful PDFs)
- [ ] Section score Spearman rank correlation ≥ 0.95
- [ ] No new warnings or errors in `run.log`
- [ ] API cost unchanged (no extra API calls)

---

## Appendix: File-Level Change Summary

| File                                  | Tasks      | Changes                                                                                                  |
| ------------------------------------- | ---------- | -------------------------------------------------------------------------------------------------------- |
| `phase_f_lab.py`                      | 1, 2, 3, 6 | ONNX import, ONNX loader, dual-backend scorer, PhaseFOptions defaults, judge concurrency, thread pinning |
| `phase_b_lab.py`                      | 4, 5       | docling_num_threads default, concurrency cap, internal parallelism                                       |
| `tools/convert_cross_encoder_onnx.py` | 1          | New file: ONNX conversion script                                                                         |
| `requirements.txt` (or equivalent)    | 1          | Add `onnxruntime>=1.18.0`                                                                                |

**No other files modified.** All changes are backward-compatible (ONNX is optional, falls
back to PyTorch; old `max_concurrent_docs` override still works).
