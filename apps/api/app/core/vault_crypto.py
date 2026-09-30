"""
Fernet-based symmetric encryption for Vault credentials.

All vault token values (access_token, refresh_token) are stored AES-128-CBC +
HMAC-SHA256 encrypted at rest using Fernet (https://cryptography.io/fernet).

Key management
--------------
* The active key is `settings.vault_encryption_key`.
* Key rotation is supported: supply `VAULT_ENCRYPTION_KEY_PREVIOUS` (comma-
  separated list of old base64 keys) as `vault_encryption_key_previous` in
  Settings; `decrypt_token` tries each in order so that previously-encrypted
  rows can be transparently decrypted and re-encrypted on next write.
* A migration helper (`rotate_all_credentials`) is exposed for the admin
  `/vault/rotate-key` endpoint.
"""
from __future__ import annotations

import base64
import os
from functools import lru_cache
from typing import Optional, Sequence

from cryptography.fernet import Fernet, MultiFernet, InvalidToken

from app.config import settings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _build_fernet(key: str) -> Fernet:
    """Validate and return a Fernet instance for *key*."""
    try:
        return Fernet(key.encode())
    except Exception as exc:
        raise ValueError(
            f"Invalid vault encryption key (must be URL-safe base64, 32 bytes): {exc}"
        ) from exc


@lru_cache(maxsize=1)
def _get_multifernet() -> MultiFernet:
    """
    Return a MultiFernet that:
    - encrypts with the *current* key (settings.vault_encryption_key)
    - decrypts with current + any previous keys (for seamless rotation)
    """
    active = _build_fernet(settings.vault_encryption_key)
    previous_raw: str = getattr(settings, "vault_encryption_key_previous", "") or ""
    previous_fernets = [
        _build_fernet(k.strip())
        for k in previous_raw.split(",")
        if k.strip()
    ]
    return MultiFernet([active, *previous_fernets])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def encrypt_token(plaintext: str) -> str:
    """Encrypt *plaintext* and return a URL-safe base64 Fernet token (str)."""
    mf = _get_multifernet()
    return mf.encrypt(plaintext.encode()).decode()


def decrypt_token(ciphertext: str) -> str:
    """Decrypt a Fernet token returned by :func:`encrypt_token`."""
    mf = _get_multifernet()
    try:
        return mf.decrypt(ciphertext.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("Vault decryption failed — wrong key or corrupted data") from exc


def is_encrypted(value: str) -> bool:
    """
    Heuristic: Fernet tokens start with 'gAAAAA' after base64-url encoding.
    Used during key rotation to skip already-plaintext rows (legacy data).
    """
    return value.startswith("gAAAAA")


def rotate_token(ciphertext: str) -> str:
    """
    Re-encrypt *ciphertext* with the current active key.
    Transparently decrypts with any previous key first.
    """
    plaintext = decrypt_token(ciphertext)
    return encrypt_token(plaintext)
