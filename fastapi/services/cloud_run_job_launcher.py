from __future__ import annotations

import json
import logging
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from utils.config import config

logger = logging.getLogger(__name__)

_EXECUTION_NAME_RE = re.compile(r"projects/.+/locations/.+/jobs/.+/executions/.+")


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = str(raw or "").strip()
    if not text:
        return {}
    decoder = json.JSONDecoder()
    for start in range(len(text)):
        if text[start] != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(text[start:])
        except Exception:
            continue
        if isinstance(payload, dict):
            return payload
    return {}


def _extract_error_message(payload: Any) -> str | None:
    if not isinstance(payload, dict):
        return None

    err = payload.get("error")
    if isinstance(err, dict):
        msg = str(err.get("message") or "").strip()
        if msg:
            return msg

    msg = str(payload.get("message") or "").strip()
    if msg:
        return msg
    return None


def _find_execution_name(value: Any) -> str | None:
    if isinstance(value, str):
        s = value.strip()
        if _EXECUTION_NAME_RE.fullmatch(s):
            return s
        return None
    if isinstance(value, dict):
        for v in value.values():
            found = _find_execution_name(v)
            if found:
                return found
        return None
    if isinstance(value, list):
        for item in value:
            found = _find_execution_name(item)
            if found:
                return found
        return None
    return None


def _resolve_gcloud_cli() -> str:
    configured = str(os.getenv("GCLOUD_BIN", "")).strip()
    candidates: list[str] = []
    if configured:
        candidates.append(configured)

    if os.name == "nt":
        cloudsdk_root = str(os.getenv("CLOUDSDK_ROOT_DIR", "")).strip()
        if cloudsdk_root:
            candidates.append(str(Path(cloudsdk_root) / "bin" / "gcloud.cmd"))
            candidates.append(str(Path(cloudsdk_root) / "bin" / "gcloud.exe"))
        home = Path.home()
        candidates.extend(
            [
                str(home / "GoogleCloudSDK" / "google-cloud-sdk" / "bin" / "gcloud.cmd"),
                str(home / "GoogleCloudSDK" / "google-cloud-sdk" / "bin" / "gcloud.exe"),
                r"C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
                r"C:\Program Files\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.exe",
                r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.cmd",
                r"C:\Program Files (x86)\Google\Cloud SDK\google-cloud-sdk\bin\gcloud.exe",
            ]
        )

    for name in ("gcloud.cmd", "gcloud.exe", "gcloud", "gcloud.ps1"):
        resolved = shutil.which(name)
        if resolved:
            candidates.append(resolved)

    seen: set[str] = set()
    for candidate in candidates:
        raw = str(candidate or "").strip()
        if not raw:
            continue
        normalized = raw.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        if Path(raw).exists():
            return raw

    if os.name == "nt":
        raise RuntimeError(
            "Cloud Run Job launch failed: Google Cloud SDK was not found. "
            "Set GCLOUD_BIN to your gcloud.cmd path."
        )
    raise RuntimeError(
        "Cloud Run Job launch failed: Google Cloud SDK was not found. "
        "Install gcloud or set GCLOUD_BIN."
    )


class CloudRunJobLauncher:
    def __init__(self) -> None:
        self._session: AuthorizedSession | None = None
        self._project_id: str | None = None

    def _ensure_session(self) -> tuple[AuthorizedSession, str]:
        if self._session is not None and self._project_id:
            return self._session, self._project_id

        credentials, project_id = google.auth.default(
            scopes=["https://www.googleapis.com/auth/cloud-platform"]
        )
        project_id = (
            str(config.GOOGLE_CLOUD_PROJECT or "").strip()
            or str(project_id or "").strip()
            or str(config.FIREBASE_PROJECT_ID or "").strip()
        )
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not configured.")

        self._session = AuthorizedSession(credentials)
        self._project_id = project_id
        return self._session, self._project_id

    def _job_name(self, value: str, env_name: str) -> str:
        job_name = str(value or "").strip()
        if not job_name:
            raise RuntimeError(f"{env_name} is not configured.")
        return job_name

    def _job_region(self, value: str, env_name: str) -> str:
        region = str(value or "").strip()
        if not region:
            raise RuntimeError(f"{env_name} is not configured.")
        return region

    def _execute_job_via_gcloud(
        self,
        *,
        job_name: str,
        region: str,
        args: list[str],
        project_id: str,
    ) -> dict[str, str | None]:
        cli_args = [
            _resolve_gcloud_cli(),
            "run",
            "jobs",
            "execute",
            job_name,
            f"--region={region}",
            f"--project={project_id}",
            f"--args={','.join(str(arg or '').strip() for arg in args if str(arg or '').strip())}",
            "--format=json",
        ]
        logger.warning(
            "Falling back to gcloud Cloud Run Job launcher locally | job=%s region=%s",
            job_name,
            region,
        )
        try:
            completed = subprocess.run(
                cli_args,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="ignore",
                timeout=120,
            )
        except FileNotFoundError as exc:
            raise RuntimeError("Cloud Run Job launch failed: gcloud CLI could not be resolved.") from exc

        stdout = str(completed.stdout or "")
        stderr = str(completed.stderr or "")
        payload = _extract_json_object(stdout)
        if completed.returncode != 0:
            msg = (
                _extract_error_message(payload)
                or stderr.strip()
                or stdout.strip()
                or f"gcloud exit code {completed.returncode}"
            )
            raise RuntimeError(f"Cloud Run Job launch failed: {msg[:1500]}")

        execution_name = _find_execution_name(payload)
        short_execution_name = str(((payload.get("metadata") or {}).get("name") or "")).strip() if isinstance(payload, dict) else ""
        if not execution_name and short_execution_name:
            execution_name = (
                f"projects/{project_id}/locations/{region}/jobs/{job_name}/executions/{short_execution_name}"
            )

        operation_name = None
        if isinstance(payload, dict):
            operation_name = (
                str((payload.get("name") or "")).strip()
                or str((((payload.get("metadata") or {}).get("annotations") or {}).get("run.googleapis.com/operation-id") or "")).strip()
                or None
            )

        return {
            "job_name": job_name,
            "region": region,
            "project_id": project_id,
            "operation_name": operation_name,
            "execution_name": execution_name,
        }

    def _execute_job(
        self,
        *,
        job_name: str,
        region: str,
        args: list[str],
    ) -> dict[str, str | None]:
        project_id = (
            str(config.GOOGLE_CLOUD_PROJECT or "").strip()
            or str(config.FIREBASE_PROJECT_ID or "").strip()
        )
        if not project_id:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT is not configured.")
        try:
            session, session_project_id = self._ensure_session()
            project_id = str(session_project_id or project_id).strip() or project_id
            url = f"https://run.googleapis.com/v2/projects/{project_id}/locations/{region}/jobs/{job_name}:run"
            payload = {"overrides": {"containerOverrides": [{"args": args}]}}

            logger.info("Launching Cloud Run Job | job=%s region=%s args=%s", job_name, region, args)
            resp = session.post(url, json=payload, timeout=60)
        except Exception as exc:
            if config.IS_CLOUD_RUN:
                raise
            return self._execute_job_via_gcloud(
                job_name=job_name,
                region=region,
                args=args,
                project_id=project_id,
            )
        try:
            body = resp.json()
        except Exception:
            body = {}

        if (not config.IS_CLOUD_RUN) and resp.status_code in {401, 403}:
            return self._execute_job_via_gcloud(
                job_name=job_name,
                region=region,
                args=args,
                project_id=project_id,
            )

        if resp.status_code < 200 or resp.status_code >= 300:
            msg = _extract_error_message(body) or resp.text.strip() or f"HTTP {resp.status_code}"
            raise RuntimeError(f"Cloud Run Job launch failed: {msg[:1500]}")

        operation_name = str((body or {}).get("name") or "").strip() or None
        execution_name = _find_execution_name(body)
        return {
            "job_name": job_name,
            "region": region,
            "project_id": project_id,
            "operation_name": operation_name,
            "execution_name": execution_name,
        }

    def execute_two_lane_sources_job(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
    ) -> dict[str, str | None]:
        region = self._job_region(
            str(config.TWO_LANE_CLOUD_RUN_JOB_REGION or "").strip(),
            "TWO_LANE_CLOUD_RUN_JOB_REGION",
        )
        job_name = self._job_name(
            str(config.TWO_LANE_CLOUD_RUN_JOB_NAME or "").strip(),
            "TWO_LANE_CLOUD_RUN_JOB_NAME",
        )
        args = [
            "run_two_lane_job.py",
            f"--user-id={str(user_id).strip()}",
            f"--project-id={str(projekt_id).strip()}",
            f"--run-id={str(run_id).strip()}",
        ]
        return self._execute_job(job_name=job_name, region=region, args=args)

    def execute_pdf_scan_cpu_job(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
    ) -> dict[str, str | None]:
        region = self._job_region(
            str(config.PDF_SCAN_CPU_CLOUD_RUN_JOB_REGION or "").strip(),
            "PDF_SCAN_CPU_CLOUD_RUN_JOB_REGION",
        )
        job_name = self._job_name(
            str(config.PDF_SCAN_CPU_CLOUD_RUN_JOB_NAME or "").strip(),
            "PDF_SCAN_CPU_CLOUD_RUN_JOB_NAME",
        )
        args = [
            "run_pdf_scan_cpu_job.py",
            f"--user-id={str(user_id).strip()}",
            f"--project-id={str(projekt_id).strip()}",
            f"--run-id={str(run_id).strip()}",
        ]
        return self._execute_job(job_name=job_name, region=region, args=args)

    def execute_pdf_scan_gpu_job(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
    ) -> dict[str, str | None]:
        region = self._job_region(
            str(config.PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION or "").strip(),
            "PDF_SCAN_GPU_CLOUD_RUN_JOB_REGION",
        )
        job_name = self._job_name(
            str(config.PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME or "").strip(),
            "PDF_SCAN_GPU_CLOUD_RUN_JOB_NAME",
        )
        args = [
            "run_pdf_scan_gpu_job.py",
            f"--user-id={str(user_id).strip()}",
            f"--project-id={str(projekt_id).strip()}",
            f"--run-id={str(run_id).strip()}",
        ]
        return self._execute_job(job_name=job_name, region=region, args=args)


cloud_run_job_launcher = CloudRunJobLauncher()
