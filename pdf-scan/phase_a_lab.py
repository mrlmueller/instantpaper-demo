#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import platform
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

try:
    import pydantic
except Exception:
    pydantic = None

try:
    import pydantic_settings
except Exception:
    pydantic_settings = None


if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def print_section(title: str, width: int = 88, char: str = "=") -> None:
    line = char * width
    print(line)
    print(title)
    print(line)


def print_kv(d: Dict[str, Any], key_width: int = 28) -> None:
    for k, v in d.items():
        print(f"{str(k):<{key_width}} {v}")


def print_table(rows: List[Dict[str, Any]], *, columns: List[str], max_rows: int = 50, max_col_width: int = 80) -> None:
    rows = list(rows or [])
    if not rows:
        print("<empty>")
        return

    show = rows[: int(max_rows)]

    def cell(row: Dict[str, Any], col: str) -> str:
        value = row.get(col, "")
        if value is None:
            value = ""
        text = str(value).replace("\r", " ").replace("\n", " ")
        return text if len(text) <= max_col_width else (text[: max_col_width - 3] + "...")

    widths: Dict[str, int] = {}
    for col in columns:
        widths[col] = min(max(len(col), max(len(cell(row, col)) for row in show)), max_col_width)

    header = " | ".join(f"{col:<{widths[col]}}" for col in columns)
    sep = "-+-".join("-" * widths[col] for col in columns)
    print(header)
    print(sep)
    for row in show:
        print(" | ".join(f"{cell(row, col):<{widths[col]}}" for col in columns))
    if len(rows) > len(show):
        print(f"... (+{len(rows) - len(show)} more rows)")


def qc_row(check: str, status: str, value: Any, expected: str, why: str, fix: str) -> Dict[str, Any]:
    return {
        "check": str(check),
        "status": str(status),
        "value": str(value),
        "expected": str(expected),
        "why": str(why),
        "fix": str(fix),
    }


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def stable_hash(*parts: str, length: int = 24) -> str:
    payload = "\n".join([(part or "").strip().replace("\r\n", "\n") for part in parts])
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[: int(length)]


def sha256_text(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _json_default(obj: Any) -> Any:
    if isinstance(obj, Path):
        return str(obj)
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def write_json(path: Path, payload: Any, retries: int = 6, sleep_sec: float = 0.25) -> None:
    ensure_dir(path.parent)
    content = json.dumps(payload, ensure_ascii=False, indent=2, default=_json_default) + "\n"
    last_error: Optional[Exception] = None
    for attempt in range(max(1, int(retries))):
        tmp = path.with_suffix(path.suffix + f".{attempt}.tmp")
        try:
            tmp.write_text(content, encoding="utf-8")
            tmp.replace(path)
            return
        except PermissionError as exc:
            last_error = exc
            time.sleep(float(sleep_sec) * float(attempt + 1))
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except Exception:
                pass
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to write JSON: {path}")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def append_jsonl(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, default=_json_default) + "\n")


def _find_repo_root_and_pdf_scan_dir() -> tuple[Path, Path]:
    cwd = Path.cwd().resolve()
    candidates = [cwd, cwd.parent]
    for base in candidates:
        pdf_scan_dir = base / "pdf-scan"
        if pdf_scan_dir.exists() and pdf_scan_dir.is_dir():
            return base, pdf_scan_dir
        if base.name == "pdf-scan":
            return base.parent, base
    raise RuntimeError("Could not resolve repo root / pdf-scan directory from current working directory.")


REPO_ROOT, PDF_SCAN_DIR = _find_repo_root_and_pdf_scan_dir()
load_dotenv(REPO_ROOT / ".env", override=False)
load_dotenv(PDF_SCAN_DIR / ".env", override=False)


def resolve_path(raw: str, *, expect_dir: bool) -> Path:
    path = Path(raw).expanduser()
    candidates = [path]
    if not path.is_absolute():
        candidates.extend([PDF_SCAN_DIR / path, REPO_ROOT / path, Path.cwd().resolve() / path])
    seen: List[Path] = []
    for candidate in candidates:
        candidate = candidate.resolve()
        if candidate in seen:
            continue
        seen.append(candidate)
        if candidate.exists() and ((candidate.is_dir() and expect_dir) or (candidate.is_file() and not expect_dir)):
            return candidate
    return candidates[0].resolve()


def resolve_output_dir(raw: str) -> Path:
    path = Path(raw).expanduser()
    if path.is_absolute():
        return path.resolve()
    return (Path.cwd().resolve() / path).resolve()


class PdfSource(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str
    path: Path

    @field_validator("label", mode="before")
    @classmethod
    def _normalize_label(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("PDF label must not be empty.")
        return text

    @field_validator("path", mode="before")
    @classmethod
    def _normalize_path(cls, value: Any) -> Path:
        text = str(value or "").strip()
        if not text:
            raise ValueError("PDF path must not be empty.")
        return resolve_path(text, expect_dir=False)


class PhaseAConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pipeline_version: str
    input_mode: Literal["small_gold", "manual"]
    chapter_title: str
    chapter_spec_text: str
    runs_root: Path
    openai_api_key_present: bool
    force_rebuild_phase_a: bool
    pdf_sources: List[PdfSource]
    pdf_dir_raw: str = ""
    pdf_glob: str = "*.pdf"
    pdf_recursive: bool = False
    max_pdfs: int = 20
    benchmark_suite_manifest: str = ""
    benchmark_suite_id: str = ""
    benchmark_chapter_id: str = ""
    resolved_source_count: int = 0
    source_discovery_total_count: int = 0
    chapter_spec_sha256: str = ""

    @field_validator("pipeline_version", "chapter_title", "chapter_spec_text", mode="before")
    @classmethod
    def _normalize_non_empty(cls, value: Any) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("Required string field must not be empty.")
        return text

    @field_validator("max_pdfs")
    @classmethod
    def _validate_max_pdfs(cls, value: int) -> int:
        if int(value) < 1:
            raise ValueError("max_pdfs must be >= 1.")
        return int(value)

    @model_validator(mode="after")
    def _validate_pdf_sources(self) -> "PhaseAConfig":
        if not self.pdf_sources:
            raise ValueError("Phase A requires at least one resolved PDF source.")
        self.resolved_source_count = len(self.pdf_sources)
        self.chapter_spec_sha256 = sha256_text(self.chapter_spec_text)
        return self

    def to_snapshot(self) -> Dict[str, Any]:
        return {
            "pipeline_version": self.pipeline_version,
            "input_mode": self.input_mode,
            "chapter_title": self.chapter_title,
            "chapter_spec_text": self.chapter_spec_text,
            "chapter_spec_text_chars": len(self.chapter_spec_text),
            "chapter_spec_text_words": len(self.chapter_spec_text.split()),
            "chapter_spec_sha256": self.chapter_spec_sha256,
            "runs_root": str(self.runs_root),
            "openai_api_key_present": self.openai_api_key_present,
            "force_rebuild_phase_a": self.force_rebuild_phase_a,
            "pdf_sources": [{"label": item.label, "path": str(item.path)} for item in self.pdf_sources],
            "pdf_dir_raw": self.pdf_dir_raw,
            "pdf_glob": self.pdf_glob,
            "pdf_recursive": self.pdf_recursive,
            "max_pdfs": self.max_pdfs,
            "benchmark_suite_manifest": self.benchmark_suite_manifest,
            "benchmark_suite_id": self.benchmark_suite_id,
            "benchmark_chapter_id": self.benchmark_chapter_id,
            "resolved_source_count": self.resolved_source_count,
            "source_discovery_total_count": self.source_discovery_total_count,
        }


class RunArtifacts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    config_json: Path
    pdf_manifest_json: Path
    query_plan_json: Path
    parser_dir: Path
    normalized_dir: Path
    retrieval_dir: Path
    rerank_dir: Path
    final_dir: Path
    logs_jsonl: Path
    run_log: Path
    metrics_json: Path
    api_calls_jsonl: Path
    phase_a_dir: Path
    phase_a_config_json: Path
    phase_a_runtime_json: Path
    phase_a_summary_json: Path
    phase_a_assessment_json: Path
    phase_a_review_dir: Path

    @classmethod
    def from_run_dir(cls, run_dir: Path) -> "RunArtifacts":
        phase_a_dir = run_dir / "phase_a"
        return cls(
            config_json=run_dir / "config.json",
            pdf_manifest_json=run_dir / "pdf_manifest.json",
            query_plan_json=run_dir / "query_plan.json",
            parser_dir=run_dir / "parser",
            normalized_dir=run_dir / "normalized",
            retrieval_dir=run_dir / "retrieval",
            rerank_dir=run_dir / "rerank",
            final_dir=run_dir / "final",
            logs_jsonl=run_dir / "logs.jsonl",
            run_log=run_dir / "run.log",
            metrics_json=run_dir / "metrics.json",
            api_calls_jsonl=run_dir / "api_calls.jsonl",
            phase_a_dir=phase_a_dir,
            phase_a_config_json=phase_a_dir / "phase_a_config.json",
            phase_a_runtime_json=phase_a_dir / "phase_a_runtime.json",
            phase_a_summary_json=phase_a_dir / "phase_a_summary.json",
            phase_a_assessment_json=phase_a_dir / "phase_a_assessment.json",
            phase_a_review_dir=run_dir / "phase_a_review",
        )


class RunContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    repo_root: Path
    pdf_scan_dir: Path
    run_id: str
    run_dir: Path
    artifacts: RunArtifacts

    def create_artifact_skeleton(self, overwrite: bool = False) -> None:
        ensure_dir(self.run_dir)
        ensure_dir(self.artifacts.parser_dir)
        ensure_dir(self.artifacts.normalized_dir)
        ensure_dir(self.artifacts.retrieval_dir)
        ensure_dir(self.artifacts.rerank_dir)
        ensure_dir(self.artifacts.final_dir)
        ensure_dir(self.artifacts.phase_a_dir)
        ensure_dir(self.artifacts.phase_a_review_dir)

        placeholders: Dict[Path, Any] = {
            self.artifacts.query_plan_json: {"status": "not_run", "phase": "query_planner"},
            self.artifacts.metrics_json: {
                "run_id": self.run_id,
                "stages": {},
                "api_usage_summary": {
                    "call_count": 0,
                    "input_tokens": 0,
                    "cached_input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                },
            },
            self.artifacts.final_dir / "output.json": {"status": "not_run"},
        }
        for path, payload in placeholders.items():
            if overwrite or (not path.exists()):
                write_json(path, payload)

        for path in [self.artifacts.logs_jsonl, self.artifacts.run_log, self.artifacts.api_calls_jsonl]:
            if overwrite or (not path.exists()):
                ensure_dir(path.parent)
                path.write_text("", encoding="utf-8")

        for path in [
            self.artifacts.normalized_dir / "documents.jsonl",
            self.artifacts.normalized_dir / "sections.jsonl",
            self.artifacts.normalized_dir / "passages.jsonl",
            self.artifacts.retrieval_dir / "fused_candidates.jsonl",
            self.artifacts.rerank_dir / "cross_encoder.jsonl",
        ]:
            if overwrite or (not path.exists()):
                ensure_dir(path.parent)
                path.write_text("", encoding="utf-8")


def load_metrics(run_ctx: RunContext) -> Dict[str, Any]:
    if run_ctx.artifacts.metrics_json.exists():
        try:
            return read_json(run_ctx.artifacts.metrics_json)
        except Exception:
            pass
    return {
        "run_id": run_ctx.run_id,
        "stages": {},
        "api_usage_summary": {
            "call_count": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        },
    }


def save_metrics(run_ctx: RunContext, metrics: Dict[str, Any]) -> None:
    write_json(run_ctx.artifacts.metrics_json, metrics)


def setup_run_logger(run_ctx: RunContext) -> logging.Logger:
    logger_name = f"pdf_scan_phase_a.{run_ctx.run_id}"
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.handlers = []
    logger.propagate = False

    file_handler = logging.FileHandler(run_ctx.artifacts.run_log, encoding="utf-8")
    file_handler.setLevel(logging.INFO)
    file_handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
    logger.addHandler(file_handler)
    return logger


def log_event(run_ctx: RunContext, *, stage: str, event: str, **payload: Any) -> None:
    append_jsonl(
        run_ctx.artifacts.logs_jsonl,
        {
            "ts_utc": utc_now_iso(),
            "stage": stage,
            "event": event,
            **payload,
        },
    )


def record_api_call(
    run_ctx: RunContext,
    *,
    stage: str,
    provider: str,
    model: str,
    input_tokens: int = 0,
    cached_input_tokens: int = 0,
    output_tokens: int = 0,
    cost_usd: float = 0.0,
    meta: Optional[Dict[str, Any]] = None,
) -> None:
    entry = {
        "ts_utc": utc_now_iso(),
        "stage": stage,
        "provider": provider,
        "model": model,
        "input_tokens": int(input_tokens),
        "cached_input_tokens": int(cached_input_tokens),
        "output_tokens": int(output_tokens),
        "total_tokens": int(input_tokens) + int(output_tokens),
        "cost_usd": round(float(cost_usd), 10),
        "meta": dict(meta or {}),
    }
    append_jsonl(run_ctx.artifacts.api_calls_jsonl, entry)
    metrics = load_metrics(run_ctx)
    usage = metrics.setdefault(
        "api_usage_summary",
        {
            "call_count": 0,
            "input_tokens": 0,
            "cached_input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "cost_usd": 0.0,
        },
    )
    usage["call_count"] = int(usage.get("call_count") or 0) + 1
    usage["input_tokens"] = int(usage.get("input_tokens") or 0) + int(input_tokens)
    usage["cached_input_tokens"] = int(usage.get("cached_input_tokens") or 0) + int(cached_input_tokens)
    usage["output_tokens"] = int(usage.get("output_tokens") or 0) + int(output_tokens)
    usage["total_tokens"] = int(usage.get("total_tokens") or 0) + int(input_tokens) + int(output_tokens)
    usage["cost_usd"] = round(float(usage.get("cost_usd") or 0.0) + float(cost_usd), 10)
    save_metrics(run_ctx, metrics)


@contextmanager
def stage_timer(run_ctx: RunContext, stage: str):
    started_at_utc = utc_now_iso()
    metrics = load_metrics(run_ctx)
    stage_metrics = metrics.setdefault("stages", {}).setdefault(stage, {})
    stage_metrics["started_at_utc"] = started_at_utc
    stage_metrics["status"] = "in_progress"
    stage_metrics.pop("failed_at_utc", None)
    stage_metrics.pop("last_error", None)
    save_metrics(run_ctx, metrics)
    log_event(run_ctx, stage=stage, event="stage_started", started_at_utc=started_at_utc)

    t0 = time.perf_counter()
    try:
        yield
    except Exception as exc:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        metrics = load_metrics(run_ctx)
        stage_metrics = metrics.setdefault("stages", {}).setdefault(stage, {})
        stage_metrics["elapsed_ms"] = elapsed_ms
        stage_metrics["failed_at_utc"] = utc_now_iso()
        stage_metrics["status"] = "failed"
        stage_metrics["last_error"] = {"type": type(exc).__name__, "message": str(exc)}
        save_metrics(run_ctx, metrics)
        logger = logging.getLogger(f"pdf_scan_phase_a.{run_ctx.run_id}")
        if getattr(logger, "handlers", None):
            logger.info(
                "Stage failed | stage=%s | elapsed_ms=%s | error=%s: %s",
                stage,
                elapsed_ms,
                type(exc).__name__,
                str(exc),
            )
        log_event(
            run_ctx,
            stage=stage,
            event="stage_failed",
            elapsed_ms=elapsed_ms,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        raise
    else:
        elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
        metrics = load_metrics(run_ctx)
        stage_metrics = metrics.setdefault("stages", {}).setdefault(stage, {})
        stage_metrics["elapsed_ms"] = elapsed_ms
        stage_metrics["finished_at_utc"] = utc_now_iso()
        stage_metrics["status"] = "success"
        stage_metrics.pop("failed_at_utc", None)
        stage_metrics.pop("last_error", None)
        save_metrics(run_ctx, metrics)
        logger = logging.getLogger(f"pdf_scan_phase_a.{run_ctx.run_id}")
        if getattr(logger, "handlers", None):
            logger.info("Stage finished | stage=%s | elapsed_ms=%s", stage, elapsed_ms)
        log_event(run_ctx, stage=stage, event="stage_finished", elapsed_ms=elapsed_ms)


def inspect_pdf(path: Path) -> Dict[str, Any]:
    result: Dict[str, Any] = {
        "page_count": None,
        "has_outline": None,
        "outline_count": None,
        "inspect_status": "not_attempted",
        "text_chars_page_1": None,
    }
    if fitz is None:
        result["inspect_status"] = "fitz_unavailable"
        return result
    try:
        with fitz.open(path) as doc:
            result["page_count"] = int(doc.page_count)
            try:
                toc = doc.get_toc() or []
                result["has_outline"] = bool(toc)
                result["outline_count"] = len(toc)
            except Exception:
                result["has_outline"] = None
                result["outline_count"] = None
            try:
                if doc.page_count > 0:
                    text = (doc.load_page(0).get_text("text") or "").strip()
                    result["text_chars_page_1"] = len(text)
            except Exception:
                result["text_chars_page_1"] = None
        result["inspect_status"] = "ok"
    except Exception as exc:
        result["inspect_status"] = f"error:{type(exc).__name__}"
    return result


def load_json(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_pdf_sources(raw_sources: List[Dict[str, Any]]) -> List[PdfSource]:
    out: List[PdfSource] = []
    seen_labels: Dict[str, int] = {}
    for item in raw_sources or []:
        if not isinstance(item, dict):
            continue
        path_raw = str(item.get("path") or "").strip()
        if not path_raw:
            continue
        path = resolve_path(path_raw, expect_dir=False)
        label = str(item.get("label") or path.stem).strip() or path.stem
        seen_labels[label] = seen_labels.get(label, 0) + 1
        if seen_labels[label] > 1:
            label = f"{label} ({seen_labels[label]})"
        out.append(PdfSource(label=label, path=path))
    return out


def resolve_small_gold_inputs(
    suite_manifest: str,
    chapter_index: int,
    doc_limit: Optional[int],
    include_doc_ids: List[str],
    exclude_doc_ids: List[str],
) -> Dict[str, Any]:
    suite_manifest_path = resolve_path(suite_manifest, expect_dir=False)
    suite = load_json(suite_manifest_path)
    suite_root = suite_manifest_path.parent.parent
    chapter_specs = list(suite.get("chapter_specs") or [])
    if not chapter_specs:
        raise ValueError("The small-gold suite manifest contains no chapter_specs entries.")
    if chapter_index < 0 or chapter_index >= len(chapter_specs):
        raise IndexError(f"chapter_index out of range: {chapter_index}")

    chapter_path = (suite_root / str(chapter_specs[chapter_index])).resolve()
    chapter_spec = load_json(chapter_path)

    include_set = {value.strip() for value in include_doc_ids if value.strip()}
    exclude_set = {value.strip() for value in exclude_doc_ids if value.strip()}
    resolved_sources: List[Dict[str, Any]] = []
    discovery_total_count = 0
    for rel_path in list(suite.get("documents") or []):
        doc_manifest_path = (suite_root / str(rel_path)).resolve()
        doc_manifest = load_json(doc_manifest_path)
        discovery_total_count += 1
        doc_id = str(doc_manifest.get("doc_id") or "").strip()
        if include_set and doc_id not in include_set:
            continue
        if doc_id and doc_id in exclude_set:
            continue
        pdf_path = (suite_root / str(doc_manifest.get("path") or "")).resolve()
        resolved_sources.append({"label": str(doc_manifest.get("label") or pdf_path.stem), "path": str(pdf_path)})

    if doc_limit is not None:
        resolved_sources = resolved_sources[: int(doc_limit)]
    if not resolved_sources:
        raise ValueError("Benchmark mode resolved zero PDFs after include/exclude filtering.")

    return {
        "input_mode": "small_gold",
        "chapter_title": str(chapter_spec.get("title") or "").strip(),
        "chapter_spec_text": str(chapter_spec.get("description") or "").strip(),
        "pdf_sources": normalize_pdf_sources(resolved_sources),
        "pdf_dir_raw": "",
        "pdf_glob": "*.pdf",
        "pdf_recursive": False,
        "max_pdfs": len(resolved_sources),
        "benchmark_suite_manifest": str(suite_manifest_path),
        "benchmark_suite_id": str(suite.get("suite_id") or "").strip(),
        "benchmark_chapter_id": str(chapter_spec.get("chapter_id") or "").strip(),
        "source_discovery_total_count": discovery_total_count,
    }


def resolve_manual_inputs(args: argparse.Namespace) -> Dict[str, Any]:
    pdf_sources: List[PdfSource] = []
    raw_sources = [{"label": "", "path": path} for path in list(args.pdf or [])]
    if raw_sources:
        pdf_sources = normalize_pdf_sources(raw_sources)

    discovery_total_count = len(pdf_sources)
    if not pdf_sources:
        pdf_dir = str(args.pdf_dir or "").strip()
        if not pdf_dir:
            raise ValueError("Manual mode requires --pdf or --pdf-dir.")
        root = resolve_path(pdf_dir, expect_dir=True)
        paths = sorted(root.rglob(args.pdf_glob) if args.pdf_recursive else root.glob(args.pdf_glob))
        paths = [path.resolve() for path in paths if path.is_file()]
        discovery_total_count = len(paths)
        pdf_sources = normalize_pdf_sources([{"label": path.stem, "path": str(path)} for path in paths[: int(args.max_pdfs)]])

    return {
        "input_mode": "manual",
        "chapter_title": str(args.chapter_title or "").strip(),
        "chapter_spec_text": str(args.chapter_description or "").strip(),
        "pdf_sources": pdf_sources,
        "pdf_dir_raw": str(args.pdf_dir or "").strip(),
        "pdf_glob": str(args.pdf_glob or "*.pdf"),
        "pdf_recursive": bool(args.pdf_recursive),
        "max_pdfs": int(args.max_pdfs),
        "benchmark_suite_manifest": "",
        "benchmark_suite_id": "",
        "benchmark_chapter_id": "",
        "source_discovery_total_count": discovery_total_count,
    }


def compute_run_id(
    chapter_title: str,
    chapter_spec_text: str,
    pipeline_version: str,
    manifest_rows: List[Dict[str, Any]],
) -> str:
    doc_parts = [f"{row.get('label')}::{row.get('sha256')}" for row in manifest_rows]
    return stable_hash(pipeline_version, chapter_title, chapter_spec_text, "\n".join(doc_parts), length=24)


def build_phase_a_assessment(cfg: PhaseAConfig, manifest_rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    warnings: List[str] = []
    failures: List[str] = []
    info: List[str] = []

    inspect_errors = [row["file_name"] for row in manifest_rows if str(row.get("inspect_status") or "") != "ok"]
    missing_page_count = [row["file_name"] for row in manifest_rows if not isinstance(row.get("page_count"), int)]
    zero_byte = [row["file_name"] for row in manifest_rows if float(row.get("size_mb") or 0.0) <= 0.0]
    duplicate_sha = sorted({row["sha256"] for row in manifest_rows if sum(1 for item in manifest_rows if item.get("sha256") == row.get("sha256")) > 1})
    truncated = int(cfg.source_discovery_total_count) > int(cfg.resolved_source_count)

    if not cfg.openai_api_key_present:
        warnings.append("OPENAI_API_KEY is absent. Later LLM phases will not run until it is provided.")
    if fitz is None:
        warnings.append("PyMuPDF is unavailable. PDF inspection depth is reduced.")
    if inspect_errors:
        failures.append(f"PDF inspection failed for {len(inspect_errors)} file(s).")
    if missing_page_count:
        failures.append(f"Page counts are missing for {len(missing_page_count)} file(s).")
    if zero_byte:
        failures.append(f"Zero-byte PDF(s) detected: {', '.join(zero_byte[:4])}")
    if duplicate_sha:
        warnings.append(f"Duplicate PDF content detected for {len(duplicate_sha)} sha256 value(s).")
    if truncated:
        info.append("Input discovery found more PDFs than were selected under the current max/doc-limit settings.")

    status = "success"
    quality_band = "high"
    if failures:
        status = "failed"
        quality_band = "blocked"
    elif warnings:
        status = "success_with_warnings"
        quality_band = "acceptable_with_issues"

    if cfg.input_mode == "small_gold":
        info.append(f"Benchmark suite: {cfg.benchmark_suite_id or '<unknown>'}")
    info.append(f"Resolved PDF count: {len(manifest_rows)}")

    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_a",
        "status": status,
        "quality_band": quality_band,
        "can_continue_to_next_phase": not bool(failures),
        "failures": failures,
        "warnings": warnings,
        "info": info,
        "counts": {
            "pdf_count": len(manifest_rows),
            "inspect_error_count": len(inspect_errors),
            "missing_page_count_count": len(missing_page_count),
            "zero_byte_count": len(zero_byte),
            "duplicate_sha_count": len(duplicate_sha),
            "selected_pdf_count": int(cfg.resolved_source_count),
            "discovered_pdf_count": int(cfg.source_discovery_total_count),
        },
    }


def build_runtime_snapshot() -> Dict[str, Any]:
    return {
        "generated_at_utc": utc_now_iso(),
        "phase": "phase_a",
        "runtime": {
            "python_executable": sys.executable,
            "python_version": sys.version.split()[0],
            "platform": platform.platform(),
            "cwd": str(Path.cwd().resolve()),
        },
        "dependencies": {
            "fitz_available": bool(fitz is not None),
            "fitz_version": getattr(fitz, "VersionBind", None) if fitz is not None else None,
            "pydantic_version": getattr(pydantic, "__version__", None),
            "pydantic_settings_version": getattr(pydantic_settings, "__version__", None),
        },
        "environment": {
            "repo_root": str(REPO_ROOT),
            "pdf_scan_dir": str(PDF_SCAN_DIR),
            "openai_api_key_present": bool((os.getenv("OPENAI_API_KEY") or "").strip()),
        },
    }


def run_phase_a(args: argparse.Namespace) -> Dict[str, Any]:
    if args.input_mode == "small_gold":
        resolved = resolve_small_gold_inputs(
            suite_manifest=args.suite_manifest,
            chapter_index=int(args.chapter_index),
            doc_limit=args.doc_limit,
            include_doc_ids=list(args.include_doc_id or []),
            exclude_doc_ids=list(args.exclude_doc_id or []),
        )
    else:
        resolved = resolve_manual_inputs(args)

    runs_root = ensure_dir(resolve_output_dir(args.runs_root) if args.runs_root else (PDF_SCAN_DIR / "runs").resolve())
    config = PhaseAConfig(
        pipeline_version=str(args.pipeline_version or "").strip(),
        input_mode=resolved["input_mode"],
        chapter_title=resolved["chapter_title"],
        chapter_spec_text=resolved["chapter_spec_text"],
        runs_root=runs_root,
        openai_api_key_present=bool((os.getenv("OPENAI_API_KEY") or "").strip()),
        force_rebuild_phase_a=bool(args.force_rebuild),
        pdf_sources=resolved["pdf_sources"],
        pdf_dir_raw=resolved["pdf_dir_raw"],
        pdf_glob=resolved["pdf_glob"],
        pdf_recursive=resolved["pdf_recursive"],
        max_pdfs=resolved["max_pdfs"],
        benchmark_suite_manifest=resolved["benchmark_suite_manifest"],
        benchmark_suite_id=resolved["benchmark_suite_id"],
        benchmark_chapter_id=resolved["benchmark_chapter_id"],
        source_discovery_total_count=resolved["source_discovery_total_count"],
    )

    pdf_manifest_rows: List[Dict[str, Any]] = []
    for src in config.pdf_sources:
        stat = src.path.stat()
        inspect = inspect_pdf(src.path)
        pdf_manifest_rows.append(
            {
                "label": src.label,
                "path": str(src.path),
                "file_name": src.path.name,
                "size_bytes": int(stat.st_size),
                "size_mb": round(float(stat.st_size) / (1024.0 * 1024.0), 6),
                "sha256": sha256_file(src.path),
                "page_count": inspect.get("page_count"),
                "has_outline": inspect.get("has_outline"),
                "outline_count": inspect.get("outline_count"),
                "inspect_status": inspect.get("inspect_status"),
                "text_chars_page_1": inspect.get("text_chars_page_1"),
                "mtime_utc": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).replace(microsecond=0).isoformat(),
            }
        )

    run_id = compute_run_id(config.chapter_title, config.chapter_spec_text, config.pipeline_version, pdf_manifest_rows)
    run_dir = runs_root / run_id
    artifacts = RunArtifacts.from_run_dir(run_dir)
    run_ctx = RunContext(repo_root=REPO_ROOT, pdf_scan_dir=PDF_SCAN_DIR, run_id=run_id, run_dir=run_dir, artifacts=artifacts)

    run_ctx.create_artifact_skeleton(overwrite=bool(args.force_rebuild))
    logger = setup_run_logger(run_ctx)

    runtime_snapshot = build_runtime_snapshot()
    assessment = build_phase_a_assessment(config, pdf_manifest_rows)
    expected_paths = [
        artifacts.config_json,
        artifacts.pdf_manifest_json,
        artifacts.query_plan_json,
        artifacts.parser_dir,
        artifacts.normalized_dir,
        artifacts.retrieval_dir,
        artifacts.rerank_dir,
        artifacts.final_dir,
        artifacts.logs_jsonl,
        artifacts.run_log,
        artifacts.metrics_json,
        artifacts.api_calls_jsonl,
        artifacts.phase_a_config_json,
        artifacts.phase_a_runtime_json,
        artifacts.phase_a_summary_json,
        artifacts.phase_a_assessment_json,
    ]

    with stage_timer(run_ctx, "phase_a"):
        logger.info("Phase A initialized | run_id=%s | run_dir=%s", run_ctx.run_id, run_ctx.run_dir)

        write_json(artifacts.config_json, config.to_snapshot())
        write_json(
            artifacts.pdf_manifest_json,
            {
                "generated_at_utc": utc_now_iso(),
                "run_id": run_ctx.run_id,
                "pdf_count": len(pdf_manifest_rows),
                "pdfs": pdf_manifest_rows,
            },
        )
        write_json(artifacts.phase_a_config_json, config.to_snapshot())
        write_json(artifacts.phase_a_runtime_json, runtime_snapshot)
        write_json(artifacts.phase_a_assessment_json, assessment)

        summary = {
            "generated_at_utc": utc_now_iso(),
            "phase": "phase_a",
            "run_id": run_ctx.run_id,
            "contract": {
                "inputs": [
                    "chapter_title",
                    "chapter_spec_text",
                    "pipeline_version",
                    "pdf_sources or pdf_dir",
                    "environment variables",
                ],
                "outputs": [
                    "config.json",
                    "pdf_manifest.json",
                    "metrics.json",
                    "logs.jsonl",
                    "run.log",
                    "api_calls.jsonl",
                    "phase_a/phase_a_config.json",
                    "phase_a/phase_a_runtime.json",
                    "phase_a/phase_a_summary.json",
                    "phase_a/phase_a_assessment.json",
                ],
            },
            "config_snapshot_path": str(artifacts.phase_a_config_json.relative_to(run_ctx.run_dir)),
            "runtime_snapshot_path": str(artifacts.phase_a_runtime_json.relative_to(run_ctx.run_dir)),
            "assessment_path": str(artifacts.phase_a_assessment_json.relative_to(run_ctx.run_dir)),
            "pdf_count": len(pdf_manifest_rows),
            "pdf_manifest_rows": pdf_manifest_rows,
            "artifact_rows": [],
            "qc_rows": [],
        }
        write_json(artifacts.phase_a_summary_json, summary)
        artifact_rows = [{"artifact": path.name, "path": str(path), "exists": path.exists()} for path in expected_paths]
        qc_rows = [
            qc_row(
                check="artifact_skeleton",
                status="OK" if all(path.exists() for path in expected_paths) else "FAIL",
                value="all present" if all(path.exists() for path in expected_paths) else "missing artifact(s)",
                expected="all core artifact paths exist",
                why="Later phases rely on deterministic artifact locations.",
                fix="Re-run Phase A or inspect path/permission errors.",
            ),
            qc_row(
                check="pdf_count",
                status="OK" if len(pdf_manifest_rows) >= 1 else "FAIL",
                value=len(pdf_manifest_rows),
                expected=">= 1",
                why="The pipeline needs at least one PDF input.",
                fix="Provide PDFs through the benchmark manifest or manual inputs.",
            ),
            qc_row(
                check="inspect_status",
                status="OK" if not assessment["counts"]["inspect_error_count"] else "FAIL",
                value=assessment["counts"]["inspect_error_count"],
                expected="0 inspection errors",
                why="Phase A must confirm that every selected PDF is openable before later parsing.",
                fix="Inspect the affected PDF(s) and the Phase A runtime snapshot.",
            ),
            qc_row(
                check="page_counts_present",
                status="OK" if not assessment["counts"]["missing_page_count_count"] else "FAIL",
                value=assessment["counts"]["missing_page_count_count"],
                expected="0 missing page counts",
                why="Page counts are part of the run contract and later parser decisions.",
                fix="Inspect fitz availability and PDF readability.",
            ),
            qc_row(
                check="openai_api_key",
                status="OK" if config.openai_api_key_present else "WARN",
                value=config.openai_api_key_present,
                expected="True before later OpenAI phases",
                why="Later query-planning and dense retrieval phases use the OpenAI API.",
                fix="Set OPENAI_API_KEY in .env before later phases.",
            ),
            qc_row(
                check="api_usage_ledger",
                status="OK" if artifacts.api_calls_jsonl.exists() else "FAIL",
                value=artifacts.api_calls_jsonl.exists(),
                expected="True",
                why="All later OpenAI usage should be recorded in one run-level ledger.",
                fix="Inspect artifact skeleton initialization.",
            ),
        ]
        summary["artifact_rows"] = artifact_rows
        summary["qc_rows"] = qc_rows
        write_json(artifacts.phase_a_summary_json, summary)

        metrics = load_metrics(run_ctx)
        phase_metrics = metrics.setdefault("stages", {}).setdefault("phase_a", {})
        phase_metrics.update(
            {
                "initialized_at_utc": utc_now_iso(),
                "input_mode": config.input_mode,
                "pdf_count": len(pdf_manifest_rows),
                "has_openai_api_key": config.openai_api_key_present,
                "pymupdf_available": bool(fitz is not None),
                "benchmark_suite_id": config.benchmark_suite_id,
                "benchmark_chapter_id": config.benchmark_chapter_id,
                "status": assessment["status"],
                "quality_band": assessment["quality_band"],
                "can_continue_to_next_phase": assessment["can_continue_to_next_phase"],
                "phase_a_summary_path": str(artifacts.phase_a_summary_json.relative_to(run_ctx.run_dir)),
                "phase_a_assessment_path": str(artifacts.phase_a_assessment_json.relative_to(run_ctx.run_dir)),
                "phase_a_runtime_path": str(artifacts.phase_a_runtime_json.relative_to(run_ctx.run_dir)),
            }
        )
        save_metrics(run_ctx, metrics)
        log_event(
            run_ctx,
            stage="phase_a",
            event="run_initialized",
            run_id=run_ctx.run_id,
            run_dir=str(run_ctx.run_dir),
            input_mode=config.input_mode,
            pdf_count=len(pdf_manifest_rows),
            benchmark_suite_id=config.benchmark_suite_id,
            benchmark_chapter_id=config.benchmark_chapter_id,
        )
        from pdf_reporting import update_run_pdf_reports

        update_run_pdf_reports(run_ctx, phase_name="phase_a")

    return {
        "run_ctx": run_ctx,
        "config": config,
        "manifest_rows": pdf_manifest_rows,
        "assessment": assessment,
        "summary": read_json(artifacts.phase_a_summary_json),
    }


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Phase A lab for the PDF scan pipeline.")
    parser.add_argument("--input-mode", choices=["small_gold", "manual"], default="small_gold")
    parser.add_argument("--pipeline-version", default="pdf_scan_v2_phase_a_lab")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--runs-root", default="")

    parser.add_argument("--suite-manifest", default="benchmark/small_gold/manifests/suite_manifest.json")
    parser.add_argument("--chapter-index", type=int, default=0)
    parser.add_argument("--doc-limit", type=int, default=None)
    parser.add_argument("--include-doc-id", action="append", default=[])
    parser.add_argument("--exclude-doc-id", action="append", default=[])

    parser.add_argument("--chapter-title", default="")
    parser.add_argument("--chapter-description", default="")
    parser.add_argument("--pdf", action="append", default=[])
    parser.add_argument("--pdf-dir", default="")
    parser.add_argument("--pdf-glob", default="*.pdf")
    parser.add_argument("--pdf-recursive", action="store_true")
    parser.add_argument("--max-pdfs", type=int, default=20)
    return parser


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()
    try:
        result = run_phase_a(args)
    except (ValidationError, Exception) as exc:
        print_section("Phase A Lab - Failure")
        print(f"{type(exc).__name__}: {exc}")
        return 1

    run_ctx: RunContext = result["run_ctx"]
    config: PhaseAConfig = result["config"]
    summary = result["summary"]
    assessment = result["assessment"]

    print_section("Phase A Lab - Run Context")
    print_kv(
        {
            "run_id": run_ctx.run_id,
            "run_dir": run_ctx.run_dir,
            "pipeline_version": config.pipeline_version,
            "input_mode": config.input_mode,
            "pdf_count": len(result["manifest_rows"]),
            "chapter_title": config.chapter_title,
        }
    )

    print_section("Phase A Lab - PDF Manifest Preview")
    print_table(
        result["manifest_rows"],
        columns=["label", "file_name", "page_count", "outline_count", "size_mb", "inspect_status", "text_chars_page_1"],
        max_rows=20,
        max_col_width=56,
    )

    print_section("Phase A Lab - Artifact Preview")
    print_table(summary["artifact_rows"], columns=["artifact", "exists", "path"], max_rows=30, max_col_width=76)

    print_section("Phase A Lab - Assessment")
    print_kv(
        {
            "status": assessment["status"],
            "quality_band": assessment["quality_band"],
            "can_continue": assessment["can_continue_to_next_phase"],
            "warning_count": len(assessment["warnings"]),
            "failure_count": len(assessment["failures"]),
        }
    )

    print_section("Phase A Lab - QC")
    print_table(summary["qc_rows"], columns=["check", "status", "value", "expected", "why", "fix"], max_rows=20, max_col_width=48)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
