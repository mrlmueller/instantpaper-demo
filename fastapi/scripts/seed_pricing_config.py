"""
Seed/overwrite the global OpenAI pricing config in Firestore.

Writes to: _config/pricing

Run:
  cd fastapi
  python scripts/seed_pricing_config.py
"""

from google.cloud.firestore_v1 import SERVER_TIMESTAMP

from services.firebase_service import firebase_service


def main() -> None:
    doc_ref = firebase_service.db.collection("_config").document("pricing")
    doc_ref.set(
        {
            "fallbackModel": "gpt-5-mini",
            "models": {
                "gpt-5-nano": {
                    "inputPerMillion": 0.05,
                    "cachedInputPerMillion": 0.005,
                    "outputPerMillion": 0.40,
                },
                "gpt-5-mini": {
                    "inputPerMillion": 0.25,
                    "cachedInputPerMillion": 0.025,
                    "outputPerMillion": 2.00,
                },
                "gpt-5.1": {
                    "inputPerMillion": 1.25,
                    "cachedInputPerMillion": 0.125,
                    "outputPerMillion": 10.00,
                },
                "gpt-5.2": {
                    "inputPerMillion": 1.75,
                    "cachedInputPerMillion": 0.175,
                    "outputPerMillion": 14.00,
                },
            },
            "updatedAt": SERVER_TIMESTAMP,
        }
    )
    print("Seeded Firestore pricing config at _config/pricing")


if __name__ == "__main__":
    main()
