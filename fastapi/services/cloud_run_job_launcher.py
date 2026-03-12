from __future__ import annotations

import logging
import re
from typing import Any

import google.auth
from google.auth.transport.requests import AuthorizedSession

from utils.config import config

logger = logging.getLogger(__name__)

_EXECUTION_NAME_RE = re.compile(r"projects/.+/locations/.+/jobs/.+/executions/.+")


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

    def _job_name(self) -> str:
        job_name = str(config.TWO_LANE_CLOUD_RUN_JOB_NAME or "").strip()
        if not job_name:
            raise RuntimeError("TWO_LANE_CLOUD_RUN_JOB_NAME is not configured.")
        return job_name

    def _job_region(self) -> str:
        region = str(config.TWO_LANE_CLOUD_RUN_JOB_REGION or "").strip()
        if not region:
            raise RuntimeError("TWO_LANE_CLOUD_RUN_JOB_REGION is not configured.")
        return region

    def execute_two_lane_sources_job(
        self,
        *,
        user_id: str,
        projekt_id: str,
        run_id: str,
    ) -> dict[str, str | None]:
        session, project_id = self._ensure_session()
        region = self._job_region()
        job_name = self._job_name()
        url = (
            f"https://run.googleapis.com/v2/projects/{project_id}/locations/{region}/jobs/{job_name}:run"
        )
        args = [
            "run_two_lane_job.py",
            f"--user-id={str(user_id).strip()}",
            f"--project-id={str(projekt_id).strip()}",
            f"--run-id={str(run_id).strip()}",
        ]
        payload = {
            "overrides": {
                "containerOverrides": [
                    {
                        "args": args,
                    }
                ]
            }
        }

        logger.info(
            "Launching Cloud Run Job | job=%s region=%s run_id=%s projekt_id=%s",
            job_name,
            region,
            run_id,
            projekt_id,
        )
        resp = session.post(url, json=payload, timeout=60)
        try:
            body = resp.json()
        except Exception:
            body = {}

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


cloud_run_job_launcher = CloudRunJobLauncher()
