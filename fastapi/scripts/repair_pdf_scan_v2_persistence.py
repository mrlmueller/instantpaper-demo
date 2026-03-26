from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from firebase_admin import storage
from google.cloud.firestore_v1 import SERVER_TIMESTAMP

SCRIPT_DIR = Path(__file__).resolve().parent
FASTAPI_DIR = SCRIPT_DIR.parent
REPO_ROOT = FASTAPI_DIR.parent
if str(FASTAPI_DIR) not in sys.path:
    sys.path.insert(0, str(FASTAPI_DIR))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from services.firebase_service import firebase_service
from services.pdf_scan.persistence_v2 import build_persisted_pdf_scan_v2_view
from services.pdf_scan.storage import parse_gs_uri
from services.quellen_finder_firestore_service import QuellenFinderFirestoreService


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_extract_archive(*, archive_path: Path, output_dir: Path) -> None:
    target = Path(output_dir).resolve()
    target.mkdir(parents=True, exist_ok=True)
    with tarfile.open(Path(archive_path).resolve(), mode="r:gz") as tar:
        for member in tar.getmembers():
            destination = (target / member.name).resolve()
            try:
                destination.relative_to(target)
            except ValueError as exc:
                raise RuntimeError(f"Unsafe archive member: {member.name}") from exc
        tar.extractall(path=str(target))


def _download_handoff(*, manifest_uri: str, work_root: Path) -> tuple[dict, Path]:
    bucket = storage.bucket()
    manifest_bucket, manifest_object = parse_gs_uri(manifest_uri)
    if bucket.name != manifest_bucket:
        bucket = storage.bucket(manifest_bucket)
    manifest = json.loads(bucket.blob(manifest_object).download_as_text())
    bundle_bucket, bundle_object = parse_gs_uri(str(manifest.get("bundle_uri") or ""))
    bundle_blob = storage.bucket(bundle_bucket).blob(bundle_object)

    archive_path = work_root / "handoff_bundle.tar.gz"
    bundle_blob.download_to_filename(str(archive_path))
    expected_sha = str(manifest.get("bundle_sha256") or "").strip()
    if expected_sha and _sha256_file(archive_path) != expected_sha:
        raise RuntimeError("Handoff archive checksum mismatch.")

    run_id = str(manifest.get("run_id") or "").strip()
    if not run_id:
        raise RuntimeError("Handoff manifest is missing run_id.")
    run_dir = work_root / "pipeline_runs" / run_id
    _safe_extract_archive(archive_path=archive_path, output_dir=run_dir)
    return manifest, run_dir


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Repair PDF-scan v2 Firestore persistence for an existing run.")
    parser.add_argument("--user-id", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--python-bin", default=sys.executable)
    parser.add_argument("--no-openai-judge", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    fs = QuellenFinderFirestoreService()
    run_doc = fs.get_run(user_id=args.user_id, projekt_id=args.project_id, run_id=args.run_id)
    artifacts = run_doc.get("pdfScanArtifacts") if isinstance(run_doc.get("pdfScanArtifacts"), dict) else {}
    handoff_manifest_uri = str((artifacts or {}).get("handoffManifestUri") or "").strip()
    if not handoff_manifest_uri:
        raise RuntimeError("Run is missing pdfScanArtifacts.handoffManifestUri.")
    resolved_pdf_snapshots = [
        row for row in list((artifacts or {}).get("resolvedPdfSnapshots") or []) if isinstance(row, dict)
    ]
    if not resolved_pdf_snapshots:
        raise RuntimeError("Run is missing resolvedPdfSnapshots.")

    firebase_service.db

    with tempfile.TemporaryDirectory(prefix="repair_pdf_scan_v2_") as tmpdir:
        work_root = Path(tmpdir)
        _manifest, run_dir = _download_handoff(manifest_uri=handoff_manifest_uri, work_root=work_root)
        cmd = [
            str(args.python_bin),
            str(FASTAPI_DIR / "run_pdf_scan_gpu_pipeline.py"),
            f"--run-dir={run_dir}",
            "--force-rebuild-phase-f",
            "--force-rebuild-phase-g",
            "--force-rebuild-phase-h",
        ]
        if bool(args.no_openai_judge):
            cmd.append("--no-openai-judge")
        completed = subprocess.run(
            cmd,
            cwd=str(FASTAPI_DIR),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        if completed.returncode != 0:
            raise RuntimeError(
                "GPU pipeline repair run failed.\n"
                f"STDOUT:\n{completed.stdout[-4000:]}\n\nSTDERR:\n{completed.stderr[-4000:]}"
            )

        pdf_snapshot_by_id = {
            str(row.get("id") or "").strip(): row
            for row in resolved_pdf_snapshots
            if str(row.get("id") or "").strip()
        }
        persisted = build_persisted_pdf_scan_v2_view(
            run_dir=run_dir,
            pdf_snapshot_by_id=pdf_snapshot_by_id,
            kapitel_snapshots=list((run_doc.get("kapitelSnapshots") or [])),
        )
        fs.replace_pdf_scan_v2_results(
            user_id=args.user_id,
            projekt_id=args.project_id,
            run_id=args.run_id,
            root_payload=dict(persisted.get("root_update") or {}),
            chapter_docs=list(persisted.get("chapter_docs") or []),
            chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
            chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
            aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
            aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
        )
        verification = fs.verify_pdf_scan_v2_results(
            user_id=args.user_id,
            projekt_id=args.project_id,
            run_id=args.run_id,
            chapter_docs=list(persisted.get("chapter_docs") or []),
            chapter_doc_docs=dict(persisted.get("chapter_doc_docs") or {}),
            chapter_section_docs=dict(persisted.get("chapter_section_docs") or {}),
            aggregate_doc_docs=list(persisted.get("aggregate_doc_docs") or []),
            aggregate_section_docs=list(persisted.get("aggregate_section_docs") or []),
        )
        if not bool((verification or {}).get("ok")):
            raise RuntimeError(f"Verification failed after repair: {verification}")

        fs.run_ref(args.user_id, args.project_id, args.run_id).set(
            {
                **dict(persisted.get("root_update") or {}),
                "resultSummary": {
                    "visibleDocCount": int((persisted.get("root_update") or {}).get("pdfScanCounts", {}).get("aggregateDocCount") or 0),
                    "visibleSectionCount": int(persisted.get("total_visible_section_count") or 0),
                    "usefulPdfCount": int(persisted.get("useful_pdf_count_any_chapter") or 0),
                },
                "updatedAt": SERVER_TIMESTAMP,
            },
            merge=True,
        )
        print(
            json.dumps(
                {
                    "runId": args.run_id,
                    "verification": verification,
                    "pdfScanSummary": (persisted.get("root_update") or {}).get("pdfScanSummary"),
                    "pdfScanCounts": (persisted.get("root_update") or {}).get("pdfScanCounts"),
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
