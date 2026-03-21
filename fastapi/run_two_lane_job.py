from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from services.quellen_finder_sources_two_lane_job import (
    run_quellen_finder_sources_two_lane_job_from_run_doc,
)
from utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Quellen-Finder two-lane worker for a specific Firestore run."
    )
    parser.add_argument("--user-id", required=True, help="Firebase user id that owns the run")
    parser.add_argument(
        "--project-id", required=True, help="Project id containing the research run"
    )
    parser.add_argument("--run-id", required=True, help="Research run id to execute")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> None:
    await run_quellen_finder_sources_two_lane_job_from_run_doc(
        user_id=str(args.user_id).strip(),
        projekt_id=str(args.project_id).strip(),
        run_id=str(args.run_id).strip(),
    )


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        asyncio.run(_main_async(args))
    except Exception as exc:
        logger.exception("Two-lane worker failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
