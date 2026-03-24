from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from google.api_core.exceptions import Forbidden, NotFound
from google.cloud import storage

logger = logging.getLogger(__name__)


def build_gs_uri(bucket: str, object_name: str) -> str:
    bucket_s = str(bucket or "").strip().strip("/")
    object_s = str(object_name or "").strip().lstrip("/")
    if not bucket_s:
        raise ValueError("bucket is required")
    if not object_s:
        raise ValueError("object_name is required")
    return f"gs://{bucket_s}/{object_s}"


def parse_gs_uri(uri: str) -> tuple[str, str]:
    text = str(uri or "").strip()
    if not text.startswith("gs://"):
        raise ValueError(f"Unsupported GCS URI: {text}")
    path = text[5:]
    bucket, _, object_name = path.partition("/")
    bucket = bucket.strip()
    object_name = object_name.strip().lstrip("/")
    if not bucket or not object_name:
        raise ValueError(f"Invalid GCS URI: {text}")
    return bucket, object_name


def _candidate_bucket_names(name: str, project_id: str) -> list[str]:
    raw = str(name or "").strip()
    project = str(project_id or "").strip()
    candidates: list[str] = []
    if raw:
        candidates.append(raw)
        if raw.endswith(".firebasestorage.app"):
            candidates.append(raw.replace(".firebasestorage.app", ".appspot.com"))
        elif raw.endswith(".appspot.com"):
            candidates.append(raw.replace(".appspot.com", ".firebasestorage.app"))
    if project:
        candidates.extend([f"{project}.firebasestorage.app", f"{project}.appspot.com"])
    seen: set[str] = set()
    out: list[str] = []
    for item in candidates:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


@dataclass(frozen=True)
class PdfScanArtifactLocation:
    bucket: str
    object_name: str

    @property
    def uri(self) -> str:
        return build_gs_uri(self.bucket, self.object_name)


class PdfScanArtifactStore:
    def __init__(
        self,
        *,
        bucket_name: str,
        base_prefix: str = "",
        project_id: str = "",
    ) -> None:
        self._client = storage.Client(project=str(project_id or "").strip() or None)
        self._configured_bucket_name = str(bucket_name or "").strip()
        self._project_id = str(project_id or "").strip()
        self._base_prefix = str(base_prefix or "").strip().strip("/")
        self._bucket = None

    @property
    def bucket_name(self) -> str:
        return str(self._resolve_bucket().name)

    @property
    def base_prefix(self) -> str:
        return self._base_prefix

    def _resolve_bucket(self):
        if self._bucket is not None:
            return self._bucket
        last_error: Exception | None = None
        candidates = _candidate_bucket_names(self._configured_bucket_name, self._project_id)
        for candidate in candidates:
            try:
                bucket = self._client.bucket(candidate)
                if bucket.exists():
                    self._bucket = bucket
                    return bucket
            except Forbidden as exc:
                # Object-level access is sufficient for upload/download, but `bucket.exists()`
                # additionally requires bucket metadata permissions. Accept the configured
                # bucket in that case and let the subsequent object operation be authoritative.
                logger.warning(
                    "Bucket metadata probe forbidden; using configured GCS bucket without existence check | bucket=%s",
                    candidate,
                )
                self._bucket = self._client.bucket(candidate)
                return self._bucket
            except NotFound as exc:
                last_error = exc
            except Exception as exc:
                last_error = exc
        if candidates:
            fallback = candidates[0]
            logger.warning(
                "Falling back to configured GCS bucket without metadata confirmation | bucket=%s | last_error=%s",
                fallback,
                str(last_error or ""),
            )
            self._bucket = self._client.bucket(fallback)
            return self._bucket
        detail = f" for {self._configured_bucket_name!r}" if self._configured_bucket_name else ""
        raise RuntimeError(f"Could not resolve a GCS artifact bucket{detail}.") from last_error

    def _normalize_object_name(self, path_or_uri: str) -> str:
        text = str(path_or_uri or "").strip()
        if text.startswith("gs://"):
            bucket, object_name = parse_gs_uri(text)
            if bucket != self.bucket_name:
                raise ValueError(f"Artifact URI bucket mismatch: expected {self.bucket_name}, got {bucket}")
            return object_name
        object_name = text.strip().lstrip("/")
        if self._base_prefix:
            return f"{self._base_prefix}/{object_name}" if object_name else self._base_prefix
        return object_name

    def location(self, path_or_uri: str) -> PdfScanArtifactLocation:
        return PdfScanArtifactLocation(self.bucket_name, self._normalize_object_name(path_or_uri))

    def run_prefix(self, run_id: str) -> str:
        root = self._base_prefix
        run_part = str(run_id or "").strip()
        if root and run_part:
            return f"{root}/{run_part}"
        return root or run_part

    def upload_file(
        self,
        *,
        local_path: Path,
        path_or_uri: str,
        content_type: str | None = None,
    ) -> str:
        blob = self._resolve_bucket().blob(self._normalize_object_name(path_or_uri))
        blob.upload_from_filename(str(Path(local_path).resolve()), content_type=content_type)
        return build_gs_uri(self.bucket_name, blob.name)

    def upload_text(
        self,
        *,
        text: str,
        path_or_uri: str,
        content_type: str = "text/plain; charset=utf-8",
    ) -> str:
        blob = self._resolve_bucket().blob(self._normalize_object_name(path_or_uri))
        blob.upload_from_string(str(text or ""), content_type=content_type)
        return build_gs_uri(self.bucket_name, blob.name)

    def upload_json(self, *, payload: Any, path_or_uri: str) -> str:
        return self.upload_text(
            text=json.dumps(payload, ensure_ascii=False, indent=2),
            path_or_uri=path_or_uri,
            content_type="application/json; charset=utf-8",
        )

    def download_file(self, *, path_or_uri: str, local_path: Path) -> Path:
        target = Path(local_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        blob = self._resolve_bucket().blob(self._normalize_object_name(path_or_uri))
        blob.download_to_filename(str(target))
        return target

    def download_text(self, *, path_or_uri: str) -> str:
        blob = self._resolve_bucket().blob(self._normalize_object_name(path_or_uri))
        raw = blob.download_as_bytes()
        return raw.decode("utf-8")

    def download_json(self, *, path_or_uri: str) -> Any:
        return json.loads(self.download_text(path_or_uri=path_or_uri))

    def exists(self, *, path_or_uri: str) -> bool:
        blob = self._resolve_bucket().blob(self._normalize_object_name(path_or_uri))
        return bool(blob.exists())

    def upload_dir(
        self,
        *,
        local_dir: Path,
        prefix: str,
        content_type_by_suffix: dict[str, str] | None = None,
    ) -> list[str]:
        root = Path(local_dir).resolve()
        if not root.exists():
            return []
        uploaded: list[str] = []
        for file_path in sorted(root.rglob("*")):
            if not file_path.is_file():
                continue
            relative = file_path.relative_to(root).as_posix()
            object_name = "/".join(part for part in [str(prefix or "").strip().strip("/"), relative] if part)
            suffix = file_path.suffix.lower()
            content_type = None
            if isinstance(content_type_by_suffix, dict):
                content_type = content_type_by_suffix.get(suffix)
            uploaded.append(self.upload_file(local_path=file_path, path_or_uri=object_name, content_type=content_type))
        logger.info("Uploaded %s PDF scan artifact file(s) to gs://%s/%s", len(uploaded), self.bucket_name, str(prefix or "").strip("/"))
        return uploaded
