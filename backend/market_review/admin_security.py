from __future__ import annotations

import hashlib
import hmac
import os


def verify_admin_password(password: str) -> bool:
    """Verify the administrator password without storing it in plaintext."""
    encoded = os.getenv("LLL_ADMIN_PASSWORD_HASH", "").strip()
    if not password or not encoded:
        return False
    try:
        algorithm, rounds_text, salt_hex, expected_hex = encoded.split("$", 3)
        rounds = int(rounds_text)
        if algorithm != "pbkdf2_sha256" or rounds < 100_000:
            return False
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(expected_hex)
    except (ValueError, TypeError):
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(actual, expected)
