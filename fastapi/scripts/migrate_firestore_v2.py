from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore


MAX_TEXT_WORDS = 7000
MAX_TEXT_CHARS = 140000


def _load_fastapi_env() -> None:
    """
    Load `fastapi/.env` regardless of current working directory.

    The FastAPI app uses `python-dotenv` via `fastapi/utils/config.py`. When this
    script is run from the repo root, we still want the same env.
    """
    fastapi_dir = Path(__file__).resolve().parents[1]
    env_path = fastapi_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)
    else:
        load_dotenv(override=True)


def _require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def _init_firestore():
    if firebase_admin._apps:
        return firestore.client()

    project_id = _require_env("FIREBASE_PROJECT_ID")
    private_key = _require_env("FIREBASE_PRIVATE_KEY").replace("\\n", "\n")
    client_email = _require_env("FIREBASE_CLIENT_EMAIL")

    cred_dict = {
        "type": "service_account",
        "project_id": project_id,
        "private_key": private_key,
        "client_email": client_email,
        "token_uri": "https://oauth2.googleapis.com/token",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
    }

    firebase_admin.initialize_app(credentials.Certificate(cred_dict))
    return firestore.client()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_datetime(value: str) -> Optional[datetime]:
    v = value.strip()
    if not v:
        return None
    if v.endswith("Z"):
        v = v[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _to_dt(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, str):
        return _parse_iso_datetime(value)
    return None


def _coerce_ts(value: Any, fallback: datetime) -> datetime:
    dt = _to_dt(value)
    return dt if dt is not None else fallback


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _count_words(text: str) -> int:
    return len([w for w in text.split() if w])


def _enforce_text_limits(
    *, text: str, doc_path: str, truncate_long_texts: bool
) -> tuple[str, int]:
    word_count = _count_words(text)
    if word_count <= MAX_TEXT_WORDS and len(text) <= MAX_TEXT_CHARS:
        return text, word_count

    if not truncate_long_texts:
        raise RuntimeError(
            f"Text too large at {doc_path}: {word_count} words / {len(text)} chars "
            f"(limits: {MAX_TEXT_WORDS} words, {MAX_TEXT_CHARS} chars). "
            "Re-run with --truncate-long-texts to hard-truncate."
        )

    words = [w for w in text.split() if w]
    truncated = " ".join(words[:MAX_TEXT_WORDS])
    truncated = truncated[:MAX_TEXT_CHARS]
    return truncated, _count_words(truncated)


def _usage_from_tokens(
    *,
    total_tokens: Any = None,
    input_tokens: Any = None,
    cached_input_tokens: Any = None,
    output_tokens: Any = None,
    reasoning_tokens: Any = None,
) -> dict:
    input_t = _as_int(input_tokens)
    cached_t = _as_int(cached_input_tokens)
    output_t = _as_int(output_tokens)
    reasoning_t = _as_int(reasoning_tokens)
    total_t = _as_int(total_tokens, default=input_t + output_t + reasoning_t)
    return {
        "inputTokens": input_t,
        "cachedInputTokens": cached_t,
        "outputTokens": output_t,
        "reasoningTokens": reasoning_t,
        "totalTokens": total_t,
    }


def _normalize_usage_map(usage: Any) -> dict:
    if not isinstance(usage, dict):
        return _usage_from_tokens()
    return _usage_from_tokens(
        total_tokens=usage.get("totalTokens")
        or usage.get("total_tokens")
        or usage.get("tokens_used"),
        input_tokens=usage.get("inputTokens")
        or usage.get("input_tokens")
        or usage.get("input"),
        cached_input_tokens=usage.get("cachedInputTokens")
        or usage.get("cached_input_tokens")
        or usage.get("cached_input"),
        output_tokens=usage.get("outputTokens")
        or usage.get("output_tokens")
        or usage.get("output"),
        reasoning_tokens=usage.get("reasoningTokens")
        or usage.get("reasoning_tokens")
        or 0,
    )


def _normalize_refinement(
    doc: dict, *, created_at: datetime, default_max_depth: int
) -> dict:
    active = (
        doc.get("refinementActiveVersionId")
        or doc.get("refinement_active_version_id")
        or doc.get("refinement_active_version")
        or "root"
    )
    max_depth = _as_int(
        doc.get("refinementMaxDepth") or doc.get("refinement_max_depth"),
        default=default_max_depth,
    )
    cost_total = _as_float(
        doc.get("refinementCostTotal") or doc.get("refinement_cost_total"), default=0.0
    )
    initialized_at = _coerce_ts(
        doc.get("refinementInitializedAt") or doc.get("refinement_initialized_at"),
        created_at,
    )
    selected_at = _to_dt(
        doc.get("refinementSelectedAt") or doc.get("refinement_selected_at")
    )

    out = {
        "rootVersionId": "root",
        "activeVersionId": str(active),
        "maxDepth": max_depth,
        "costTotalUsd": cost_total,
        "initializedAt": initialized_at,
    }
    if selected_at is not None:
        out["selectedAt"] = selected_at
    return out


def _normalize_version(doc: dict) -> dict:
    created_at = _coerce_ts(doc.get("createdAt") or doc.get("created_at"), _utc_now())
    updated_at = _to_dt(doc.get("updatedAt") or doc.get("updated_at"))

    out = {
        "parentVersionId": (
            doc.get("parentVersionId")
            if "parentVersionId" in doc
            else doc.get("parent_version_id")
        ),
        "depth": _as_int(doc.get("depth"), default=0),
        "userMessage": (
            doc.get("userMessage") if "userMessage" in doc else doc.get("user_message")
        ),
        "assistantText": (
            doc.get("assistantText")
            if "assistantText" in doc
            else (doc.get("assistant_text") or "")
        ),
        "hasContent": bool(
            doc.get("hasContent")
            if "hasContent" in doc
            else doc.get("has_content", True)
        ),
        "status": doc.get("status") or "success",
        "model": doc.get("model") or "",
        "usage": _normalize_usage_map(doc.get("usage")),
        "costUsd": _as_float(
            doc.get("costUsd"), default=_as_float(doc.get("cost"), default=0.0)
        ),
        "createdAt": created_at,
    }
    assistant_explanation = (
        doc.get("assistantExplanation")
        if "assistantExplanation" in doc
        else doc.get("assistant_explanation")
    )
    if assistant_explanation is not None:
        out["assistantExplanation"] = str(assistant_explanation)
    if updated_at is not None:
        out["updatedAt"] = updated_at
    if (doc.get("errorMessage") or doc.get("error_message")) is not None:
        out["errorMessage"] = doc.get("errorMessage") or doc.get("error_message")
    return out


@dataclass
class BatchWriter:
    db: Any
    dry_run: bool
    ops: int = 0
    commits: int = 0
    _batch: Any = None

    def __post_init__(self) -> None:
        self._batch = self.db.batch()

    def _maybe_commit(self) -> None:
        if self.dry_run:
            return
        if self.ops >= 400:
            self._batch.commit()
            self.commits += 1
            self._batch = self.db.batch()
            self.ops = 0

    def set(self, ref: Any, data: dict, *, merge: bool = False) -> None:
        if not self.dry_run:
            self._batch.set(ref, data, merge=merge)
        self.ops += 1
        self._maybe_commit()

    def delete(self, ref: Any) -> None:
        if not self.dry_run:
            self._batch.delete(ref)
        self.ops += 1
        self._maybe_commit()

    def commit(self) -> None:
        if self.dry_run:
            return
        if self.ops > 0:
            self._batch.commit()
            self.commits += 1
            self._batch = self.db.batch()
            self.ops = 0


def _migrate_user(
    *,
    db: Any,
    uid: str,
    writer: BatchWriter,
    default_max_depth: int,
    delete_old: bool,
    truncate_long_texts: bool,
) -> None:
    users_ref = db.collection("users").document(uid)

    for snap in users_ref.collection("projects").stream():
        data = snap.to_dict() or {}
        created_at = _coerce_ts(
            data.get("createdAt") or data.get("created_at"), _utc_now()
        )
        updated_at = _coerce_ts(
            data.get("updatedAt") or data.get("updated_at"), created_at
        )
        archived = bool(data.get("archived", False))
        archived_at = _to_dt(data.get("archivedAt") or data.get("archived_at"))
        if archived and archived_at is None:
            archived_at = updated_at

        project_v2 = {
            "name": data.get("name") or "",
            "ownerId": data.get("ownerId") or uid,
            "createdAt": created_at,
            "updatedAt": updated_at,
            "archived": archived,
        }
        if archived_at is not None:
            project_v2["archivedAt"] = archived_at
        writer.set(snap.reference, project_v2, merge=False)

    for snap in users_ref.collection("quellen").stream():
        data = snap.to_dict() or {}
        created_at = _coerce_ts(
            data.get("createdAt") or data.get("created_at"), _utc_now()
        )
        updated_at = _coerce_ts(
            data.get("updatedAt") or data.get("updated_at"), created_at
        )

        text = str(data.get("content") or "")
        text, word_count = _enforce_text_limits(
            text=text,
            doc_path=f"users/{uid}/quellen/{snap.id}",
            truncate_long_texts=truncate_long_texts,
        )

        archived = bool(data.get("archived", False))
        archived_at = _to_dt(data.get("archivedAt") or data.get("archived_at"))
        if archived and archived_at is None:
            archived_at = updated_at

        meta_doc = {
            "projektId": data.get("projektId") or data.get("projekt_id") or "",
            "title": data.get("title") or "",
            "createdAt": created_at,
            "updatedAt": updated_at,
            "archived": archived,
            "wordCount": _as_int(data.get("wordCount"), default=word_count),
        }
        if archived_at is not None:
            meta_doc["archivedAt"] = archived_at
        for k in ["images", "autor", "jahr", "typ", "url", "zugriffAm", "color"]:
            if k in data:
                meta_doc[k] = data.get(k)

        writer.set(snap.reference, meta_doc, merge=False)
        writer.set(
            snap.reference.collection("content").document("main"),
            {
                "text": text,
                "wordCount": word_count,
                "createdAt": created_at,
                "updatedAt": updated_at,
            },
            merge=False,
        )

    for kap_snap in users_ref.collection("kapitels").stream():
        kap = kap_snap.to_dict() or {}
        kap_created = _coerce_ts(
            kap.get("createdAt") or kap.get("created_at"), _utc_now()
        )
        kap_updated = _coerce_ts(
            kap.get("updatedAt") or kap.get("updated_at"), kap_created
        )
        kap_archived = bool(kap.get("archived", False))
        kap_archived_at = _to_dt(kap.get("archivedAt") or kap.get("archived_at"))
        if kap_archived and kap_archived_at is None:
            kap_archived_at = kap_updated

        kap_v2 = {
            "projektId": kap.get("projektId") or kap.get("projekt_id") or "",
            "title": kap.get("title") or "",
            "nummer": kap.get("nummer") or "",
            "parentId": (
                kap.get("parentId") if "parentId" in kap else kap.get("parent_id")
            ),
            "order": _as_int(kap.get("order"), default=0),
            "quelleIds": kap.get("quelleIds") or kap.get("quelle_ids") or [],
            "createdAt": kap_created,
            "updatedAt": kap_updated,
            "archived": kap_archived,
        }
        if kap_archived_at is not None:
            kap_v2["archivedAt"] = kap_archived_at
        if isinstance(kap.get("latestRun"), dict):
            kap_v2["latestRun"] = kap.get("latestRun")
        writer.set(kap_snap.reference, kap_v2, merge=False)

        results_expected = len(kap_v2["quelleIds"])

        for run_snap in kap_snap.reference.collection("runs").stream():
            run = run_snap.to_dict() or {}
            run_created = _coerce_ts(
                run.get("createdAt") or run.get("created_at"), _utc_now()
            )
            run_updated = _coerce_ts(
                run.get("updatedAt") or run.get("updated_at"), run_created
            )
            run_archived = bool(run.get("archived", False))
            run_archived_at = _to_dt(run.get("archivedAt") or run.get("archived_at"))
            if run_archived and run_archived_at is None:
                run_archived_at = run_updated

            results_completed = 0
            results_with_content = 0
            last_result_at: Optional[datetime] = None

            for res_snap in run_snap.reference.collection("results").stream():
                res = res_snap.to_dict() or {}
                created_at = _coerce_ts(
                    res.get("createdAt") or res.get("created_at"), _utc_now()
                )
                updated_at = _coerce_ts(
                    res.get("updatedAt") or res.get("updated_at"), created_at
                )

                result_v2 = {
                    "quelleId": res_snap.id,
                    "userInput": res.get("userInput") or res.get("user_input") or "",
                    "content": res.get("content")
                    or res.get("resultContent")
                    or res.get("result_content")
                    or "",
                    "hasContent": bool(
                        res.get("hasContent")
                        if "hasContent" in res
                        else res.get("has_content", True)
                    ),
                    "model": res.get("model")
                    or res.get("model_used")
                    or res.get("modelUsed")
                    or "",
                    "usage": _usage_from_tokens(
                        total_tokens=res.get("tokensUsed") or res.get("tokens_used"),
                        input_tokens=res.get("inputTokens") or res.get("input_tokens"),
                        cached_input_tokens=res.get("cachedInputTokens")
                        or res.get("cached_input_tokens"),
                        output_tokens=res.get("outputTokens")
                        or res.get("output_tokens"),
                        reasoning_tokens=res.get("reasoningTokens")
                        or res.get("reasoning_tokens"),
                    ),
                    "costUsd": _as_float(
                        res.get("costUsd"),
                        default=_as_float(res.get("cost"), default=0.0),
                    ),
                    "keySource": res.get("keySource") or res.get("key_source"),
                    "createdAt": created_at,
                    "updatedAt": updated_at,
                    "refinement": _normalize_refinement(
                        res, created_at=created_at, default_max_depth=default_max_depth
                    ),
                }

                results_completed += 1
                if result_v2["hasContent"] and result_v2["content"].strip():
                    results_with_content += 1
                last_result_at = max(last_result_at or created_at, created_at)

                writer.set(res_snap.reference, result_v2, merge=False)

                for ver_snap in res_snap.reference.collection("versions").stream():
                    writer.set(
                        ver_snap.reference,
                        _normalize_version(ver_snap.to_dict() or {}),
                        merge=False,
                    )

            artifacts_status = {
                "combined": "empty",
                "shortened": "empty",
                "lesefluss": "empty",
            }
            artifacts_ref = run_snap.reference.collection("artifacts")

            old_combined_ref = run_snap.reference.collection("combined").document(
                "combined"
            )
            old_combined = old_combined_ref.get()
            combined_art_ref = artifacts_ref.document("combined")
            if old_combined.exists:
                d = old_combined.to_dict() or {}
                created_at = _coerce_ts(
                    d.get("createdAt") or d.get("created_at"), run_created
                )

                combined_v2 = {
                    "artifactId": "combined",
                    "content": d.get("content")
                    or d.get("combinedContent")
                    or d.get("combined_content")
                    or "",
                    "heading": d.get("heading") or "",
                    "topic": d.get("topic") or "",
                    "sourceQuelleIds": d.get("sourceQuelleIds")
                    or d.get("source_quelle_ids")
                    or [],
                    "model": d.get("model")
                    or d.get("model_used")
                    or d.get("modelUsed")
                    or "",
                    "usage": _usage_from_tokens(
                        total_tokens=d.get("tokensUsed") or d.get("tokens_used"),
                        input_tokens=d.get("inputTokens") or d.get("input_tokens"),
                        cached_input_tokens=d.get("cachedInputTokens")
                        or d.get("cached_input_tokens"),
                        output_tokens=d.get("outputTokens") or d.get("output_tokens"),
                        reasoning_tokens=d.get("reasoningTokens")
                        or d.get("reasoning_tokens"),
                    ),
                    "costUsd": _as_float(
                        d.get("costUsd"), default=_as_float(d.get("cost"), default=0.0)
                    ),
                    "keySource": d.get("keySource") or d.get("key_source"),
                    "createdAt": created_at,
                    "refinement": _normalize_refinement(
                        d, created_at=created_at, default_max_depth=default_max_depth
                    ),
                }
                updated_at = _to_dt(d.get("updatedAt") or d.get("updated_at"))
                if updated_at is not None:
                    combined_v2["updatedAt"] = updated_at

                writer.set(combined_art_ref, combined_v2, merge=False)
                artifacts_status["combined"] = "success"

                for ver_snap in old_combined_ref.collection("versions").stream():
                    writer.set(
                        combined_art_ref.collection("versions").document(ver_snap.id),
                        _normalize_version(ver_snap.to_dict() or {}),
                        merge=False,
                    )
                    if delete_old:
                        writer.delete(ver_snap.reference)
                if delete_old:
                    writer.delete(old_combined_ref)

            old_groups_ref = run_snap.reference.collection("intermediate_groups")
            group_snaps = list(old_groups_ref.stream())
            if group_snaps:
                if not old_combined.exists:
                    writer.set(
                        combined_art_ref,
                        {
                            "artifactId": "combined",
                            "content": "",
                            "heading": "",
                            "topic": "",
                            "sourceQuelleIds": [],
                            "model": "",
                            "usage": _usage_from_tokens(),
                            "costUsd": 0.0,
                            "keySource": None,
                            "createdAt": run_created,
                            "refinement": {
                                "rootVersionId": "root",
                                "activeVersionId": "root",
                                "maxDepth": default_max_depth,
                                "costTotalUsd": 0.0,
                                "initializedAt": run_created,
                            },
                        },
                        merge=True,
                    )
                artifacts_status["combined"] = "success"

                for g_snap in group_snaps:
                    g = g_snap.to_dict() or {}
                    writer.set(
                        combined_art_ref.collection("groups").document(g_snap.id),
                        {
                            "groupNumber": _as_int(
                                g.get("groupNumber"),
                                default=_as_int(g.get("group_number"), default=0),
                            ),
                            "content": g.get("content")
                            or g.get("combinedContent")
                            or g.get("combined_content")
                            or "",
                            "heading": g.get("heading") or "",
                            "topic": g.get("topic") or "",
                            "sourceQuelleIds": g.get("sourceQuelleIds")
                            or g.get("source_quelle_ids")
                            or [],
                            "model": g.get("model")
                            or g.get("model_used")
                            or g.get("modelUsed")
                            or "",
                            "usage": _usage_from_tokens(
                                total_tokens=g.get("tokensUsed")
                                or g.get("tokens_used"),
                                input_tokens=g.get("inputTokens")
                                or g.get("input_tokens"),
                                cached_input_tokens=g.get("cachedInputTokens")
                                or g.get("cached_input_tokens"),
                                output_tokens=g.get("outputTokens")
                                or g.get("output_tokens"),
                                reasoning_tokens=g.get("reasoningTokens")
                                or g.get("reasoning_tokens"),
                            ),
                            "costUsd": _as_float(
                                g.get("costUsd"),
                                default=_as_float(g.get("cost"), default=0.0),
                            ),
                            "keySource": g.get("keySource") or g.get("key_source"),
                            "createdAt": _coerce_ts(
                                g.get("createdAt") or g.get("created_at"), run_created
                            ),
                        },
                        merge=False,
                    )
                    if delete_old:
                        writer.delete(g_snap.reference)

            old_short_ref = run_snap.reference.collection("shortened").document(
                "shortened"
            )
            old_short = old_short_ref.get()
            short_art_ref = artifacts_ref.document("shortened")
            if old_short.exists:
                d = old_short.to_dict() or {}
                created_at = _coerce_ts(
                    d.get("createdAt") or d.get("created_at"), run_created
                )

                cost_raw = d.get("costUsd") if "costUsd" in d else d.get("cost")
                cost_usd = _as_float(cost_raw, default=0.0)
                if isinstance(cost_raw, int):
                    cost_usd = cost_raw / 100.0

                tokens_used = d.get("tokensUsed") or d.get("tokens_used") or {}
                if not isinstance(tokens_used, dict):
                    tokens_used = {}

                explanation = (
                    d.get("explanation")
                    if isinstance(d.get("explanation"), dict)
                    else None
                )
                short_v2 = {
                    "artifactId": "shortened",
                    "content": d.get("content")
                    or d.get("shortenedContent")
                    or d.get("shortened_content")
                    or "",
                    "originalLength": _as_int(
                        d.get("originalLength"),
                        default=_as_int(d.get("original_length"), default=0),
                    ),
                    "shortenedLength": _as_int(
                        d.get("shortenedLength"),
                        default=_as_int(d.get("shortened_length"), default=0),
                    ),
                    "compressionRatio": _as_float(
                        d.get("compressionRatio"),
                        default=_as_float(d.get("compression_ratio"), default=0.0),
                    ),
                    "usedKapitelIds": d.get("usedKapitelIds")
                    or d.get("used_kapitel_ids")
                    or [],
                    "model": d.get("model") or "",
                    "usage": _usage_from_tokens(
                        input_tokens=tokens_used.get("inputTokens")
                        or tokens_used.get("input"),
                        cached_input_tokens=tokens_used.get("cachedInputTokens")
                        or tokens_used.get("cachedInput")
                        or tokens_used.get("cached_input"),
                        output_tokens=tokens_used.get("outputTokens")
                        or tokens_used.get("output"),
                        reasoning_tokens=tokens_used.get("reasoningTokens") or 0,
                        total_tokens=tokens_used.get("totalTokens"),
                    ),
                    "costUsd": cost_usd,
                    "keySource": d.get("keySource") or d.get("key_source"),
                    "createdAt": created_at,
                    "refinement": _normalize_refinement(
                        d, created_at=created_at, default_max_depth=default_max_depth
                    ),
                }
                updated_at = _to_dt(d.get("updatedAt") or d.get("updated_at"))
                if updated_at is not None:
                    short_v2["updatedAt"] = updated_at
                if explanation is not None:
                    short_v2["explanation"] = {
                        "lengthDecision": explanation.get("lengthDecision")
                        or explanation.get("length_decision")
                        or "",
                        "omittedTopics": explanation.get("omittedTopics")
                        or explanation.get("omitted_topics")
                        or [],
                        "preservedFocus": explanation.get("preservedFocus")
                        or explanation.get("preserved_focus")
                        or [],
                        "compressionNotes": explanation.get("compressionNotes")
                        or explanation.get("compression_notes")
                        or "",
                    }

                writer.set(short_art_ref, short_v2, merge=False)
                artifacts_status["shortened"] = "success"

                for ver_snap in old_short_ref.collection("versions").stream():
                    writer.set(
                        short_art_ref.collection("versions").document(ver_snap.id),
                        _normalize_version(ver_snap.to_dict() or {}),
                        merge=False,
                    )
                    if delete_old:
                        writer.delete(ver_snap.reference)
                if delete_old:
                    writer.delete(old_short_ref)

            old_lese_ref = run_snap.reference.collection("lesefluss").document(
                "lesefluss"
            )
            old_lese = old_lese_ref.get()
            lese_art_ref = artifacts_ref.document("lesefluss")
            if old_lese.exists:
                d = old_lese.to_dict() or {}
                created_at = _coerce_ts(
                    d.get("createdAt") or d.get("created_at"), run_created
                )

                cost_raw = d.get("costUsd") if "costUsd" in d else d.get("cost")
                cost_usd = _as_float(cost_raw, default=0.0)
                if isinstance(cost_raw, int):
                    cost_usd = cost_raw / 100.0

                tokens_used = d.get("tokensUsed") or d.get("tokens_used") or {}
                if not isinstance(tokens_used, dict):
                    tokens_used = {}

                lese_v2 = {
                    "artifactId": "lesefluss",
                    "content": d.get("content")
                    or d.get("leseflussContent")
                    or d.get("lesefluss_content")
                    or "",
                    "aufgabenstellung": d.get("aufgabenstellung") or "",
                    "explanation": d.get("explanation") or "",
                    "originalLength": _as_int(
                        d.get("originalLength"),
                        default=_as_int(d.get("original_length"), default=0),
                    ),
                    "leseflussLength": _as_int(
                        d.get("leseflussLength"),
                        default=_as_int(d.get("lesefluss_length"), default=0),
                    ),
                    "usedKapitelIds": d.get("usedKapitelIds")
                    or d.get("used_kapitel_ids")
                    or [],
                    "model": d.get("model") or "",
                    "usage": _usage_from_tokens(
                        input_tokens=tokens_used.get("inputTokens")
                        or tokens_used.get("input"),
                        cached_input_tokens=tokens_used.get("cachedInputTokens")
                        or tokens_used.get("cachedInput")
                        or tokens_used.get("cached_input"),
                        output_tokens=tokens_used.get("outputTokens")
                        or tokens_used.get("output"),
                        reasoning_tokens=tokens_used.get("reasoningTokens") or 0,
                        total_tokens=tokens_used.get("totalTokens"),
                    ),
                    "costUsd": cost_usd,
                    "keySource": d.get("keySource") or d.get("key_source"),
                    "createdAt": created_at,
                    "refinement": _normalize_refinement(
                        d, created_at=created_at, default_max_depth=default_max_depth
                    ),
                }
                updated_at = _to_dt(d.get("updatedAt") or d.get("updated_at"))
                if updated_at is not None:
                    lese_v2["updatedAt"] = updated_at

                writer.set(lese_art_ref, lese_v2, merge=False)
                artifacts_status["lesefluss"] = "success"

                for ver_snap in old_lese_ref.collection("versions").stream():
                    writer.set(
                        lese_art_ref.collection("versions").document(ver_snap.id),
                        _normalize_version(ver_snap.to_dict() or {}),
                        merge=False,
                    )
                    if delete_old:
                        writer.delete(ver_snap.reference)
                if delete_old:
                    writer.delete(old_lese_ref)

            for sum_snap in run_snap.reference.collection("summaries").stream():
                d = sum_snap.to_dict() or {}
                created_at = _coerce_ts(
                    d.get("createdAt") or d.get("created_at"), run_created
                )
                updated_at = _to_dt(d.get("updatedAt") or d.get("updated_at"))

                cost_raw = d.get("costUsd") if "costUsd" in d else d.get("cost")
                cost_usd = _as_float(cost_raw, default=0.0)
                if isinstance(cost_raw, int):
                    cost_usd = cost_raw / 100.0

                tokens_used = d.get("tokensUsed") or d.get("tokens_used") or {}
                if not isinstance(tokens_used, dict):
                    tokens_used = {}
                input_t = _as_int(
                    tokens_used.get("inputTokens") or tokens_used.get("input")
                )
                output_t = _as_int(
                    tokens_used.get("outputTokens") or tokens_used.get("output")
                )

                summary_v2 = {
                    "sourceKapitelId": d.get("sourceKapitelId")
                    or d.get("source_kapitel_id")
                    or sum_snap.id,
                    "sourceRunId": d.get("sourceRunId") or d.get("source_run_id") or "",
                    "sourceType": d.get("sourceType") or d.get("source_type") or "",
                    "content": d.get("content")
                    or d.get("summaryContent")
                    or d.get("summary_content")
                    or "",
                    "originalLength": _as_int(
                        d.get("originalLength"),
                        default=_as_int(d.get("original_length"), default=0),
                    ),
                    "summaryLength": _as_int(
                        d.get("summaryLength"),
                        default=_as_int(d.get("summary_length"), default=0),
                    ),
                    "model": d.get("model") or "",
                    "usage": {
                        "inputTokens": input_t,
                        "outputTokens": output_t,
                        "totalTokens": input_t + output_t,
                    },
                    "costUsd": cost_usd,
                    "keySource": d.get("keySource") or d.get("key_source"),
                    "createdAt": created_at,
                }
                if updated_at is not None:
                    summary_v2["updatedAt"] = updated_at
                writer.set(sum_snap.reference, summary_v2, merge=False)

            last_result_at = last_result_at or run_updated
            last_activity_at = max(last_result_at, run_updated)

            run_v2 = {
                "projektId": run.get("projektId")
                or run.get("projekt_id")
                or kap_v2.get("projektId")
                or "",
                "index": _as_int(run.get("index"), default=0),
                "instruction": run.get("instruction") or "",
                "model": run.get("model") or "",
                "createdAt": run_created,
                "updatedAt": run_updated,
                "archived": run_archived,
                "autoCombine": bool(run.get("autoCombine", False)),
                "promptTemplateId": run.get("promptTemplateId"),
                "promptPayload": run.get("promptPayload"),
                "grundlegendeInformationen": run.get("grundlegendeInformationen"),
                "ueberschrift": run.get("ueberschrift"),
                "thema": run.get("thema"),
                "resultsExpectedCount": _as_int(
                    run.get("resultsExpectedCount"), default=results_expected
                ),
                "resultsCompletedCount": _as_int(
                    run.get("resultsCompletedCount"), default=results_completed
                ),
                "resultsWithContentCount": _as_int(
                    run.get("resultsWithContentCount"), default=results_with_content
                ),
                "artifactsStatus": (
                    run.get("artifactsStatus")
                    if isinstance(run.get("artifactsStatus"), dict)
                    else artifacts_status
                ),
                "lastResultAt": last_result_at,
                "lastActivityAt": last_activity_at,
            }
            if run_archived_at is not None:
                run_v2["archivedAt"] = run_archived_at

            writer.set(run_snap.reference, run_v2, merge=False)


def migrate(
    *,
    user_id: Optional[str],
    dry_run: bool,
    delete_old: bool,
    truncate_long_texts: bool,
) -> None:
    _load_fastapi_env()
    db = _init_firestore()
    default_max_depth = _as_int(os.getenv("TEXT_REFINEMENT_MAX_DEPTH", "4"), default=4)

    users_coll = db.collection("users")
    user_ids = [user_id] if user_id else [doc.id for doc in users_coll.stream()]

    if not user_ids:
        print("No users found. Nothing to migrate.")
        return

    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"Firestore V2 migration starting ({mode}). Users: {len(user_ids)}")
    if delete_old:
        print("Old-path cleanup: ENABLED (--delete-old)")
    if truncate_long_texts:
        print("Text truncation: ENABLED (--truncate-long-texts)")

    for uid in user_ids:
        print(f"\n=== Migrating user {uid} ===")
        writer = BatchWriter(db=db, dry_run=dry_run)
        _migrate_user(
            db=db,
            uid=uid,
            writer=writer,
            default_max_depth=default_max_depth,
            delete_old=delete_old,
            truncate_long_texts=truncate_long_texts,
        )
        writer.commit()
        if dry_run:
            print(f"[DRY-RUN] queued ops: {writer.ops} (no commits)")
        else:
            print(f"Committed batches: {writer.commits}")

    print("\nFirestore V2 migration complete.")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Migrate Firestore to V2 schema (big-bang)."
    )
    mode = p.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Print actions without writing (default).",
    )
    mode.add_argument("--apply", action="store_true", help="Apply writes to Firestore.")
    p.add_argument(
        "--user-id",
        default=None,
        help="Only migrate one user (uid). Default: all users.",
    )
    p.add_argument(
        "--delete-old",
        action="store_true",
        help="Delete old singleton docs after copying (combined/shortened/lesefluss/intermediate_groups).",
    )
    p.add_argument(
        "--truncate-long-texts",
        action="store_true",
        help=f"Hard-truncate Quelle content to V2 limits ({MAX_TEXT_WORDS} words, {MAX_TEXT_CHARS} chars).",
    )
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = _parse_args(argv)
    dry_run = args.dry_run or not args.apply
    try:
        migrate(
            user_id=args.user_id,
            dry_run=dry_run,
            delete_old=bool(args.delete_old),
            truncate_long_texts=bool(args.truncate_long_texts),
        )
        return 0
    except KeyboardInterrupt:
        print("Interrupted.")
        return 130
    except Exception as exc:
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
