from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

from services.prompt_service import DEFAULT_INSTRUCTIONS
from services.prompt_service import (
    PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT,
    PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS,
    PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT,
)


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


def _doc_id(stage: str, template_key: str) -> str:
    return f"{stage}__{template_key}"


def main() -> int:
    parser = argparse.ArgumentParser(description="Seed server-only system prompt templates in Firestore.")
    parser.add_argument("--stage", default="process_quelle", help="Prompt stage to seed (default: process_quelle)")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing templates (otherwise only creates missing docs).",
    )
    args = parser.parse_args()

    _load_fastapi_env()
    db = _init_firestore()

    stage = (args.stage or "").strip()
    if not stage:
        raise RuntimeError("stage must be non-empty")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    default_v1_instructions = DEFAULT_INSTRUCTIONS.get(stage, "")
    if not default_v1_instructions:
        raise RuntimeError(f"No DEFAULT_INSTRUCTIONS found for stage '{stage}'")

    default_v1_system_prompt = PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT if stage == "process_quelle" else ""

    default_v2_instructions = (
        PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS if stage == "process_quelle" else default_v1_instructions
    )
    default_v2_system_prompt = (
        PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT if stage == "process_quelle" else default_v1_system_prompt
    )

    templates = [
        ("default", "System-Standard", default_v1_system_prompt, default_v1_instructions),
        ("default_v2", "System-Standard (v2)", default_v2_system_prompt, default_v2_instructions),
    ]

    for key, name, system_prompt, instructions in templates:
        ref = db.collection("systemPromptTemplates").document(_doc_id(stage, key))
        snap = ref.get()
        exists = snap.exists
        if exists and not args.force:
            print(f"skip {stage}/{key} (exists)")
            continue
        payload = {
            "stage": stage,
            "templateKey": key,
            "name": name,
            "instructions": instructions,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        }
        if (system_prompt or "").strip():
            payload["systemPrompt"] = system_prompt
        if not exists:
            payload["createdAt"] = firestore.SERVER_TIMESTAMP
        ref.set(payload, merge=True)
        print(f"upsert {stage}/{key} ({'overwrite' if exists else 'create'}) @ {now}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
