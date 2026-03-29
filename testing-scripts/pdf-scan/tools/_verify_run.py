"""Quick verification of a pipeline run's output."""

import json, sys
from pathlib import Path

run_path = Path(sys.argv[1])

out = json.load(open(run_path / "final" / "output.json", encoding="utf-8"))
print(f"=== output.json keys: {list(out.keys())}")

f_sum = json.load(open(run_path / "rerank" / "phase_f_summary.json", encoding="utf-8"))
print(f"\n=== Phase F Summary ===")
print(f"  cross_encoder_pairs: {f_sum.get('cross_encoder_pairs_scored', '?')}")
print(f"  judge_calls: {f_sum.get('judge_calls', '?')}")
print(f"  quality_band: {f_sum.get('quality_band', '?')}")

m = json.load(open(run_path / "metrics.json", encoding="utf-8"))
stages = m.get("stages", {})
for s in ["phase_f", "phase_g"]:
    st = stages.get(s, {})
    ms_val = st.get("elapsed_ms", 0)
    print(
        f"\n{s}: {ms_val/1000:.1f}s, status={st.get('status','?')}, band={st.get('quality_band','?')}"
    )

print(f"\nChapter: {out.get('chapter_title', '?')}")
print(
    f"Useful: {out.get('useful_pdf_count', '?')}, No-match: {out.get('no_match_pdf_count', '?')}"
)
print(f"Global top sections: {len(out.get('global_top_sections', []))}")

if "documents" in out:
    docs = out["documents"]
    print(f"\n=== Documents ({len(docs)}) ===")
    for doc in docs[:10]:
        useful = doc.get("has_useful_information", False)
        prob = doc.get("doc_match_probability", 0)
        title = doc.get("doc_title", "?")[:70]
        label = "USEFUL" if useful else "skip"
        print(f"  [{label}] p={prob:.2f} {title}")
