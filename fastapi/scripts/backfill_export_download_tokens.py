import argparse
import uuid

from firebase_admin import storage

from services.firebase_service import firebase_service
from utils.config import config


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Add firebaseStorageDownloadTokens to DOCX exports uploaded via server code."
    )
    parser.add_argument("--user-id", required=True, help="Firebase Auth UID (users/{uid})")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only print what would change; do not patch Storage objects.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=200,
        help="Max number of export docs to scan (default: 200).",
    )
    args = parser.parse_args()

    user_id = str(args.user_id).strip()
    if not user_id:
        raise SystemExit("--user-id is required")

    # Ensure Firebase Admin SDK initialized.
    db = firebase_service.db
    bucket = storage.bucket(config.FIREBASE_STORAGE_BUCKET)

    exports_ref = db.collection("users").document(user_id).collection("exports")
    query = exports_ref.order_by("createdAt", direction="DESCENDING").limit(max(1, int(args.limit)))

    scanned = 0
    updated = 0
    skipped = 0

    for doc in query.stream():
        scanned += 1
        data = doc.to_dict() or {}
        status = str(data.get("status") or "").strip()
        if status != "success":
            skipped += 1
            continue

        file_info = data.get("file") if isinstance(data.get("file"), dict) else {}
        storage_path = str((file_info or {}).get("storagePath") or "").strip()
        file_name = str((file_info or {}).get("fileName") or "").strip()
        if not storage_path:
            skipped += 1
            continue

        blob = bucket.blob(storage_path)
        if not blob.exists():
            print(f"[missing] {doc.id}: {storage_path}")
            skipped += 1
            continue

        blob.reload()
        md = blob.metadata or {}
        has_token = bool(md.get("firebaseStorageDownloadTokens"))
        if has_token:
            skipped += 1
            continue

        token = str(uuid.uuid4())
        md = dict(md)
        md["firebaseStorageDownloadTokens"] = token

        print(f"[patch] {doc.id}: add firebaseStorageDownloadTokens (bucket={bucket.name})")

        if not args.dry_run:
            blob.metadata = md
            if file_name:
                blob.content_disposition = f'attachment; filename="{file_name}"'
            blob.patch()

        updated += 1

    print(f"Scanned: {scanned}, Updated: {updated}, Skipped: {skipped}, DryRun: {bool(args.dry_run)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

