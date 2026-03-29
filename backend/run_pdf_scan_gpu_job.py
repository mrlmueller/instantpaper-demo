from __future__ import annotations

import argparse
import asyncio
import contextlib
import logging
import signal
import sys
from typing import Any

from services.pdf_scan.gpu_job import run_pdf_scan_gpu_job_from_run_doc
from utils.logging_config import configure_logging

configure_logging()
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the split PDF scan GPU worker for a specific Firestore run.")
    parser.add_argument("--user-id", required=True, help="Firebase user id that owns the run")
    parser.add_argument("--project-id", required=True, help="Project id containing the research run")
    parser.add_argument("--run-id", required=True, help="Research run id to execute")
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> None:
    loop = asyncio.get_running_loop()
    termination_event = asyncio.Event()
    termination_state: dict[str, str | None] = {"signal": None}
    previous_handlers: dict[int, Any] = {}

    def termination_message() -> str:
        signal_name = str(termination_state.get("signal") or "").strip()
        if signal_name:
            return f"PDF scan GPU worker terminated by {signal_name}."
        return "PDF scan GPU worker termination requested."

    def request_shutdown(sig_name: str) -> None:
        if not termination_event.is_set():
            logger.warning("PDF scan GPU worker received %s; requesting graceful shutdown.", sig_name)
            termination_state["signal"] = sig_name
            termination_event.set()

    for sig in [getattr(signal, "SIGTERM", None), getattr(signal, "SIGINT", None)]:
        if sig is None:
            continue
        try:
            loop.add_signal_handler(sig, request_shutdown, sig.name)
        except (NotImplementedError, RuntimeError):
            previous_handlers[int(sig)] = signal.getsignal(sig)

            def _fallback_handler(signum, _frame, *, sig_name=sig.name):
                loop.call_soon_threadsafe(request_shutdown, sig_name)

            signal.signal(sig, _fallback_handler)

    try:
        await run_pdf_scan_gpu_job_from_run_doc(
            user_id=str(args.user_id).strip(),
            projekt_id=str(args.project_id).strip(),
            run_id=str(args.run_id).strip(),
            external_termination_event=termination_event,
            external_termination_message_getter=termination_message,
        )
    finally:
        for sig_num, previous_handler in previous_handlers.items():
            with contextlib.suppress(Exception):
                signal.signal(signal.Signals(sig_num), previous_handler)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(list(argv or sys.argv[1:]))
    try:
        asyncio.run(_main_async(args))
    except Exception as exc:
        logger.exception("PDF scan GPU worker failed: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
