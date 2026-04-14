from __future__ import annotations

import base64
import hashlib
import os

from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import check_password_hash, generate_password_hash


def _build_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class CredentialCipher:
    def __init__(self) -> None:
        secret = os.getenv("APP_CREDENTIAL_SECRET", "gas-monitor-default-secret")
        self.fernet = Fernet(_build_key(secret))

    def encrypt(self, plaintext: str) -> str:
        return self.fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")

    def decrypt(self, token: str) -> str | None:
        try:
            return self.fernet.decrypt(token.encode("utf-8")).decode("utf-8")
        except (InvalidToken, ValueError):
            return None

    def verify(self, stored_value: str, plaintext: str) -> tuple[bool, str | None]:
        decrypted = self.decrypt(stored_value)
        if decrypted is not None:
            return decrypted == plaintext, None

        # Backward compatibility: migrate old hashed passwords if they exist.
        if check_password_hash(stored_value, plaintext):
            return True, self.encrypt(plaintext)
        return False, None

    def legacy_hash(self, plaintext: str) -> str:
        return generate_password_hash(plaintext)


cipher = CredentialCipher()
