from __future__ import annotations

import asyncio
from typing import Any

from services.two_lane_sources.provider_tasks import (
    process_openalex_query_task,
    process_openalex_page_task,
    process_s2_bulk_query_task,
    process_s2_bulk_page_task,
)


async def run_two_lane_internal_task_payload(payload: dict[str, Any]) -> dict[str, Any]:
    kind = str((payload or {}).get("kind") or "").strip().lower()
    if kind == "openalex_query":
        return await process_openalex_query_task(payload)
    if kind == "openalex_page":
        return await process_openalex_page_task(payload)
    if kind == "s2_bulk_query":
        return await process_s2_bulk_query_task(payload)
    if kind == "s2_bulk_page":
        return await process_s2_bulk_page_task(payload)
    raise ValueError(f"Unsupported two-lane internal task kind: {kind}")


def run_two_lane_internal_task_payload_sync(payload: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(run_two_lane_internal_task_payload(payload))
