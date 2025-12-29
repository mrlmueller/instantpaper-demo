from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

FASTAPI_DIR = Path(__file__).resolve().parents[1]
if str(FASTAPI_DIR) not in sys.path:
    sys.path.insert(0, str(FASTAPI_DIR))

from services.prompt_service import prompt_service


def _load_fastapi_env() -> None:
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


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


REPLACEMENTS: list[tuple[str, str]] = [
    # process_quelle + combine (v1 -> v2 tokens)
    ("{heading}", "{KAPITEL_TITEL}"),
    ("{topic}", "{KAPITEL_BESCHREIBUNG}"),
    ("{ANWEISUNGEN}", "{KAPITEL_BESCHREIBUNG}"),
    # process_quelle basic info (old -> new canonical)
    ("{GRUNDLEGENDE_INFOS_ODER_LEER}", "{OPTIONAL_GRUNDLEGENDE_INFOS}"),
    ("{grundlegende_infos}", "{OPTIONAL_GRUNDLEGENDE_INFOS}"),
    # summary
    ("{text}", "{KAPITELTEXT}"),
    # shorten (legacy -> canonical)
    ("{ueberschrift}", "{KAPITEL_TITEL}"),
    ("{thema}", "{KAPITEL_BESCHREIBUNG}"),
    ("{KONTEXT_ANDERE_KAPITEL}", "{GLIEDERUNG_SUMMARY}"),
    ("{TEXT_ZUM_KUERZEN}", "{KAPITELTEXT}"),
    ("{gliederung}", "{GLIEDERUNG_SUMMARY}"),
    ("{target_text}", "{KAPITELTEXT}"),
    # lesefluss (legacy -> canonical)
    ("{aufgabenstellung}", "{AUFGABENSTELLUNG}"),
    ("{kapitel_nummer}", "{AKTUELLES_KAPITEL_NUMMER}"),
]


APPEND_HINTS: dict[str, dict[str, str]] = {
    "process_quelle": {
        "{KAPITEL_TITEL}": "Kapitelname: {KAPITEL_TITEL}",
        "{KAPITEL_BESCHREIBUNG}": "Kapitelbeschreibung (Scope): {KAPITEL_BESCHREIBUNG}",
        "{OPTIONAL_GRUNDLEGENDE_INFOS}": "[GRUNDLEGENDE INFORMATIONEN - OPTIONAL]\n{OPTIONAL_GRUNDLEGENDE_INFOS}",
        "{QUELLTEXT}": "Quelltext:\n{QUELLTEXT}",
    },
    "combine": {
        "{KAPITEL_TITEL}": "Titel (nur Kontext, NICHT ausgeben): {KAPITEL_TITEL}",
        "{KAPITEL_BESCHREIBUNG}": "Thema: {KAPITEL_BESCHREIBUNG}",
        "{DRAFTS}": "[ENTWÜRFE]\n{DRAFTS}",
    },
    "shorten": {
        "{KAPITEL_TITEL}": "<kapitel_titel>\n{KAPITEL_TITEL}\n</kapitel_titel>",
        "{KAPITEL_BESCHREIBUNG}": "<kapitel_beschreibung>\n{KAPITEL_BESCHREIBUNG}\n</kapitel_beschreibung>",
        "{GLIEDERUNG_SUMMARY}": "<gliederung_und_kapitelzusammenfassungen>\n{GLIEDERUNG_SUMMARY}\n</gliederung_und_kapitelzusammenfassungen>",
        "{KAPITELTEXT}": "<kapiteltext>\n{KAPITELTEXT}\n</kapiteltext>",
    },
    "lesefluss": {
        "{AUFGABENSTELLUNG}": "<aufgabenstellung>\n{AUFGABENSTELLUNG}\n</aufgabenstellung>",
        "{GLIEDERUNG_SUMMARY}": "<gliederung_und_kapitelzusammenfassungen>\n{GLIEDERUNG_SUMMARY}\n</gliederung_und_kapitelzusammenfassungen>",
        "{KAPITELTEXT}": "<kapiteltext_zu_ueberarbeiten>\n{KAPITELTEXT}\n</kapiteltext_zu_ueberarbeiten>",
    },
    "summary": {
        "{KAPITELTEXT}": "### Text\n{KAPITELTEXT}",
    },
}


def _transform_instructions(stage: str, instructions: str) -> tuple[str, list[str], list[str]]:
    original = instructions or ""
    updated = original

    for old, new in REPLACEMENTS:
        if old in updated:
            updated = updated.replace(old, new)

    required = list(prompt_service.REQUIRED_PLACEHOLDERS.get(stage, []) or [])
    missing = [ph for ph in required if ph not in updated]

    appended: list[str] = []
    if missing:
        hints = APPEND_HINTS.get(stage, {})
        blocks: list[str] = []
        for ph in missing:
            hint = hints.get(ph, ph)
            blocks.append(hint)
            appended.append(ph)
        if blocks:
            updated = updated.rstrip() + "\n\n" + "\n\n".join(blocks) + "\n"

    changed = (updated != original)
    return updated, missing, appended if changed else []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Migrate systemPromptTemplates instructions to the canonical v2 placeholder tokens."
    )
    parser.add_argument("--stage", default="", help="Only migrate this stage (default: all).")
    parser.add_argument("--apply", action="store_true", help="Write changes to Firestore (default: dry-run).")
    parser.add_argument("--limit", type=int, default=0, help="Only process first N docs (0 = no limit).")
    args = parser.parse_args()

    _load_fastapi_env()
    db = _init_firestore()

    stage_filter = (args.stage or "").strip()
    now = _utc_iso()

    docs = list(db.collection("systemPromptTemplates").stream())
    if args.limit and args.limit > 0:
        docs = docs[: args.limit]

    changed_count = 0
    scanned = 0

    for snap in docs:
        scanned += 1
        data = snap.to_dict() or {}
        stage = str((data.get("stage") or "")).strip()
        template_key = str((data.get("templateKey") or "")).strip()
        if not stage or not template_key:
            continue
        if stage_filter and stage != stage_filter:
            continue

        instructions = data.get("instructions")
        if not isinstance(instructions, str):
            continue

        next_text, missing, appended = _transform_instructions(stage, instructions)
        if next_text == instructions:
            continue

        changed_count += 1
        print(
            f"{'apply' if args.apply else 'dry'} {stage}/{template_key} "
            f"(missing before append: {', '.join(missing) if missing else '-'}) @ {now}"
        )

        if args.apply:
            snap.reference.set(
                {"instructions": next_text, "updatedAt": firestore.SERVER_TIMESTAMP},
                merge=True,
            )

    print(
        f"done. scanned={scanned}, changed={changed_count}, mode={'apply' if args.apply else 'dry-run'}"
    )
    if not args.apply:
        print("Tip: re-run with --apply to write the changes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

