from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.prompt_service import DEFAULT_INSTRUCTIONS
from services.prompt_service import (
    COMBINE_DEFAULT_SYSTEM_PROMPT,
    COMBINE_DEFAULT_V2_INSTRUCTIONS,
    COMBINE_DEFAULT_V2_SYSTEM_PROMPT,
    LESEFLUSS_DEFAULT_V2_INSTRUCTIONS,
    LESEFLUSS_DEFAULT_V2_SYSTEM_PROMPT,
    PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT,
    PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS,
    PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT,
    SUMMARY_DEFAULT_SYSTEM_PROMPT,
    SUMMARY_DEFAULT_V2_INSTRUCTIONS,
    SUMMARY_DEFAULT_V2_SYSTEM_PROMPT,
    SHORTEN_DEFAULT_V2_INSTRUCTIONS,
    SHORTEN_DEFAULT_V2_SYSTEM_PROMPT,
)


def _load_backend_env() -> None:
    backend_dir = Path(__file__).resolve().parents[1]
    env_path = backend_dir / ".env"
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
    parser.add_argument("--stage", default="", help="Prompt stage to seed (default: all stages)")
    parser.add_argument("--all", action="store_true", help="Seed all supported stages.")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing templates (otherwise only creates missing docs).",
    )
    args = parser.parse_args()

    _load_backend_env()
    db = _init_firestore()

    supported_stages = ["process_quelle", "combine", "summary", "shorten", "lesefluss"]
    stage_arg = (args.stage or "").strip()
    stages = supported_stages if (args.all or not stage_arg) else [stage_arg]
    for s in stages:
        if s not in supported_stages:
            raise RuntimeError(f"Unsupported stage: {s}")

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for stage in stages:
        default_v1_instructions = DEFAULT_INSTRUCTIONS.get(stage, "")
        if not default_v1_instructions:
            raise RuntimeError(f"No DEFAULT_INSTRUCTIONS found for stage '{stage}'")

        if stage == "process_quelle":
            default_v1_system_prompt = PROCESS_QUELLE_DEFAULT_SYSTEM_PROMPT
        elif stage == "combine":
            default_v1_system_prompt = COMBINE_DEFAULT_SYSTEM_PROMPT
        elif stage == "summary":
            default_v1_system_prompt = SUMMARY_DEFAULT_SYSTEM_PROMPT
        elif stage == "shorten":
            default_v1_system_prompt = ""
        elif stage == "lesefluss":
            default_v1_system_prompt = ""
        else:
            default_v1_system_prompt = ""

        if stage == "process_quelle":
            default_v2_instructions = PROCESS_QUELLE_DEFAULT_V2_INSTRUCTIONS
            default_v2_system_prompt = PROCESS_QUELLE_DEFAULT_V2_SYSTEM_PROMPT
        elif stage == "combine":
            default_v2_instructions = COMBINE_DEFAULT_V2_INSTRUCTIONS
            default_v2_system_prompt = COMBINE_DEFAULT_V2_SYSTEM_PROMPT
        elif stage == "summary":
            default_v2_instructions = SUMMARY_DEFAULT_V2_INSTRUCTIONS
            default_v2_system_prompt = SUMMARY_DEFAULT_V2_SYSTEM_PROMPT
        elif stage == "shorten":
            default_v2_instructions = SHORTEN_DEFAULT_V2_INSTRUCTIONS
            default_v2_system_prompt = SHORTEN_DEFAULT_V2_SYSTEM_PROMPT
        elif stage == "lesefluss":
            default_v2_instructions = LESEFLUSS_DEFAULT_V2_INSTRUCTIONS
            default_v2_system_prompt = LESEFLUSS_DEFAULT_V2_SYSTEM_PROMPT
        else:
            default_v2_instructions = default_v1_instructions
            default_v2_system_prompt = default_v1_system_prompt

        templates = [
            ("default", "System-Standard", default_v1_system_prompt, default_v1_instructions),
            ("default_v2", "System-Standard (v2)", default_v2_system_prompt, default_v2_instructions),
        ]

        for key, name, system_prompt, instructions in templates:
            ref = db.collection("systemPromptTemplates").document(_doc_id(stage, key))
            snap = ref.get()
            exists = snap.exists
            if exists and not args.force:
                # Only patch missing meta fields without touching prompt text.
                existing_data = snap.to_dict() or {}
                patch = {}
                if "published" not in existing_data:
                    patch["published"] = True
                if "archived" not in existing_data:
                    patch["archived"] = False
                if patch:
                    ref.set(patch, merge=True)
                    print(f"patch {stage}/{key} (add fields: {', '.join(sorted(patch.keys()))}) @ {now}")
                else:
                    print(f"skip {stage}/{key} (exists)")
                continue

            payload = {
                "stage": stage,
                "templateKey": key,
                "name": name,
                "instructions": instructions,
                "published": True,
                "archived": False,
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
