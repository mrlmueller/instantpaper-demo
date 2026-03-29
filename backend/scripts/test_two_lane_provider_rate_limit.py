"""
Assertion-based tests for the shared Quellen-Finder provider rate limiter.

This script covers:
- deterministic in-memory scheduling
- contention across multiple concurrent workers
- provider independence
- stale-future recovery
- optional live Firestore-backed scheduling
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources.provider_rate_limit import (
    FirestoreProviderRateLimitStore,
    InMemoryProviderRateLimitStore,
    SharedProviderRateLimiter,
    delete_provider_rate_limit_docs,
)


ARTIFACT_ROOT = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"


def _write_result(name: str, payload: dict[str, Any]) -> Path:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_ROOT / name
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = ARTIFACT_ROOT / "test_two_lane_provider_rate_limit_latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _collect_parallel(*, workers: int, per_worker: int, fn):
    rows: list[dict[str, Any]] = []
    rows_lock = threading.Lock()

    def worker(worker_index: int) -> None:
        local_rows = []
        for step in range(per_worker):
            local_rows.append(fn(worker_index, step))
        with rows_lock:
            rows.extend(local_rows)

    with ThreadPoolExecutor(max_workers=int(workers)) as pool:
        list(pool.map(worker, range(int(workers))))

    return rows


def _assert_min_gap(rows: list[dict[str, Any]], *, provider: str, min_gap_ms: int) -> list[int]:
    provider_rows = sorted(
        [row for row in rows if str(row.get("provider")) == str(provider)],
        key=lambda row: (int(row.get("reserved_at_epoch_ms") or 0), int(row.get("worker") or 0), int(row.get("step") or 0)),
    )
    gaps: list[int] = []
    for prev, cur in zip(provider_rows, provider_rows[1:]):
        gap = int(cur["reserved_at_epoch_ms"]) - int(prev["reserved_at_epoch_ms"])
        gaps.append(gap)
        if gap < int(min_gap_ms):
            raise AssertionError(f"{provider} gap too small: {gap}ms < {min_gap_ms}ms")
    return gaps


def test_in_memory_sequential() -> dict[str, Any]:
    store = InMemoryProviderRateLimitStore()
    limiter = SharedProviderRateLimiter(
        provider="openalex",
        rps=5.0,
        store=store,
        holder="sequential",
        run_id="seq",
        stage="unit",
    )
    rows = []
    for step in range(5):
        reservation = limiter.acquire()
        assert reservation is not None
        rows.append(
            {
                "provider": reservation.provider,
                "reserved_at_epoch_ms": reservation.reserved_at_epoch_ms,
                "worker": 0,
                "step": step,
            }
        )

    gaps = _assert_min_gap(rows, provider="openalex", min_gap_ms=200)
    return {"name": "in_memory_sequential", "count": len(rows), "gaps_ms": gaps}


def test_in_memory_parallel_contention() -> dict[str, Any]:
    store = InMemoryProviderRateLimitStore()

    def one(worker_index: int, step: int) -> dict[str, Any]:
        limiter = SharedProviderRateLimiter(
            provider="openalex",
            rps=5.0,
            store=store,
            holder=f"worker-{worker_index}",
            run_id=f"run-{worker_index}",
            stage="parallel_contention",
        )
        reservation = limiter.acquire()
        assert reservation is not None
        return {
            "provider": reservation.provider,
            "reserved_at_epoch_ms": reservation.reserved_at_epoch_ms,
            "worker": worker_index,
            "step": step,
        }

    rows = _collect_parallel(workers=8, per_worker=3, fn=one)
    gaps = _assert_min_gap(rows, provider="openalex", min_gap_ms=200)
    return {"name": "in_memory_parallel_contention", "count": len(rows), "gaps_ms": gaps[:12]}


def test_provider_independence() -> dict[str, Any]:
    store = InMemoryProviderRateLimitStore()

    def one(provider: str, rps: float, worker_index: int, step: int) -> dict[str, Any]:
        limiter = SharedProviderRateLimiter(
            provider=provider,
            rps=rps,
            store=store,
            holder=f"{provider}-{worker_index}",
            run_id=f"{provider}-run-{worker_index}",
            stage="provider_independence",
        )
        reservation = limiter.acquire()
        assert reservation is not None
        return {
            "provider": reservation.provider,
            "reserved_at_epoch_ms": reservation.reserved_at_epoch_ms,
            "worker": worker_index,
            "step": step,
        }

    rows: list[dict[str, Any]] = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        future_oa = pool.submit(_collect_parallel, workers=4, per_worker=2, fn=lambda worker, step: one("openalex", 5.0, worker, step))
        future_s2 = pool.submit(
            _collect_parallel,
            workers=4,
            per_worker=2,
            fn=lambda worker, step: one("semanticscholar", 2.0, worker, step),
        )
        rows.extend(future_oa.result())
        rows.extend(future_s2.result())

    oa_gaps = _assert_min_gap(rows, provider="openalex", min_gap_ms=200)
    s2_gaps = _assert_min_gap(rows, provider="semanticscholar", min_gap_ms=500)

    first_oa = min(int(row["reserved_at_epoch_ms"]) for row in rows if row["provider"] == "openalex")
    first_s2 = min(int(row["reserved_at_epoch_ms"]) for row in rows if row["provider"] == "semanticscholar")
    if abs(first_oa - first_s2) > 250:
        raise AssertionError("Providers appear to be blocking each other unexpectedly")

    return {
        "name": "provider_independence",
        "openalex_gaps_ms": oa_gaps,
        "semanticscholar_gaps_ms": s2_gaps,
        "first_reservation_delta_ms": abs(first_oa - first_s2),
    }


def test_future_guard() -> dict[str, Any]:
    store = InMemoryProviderRateLimitStore()
    now_ms = int(time.time() * 1000.0)
    store._next_allowed_ms["openalex"] = now_ms + 600_000  # pylint: disable=protected-access
    limiter = SharedProviderRateLimiter(
        provider="openalex",
        rps=5.0,
        store=store,
        holder="future_guard",
        run_id="future_guard",
        stage="future_guard",
        max_future_ms=1_000,
    )
    reservation = limiter.acquire()
    assert reservation is not None
    delta_ms = int(reservation.reserved_at_epoch_ms) - int(reservation.observed_at_epoch_ms)
    if delta_ms > 1_500:
        raise AssertionError(f"Future guard failed; reserved too far ahead: {delta_ms}ms")
    return {
        "name": "future_guard",
        "observed_at_epoch_ms": reservation.observed_at_epoch_ms,
        "reserved_at_epoch_ms": reservation.reserved_at_epoch_ms,
        "delta_ms": delta_ms,
    }


def test_firestore_parallel(*, collection_name: str) -> dict[str, Any]:
    store = FirestoreProviderRateLimitStore(collection_name=collection_name)
    providers = ["openalex", "semanticscholar"]
    delete_provider_rate_limit_docs(collection_name=collection_name, providers=providers)

    try:
        def one(provider: str, rps: float, worker_index: int, step: int) -> dict[str, Any]:
            limiter = SharedProviderRateLimiter(
                provider=provider,
                rps=rps,
                store=store,
                holder=f"{provider}-{worker_index}",
                run_id=f"{provider}-run-{worker_index}",
                stage="firestore_parallel",
                max_future_ms=60_000,
            )
            reservation = limiter.acquire()
            assert reservation is not None
            return {
                "provider": reservation.provider,
                "reserved_at_epoch_ms": reservation.reserved_at_epoch_ms,
                "worker": worker_index,
                "step": step,
            }

        rows: list[dict[str, Any]] = []
        rows.extend(_collect_parallel(workers=5, per_worker=2, fn=lambda worker, step: one("openalex", 5.0, worker, step)))
        rows.extend(
            _collect_parallel(
                workers=4,
                per_worker=2,
                fn=lambda worker, step: one("semanticscholar", 2.0, worker, step),
            )
        )

        oa_gaps = _assert_min_gap(rows, provider="openalex", min_gap_ms=200)
        s2_gaps = _assert_min_gap(rows, provider="semanticscholar", min_gap_ms=500)
        return {
            "name": "firestore_parallel",
            "collection_name": collection_name,
            "openalex_gaps_ms": oa_gaps,
            "semanticscholar_gaps_ms": s2_gaps,
            "count": len(rows),
        }
    finally:
        delete_provider_rate_limit_docs(collection_name=collection_name, providers=providers)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Test the shared Quellen-Finder provider rate limiter.")
    parser.add_argument("--firestore", action="store_true", help="Also run the live Firestore-backed limiter test.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    started_at = int(time.time())
    results = {
        "started_at_epoch_s": started_at,
        "tests": [],
    }

    tests = [
        test_in_memory_sequential,
        test_in_memory_parallel_contention,
        test_provider_independence,
        test_future_guard,
    ]
    for fn in tests:
        results["tests"].append(fn())

    if args.firestore:
        collection_name = f"quellenFinderProviderRateLimitsTest_{int(time.time())}"
        results["tests"].append(test_firestore_parallel(collection_name=collection_name))

    out = _write_result(
        f"test_two_lane_provider_rate_limit_{started_at}.json",
        results,
    )
    print(f"OK {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
