from __future__ import annotations

import base64
import hashlib
import os
import warnings

from cryptography.fernet import Fernet, InvalidToken
from werkzeug.security import check_password_hash, generate_password_hash


def _build_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class CredentialCipher:
    def __init__(self) -> None:
        secret = os.getenv("APP_CREDENTIAL_SECRET", "gas-monitor-default-secret")
        if secret == "gas-monitor-default-secret":
            warnings.warn(
                "APP_CREDENTIAL_SECRET is using the development default. "
                "Set a stable private value before using real data.",
                RuntimeWarning,
                stacklevel=2,
            )
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
            if decrypted == plaintext:
                return True, self.hash_password(plaintext)
            return False, None

        # Backward compatibility: keep existing Werkzeug hashes valid.
        if check_password_hash(stored_value, plaintext):
            return True, None
        return False, None

    def hash_password(self, plaintext: str) -> str:
        return generate_password_hash(plaintext)

    def legacy_hash(self, plaintext: str) -> str:
        return self.hash_password(plaintext)


cipher = CredentialCipher()
