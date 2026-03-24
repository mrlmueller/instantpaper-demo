from __future__ import annotations

import hashlib
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from services.pdf_scan.storage import PdfScanArtifactStore

PDF_SCAN_HANDOFF_SCHEMA_VERSION = "1"
PDF_SCAN_HANDOFF_RELATIVE_PATHS = [
    "config.json",
    "pdf_manifest.json",
    "query_plan.json",
    "metrics.json",
    "logs.jsonl",
    "api_calls.jsonl",
    "parser",
    "normalized",
    "retrieval",
]

PDF_SCAN_FINAL_UPLOAD_RELATIVE_PATHS = [
    "config.json",
    "pdf_manifest.json",
    "metrics.json",
    "logs.jsonl",
    "api_calls.jsonl",
    "query_plan.json",
    "parser",
    "normalized",
    "retrieval",
    "rerank",
    "final",
    "pdf_reports",
]


def _safe_rel(path: str) -> str:
    value = str(path or "").strip().replace("\\", "/").lstrip("/")
    if not value:
        raise ValueError("relative path is required")
    if value.startswith("../") or "/../" in value:
        raise ValueError(f"unsafe relative path: {value}")
    return value


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _add_path_to_tar(bundle: tarfile.TarFile, *, run_dir: Path, relative_path: str) -> None:
    rel = _safe_rel(relative_path)
    abs_path = (Path(run_dir).resolve() / rel).resolve()
    if not abs_path.exists():
        raise FileNotFoundError(f"Required handoff artifact missing: {abs_path}")
    bundle.add(str(abs_path), arcname=rel, recursive=True)


def create_handoff_archive(*, run_dir: Path, archive_path: Path) -> Path:
    archive = Path(archive_path).resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive, mode="w:gz") as tar:
        for rel in PDF_SCAN_HANDOFF_RELATIVE_PATHS:
            _add_path_to_tar(tar, run_dir=Path(run_dir), relative_path=rel)
    return archive


def build_handoff_manifest(
    *,
    run_id: str,
    pipeline_version: str,
    bundle_uri: str,
    bundle_sha256: str,
    bundle_size_bytes: int,
    last_completed_phase: str = "phase_e",
) -> dict[str, Any]:
    return {
        "schema_version": PDF_SCAN_HANDOFF_SCHEMA_VERSION,
        "run_id": str(run_id or "").strip(),
        "pipeline_version": str(pipeline_version or "").strip() or "pdf_scan_v3_topic_best",
        "last_completed_phase": str(last_completed_phase or "phase_e").strip() or "phase_e",
        "bundle_uri": str(bundle_uri or "").strip(),
        "bundle_sha256": str(bundle_sha256 or "").strip(),
        "bundle_size_bytes": int(bundle_size_bytes or 0),
        "required_paths": list(PDF_SCAN_HANDOFF_RELATIVE_PATHS),
    }


def upload_handoff_bundle(
    *,
    run_dir: Path,
    artifact_store: PdfScanArtifactStore,
    run_id: str,
    pipeline_version: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="pdf_scan_handoff_") as tmpdir:
        archive_path = Path(tmpdir) / f"{str(run_id).strip() or 'run'}_handoff.tar.gz"
        create_handoff_archive(run_dir=run_dir, archive_path=archive_path)
        bundle_rel = f"{artifact_store.run_prefix(run_id)}/handoff/handoff_bundle.tar.gz"
        bundle_uri = artifact_store.upload_file(
            local_path=archive_path,
            path_or_uri=bundle_rel,
            content_type="application/gzip",
        )
        manifest = build_handoff_manifest(
            run_id=run_id,
            pipeline_version=pipeline_version,
            bundle_uri=bundle_uri,
            bundle_sha256=_sha256_file(archive_path),
            bundle_size_bytes=int(archive_path.stat().st_size),
        )
        manifest_rel = f"{artifact_store.run_prefix(run_id)}/handoff/handoff_manifest.json"
        manifest_uri = artifact_store.upload_json(payload=manifest, path_or_uri=manifest_rel)
        manifest["manifest_uri"] = manifest_uri
        manifest["bundle_object_name"] = artifact_store.location(bundle_rel).object_name
        manifest["manifest_object_name"] = artifact_store.location(manifest_rel).object_name
        return manifest


def _safe_extract_archive(*, archive_path: Path, output_dir: Path) -> None:
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(Path(archive_path).resolve(), mode="r:gz") as tar:
        for member in tar.getmembers():
            name = _safe_rel(member.name)
            destination = (target / name).resolve()
            try:
                destination.relative_to(target)
            except ValueError as exc:
                raise RuntimeError(f"Unsafe archive member: {member.name}") from exc
        tar.extractall(path=str(target))


def restore_handoff_bundle(
    *,
    artifact_store: PdfScanArtifactStore,
    manifest: dict[str, Any],
    work_root: Path,
) -> Path:
    run_id = str((manifest or {}).get("run_id") or "").strip()
    if not run_id:
        raise ValueError("manifest is missing run_id")
    bundle_uri = str((manifest or {}).get("bundle_uri") or "").strip()
    if not bundle_uri:
        raise ValueError("manifest is missing bundle_uri")
    work_root = Path(work_root).resolve()
    run_dir = work_root / "pipeline_runs" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    archive_path = work_root / "handoff_bundle.tar.gz"
    artifact_store.download_file(path_or_uri=bundle_uri, local_path=archive_path)
    expected_sha = str((manifest or {}).get("bundle_sha256") or "").strip()
    if expected_sha and _sha256_file(archive_path) != expected_sha:
        raise RuntimeError(f"Handoff archive checksum mismatch for {bundle_uri}")
    _safe_extract_archive(archive_path=archive_path, output_dir=run_dir)
    return run_dir


def upload_final_outputs(
    *,
    run_dir: Path,
    artifact_store: PdfScanArtifactStore,
    run_id: str,
) -> dict[str, Any]:
    uploaded: list[str] = []
    prefix = artifact_store.run_prefix(run_id)
    suffix_map = {
        ".json": "application/json; charset=utf-8",
        ".jsonl": "application/x-ndjson; charset=utf-8",
        ".md": "text/markdown; charset=utf-8",
        ".html": "text/html; charset=utf-8",
    }
    for rel in PDF_SCAN_FINAL_UPLOAD_RELATIVE_PATHS:
        abs_path = (Path(run_dir).resolve() / rel).resolve()
        if not abs_path.exists():
            continue
        if abs_path.is_dir():
            uploaded.extend(
                artifact_store.upload_dir(
                    local_dir=abs_path,
                    prefix=f"{prefix}/{_safe_rel(rel)}",
                    content_type_by_suffix=suffix_map,
                )
            )
        else:
            uploaded.append(
                artifact_store.upload_file(
                    local_path=abs_path,
                    path_or_uri=f"{prefix}/{_safe_rel(rel)}",
                    content_type=suffix_map.get(abs_path.suffix.lower()),
                )
            )
    return {
        "uploaded_count": int(len(uploaded)),
        "uploaded_uris_preview": uploaded[:20],
        "prefix_uri": f"gs://{artifact_store.bucket_name}/{prefix}",
    }
