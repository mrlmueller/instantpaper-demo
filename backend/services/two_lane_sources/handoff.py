from __future__ import annotations

import hashlib
import tarfile
import tempfile
from pathlib import Path
from typing import Any

from services.two_lane_sources.storage import TwoLaneArtifactStore

TWO_LANE_HANDOFF_SCHEMA_VERSION = "1"


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


def create_handoff_archive(*, run_dir: Path, archive_path: Path) -> tuple[Path, list[str]]:
    source = Path(run_dir).resolve()
    archive = Path(archive_path).resolve()
    archive.parent.mkdir(parents=True, exist_ok=True)
    rel_paths: list[str] = []
    with tarfile.open(archive, mode="w:gz") as tar:
        for file_path in sorted(source.rglob("*")):
            if not file_path.is_file():
                continue
            rel = file_path.relative_to(source).as_posix()
            rel_safe = _safe_rel(rel)
            tar.add(str(file_path), arcname=rel_safe, recursive=False)
            rel_paths.append(rel_safe)
    return archive, rel_paths


def build_handoff_manifest(
    *,
    run_id: str,
    pipeline_version: str,
    stage_name: str,
    bundle_uri: str,
    bundle_sha256: str,
    bundle_size_bytes: int,
    relative_paths: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": TWO_LANE_HANDOFF_SCHEMA_VERSION,
        "run_id": str(run_id or "").strip(),
        "pipeline_version": str(pipeline_version or "").strip() or "two_lane_v1",
        "stage_name": str(stage_name or "").strip() or "unknown",
        "bundle_uri": str(bundle_uri or "").strip(),
        "bundle_sha256": str(bundle_sha256 or "").strip(),
        "bundle_size_bytes": int(bundle_size_bytes or 0),
        "relative_paths": list(relative_paths or []),
        "file_count": int(len(relative_paths or [])),
    }


def upload_handoff_bundle(
    *,
    run_dir: Path,
    artifact_store: TwoLaneArtifactStore,
    run_id: str,
    pipeline_version: str,
    stage_name: str,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="two_lane_handoff_") as tmpdir:
        archive_path = Path(tmpdir) / f"{str(run_id).strip() or 'run'}_{str(stage_name).strip() or 'stage'}_handoff.tar.gz"
        archive_path, rel_paths = create_handoff_archive(run_dir=run_dir, archive_path=archive_path)
        bundle_rel = f"{artifact_store.run_prefix(run_id)}/{_safe_rel(stage_name)}/handoff_bundle.tar.gz"
        bundle_uri = artifact_store.upload_file(
            local_path=archive_path,
            path_or_uri=bundle_rel,
            content_type="application/gzip",
        )
        manifest = build_handoff_manifest(
            run_id=run_id,
            pipeline_version=pipeline_version,
            stage_name=stage_name,
            bundle_uri=bundle_uri,
            bundle_sha256=_sha256_file(archive_path),
            bundle_size_bytes=int(archive_path.stat().st_size),
            relative_paths=rel_paths,
        )
        manifest_rel = f"{artifact_store.run_prefix(run_id)}/{_safe_rel(stage_name)}/handoff_manifest.json"
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
    artifact_store: TwoLaneArtifactStore,
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
