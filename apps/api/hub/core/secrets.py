"""Authenticated, versioned server-side credential encryption."""

from cryptography.fernet import Fernet, InvalidToken


class SecretCipher:
    def __init__(self, key: str):
        try:
            self._cipher = Fernet(key.encode("ascii"))
        except (ValueError, UnicodeError) as exc:
            raise ValueError("CONFIGURATION_ERROR") from exc

    def encrypt(self, value: str) -> str:
        return "v1:" + self._cipher.encrypt(value.encode()).decode("ascii")

    def decrypt(self, value: str) -> str:
        try:
            if not value.startswith("v1:"):
                raise ValueError()
            return self._cipher.decrypt(value[3:].encode("ascii")).decode()
        except (InvalidToken, ValueError, UnicodeError):
            raise ValueError("CREDENTIAL_UNREADABLE") from None
