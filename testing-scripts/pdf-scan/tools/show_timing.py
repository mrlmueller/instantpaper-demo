#!/usr/bin/env python3
"""Show phase timings for a run."""
import json, sys

run_id = sys.argv[1] if len(sys.argv) > 1 else "a33419bf76ad298d82369172"
d = json.load(open(f"runs/{run_id}/metrics.json"))
for k, v in d["stages"].items():
    ms = v.get("elapsed_ms", "?")
    if isinstance(ms, (int, float)):
        print(f"  {k}: {ms:.0f} ms  ({ms/1000:.1f}s)")
    else:
        print(f"  {k}: {ms}")
