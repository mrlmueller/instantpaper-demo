import base64
import os
from typing import Dict

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionService:
    """Small helper for AES-256-GCM encryption/decryption."""

    def __init__(self, key_b64: str):
        if not key_b64:
            raise ValueError("USER_KEY_ENCRYPTION_KEY is not configured")

        try:
            raw_key = base64.b64decode(key_b64)
        except Exception as exc:  # pragma: no cover - defensive
            raise ValueError("USER_KEY_ENCRYPTION_KEY must be base64-encoded") from exc

        if len(raw_key) not in (16, 24, 32):
            raise ValueError("USER_KEY_ENCRYPTION_KEY must decode to 16/24/32 bytes (AES key sizes)")

        self._key = raw_key

    @staticmethod
    def _b64_encode(value: bytes) -> str:
        return base64.b64encode(value).decode("utf-8")

    @staticmethod
    def _b64_decode(value: str) -> bytes:
        return base64.b64decode(value.encode("utf-8"))

    def encrypt(self, plaintext: str) -> Dict[str, str]:
        """
        Encrypt a plaintext string with AES-GCM.

        Returns dict with base64-encoded iv, ciphertext, tag.
        """
        iv = os.urandom(12)  # Recommended nonce length for AES-GCM
        aesgcm = AESGCM(self._key)
        cipher_with_tag = aesgcm.encrypt(iv, plaintext.encode("utf-8"), None)

        # AESGCM.encrypt returns ciphertext || tag
        ciphertext, tag = cipher_with_tag[:-16], cipher_with_tag[-16:]

        return {
            "iv": self._b64_encode(iv),
            "ciphertext": self._b64_encode(ciphertext),
            "tag": self._b64_encode(tag),
        }

    def decrypt(self, data: Dict[str, str]) -> str:
        """Decrypt data previously produced by encrypt()."""
        required = ("iv", "ciphertext", "tag")
        if not all(k in data for k in required):
            raise ValueError("Encrypted payload missing required fields")

        iv = self._b64_decode(data["iv"])
        ciphertext = self._b64_decode(data["ciphertext"])
        tag = self._b64_decode(data["tag"])

        aesgcm = AESGCM(self._key)
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
        return plaintext.decode("utf-8")
