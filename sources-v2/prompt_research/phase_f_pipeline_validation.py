from __future__ import annotations

import ast
import json
import time
from array import array
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, Iterable, List


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNS_ROOT = REPO_ROOT / "sources-v2" / "runs"
EXTRACTED_PATH = REPO_ROOT / "sources-v2" / "sources_two_lane_extracted.py"
OUTPUT_DIR = REPO_ROOT / "sources-v2" / "prompt_research" / "probe_outputs"


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if isinstance(obj, dict):
                rows.append(obj)
    return rows


def _has_jsonl_data(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                return True
    return False


def _to_ns(obj: Any) -> Any:
    if isinstance(obj, dict):
        return SimpleNamespace(**{k: _to_ns(v) for k, v in obj.items()})
    if isinstance(obj, list):
        return [_to_ns(x) for x in obj]
    return obj


def _latest_runs(limit: int = 2) -> List[Path]:
    runs = [p for p in RUNS_ROOT.iterdir() if p.is_dir()]
    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    out: List[Path] = []
    for run_dir in runs:
        if _has_jsonl_data(run_dir / "candidates_expanded.jsonl") or _has_jsonl_data(run_dir / "candidates_normalized.jsonl"):
            out.append(run_dir)
        if len(out) >= limit:
            break
    return out


def _load_phase_f_helpers() -> Dict[str, Any]:
    source = EXTRACTED_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    wanted_assigns = {"_PHASE_F_JUNK_TITLES"}
    wanted_funcs = {
        "_f32_norm",
        "_f32_dot",
        "_cos",
        "_phase_f_clean_text",
        "_phase_f_clean_list",
        "_phase_f_normalized_title",
        "_phase_f_is_junk_title",
        "chapter_target_embed_text",
        "candidate_embed_text_main",
        "_phase_f_apply_hygiene_order",
        "_phase_f_apply_mmr_order",
    }
    parts = [
        "from __future__ import annotations",
        "import math",
        "import re",
        "from array import array",
        "from typing import Any, Dict, List, Optional",
        "QueryPlan = object",
    ]
    for node in tree.body:
        if isinstance(node, ast.Assign):
            names = {t.id for t in node.targets if isinstance(t, ast.Name)}
            if names & wanted_assigns:
                seg = ast.get_source_segment(source, node)
                if seg:
                    parts.append(seg)
        elif isinstance(node, ast.FunctionDef) and node.name in wanted_funcs:
            seg = ast.get_source_segment(source, node)
            if seg:
                parts.append(seg)
    ns: Dict[str, Any] = {}
    exec("\n\n".join(parts), ns)
    return ns


def _top_candidates(candidates: List[Dict[str, Any]], n: int = 5) -> List[Dict[str, Any]]:
    rows = sorted(
        candidates,
        key=lambda c: (int(c.get("citations") or 0), int(c.get("year") or 0)),
        reverse=True,
    )
    return rows[:n]


def _validate_run(run_dir: Path, helpers: Dict[str, Any]) -> Dict[str, Any]:
    plan_data = json.loads((run_dir / "query_plan.json").read_text(encoding="utf-8"))
    chapter_target_embed_text = helpers["chapter_target_embed_text"]
    candidate_embed_text_main = helpers["candidate_embed_text_main"]
    clean_text = helpers["_phase_f_clean_text"]
    normalized_title = helpers["_phase_f_normalized_title"]
    is_junk_title = helpers["_phase_f_is_junk_title"]
    apply_hygiene_order = helpers["_phase_f_apply_hygiene_order"]

    candidates_path = run_dir / "candidates_expanded.jsonl"
    if not candidates_path.exists():
        candidates_path = run_dir / "candidates_normalized.jsonl"
    candidates = list(_iter_jsonl(candidates_path))
    if not candidates:
        raise RuntimeError(f"No candidates in {candidates_path}")

    topic_title = "unknown"
    try:
        metrics = json.loads((run_dir / "metrics.json").read_text(encoding="utf-8"))
        topic_title = str((((metrics.get("stages") or {}).get("phase_a") or {}).get("inputs") or {}).get("chapter_title") or "unknown")
    except Exception:
        pass

    plan = _to_ns(plan_data)
    target_text = chapter_target_embed_text(
        plan,
        chapter_title=topic_title,
        chapter_spec_text=plan_data.get("topic_summary_en") or "",
    )
    assert "Core object terms EN:" in target_text
    assert "Must keep constraints:" in target_text
    assert "Drift risks:" in target_text

    cleaned_titles = sum(1 for c in candidates if clean_text(c.get("title")) != str(c.get("title") or "").strip())
    junk_titles = sum(1 for c in candidates if is_junk_title(c.get("title")))
    norm_titles = [normalized_title(c.get("title")) for c in candidates]
    dup_titles = len([t for t in norm_titles if t]) - len(set([t for t in norm_titles if t]))

    with_abs = [c for c in candidates if str(c.get("pool") or "") == "with_abstract" and str(c.get("abstract") or "").strip()]
    sample_doc = with_abs[0] if with_abs else candidates[0]
    doc_text = candidate_embed_text_main(
        sample_doc,
        abstract_chars=800,
        include_venue=True,
        include_year=True,
        include_authors=False,
    )
    assert "Title:" in doc_text
    assert ("Abstract:" in doc_text) == bool(str(sample_doc.get("abstract") or "").strip())
    assert "Authors:" not in doc_text

    top_ids = [str(c.get("id") or "") for c in _top_candidates(candidates, n=200)]
    hygiene_stats: Dict[str, Any] = {"junk_title_dropped": 0, "duplicate_title_suppressed": 0}
    filtered_ids = apply_hygiene_order(
        top_ids,
        cand_by_id={str(c.get("id") or ""): c for c in candidates},
        stats=hygiene_stats,
    )
    filtered_norms = [normalized_title((next(c for c in candidates if str(c.get("id") or "") == cid)).get("title")) for cid in filtered_ids]
    assert len(filtered_norms) == len(set(filtered_norms))

    return {
        "run_id": run_dir.name,
        "candidates_path": str(candidates_path),
        "candidates": len(candidates),
        "with_abstract": len(with_abs),
        "cleaned_titles": cleaned_titles,
        "junk_titles": junk_titles,
        "duplicate_normalized_titles": dup_titles,
        "target_chars": len(target_text),
        "sample_doc_chars": len(doc_text),
        "hygiene_input": len(top_ids),
        "hygiene_output": len(filtered_ids),
        "hygiene_dropped_junk": int(hygiene_stats.get("junk_title_dropped") or 0),
        "hygiene_suppressed_duplicates": int(hygiene_stats.get("duplicate_title_suppressed") or 0),
    }


def _validate_mmr(helpers: Dict[str, Any]) -> Dict[str, Any]:
    mmr = helpers["_phase_f_apply_mmr_order"]
    vecs = {
        "A": array("f", [1.0, 0.0]),
        "B": array("f", [0.999, 0.02]),
        "C": array("f", [0.0, 1.0]),
        "D": array("f", [0.1, 0.99]),
    }
    norm = helpers["_f32_norm"]
    inv = {k: 1.0 / (norm(v) or 1.0) for k, v in vecs.items()}
    order = mmr(
        ["A", "B", "C", "D"],
        score_by_id={"A": 0.95, "B": 0.94, "C": 0.90, "D": 0.88},
        vec_by_id=vecs,
        invnorm_by_id=inv,
        top_k=2,
        lambda_mult=0.82,
    )
    assert order[:2] == ["A", "C"], f"Unexpected MMR order: {order[:2]}"
    return {"expected_top2": ["A", "C"], "actual_top2": order[:2]}


def _write_md(path: Path, payload: Dict[str, Any]) -> None:
    lines: List[str] = []
    lines.append("# Phase F Pipeline Validation")
    lines.append("")
    lines.append(f"- generated_at: `{payload['generated_at']}`")
    lines.append(f"- extracted_file: `{payload['extracted_file']}`")
    lines.append("")
    lines.append("## Synthetic MMR")
    lines.append("")
    lines.append(f"- expected_top2: `{payload['mmr']['expected_top2']}`")
    lines.append(f"- actual_top2: `{payload['mmr']['actual_top2']}`")
    for run in payload["runs"]:
        lines.append("")
        lines.append(f"## Run `{run['run_id']}`")
        lines.append("")
        lines.append(f"- candidates: `{run['candidates']}`")
        lines.append(f"- with_abstract: `{run['with_abstract']}`")
        lines.append(f"- cleaned_titles: `{run['cleaned_titles']}`")
        lines.append(f"- junk_titles: `{run['junk_titles']}`")
        lines.append(f"- duplicate_normalized_titles: `{run['duplicate_normalized_titles']}`")
        lines.append(f"- target_chars: `{run['target_chars']}`")
        lines.append(f"- sample_doc_chars: `{run['sample_doc_chars']}`")
        lines.append(f"- hygiene_input/output: `{run['hygiene_input']}` / `{run['hygiene_output']}`")
        lines.append(f"- hygiene_dropped_junk: `{run['hygiene_dropped_junk']}`")
        lines.append(f"- hygiene_suppressed_duplicates: `{run['hygiene_suppressed_duplicates']}`")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    helpers = _load_phase_f_helpers()
    runs = _latest_runs(limit=2)
    results = [_validate_run(run_dir, helpers) for run_dir in runs]
    mmr = _validate_mmr(helpers)
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "extracted_file": str(EXTRACTED_PATH),
        "runs": results,
        "mmr": mmr,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    slug = time.strftime("%Y%m%d-%H%M%S")
    json_path = OUTPUT_DIR / f"phase_f_pipeline_validation_{slug}.json"
    md_path = OUTPUT_DIR / f"phase_f_pipeline_validation_{slug}.summary.md"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_md(md_path, payload)
    print(json.dumps({"json": str(json_path), "summary": str(md_path)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
