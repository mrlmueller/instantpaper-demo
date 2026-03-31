"""
Integration tests for Quellen-Finder provider throttling against a local fake HTTP server.

This script exercises the real pipeline request paths:
- Phase D OpenAlex retrieval
- Phase D Semantic Scholar retrieval
- Phase F Semantic Scholar recommendations

It validates:
- global spacing under concurrent runs
- actual output artifacts are populated
- optional Firestore-backed limiter works end to end
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from services.two_lane_sources.phase_f import s2_recommendations_expand
from services.two_lane_sources.pipeline import (
    OpenAlexQuery,
    PipelineConfig,
    S2BulkQuery,
    fetch_openalex_to_cache,
    fetch_s2_to_cache,
)
from services.two_lane_sources.provider_rate_limit import delete_provider_rate_limit_docs
from services.two_lane_sources.runner import _build_run_ctx


ARTIFACT_ROOT = BACKEND_ROOT / ".two_lane_artifacts" / "rate_limit_tests"


class _ServerState:
    def __init__(self):
        self.lock = threading.Lock()
        self.requests: list[dict[str, Any]] = []

    def record(self, *, provider: str, endpoint: str, path: str, method: str, params: dict[str, Any]) -> None:
        with self.lock:
            self.requests.append(
                {
                    "provider": provider,
                    "endpoint": endpoint,
                    "path": path,
                    "method": method,
                    "params": params,
                    "ts_monotonic": time.monotonic(),
                }
            )


class _FakeHandler(BaseHTTPRequestHandler):
    state: _ServerState

    def log_message(self, format, *args):  # noqa: A003
        return

    def _send_json(self, status: int, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}
        if parsed.path == "/works":
            self.state.record(provider="openalex", endpoint="works", path=parsed.path, method="GET", params=params)
            query_text = " ".join([str(params.get("search") or ""), str(params.get("filter") or "")])
            if "FORCE429" in query_text and str(params.get("api_key") or "").strip():
                payload = {"error": "insufficient budget", "message": "OpenAlex test budget exhausted"}
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(429)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Retry-After", "47684")
                self.send_header("X-RateLimit-Remaining", "0")
                self.send_header("X-RateLimit-Remaining-USD", "0")
                self.end_headers()
                self.wfile.write(data)
                return
            search = str(params.get("search") or params.get("filter") or "unknown")
            self._send_json(
                200,
                {
                    "results": [
                        {
                            "id": f"https://openalex.org/W_{abs(hash(search)) % 1_000_000}",
                            "doi": "10.1000/openalex-test",
                            "display_name": f"OpenAlex Test {search[:40]}",
                            "publication_year": 2024,
                            "type": "article",
                            "ids": {"openalex": "WTEST"},
                            "cited_by_count": 3,
                            "primary_location": {"source": {"display_name": "Journal of Tests"}},
                            "authorships": [{"author": {"display_name": "Test Author"}}],
                            "abstract_inverted_index": {"test": [0], "openalex": [1]},
                        }
                    ],
                    "meta": {"next_cursor": None},
                },
            )
            return

        if parsed.path == "/graph/v1/paper/search/bulk":
            self.state.record(provider="semanticscholar", endpoint="bulk", path=parsed.path, method="GET", params=params)
            query = str(params.get("query") or "query")
            self._send_json(
                200,
                {
                    "data": [
                        {"paperId": f"{query[:12]}-A"},
                        {"paperId": f"{query[:12]}-B"},
                    ],
                    "token": None,
                },
            )
            return

        self._send_json(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        body_raw = self.rfile.read(int(self.headers.get("Content-Length", "0") or 0))
        try:
            body = json.loads(body_raw.decode("utf-8")) if body_raw else {}
        except Exception:
            body = {}
        params = {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}

        if parsed.path == "/graph/v1/paper/batch":
            self.state.record(provider="semanticscholar", endpoint="batch", path=parsed.path, method="POST", params=params)
            ids = [str(x) for x in ((body or {}).get("ids") or [])]
            self._send_json(
                200,
                {
                    "data": [
                        {
                            "paperId": pid,
                            "title": f"Hydrated {pid}",
                            "year": 2024,
                            "authors": [{"name": "Test Author"}],
                            "venue": "Test Venue",
                            "url": f"https://example.org/{pid}",
                            "externalIds": {"DOI": f"10.1000/{pid.lower()}"},
                            "citationCount": 1,
                            "influentialCitationCount": 0,
                            "abstract": f"Abstract for {pid}",
                        }
                        for pid in ids
                    ]
                },
            )
            return

        if parsed.path == "/recommendations/v1/papers":
            self.state.record(provider="semanticscholar", endpoint="recommendations", path=parsed.path, method="POST", params=params)
            seed_ids = [str(x) for x in ((body or {}).get("positivePaperIds") or [])]
            seed = seed_ids[0] if seed_ids else "seed"
            self._send_json(
                200,
                {
                    "recommendedPapers": [
                        {"paperId": f"{seed}-REC-1"},
                        {"paperId": f"{seed}-REC-2"},
                    ]
                },
            )
            return

        self._send_json(404, {"error": "not found"})


def _write_result(name: str, payload: dict[str, Any]) -> Path:
    ARTIFACT_ROOT.mkdir(parents=True, exist_ok=True)
    out = ARTIFACT_ROOT / name
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    latest = ARTIFACT_ROOT / "test_two_lane_provider_pipeline_http_latest.json"
    latest.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def _provider_gaps(requests_: list[dict[str, Any]], provider: str) -> list[float]:
    rows = sorted([row for row in requests_ if row["provider"] == provider], key=lambda row: float(row["ts_monotonic"]))
    return [float(cur["ts_monotonic"]) - float(prev["ts_monotonic"]) for prev, cur in zip(rows, rows[1:])]


def _assert_min_gap(requests_: list[dict[str, Any]], *, provider: str, min_gap_s: float) -> list[float]:
    gaps = _provider_gaps(requests_, provider)
    for gap in gaps:
        if gap < float(min_gap_s):
            raise AssertionError(f"{provider} request gap too small: {gap:.3f}s < {min_gap_s:.3f}s")
    return gaps


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8") as handle:
        return sum(1 for line in handle if line.strip())


def _run_openalex_scenario(*, cfg: PipelineConfig, runs_root: Path, workers: int) -> dict[str, Any]:
    queries = [
        OpenAlexQuery(
            intent="match",
            language="en",
            search_field="title_and_abstract.search",
            query_string='("balance sheet" OR "BWA") AND ("automation" OR "LLM")',
            filters="is_paratext:false,is_retracted:false,language:en",
            sort="relevance_score:desc",
            per_page=200,
            notes="openalex fake 1",
        ),
        OpenAlexQuery(
            intent="authority",
            language="de",
            search_field="title_and_abstract.search",
            query_string='("Bilanz" OR "BWA") AND ("Dokumentenanalyse" OR "NLP")',
            filters="is_paratext:false,is_retracted:false,language:de",
            sort="cited_by_count:desc",
            per_page=200,
            notes="openalex fake 2",
        ),
    ]

    def worker(worker_index: int) -> dict[str, Any]:
        run_dir = runs_root / f"openalex_{worker_index}"
        run_ctx = _build_run_ctx(run_dir=run_dir, run_id=f"openalex_{worker_index}")
        run_ctx.create_artifact_skeleton(overwrite=True)
        meta = fetch_openalex_to_cache(cfg=cfg, run_ctx=run_ctx, queries=queries, force_rebuild=True)
        cache_lines = sum(_line_count(Path(path)) for path in meta["used_cache_paths"])
        return {
            "worker": worker_index,
            "records": int(meta["records"]),
            "records_fetched": int(meta["records_fetched"]),
            "cache_lines": cache_lines,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(worker, range(workers)))

    for row in rows:
        if int(row["records"]) <= 0 or int(row["cache_lines"]) <= 0:
            raise AssertionError(f"OpenAlex scenario produced no output for worker {row['worker']}")
    return {"workers": workers, "rows": rows}


def _run_openalex_key_fallback_scenario(*, cfg: PipelineConfig, runs_root: Path) -> dict[str, Any]:
    query = OpenAlexQuery(
        intent="match",
        language="en",
        search_field="title_and_abstract.search",
        query_string='FORCE429 AND "balance sheet" AND automation',
        filters="is_paratext:false,is_retracted:false,language:en",
        sort="relevance_score:desc",
        per_page=200,
        notes="openalex fallback",
    )
    run_dir = runs_root / "openalex_fallback"
    run_ctx = _build_run_ctx(run_dir=run_dir, run_id="openalex_fallback")
    run_ctx.create_artifact_skeleton(overwrite=True)
    meta = fetch_openalex_to_cache(cfg=cfg, run_ctx=run_ctx, queries=[query], force_rebuild=True)
    cache_lines = sum(_line_count(Path(path)) for path in meta["used_cache_paths"])
    if int(meta["records"]) <= 0 or int(cache_lines) <= 0:
        raise AssertionError(f"OpenAlex fallback scenario produced no output: {meta}")
    return {
        "records": int(meta["records"]),
        "records_fetched": int(meta["records_fetched"]),
        "cache_lines": int(cache_lines),
        "used_cache_paths": [str(path) for path in meta["used_cache_paths"]],
    }


def _run_s2_retrieval_scenario(*, cfg: PipelineConfig, runs_root: Path, workers: int) -> dict[str, Any]:
    queries = [
        S2BulkQuery(intent="match", language="en", query_string='"balance sheet" AND automation', notes="s2 fake 1"),
        S2BulkQuery(intent="authority", language="de", query_string='"Bilanz" AND Dokumentenanalyse', notes="s2 fake 2"),
    ]

    def worker(worker_index: int) -> dict[str, Any]:
        run_dir = runs_root / f"s2_retrieval_{worker_index}"
        run_ctx = _build_run_ctx(run_dir=run_dir, run_id=f"s2_retrieval_{worker_index}")
        run_ctx.create_artifact_skeleton(overwrite=True)
        meta = fetch_s2_to_cache(cfg=cfg, run_ctx=run_ctx, queries=queries, force_rebuild=True, bulk_limit=2)
        cache_lines = sum(_line_count(Path(path)) for path in meta["used_cache_paths"])
        return {
            "worker": worker_index,
            "records": int(meta["records"]),
            "records_fetched": int(meta["records_fetched"]),
            "cache_lines": cache_lines,
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(worker, range(workers)))

    for row in rows:
        if int(row["records"]) <= 0 or int(row["cache_lines"]) <= 0:
            raise AssertionError(f"S2 retrieval scenario produced no output for worker {row['worker']}")
    return {"workers": workers, "rows": rows}


def _run_s2_recommendations_scenario(*, cfg: PipelineConfig, runs_root: Path, workers: int) -> dict[str, Any]:
    def worker(worker_index: int) -> dict[str, Any]:
        run_dir = runs_root / f"s2_recs_{worker_index}"
        run_ctx = _build_run_ctx(run_dir=run_dir, run_id=f"s2_recs_{worker_index}")
        run_ctx.create_artifact_skeleton(overwrite=True)
        hydrated, meta = s2_recommendations_expand(
            cfg=cfg,
            run_ctx=run_ctx,
            seeds=[f"SEED-{worker_index}-A", f"SEED-{worker_index}-B"],
            limit=2,
        )
        return {
            "worker": worker_index,
            "hydrated": len(hydrated),
            "meta": meta,
            "artifact_lines": _line_count(run_ctx.artifacts.semanticscholar_recommendations_jsonl),
        }

    with ThreadPoolExecutor(max_workers=workers) as pool:
        rows = list(pool.map(worker, range(workers)))

    for row in rows:
        if int(row["hydrated"]) <= 0 or int(row["artifact_lines"]) <= 0:
            raise AssertionError(f"S2 recommendations scenario produced no output for worker {row['worker']}")
    return {"workers": workers, "rows": rows}


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run Quellen-Finder provider throttle integration tests against a fake local server.")
    parser.add_argument("--backend", choices=["local", "firestore"], default="local")
    parser.add_argument("--workers", type=int, default=4)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    started_at = int(time.time())
    state = _ServerState()

    handler_cls = type("FakeHandler", (_FakeHandler,), {"state": state})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    base_url = f"http://127.0.0.1:{server.server_port}"
    collection_name = f"quellenFinderProviderRateLimitsHttpTest_{started_at}"
    providers = ["openalex", "semanticscholar"]

    tmp_dir = Path(tempfile.mkdtemp(prefix="two_lane_http_rate_limit_"))
    try:
        if args.backend == "firestore":
            delete_provider_rate_limit_docs(collection_name=collection_name, providers=providers)

        cfg = PipelineConfig(
            runs_root=tmp_dir,
            pipeline_version="two_lane_v1",
            openalex_base_url=base_url,
            openalex_api_key="budget-exhausted-key",
            openalex_rps=5.0,
            semanticscholar_base_url=base_url + "/graph/v1",
            semanticscholar_recommendations_url=base_url + "/recommendations/v1/papers",
            semanticscholar_rps=2.0,
            provider_rate_limit_backend=args.backend,
            provider_rate_limit_collection=collection_name,
            force_rebuild=True,
        )

        openalex_result = _run_openalex_scenario(cfg=cfg, runs_root=tmp_dir, workers=args.workers)
        openalex_fallback_result = _run_openalex_key_fallback_scenario(cfg=cfg, runs_root=tmp_dir)
        s2_retrieval_result = _run_s2_retrieval_scenario(cfg=cfg, runs_root=tmp_dir, workers=args.workers)
        s2_recs_result = _run_s2_recommendations_scenario(cfg=cfg, runs_root=tmp_dir, workers=args.workers)

        openalex_gaps = _assert_min_gap(state.requests, provider="openalex", min_gap_s=0.16)
        s2_gaps = _assert_min_gap(state.requests, provider="semanticscholar", min_gap_s=0.42)
        openalex_fallback_requests = [
            row
            for row in state.requests
            if row["provider"] == "openalex" and "FORCE429" in json.dumps(row.get("params") or {})
        ]
        if len(openalex_fallback_requests) < 2:
            raise AssertionError(f"Expected at least two OpenAlex fallback requests, got {openalex_fallback_requests}")
        if not str((openalex_fallback_requests[0].get("params") or {}).get("api_key") or "").strip():
            raise AssertionError(f"Expected first OpenAlex fallback request to include api_key: {openalex_fallback_requests}")
        if str((openalex_fallback_requests[1].get("params") or {}).get("api_key") or "").strip():
            raise AssertionError(f"Expected second OpenAlex fallback request to drop api_key: {openalex_fallback_requests}")

        payload = {
            "backend": args.backend,
            "started_at_epoch_s": started_at,
            "base_url": base_url,
            "collection_name": collection_name if args.backend == "firestore" else None,
            "openalex": {
                "result": openalex_result,
                "fallback_result": openalex_fallback_result,
                "fallback_requests": openalex_fallback_requests,
                "request_gaps_s": openalex_gaps,
                "request_count": len([row for row in state.requests if row["provider"] == "openalex"]),
            },
            "semanticscholar_retrieval": {
                "result": s2_retrieval_result,
            },
            "semanticscholar_recommendations": {
                "result": s2_recs_result,
                "request_gaps_s": s2_gaps,
                "request_count": len([row for row in state.requests if row["provider"] == "semanticscholar"]),
            },
            "requests": state.requests,
        }

        out = _write_result(
            f"test_two_lane_provider_pipeline_http_{args.backend}_{started_at}.json",
            payload,
        )
        print(f"OK {out}")
        return 0
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5.0)
        if args.backend == "firestore":
            delete_provider_rate_limit_docs(collection_name=collection_name, providers=providers)
        shutil.rmtree(tmp_dir, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
