from __future__ import annotations

import logging
from collections import defaultdict
from pathlib import Path
from typing import Any

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.pdf_scan.common import (
    VISIBLE_SCORE_THRESHOLD,
    _as_float,
    _as_int_or_none,
    _as_str_or_none,
    _build_preview_sections,
    _normalize_abs_path,
    _read_json,
    _read_jsonl,
    _trim_text,
)

logger = logging.getLogger(__name__)


def _load_section_locator_index(run_dir: Path, doc_id: str) -> dict[str, dict[str, Any]]:
    doc_dir = run_dir / "normalized" / doc_id
    all_sections = _read_jsonl(doc_dir / "sections.jsonl")
    return {
        _as_str_or_none(row.get("section_id")) or "": row
        for row in all_sections
        if _as_str_or_none(row.get("section_id"))
    }


def _map_doc_to_pdf_snapshot(
    *,
    document_row: dict[str, Any],
    manifest_by_source_path: dict[str, dict[str, Any]],
    pdf_snapshot_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    source_path = _normalize_abs_path(document_row.get("source_path"))
    manifest_row = dict(manifest_by_source_path.get(source_path) or {})

    pdf_snapshot = None
    manifest_path = _normalize_abs_path(manifest_row.get("path"))
    if manifest_path:
        for snapshot in pdf_snapshot_by_id.values():
            if _normalize_abs_path(snapshot.get("localPath")) == manifest_path:
                pdf_snapshot = snapshot
                break
    return pdf_snapshot, manifest_row


def _build_evidence_preview_rows(row: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_preview_rows = []
    for item in list(row.get("evidence_preview") or [])[:3]:
        if not isinstance(item, dict):
            continue
        evidence_preview_rows.append(
            {
                "pageStart": _as_int_or_none(item.get("page_start")),
                "pageEnd": _as_int_or_none(item.get("page_end")),
                "lanes": list(item.get("lanes") or [])[:4],
                "text": _trim_text(item.get("text"), max_chars=340),
            }
        )
    return evidence_preview_rows


def build_persisted_pdf_scan_v2_view(
    *,
    run_dir: Path,
    pdf_snapshot_by_id: dict[str, dict[str, Any]],
    kapitel_snapshots: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    run_dir = Path(run_dir).resolve()
    config = _read_json(run_dir / "config.json")
    manifest_payload = _read_json(run_dir / "pdf_manifest.json")
    phase_b_summary_payload = (
        _read_json(run_dir / "parser" / "phase_b_summary.json")
        if (run_dir / "parser" / "phase_b_summary.json").exists()
        else {}
    )
    aggregate_output = (
        _read_json(run_dir / "aggregate" / "output.json")
        if (run_dir / "aggregate" / "output.json").exists()
        else {}
    )

    document_rows = _read_jsonl(run_dir / "normalized" / "documents.jsonl")
    document_by_doc_id = {
        _as_str_or_none(row.get("doc_id")) or "": row
        for row in document_rows
        if _as_str_or_none(row.get("doc_id"))
    }
    manifest_rows = list((manifest_payload or {}).get("pdfs") or [])
    manifest_by_source_path = {
        _normalize_abs_path(row.get("path")): row for row in manifest_rows if _normalize_abs_path(row.get("path"))
    }
    kapitel_snapshot_by_id = {
        str(row.get("id") or "").strip(): row
        for row in list(kapitel_snapshots or [])
        if isinstance(row, dict) and str(row.get("id") or "").strip()
    }

    chapter_configs = [row for row in list((config or {}).get("chapters") or []) if isinstance(row, dict)]
    aggregate_chapter_rows = {
        str(row.get("chapter_id") or "").strip(): row
        for row in list((aggregate_output or {}).get("chapter_results") or [])
        if isinstance(row, dict) and str(row.get("chapter_id") or "").strip()
    }

    chapter_docs: list[tuple[str, dict[str, Any]]] = []
    chapter_doc_docs: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    chapter_section_docs: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    section_identity_map: dict[str, dict[str, Any]] = {}
    aggregate_doc_docs: list[tuple[str, dict[str, Any]]] = []
    aggregate_section_docs: list[tuple[str, dict[str, Any]]] = []

    phase_b_counts = (((phase_b_summary_payload or {}).get("assessment") or {}).get("counts") or {})
    had_partial_failures = bool(
        _as_int_or_none(phase_b_counts.get("bundle_failure_count"))
        or ((_as_int_or_none(phase_b_counts.get("documents_processed")) or 0) < (_as_int_or_none(phase_b_counts.get("selected_count")) or 0))
    )

    total_chapter_doc_count = 0
    total_chapter_section_count = 0
    total_visible_section_count = 0

    for chapter_order, chapter in enumerate(chapter_configs):
        chapter_id = str(chapter.get("chapter_id") or "").strip()
        if not chapter_id:
            continue
        chapter_title = str(chapter.get("chapter_title") or "").strip()
        chapter_dir = run_dir / "chapters" / chapter_id
        final_dir = chapter_dir / "final"
        output_path = final_dir / "output.json"
        doc_features_path = final_dir / "doc_features.jsonl"
        section_scores_path = final_dir / "section_scores.jsonl"
        chapter_status_row = dict(aggregate_chapter_rows.get(chapter_id) or {})
        chapter_status = str(chapter_status_row.get("status") or "")

        chapter_doc_rows_raw = _read_jsonl(doc_features_path) if doc_features_path.exists() else []
        chapter_section_rows_all = _read_jsonl(section_scores_path) if section_scores_path.exists() else []
        chapter_section_rows_visible_raw = [
            row for row in chapter_section_rows_all if _as_float(row.get("score_0_to_100")) >= float(VISIBLE_SCORE_THRESHOLD)
        ]

        # Downstream phases can still emit duplicate doc_ids when multiple selected project PDFs
        # resolve to the same normalized pipeline document. Persist each pipeline doc only once
        # per chapter so Firestore doc ids remain stable and verification matches actual writes.
        chapter_doc_rows_by_doc_id: dict[str, dict[str, Any]] = {}
        for row in list(chapter_doc_rows_raw):
            doc_id = _as_str_or_none(row.get("doc_id"))
            if not doc_id:
                continue
            existing = chapter_doc_rows_by_doc_id.get(doc_id)
            candidate_key = (
                bool(row.get("has_useful_information")),
                _as_float(row.get("doc_match_probability")),
                _as_float(row.get("top_section_score")),
            )
            existing_key = (
                bool((existing or {}).get("has_useful_information")),
                _as_float((existing or {}).get("doc_match_probability")),
                _as_float((existing or {}).get("top_section_score")),
            )
            if existing is None or candidate_key > existing_key:
                chapter_doc_rows_by_doc_id[doc_id] = row
        chapter_doc_rows = list(chapter_doc_rows_by_doc_id.values())

        chapter_section_rows_visible: list[dict[str, Any]] = []
        seen_visible_section_keys: set[tuple[str, str]] = set()
        for row in list(chapter_section_rows_visible_raw):
            doc_id = _as_str_or_none(row.get("doc_id"))
            section_id = _as_str_or_none(row.get("section_id"))
            if not doc_id or not section_id:
                continue
            dedupe_key = (doc_id, section_id)
            if dedupe_key in seen_visible_section_keys:
                continue
            seen_visible_section_keys.add(dedupe_key)
            chapter_section_rows_visible.append(row)

        visible_sections_by_doc_id: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in chapter_section_rows_visible:
            doc_id = _as_str_or_none(row.get("doc_id"))
            if doc_id:
                visible_sections_by_doc_id[doc_id].append(row)

        section_locator_cache: dict[str, dict[str, dict[str, Any]]] = {}
        chapter_doc_payloads: list[tuple[str, dict[str, Any]]] = []
        chapter_section_payloads: list[tuple[str, dict[str, Any]]] = []

        sorted_chapter_doc_rows = sorted(
            list(chapter_doc_rows),
            key=lambda row: (
                bool(row.get("has_useful_information")),
                _as_float(row.get("doc_match_probability")),
                _as_float(row.get("top_section_score")),
            ),
            reverse=True,
        )

        for chapter_rank, doc_feature_row in enumerate(sorted_chapter_doc_rows, start=1):
            doc_id = _as_str_or_none(doc_feature_row.get("doc_id"))
            if not doc_id:
                had_partial_failures = True
                continue
            document_row = dict(document_by_doc_id.get(doc_id) or {})
            pdf_snapshot, manifest_row = _map_doc_to_pdf_snapshot(
                document_row=document_row,
                manifest_by_source_path=manifest_by_source_path,
                pdf_snapshot_by_id=pdf_snapshot_by_id,
            )
            if pdf_snapshot is None:
                had_partial_failures = True
                logger.warning("PDF scan v2 persistence could not map doc_id=%s back to a project PDF", doc_id)
                continue
            pdf_id = _as_str_or_none(pdf_snapshot.get("id"))
            if not pdf_id:
                had_partial_failures = True
                continue

            visible_rows = sorted(
                list(visible_sections_by_doc_id.get(doc_id) or []),
                key=lambda row: (_as_float(row.get("score_0_to_100")), -(_as_int_or_none(row.get("doc_rank")) or 10_000)),
                reverse=True,
            )

            summary_payload = {
                "chapterId": chapter_id,
                "chapterOrder": chapter_order,
                "chapterTitle": chapter_title or None,
                "chapterRank": chapter_rank,
                "docId": doc_id,
                "pdfId": pdf_id,
                "pdfFilename": _as_str_or_none(pdf_snapshot.get("filename")),
                "pdfLabel": _as_str_or_none(manifest_row.get("label")) or _as_str_or_none(pdf_snapshot.get("filename")) or doc_id,
                "docTitle": _as_str_or_none(document_row.get("title")) or _as_str_or_none(manifest_row.get("label")) or doc_id,
                "pageCount": _as_int_or_none(document_row.get("page_count")),
                "sectionCount": _as_int_or_none(document_row.get("section_count")),
                "acceptedHeadingCount": _as_int_or_none(document_row.get("accepted_heading_count")),
                "strategy": _as_str_or_none(document_row.get("strategy")),
                "doclingStatus": _as_str_or_none(document_row.get("docling_status")),
                "hasOutline": bool(document_row.get("has_outline")),
                "outlineCount": _as_int_or_none(manifest_row.get("outline_count") or document_row.get("outline_count")),
                "qualityFlags": list(document_row.get("quality_flags") or [])[:12],
                "hasUsefulInformation": bool(doc_feature_row.get("has_useful_information")),
                "docMatchProbability": round(_as_float(doc_feature_row.get("doc_match_probability")), 3),
                "topSectionScore": round(_as_float(doc_feature_row.get("top_section_score")), 1),
                "topSectionTitle": _trim_text(doc_feature_row.get("top_section_title"), max_chars=220),
                "visibleSectionCount": int(len(visible_rows)),
                "previewSections": _build_preview_sections(visible_rows, limit=3),
                "createdAt": SERVER_TIMESTAMP,
            }
            chapter_doc_payloads.append((doc_id, summary_payload))

            if doc_id not in section_locator_cache:
                section_locator_cache[doc_id] = _load_section_locator_index(run_dir, doc_id)
            section_locator_by_id = section_locator_cache[doc_id]

            for row in visible_rows:
                section_id = _as_str_or_none(row.get("section_id"))
                if not section_id:
                    had_partial_failures = True
                    continue
                locator_row = dict(section_locator_by_id.get(section_id) or {})
                heading_anchor = locator_row.get("heading_anchor") if isinstance(locator_row.get("heading_anchor"), dict) else {}
                span = locator_row.get("span") if isinstance(locator_row.get("span"), dict) else {}
                section_doc_id = f"{doc_id}__{section_id}"
                section_payload = {
                    "chapterId": chapter_id,
                    "chapterOrder": chapter_order,
                    "chapterTitle": chapter_title or None,
                    "docId": doc_id,
                    "pdfId": pdf_id,
                    "pdfFilename": _as_str_or_none(pdf_snapshot.get("filename")),
                    "pdfLabel": summary_payload["pdfLabel"],
                    "docTitle": summary_payload["docTitle"],
                    "sectionId": section_id,
                    "title": _trim_text(row.get("title"), max_chars=260),
                    "sectionPath": list(row.get("section_path") or []),
                    "sectionPathText": _trim_text(" / ".join(list(row.get("section_path") or [])) or row.get("title"), max_chars=400),
                    "sectionType": _as_str_or_none(row.get("section_type")) or "body_other",
                    "pageStart": _as_int_or_none(row.get("page_start")),
                    "pageEnd": _as_int_or_none(row.get("page_end")),
                    "score0To100": round(_as_float(row.get("score_0_to_100")), 1),
                    "scoreBand": _as_str_or_none(row.get("score_band")),
                    "supportStrength": round(_as_float(row.get("support_strength")), 3),
                    "supportingPassageCount": _as_int_or_none(row.get("supporting_passage_count")),
                    "subpointCoverageIds": list(row.get("subpoint_coverage_ids") or [])[:12],
                    "qualityFlags": list(row.get("quality_flags") or [])[:12],
                    "globalRank": _as_int_or_none(row.get("global_rank")),
                    "docRank": _as_int_or_none(row.get("doc_rank")),
                    "headingAnchor": {
                        "page": _as_int_or_none(heading_anchor.get("page")),
                        "blockIndex": _as_int_or_none(heading_anchor.get("block_index")),
                        "absBlockIndex": _as_int_or_none(heading_anchor.get("abs_block_index")),
                        "method": _as_str_or_none(heading_anchor.get("method")),
                        "confidence": _as_float(heading_anchor.get("confidence"), 0.0),
                    },
                    "span": {
                        "startAbsBlockIndex": _as_int_or_none(span.get("start_abs_block_index")),
                        "endAbsBlockIndex": _as_int_or_none(span.get("end_abs_block_index")),
                        "blockCount": _as_int_or_none(span.get("block_count")),
                    },
                    "anchorPage": _as_int_or_none((heading_anchor or {}).get("page")),
                    "evidencePreview": _build_evidence_preview_rows(row),
                    "createdAt": SERVER_TIMESTAMP,
                }
                chapter_section_payloads.append((section_doc_id, section_payload))
                section_identity_map.setdefault(section_id, section_payload)

        chapter_doc_docs[chapter_id] = chapter_doc_payloads
        chapter_section_docs[chapter_id] = chapter_section_payloads
        total_chapter_doc_count += len(chapter_doc_payloads)
        total_chapter_section_count += len(chapter_section_payloads)
        total_visible_section_count += len(chapter_section_payloads)
        useful_pdf_count = sum(
            1 for _doc_id, payload in chapter_doc_payloads if bool(payload.get("hasUsefulInformation"))
        )

        kapitel_snapshot = dict(kapitel_snapshot_by_id.get(chapter_id) or {})
        chapter_docs.append(
            (
                chapter_id,
                {
                    "chapterId": chapter_id,
                    "chapterOrder": chapter_order,
                    "kapitelSnapshot": {
                        "id": chapter_id,
                        "nummer": _as_str_or_none(kapitel_snapshot.get("nummer")),
                        "title": _as_str_or_none(kapitel_snapshot.get("title") or kapitel_snapshot.get("ueberschrift")),
                        "ueberschrift": _as_str_or_none(kapitel_snapshot.get("ueberschrift") or kapitel_snapshot.get("title")),
                        "thema": _trim_text(kapitel_snapshot.get("thema"), max_chars=2400),
                    },
                    "status": chapter_status or ("success" if output_path.exists() else "error"),
                    "errorMessage": chapter_status_row.get("error"),
                    "usefulPdfCount": int(useful_pdf_count),
                    "documentCount": int(len(chapter_doc_payloads)),
                    "visibleSectionCount": int(len(chapter_section_payloads)),
                    "topSectionCount": int(min(len(list(chapter_status_row.get("global_top_sections") or [])), 10)),
                    "outputPath": str(chapter_status_row.get("paths", {}).get("output_path") or "") or None,
                    "docFeaturesPath": str(chapter_status_row.get("paths", {}).get("doc_features_path") or "") or None,
                    "sectionScoresPath": str(chapter_status_row.get("paths", {}).get("section_scores_path") or "") or None,
                    "createdAt": SERVER_TIMESTAMP,
                    "updatedAt": SERVER_TIMESTAMP,
                },
            )
        )

    aggregate_document_rows = list((aggregate_output or {}).get("document_matrix") or [])
    for row in aggregate_document_rows:
        if not isinstance(row, dict):
            continue
        doc_id = _as_str_or_none(row.get("doc_id"))
        if not doc_id:
            had_partial_failures = True
            continue
        document_row = dict(document_by_doc_id.get(doc_id) or {})
        pdf_snapshot, manifest_row = _map_doc_to_pdf_snapshot(
            document_row=document_row,
            manifest_by_source_path=manifest_by_source_path,
            pdf_snapshot_by_id=pdf_snapshot_by_id,
        )
        if pdf_snapshot is None:
            had_partial_failures = True
            continue
        pdf_id = _as_str_or_none(pdf_snapshot.get("id"))
        if not pdf_id:
            had_partial_failures = True
            continue
        aggregate_doc_docs.append(
            (
                doc_id,
                {
                    "pdfId": pdf_id,
                    "docId": doc_id,
                    "pdfFilename": _as_str_or_none(pdf_snapshot.get("filename")),
                    "pdfLabel": _as_str_or_none(manifest_row.get("label")) or _as_str_or_none(pdf_snapshot.get("filename")) or doc_id,
                    "docTitle": _as_str_or_none(document_row.get("title")) or _as_str_or_none(manifest_row.get("label")) or doc_id,
                    "usefulForChapters": list(row.get("useful_for_chapters") or []),
                    "usefulChapterCount": int(row.get("useful_chapter_count") or 0),
                    "bestChapterMatch": row.get("best_chapter_match") if isinstance(row.get("best_chapter_match"), dict) else None,
                    "perChapter": row.get("per_chapter") if isinstance(row.get("per_chapter"), dict) else {},
                    "createdAt": SERVER_TIMESTAMP,
                },
            )
        )

    multi_chapter_sections = (((aggregate_output or {}).get("multi_chapter_sections") or {}).get("sections") or {})
    for section_id, chapter_ids in sorted(multi_chapter_sections.items()):
        if not isinstance(chapter_ids, list):
            continue
        section_payload = dict(section_identity_map.get(str(section_id)) or {})
        if not section_payload:
            had_partial_failures = True
            logger.warning("PDF scan v2 persistence could not resolve aggregate section metadata | section_id=%s", section_id)
            continue
        aggregate_section_doc_id = f"{section_payload.get('docId')}__{section_id}"
        aggregate_section_docs.append(
            (
                aggregate_section_doc_id,
                {
                    "pdfId": section_payload.get("pdfId"),
                    "docId": section_payload.get("docId"),
                    "docTitle": section_payload.get("docTitle"),
                    "sectionId": section_id,
                    "title": section_payload.get("title"),
                    "sectionType": section_payload.get("sectionType"),
                    "pageStart": section_payload.get("pageStart"),
                    "pageEnd": section_payload.get("pageEnd"),
                    "chapterIds": list(chapter_ids),
                    "chapterCount": int(len(chapter_ids)),
                    "createdAt": SERVER_TIMESTAMP,
                },
            )
        )

    useful_pdf_count_any_chapter = sum(
        1 for _doc_id, payload in aggregate_doc_docs if int(payload.get("usefulChapterCount") or 0) > 0
    )
    useful_chapter_pair_count = sum(
        int(payload.get("usefulChapterCount") or 0) for _doc_id, payload in aggregate_doc_docs
    )
    chapter_preview = []
    for chapter_id, chapter_payload in chapter_docs:
        kapitel_snapshot = chapter_payload.get("kapitelSnapshot") if isinstance(chapter_payload.get("kapitelSnapshot"), dict) else {}
        chapter_preview.append(
            {
                "chapterId": chapter_id,
                "nummer": _as_str_or_none((kapitel_snapshot or {}).get("nummer")),
                "title": _as_str_or_none((kapitel_snapshot or {}).get("title")),
            }
        )

    aggregate_status = str((aggregate_output or {}).get("status") or "error")
    run_summary = {
        "chapterCount": int(len(chapter_docs)),
        "completedChapterCount": int(len(list((aggregate_output or {}).get("completed_chapters") or []))),
        "failedChapterCount": int(len(list((aggregate_output or {}).get("failed_chapters") or []))),
        "documentCount": int(len(aggregate_doc_docs)),
        "usefulPdfCountAnyChapter": int(useful_pdf_count_any_chapter),
        "usefulChapterPairCount": int(useful_chapter_pair_count),
        "multiChapterSectionCount": int(len(aggregate_section_docs)),
        "totalVisibleSectionCount": int(total_visible_section_count),
        "aggregateStatus": aggregate_status,
    }
    run_counts = {
        "aggregateDocCount": int(len(aggregate_doc_docs)),
        "aggregateSectionCount": int(len(aggregate_section_docs)),
        "chapterDocCount": int(total_chapter_doc_count),
        "chapterSectionCount": int(total_chapter_section_count),
    }
    run_display = {
        "runLabel": f"{len(chapter_docs)} Kapitel • {len(pdf_snapshot_by_id)} PDFs",
        "chapterPreview": chapter_preview[:6],
        "chapterCountLabel": f"{len(chapter_docs)} Kapitel",
    }

    return {
        "root_update": {
            "pdfScanSchemaVersion": 2,
            "pdfScanMode": "chapter_matrix",
            "chapterInputMode": "single" if len(chapter_docs) == 1 else "multi",
            "pdfScanSummary": run_summary,
            "pdfScanCounts": run_counts,
            "pdfScanDisplay": run_display,
        },
        "chapter_docs": chapter_docs,
        "chapter_doc_docs": chapter_doc_docs,
        "chapter_section_docs": chapter_section_docs,
        "aggregate_doc_docs": aggregate_doc_docs,
        "aggregate_section_docs": aggregate_section_docs,
        "useful_pdf_count_any_chapter": int(useful_pdf_count_any_chapter),
        "total_visible_section_count": int(total_visible_section_count),
        "had_partial_failures": bool(had_partial_failures or aggregate_status == "partial_success"),
    }
