from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from utils.config import config

logger = logging.getLogger(__name__)

_TASK_TOKEN_HEADER = "X-TwoLane-Dispatch-Token"
_DEFAULT_TASK_PATH = "/api/internal/quellen-finder/two-lane/task"


@dataclass(frozen=True)
class TwoLaneDispatchResult:
    backend: str
    queue_name: str
    task_name: str
    created: bool
    target_url: str | None = None


def _task_handler_url() -> str | None:
    explicit = str(config.TWO_LANE_TASK_HANDLER_URL or "").strip()
    if explicit:
        return explicit
    service_url = str(getattr(config, "SERVICE_URL", "") or "").strip()
    if service_url:
        return service_url.rstrip("/") + _DEFAULT_TASK_PATH
    return None


class TwoLaneTaskDispatcher:
    def __init__(
        self,
        *,
        backend: str,
        project_id: str,
        location: str,
        openalex_queue: str,
        semanticscholar_queue: str,
        task_handler_url: str | None,
        dispatch_token: str | None,
    ) -> None:
        self.backend = str(backend or "").strip().lower()
        self.project_id = str(project_id or "").strip()
        self.location = str(location or "").strip()
        self.openalex_queue = str(openalex_queue or "").strip()
        self.semanticscholar_queue = str(semanticscholar_queue or "").strip()
        self.task_handler_url = str(task_handler_url or "").strip() or None
        self.dispatch_token = str(dispatch_token or "").strip() or None
        self._client: Any | None = None

    def _queue_name(self, queue_key: str) -> str:
        key = str(queue_key or "").strip().lower()
        if key == "openalex":
            return self.openalex_queue
        if key in {"s2", "semanticscholar"}:
            return self.semanticscholar_queue
        raise ValueError(f"Unsupported two-lane task queue: {queue_key}")

    def _client_or_raise(self):
        if self._client is None:
            from google.cloud import tasks_v2

            self._client = tasks_v2.CloudTasksClient()
        return self._client

    def _dispatch_local_background(self, payload: dict[str, Any], *, schedule_delay_seconds: float | None = None) -> None:
        def _runner() -> None:
            try:
                if schedule_delay_seconds and float(schedule_delay_seconds) > 0:
                    time.sleep(float(schedule_delay_seconds))
                from services.two_lane_sources.internal_tasks import run_two_lane_internal_task_payload

                asyncio.run(run_two_lane_internal_task_payload(payload))
            except Exception:
                logger.exception("Two-lane local background task failed")

        thread = threading.Thread(target=_runner, daemon=True, name="two-lane-task")
        thread.start()

    def _dispatch_local_inline(self, payload: dict[str, Any], *, schedule_delay_seconds: float | None = None) -> None:
        from services.two_lane_sources.internal_tasks import run_two_lane_internal_task_payload

        if schedule_delay_seconds and float(schedule_delay_seconds) > 0:
            time.sleep(float(schedule_delay_seconds))
        asyncio.run(run_two_lane_internal_task_payload(payload))

    def enqueue(
        self,
        *,
        queue_key: str,
        task_name: str,
        payload: dict[str, Any],
        schedule_delay_seconds: float | None = None,
        deadline_seconds: int | None = None,
    ) -> TwoLaneDispatchResult:
        queue_name = self._queue_name(queue_key)
        task_id = str(task_name or "").strip()
        if not task_id:
            raise ValueError("task_name is required")
        effective_deadline_seconds = (
            int(deadline_seconds)
            if deadline_seconds is not None
            else int(getattr(config, "TWO_LANE_TASK_DISPATCH_DEADLINE_S", 630) or 630)
        )

        if self.backend in {"local_inline", "inline"}:
            self._dispatch_local_inline(payload, schedule_delay_seconds=schedule_delay_seconds)
            return TwoLaneDispatchResult(
                backend="local_inline",
                queue_name=queue_name,
                task_name=task_id,
                created=True,
            )
        if self.backend in {"local_background", "local_thread", "local"}:
            self._dispatch_local_background(payload, schedule_delay_seconds=schedule_delay_seconds)
            return TwoLaneDispatchResult(
                backend="local_background",
                queue_name=queue_name,
                task_name=task_id,
                created=True,
            )
        if self.backend != "cloud_tasks":
            raise ValueError(f"Unsupported TWO_LANE_TASK_DISPATCH_BACKEND: {self.backend}")
        if not self.project_id or not self.location:
            raise RuntimeError("Cloud Tasks project/location are not configured.")
        if not self.task_handler_url:
            raise RuntimeError("TWO_LANE_TASK_HANDLER_URL is not configured.")

        from google.api_core.exceptions import AlreadyExists
        from google.cloud.tasks_v2 import HttpMethod
        from google.protobuf import duration_pb2, timestamp_pb2

        client = self._client_or_raise()
        parent = client.queue_path(self.project_id, self.location, queue_name)
        name = client.task_path(self.project_id, self.location, queue_name, task_id)
        headers = {"Content-Type": "application/json; charset=utf-8"}
        if self.dispatch_token:
            headers[_TASK_TOKEN_HEADER] = self.dispatch_token

        task: dict[str, Any] = {
            "name": name,
            "http_request": {
                "http_method": HttpMethod.POST,
                "url": self.task_handler_url,
                "headers": headers,
                "body": json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            },
        }
        if effective_deadline_seconds and int(effective_deadline_seconds) > 0:
            duration = duration_pb2.Duration()
            duration.FromSeconds(int(effective_deadline_seconds))
            task["dispatch_deadline"] = duration
        if schedule_delay_seconds and float(schedule_delay_seconds) > 0:
            eta = datetime.now(timezone.utc) + timedelta(seconds=float(schedule_delay_seconds))
            ts = timestamp_pb2.Timestamp()
            ts.FromDatetime(eta)
            task["schedule_time"] = ts

        try:
            client.create_task(parent=parent, task=task)
            created = True
        except AlreadyExists:
            created = False

        return TwoLaneDispatchResult(
            backend="cloud_tasks",
            queue_name=queue_name,
            task_name=task_id,
            created=created,
            target_url=self.task_handler_url,
        )


def build_two_lane_task_dispatcher() -> TwoLaneTaskDispatcher:
    return TwoLaneTaskDispatcher(
        backend=str(config.TWO_LANE_TASK_DISPATCH_BACKEND or "").strip().lower(),
        project_id=str(config.TWO_LANE_TASKS_PROJECT or config.GOOGLE_CLOUD_PROJECT or "").strip(),
        location=str(config.TWO_LANE_TASKS_LOCATION or config.TWO_LANE_CLOUD_RUN_JOB_REGION or "").strip(),
        openalex_queue=str(config.TWO_LANE_OPENALEX_TASK_QUEUE or "").strip(),
        semanticscholar_queue=str(config.TWO_LANE_SEMANTICSCHOLAR_TASK_QUEUE or "").strip(),
        task_handler_url=_task_handler_url(),
        dispatch_token=str(config.TWO_LANE_TASK_DISPATCH_TOKEN or "").strip(),
    )


def validate_two_lane_dispatch_token(value: str | None) -> bool:
    expected = str(config.TWO_LANE_TASK_DISPATCH_TOKEN or "").strip()
    supplied = str(value or "").strip()
    if not expected:
        return False
    return supplied == expected
