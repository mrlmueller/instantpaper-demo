# Exhaustive Benchmark Creation Report

Date: 2026-03-17
Suite: `full_dump_webshop_manual_v2_exhaustive`
Source run: `386e04657c41c805f8c1b974`

## What Was Created

A new exhaustive benchmark suite was created at:

- [full_dump_webshop_manual_v2_exhaustive](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive)

Main artifacts:

- [suite_manifest.json](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive/manifests/suite_manifest.json)
- [suite_summary.json](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive/suite_summary.json)
- [README.md](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive/README.md)
- [review_packets](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive/review_packets)
- [judgments](<projektverzeichnis>/pdf-scan/benchmark/full_dump_webshop_manual_v2_exhaustive/judgments)

## Scope

- `22` PDFs
- `574` exhaustive section judgments
- `166` gold sections with usefulness `>= 8/10`
- `2` explicit structural-miss entries
- `21` positive documents
- `1` negative document

## Judgment Design

Each document judgment file now contains:

- `has_useful_information`
- `document_label_0_to_3`
- `document_notes`
- `gold_section_refs`
- `near_miss_sections`
- `structural_miss_sections`
- exhaustive `section_judgments`

Section labels:

- `0`: not useful
- `1`: weak or marginal
- `2`: useful support
- `3`: core or strong support

## Provenance

This suite was built from:

- the full extracted section inventory
- the full section usefulness scoring pass
- the benchmark-target review pass
- document-level manual curation of the 22-paper set

## Important Limitation

This suite is a strong exhaustive benchmark foundation, but it is still a first exhaustive version, not a final immutable gold standard.

Why:

- every extracted section is represented
- the strongest useful regions, near misses, and structural misses are now encoded
- but not every single section entry has been individually hand-rewritten from scratch after generation

Practical interpretation:

- this suite is already strong enough to drive the next D/E/G optimization loop
- a later pure-manual correction pass can still improve consistency on marginal `1` vs `2` boundaries

## Recommended Use

Use this suite for:

- document-level recall / precision
- section-level hit@k
- false-negative analysis
- calibration analysis for Phase G
- category-aware evaluation by subtopic family

Do not yet use it as a final public benchmark without one more manual consistency pass.
