"""Rehearse credential-key recovery and envelope rotation without providers or a database."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from cryptography.fernet import Fernet

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "apps" / "api"))

from hub.core.secrets import SecretCipher  # noqa: E402


def rehearse(label: str) -> dict[str, str]:
    original_key = Fernet.generate_key().decode("ascii")
    replacement_key = Fernet.generate_key().decode("ascii")
    value = f"synthetic-{label}-credential"
    encrypted = SecretCipher(original_key).encrypt(value)

    if SecretCipher(original_key).decrypt(encrypted) != value:
        raise RuntimeError("Original key recovery failed.")
    try:
        SecretCipher(replacement_key).decrypt(encrypted)
    except ValueError as exc:
        if str(exc) != "CREDENTIAL_UNREADABLE":
            raise
    else:
        raise RuntimeError("Replacement key unexpectedly decrypted the old envelope.")

    recovered = SecretCipher(original_key).decrypt(encrypted)
    rotated = SecretCipher(replacement_key).encrypt(recovered)
    if SecretCipher(replacement_key).decrypt(rotated) != value:
        raise RuntimeError("Replacement-key envelope verification failed.")
    try:
        SecretCipher(original_key).decrypt(rotated)
    except ValueError as exc:
        if str(exc) != "CREDENTIAL_UNREADABLE":
            raise
    else:
        raise RuntimeError("Original key unexpectedly decrypted the rotated envelope.")

    return {
        "original_key_recovery": "PASS",
        "wrong_key_failure": "PASS",
        "synthetic_envelope_rotation": "PASS",
    }


def main() -> None:
    print(
        json.dumps(
            {
                "google": rehearse("google"),
                "schedule": rehearse("schedule"),
                "provider_contact": "NONE",
                "database_writes": "NONE",
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
