"""Encryption and decryption utilities for API keys."""

from __future__ import annotations

import base64
import hashlib
import platform


def _derive_encryption_key() -> bytes:
    """Derive encryption key from machine fingerprint."""
    machine_id = f"{platform.node()}-{platform.machine()}-{platform.processor()}"
    digest = hashlib.sha256(machine_id.encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_value(plaintext: str) -> str:
    """Encrypt a string value using Fernet."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return plaintext
    key = _derive_encryption_key()
    f = Fernet(key)
    return f.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    """Decrypt a string value using Fernet."""
    try:
        from cryptography.fernet import Fernet
    except ImportError:
        return ciphertext
    key = _derive_encryption_key()
    f = Fernet(key)
    return f.decrypt(ciphertext.encode()).decode()
